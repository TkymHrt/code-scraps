"""画像上で計測範囲・正常部分・候補条件を決め、提出版の設定をコピーする."""

import ast
import math
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

import cv2 as cv
import numpy as np

PALETTE = np.array([(255, 80, 0), (0, 255, 0), (64, 64, 64), (0, 165, 255)], np.uint8)
LEVELS = {"計測（03・05）": 0, "基準線（06）": 1, "候補（07・08）": 2}
SETTING_NAMES = (
    "INPUT_PATH",
    "CANDIDATE_RECT",
    "BACKGROUND_RECTS",
    "FOREGROUND_RECTS",
    "ITERATIONS",
    "RANDOM_SEED",
    "START_Y",
    "END_Y",
    "LEFT_REFERENCE_RANGES",
    "RIGHT_REFERENCE_RANGES",
    "MIN_INWARD_PX",
    "MIN_ROWS",
)


def read_settings(text: str) -> dict:
    """スクリプトや01のコピーから、設定値のリテラルだけを読む."""
    values = {}
    for node in ast.parse(text).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in SETTING_NAMES:
                values[name] = ast.literal_eval(node.value)
    return values


def initial_labels(image: np.ndarray, settings: dict) -> np.ndarray:
    height, width = image.shape[:2]
    labels = np.full((height, width), cv.GC_PR_BGD, np.uint8)
    candidate = settings.get("CANDIDATE_RECT")
    candidate_rects = () if candidate is None else (candidate,)
    for label, rectangles in (
        (cv.GC_PR_FGD, candidate_rects),
        (cv.GC_BGD, settings.get("BACKGROUND_RECTS", ())),
        (cv.GC_FGD, settings.get("FOREGROUND_RECTS", ())),
    ):
        for left, top, right, bottom in rectangles:
            if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
                raise ValueError("矩形は0〜1で、左 < 右、上 < 下にしてください")
            x0, y0 = int(width * left), int(height * top)
            x1, y1 = int(width * right), int(height * bottom)
            if x0 == x1 or y0 == y1:
                raise ValueError("初期指定の矩形が1画素未満です")
            labels[y0:y1, x0:x1] = label
    return labels


def validate_settings(image: np.ndarray, settings: dict, level: int) -> None:
    if settings.get("CANDIDATE_RECT") is None:
        raise ValueError(
            "01の初期指定を貼り付けるか、スクリプトから設定を読んでください"
        )
    initial_labels(image, settings)
    height = image.shape[0]
    start = settings["START_Y"]
    end = height - 1 if settings["END_Y"] is None else settings["END_Y"]
    if (
        not isinstance(start, int)
        or not isinstance(end, int)
        or not (0 <= start <= end < height)
    ):
        raise ValueError("計測範囲は画像内の整数で、開始 <= 終了にしてください")
    if not isinstance(settings["ITERATIONS"], int) or settings["ITERATIONS"] < 1:
        raise ValueError("反復回数は1以上の整数にしてください")
    if not isinstance(settings["RANDOM_SEED"], int) or not (
        -2147483648 <= settings["RANDOM_SEED"] <= 2147483647
    ):
        raise ValueError("乱数シードは32bitの符号付き整数にしてください")
    if level >= 1:
        for key in ("LEFT_REFERENCE_RANGES", "RIGHT_REFERENCE_RANGES"):
            selected_ys = set()
            for first, last in settings[key]:
                if (
                    not isinstance(first, int)
                    or not isinstance(last, int)
                    or not (start <= first <= last <= end)
                ):
                    raise ValueError(
                        "正常部分は計測範囲内の整数で、開始 <= 終了にしてください"
                    )
                for y in range(first, last + 1):
                    if y in selected_ys:
                        raise ValueError("同じ側の正常部分は重ねないでください")
                    selected_ys.add(y)
            if len(selected_ys) < 2:
                raise ValueError("左・右それぞれの正常部分を2行以上選んでください")
    if level >= 2:
        threshold = settings["MIN_INWARD_PX"]
        if not math.isfinite(threshold) or threshold <= 0:
            raise ValueError("内向き偏差は0より大きい有限値にしてください")
        if not isinstance(settings["MIN_ROWS"], int) or settings["MIN_ROWS"] < 2:
            raise ValueError("最小連続行数は2以上の整数にしてください")


def settings_text(image: np.ndarray, settings: dict, level: int) -> str:
    validate_settings(image, settings, level)
    names = list(SETTING_NAMES[:8])
    if level >= 1:
        names.extend(SETTING_NAMES[8:10])
    if level >= 2:
        names.extend(SETTING_NAMES[10:])
    lines = []
    for name in names:
        lines.append(f"{name} = {settings[name]!r}")
    return "\n".join(lines) + "\n"


def extract_mask(image: np.ndarray, settings: dict) -> np.ndarray:
    validate_settings(image, settings, 0)
    labels = initial_labels(image, settings)
    background = np.zeros((1, 65), np.float64)
    foreground = np.zeros((1, 65), np.float64)
    cv.setRNGSeed(settings["RANDOM_SEED"])
    cv.grabCut(
        image,
        labels,
        (0, 0, 0, 0),
        background,
        foreground,
        settings["ITERATIONS"],
        cv.GC_INIT_WITH_MASK,
    )
    raw_mask = np.isin(labels, (cv.GC_FGD, cv.GC_PR_FGD)).astype(np.uint8) * 255
    contours, _ = cv.findContours(raw_mask, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise ValueError("試料の領域が見つかりません。初期指定を確認してください")
    contour = max(contours, key=cv.contourArea)
    mask = np.zeros(image.shape[:2], np.uint8)
    cv.drawContours(mask, [contour], -1, 255, -1)
    return mask


def fit_reference(edge_rows, column, ranges, start_y, end_y):
    """指定した正常部分の点に、x = slope * y + intercept の直線を当てる."""
    x_by_y = {}
    for row in edge_rows:
        x_by_y[row[0]] = row[column]
    ys = []
    xs = []
    for first_y, last_y in ranges:
        if not (start_y <= first_y <= last_y <= end_y):
            raise ValueError("正常部分の範囲は計測範囲内で、開始 <= 終了にしてください")
        for y in range(first_y, last_y + 1):
            if y not in x_by_y:
                raise ValueError(f"正常部分のy={y}に試料がありません")
            if y in ys:
                raise ValueError("正常部分の範囲は重ねないでください")
            ys.append(y)
            xs.append(x_by_y[y])
    if len(ys) < 2:
        raise ValueError("基準線には正常部分の点が2行以上必要です")
    mean_y = float(np.mean(ys))
    mean_x = float(np.mean(xs))
    numerator = 0.0
    denominator = 0.0
    for y, x in zip(ys, xs):
        numerator += (y - mean_y) * (x - mean_x)
        denominator += (y - mean_y) ** 2
    slope = numerator / denominator
    intercept = mean_x - slope * mean_y
    return slope, intercept, ys


def find_candidates(deviation_rows, edge, threshold, min_rows):
    """左右別に、しきい値以上の連続する行を1候補として数える."""
    x_column = 1 if edge == "left" else 2
    inward_column = 5 if edge == "left" else 6
    prefix = "L" if edge == "left" else "R"
    segments = []
    current = []
    for row in deviation_rows:
        if current and row[0] != current[-1][0] + 1:
            segments.append(current)
            current = []
        if row[inward_column] >= threshold:
            current.append(row)
        elif current:
            segments.append(current)
            current = []
    if current:
        segments.append(current)
    candidates = []
    for segment in segments:
        if len(segment) < min_rows:
            continue
        peak = segment[0]
        for row in segment[1:]:
            if row[inward_column] > peak[inward_column]:
                peak = row
        candidate = {
            "candidate_id": f"{prefix}{len(candidates) + 1:02d}",
            "edge": edge,
            "start_y": segment[0][0],
            "end_y": segment[-1][0],
            "peak_y": peak[0],
            "peak_x": peak[x_column],
            "point_count": len(segment),
            "max_inward_px": peak[inward_column],
        }
        candidates.append(candidate)
    return candidates


def analyze(image: np.ndarray, mask: np.ndarray, settings: dict, level: int) -> dict:
    validate_settings(image, settings, level)
    start_y = settings["START_Y"]
    end_y = image.shape[0] - 1 if settings["END_Y"] is None else settings["END_Y"]
    edge_rows = []
    widths = []
    for y in range(start_y, end_y + 1):
        xs = np.flatnonzero(mask[y])
        if len(xs) > 0:
            left_x, right_x = int(xs[0]), int(xs[-1])
            edge_rows.append((y, left_x, right_x))
            widths.append(right_x - left_x)
    if len(edge_rows) < 2:
        raise ValueError("計測範囲に試料が2行以上必要です")
    left_length = right_length = 0.0
    for before, after in zip(edge_rows, edge_rows[1:]):
        left_length += math.hypot(after[1] - before[1], after[0] - before[0])
        right_length += math.hypot(after[2] - before[2], after[0] - before[0])
    result = image.copy()
    for area in (result[:start_y], result[end_y + 1 :]):
        if area.size > 0:
            area[:] = cv.addWeighted(area, 0.4, np.full_like(area, 220), 0.6, 0)
    for y in (start_y, end_y):
        cv.line(result, (0, y), (image.shape[1] - 1, y), (0, 255, 255), 1)
    for column in (1, 2):
        points = []
        for row in edge_rows:
            points.append((row[column], row[0]))
        cv.polylines(result, [np.array(points, np.int32)], False, (0, 0, 255), 2)
    data = {
        "image": result,
        "edge_rows": edge_rows,
        "left_length": left_length,
        "right_length": right_length,
        "widths": widths,
        "candidates": [],
    }
    if level == 0:
        return data
    left_slope, left_intercept, left_ys = fit_reference(
        edge_rows, 1, settings["LEFT_REFERENCE_RANGES"], start_y, end_y
    )
    right_slope, right_intercept, right_ys = fit_reference(
        edge_rows, 2, settings["RIGHT_REFERENCE_RANGES"], start_y, end_y
    )
    deviation_rows = []
    for y, left_x, right_x in edge_rows:
        left_reference = left_slope * y + left_intercept
        right_reference = right_slope * y + right_intercept
        if left_reference >= right_reference:
            raise ValueError("左右の基準線が交差します。正常部分を選び直してください")
        deviation_rows.append(
            (
                y,
                left_x,
                right_x,
                left_reference,
                right_reference,
                left_x - left_reference,
                right_reference - right_x,
            )
        )
    for column, slope, intercept, selected_ys in (
        (1, left_slope, left_intercept, left_ys),
        (2, right_slope, right_intercept, right_ys),
    ):
        cv.line(
            result,
            (round(slope * start_y + intercept), start_y),
            (round(slope * end_y + intercept), end_y),
            (255, 255, 0),
            1,
        )
        for row in edge_rows:
            if row[0] in selected_ys:
                cv.circle(result, (row[column], row[0]), 2, (0, 255, 0), -1)
    data["deviation_rows"] = deviation_rows
    if level == 1:
        return data
    if len(edge_rows) != end_y - start_y + 1:
        raise ValueError(
            "計測範囲に端を取得できない行があります。範囲を選び直してください"
        )
    candidates = []
    for edge, slope in (("left", left_slope), ("right", right_slope)):
        found = find_candidates(
            deviation_rows, edge, settings["MIN_INWARD_PX"], settings["MIN_ROWS"]
        )
        for candidate in found:
            span_y = candidate["end_y"] - candidate["start_y"]
            candidate["span_y_px"] = span_y
            candidate["span_along_reference_px"] = math.hypot(slope * span_y, span_y)
            candidate["touches_boundary"] = int(
                candidate["start_y"] == start_y or candidate["end_y"] == end_y
            )
        candidates.extend(found)
    for candidate in candidates:
        column = 1 if candidate["edge"] == "left" else 2
        points = []
        for row in edge_rows:
            if candidate["start_y"] <= row[0] <= candidate["end_y"]:
                points.append((row[column], row[0]))
        cv.polylines(result, [np.array(points, np.int32)], False, (255, 0, 255), 4)
        text_x = candidate["peak_x"] - 60 if column == 1 else candidate["peak_x"] + 12
        position = (
            max(0, min(text_x, image.shape[1] - 45)),
            max(16, candidate["peak_y"]),
        )
        for color, thickness in (((0, 0, 0), 4), ((255, 255, 255), 1)):
            cv.putText(
                result,
                candidate["candidate_id"],
                position,
                cv.FONT_HERSHEY_SIMPLEX,
                0.55,
                color,
                thickness,
            )
    data["candidates"] = candidates
    return data


def main() -> None:
    directory = Path(__file__).resolve().parent
    root = tk.Tk()
    root.title("画像の計測設定 — 範囲・正常部分・候補条件")
    root.geometry("1180x780")
    root.minsize(1040, 720)
    image = None
    height = 1
    input_path = None
    initial = {"CANDIDATE_RECT": None, "BACKGROUND_RECTS": (), "FOREGROUND_RECTS": ()}
    reference_ranges = {"left": [], "right": []}
    range_rows = []
    cached_mask = None
    cached_settings = None
    data = None
    photo = None
    display_bounds = (0, 0, 1, 1)
    drag_start = None

    file_text = tk.StringVar(value="未読込")
    status = tk.StringVar(value="画像と初期指定を読み込み、範囲をドラッグしてください")
    summary = tk.StringVar(value="未計算")
    view = tk.StringVar(value="original")
    draw_kind = tk.StringVar(value="measurement")
    target = tk.StringVar(value="候補（07・08）")
    start_var = tk.StringVar()
    end_var = tk.StringVar()
    iterations_var = tk.StringVar(value="5")
    seed_var = tk.StringVar(value="0")
    inward_var = tk.StringVar(value="5")
    rows_var = tk.StringVar(value="3")

    toolbar = ttk.Frame(root, padding=12)
    toolbar.pack(fill="x")
    for text, action in (
        ("画像を読み込む", lambda: load_image()),
        ("スクリプトから設定を読む", lambda: load_script()),
        ("01の初期指定を貼り付け", lambda: paste_initial()),
    ):
        ttk.Button(toolbar, text=text, padding=(8, 8), command=action).pack(
            side="left", padx=(0, 8)
        )
    ttk.Label(toolbar, textvariable=file_text).pack(side="left")
    body = ttk.Frame(root, padding=(12, 0, 12, 0))
    body.pack(fill="both", expand=True)
    sidebar = ttk.Frame(body, width=300)
    sidebar.pack(side="left", fill="y", padx=(0, 16))
    preview = ttk.Frame(body)
    preview.pack(side="left", fill="both", expand=True)
    notebook = ttk.Notebook(sidebar)
    notebook.pack(fill="x")
    range_tab = ttk.Frame(notebook, padding=12)
    condition_tab = ttk.Frame(notebook, padding=12)
    notebook.add(range_tab, text="画像上で範囲を選ぶ")
    notebook.add(condition_tab, text="計算・候補条件")
    ttk.Label(range_tab, text="ドラッグする範囲").pack(anchor="w")
    for value, name in (
        ("measurement", "計測範囲（黄）"),
        ("left", "左の正常部分（緑）"),
        ("right", "右の正常部分（水色）"),
    ):
        ttk.Radiobutton(
            range_tab, text=name, variable=draw_kind, value=value, padding=4
        ).pack(anchor="w", pady=4)
    coordinate_frame = ttk.Frame(range_tab)
    coordinate_frame.pack(fill="x", pady=8)
    ttk.Label(coordinate_frame, text="開始y").grid(row=0, column=0, padx=(0, 8))
    ttk.Spinbox(
        coordinate_frame, from_=0, to=100000, width=8, textvariable=start_var
    ).grid(row=0, column=1)
    ttk.Label(coordinate_frame, text="終了y").grid(row=0, column=2, padx=(8, 8))
    ttk.Spinbox(
        coordinate_frame, from_=0, to=100000, width=8, textvariable=end_var
    ).grid(row=0, column=3)
    ttk.Button(
        range_tab, text="画像全体を計測範囲にする", command=lambda: full_range()
    ).pack(fill="x", pady=(0, 8))
    range_list = tk.Listbox(range_tab, width=30, height=5, exportselection=False)
    range_list.pack(fill="x")
    range_actions = ttk.Frame(range_tab)
    range_actions.pack(fill="x", pady=(8, 0))
    for text, action in (
        ("選択を削除", lambda: delete_range()),
        ("すべて削除", lambda: clear_ranges()),
    ):
        ttk.Button(range_actions, text=text, command=action).pack(
            side="left", padx=(0, 8)
        )
    for row, (label, variable, first, step) in enumerate(
        (
            ("反復回数", iterations_var, 1, 1),
            ("乱数シード", seed_var, -2147483648, 1),
            ("内向き偏差（px以上）", inward_var, 0.1, 0.5),
            ("最小連続行数", rows_var, 2, 1),
        )
    ):
        ttk.Label(condition_tab, text=label).grid(row=row, column=0, sticky="w", pady=8)
        ttk.Spinbox(
            condition_tab,
            from_=first,
            to=2147483647,
            increment=step,
            width=10,
            textvariable=variable,
        ).grid(row=row, column=1, padx=(8, 0))
    ttk.Label(
        condition_tab, text="候補条件は用途「候補」で使います。", wraplength=260
    ).grid(row=4, column=0, columnspan=2, sticky="w", pady=12)
    actions = ttk.Frame(root, padding=(12, 8))
    actions.pack(fill="x")
    ttk.Label(actions, text="用途・コピー先").pack(side="left", padx=(0, 8))
    target_box = ttk.Combobox(
        actions, values=list(LEVELS), textvariable=target, state="readonly"
    )
    target_box.pack(side="left", padx=(0, 16))
    for text, action in (
        ("計算して確認", lambda: calculate()),
        ("確認画像を保存", lambda: save_preview()),
        ("設定をコピー", lambda: copy_settings()),
    ):
        ttk.Button(actions, text=text, padding=(12, 8), command=action).pack(
            side="left", padx=(0, 8)
        )
    ttk.Label(root, textvariable=summary, wraplength=1016, padding=(12, 4)).pack(
        fill="x"
    )
    views = ttk.Frame(preview)
    views.pack(fill="x", pady=(0, 8))
    for value, label in (
        ("original", "元画像＋範囲"),
        ("initial", "初期指定"),
        ("result", "計算結果"),
    ):
        ttk.Radiobutton(
            views,
            text=label,
            variable=view,
            value=value,
            padding=4,
            command=lambda: render(),
        ).pack(side="left", padx=(0, 12))
    canvas = tk.Canvas(preview, background="#242424", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    ttk.Label(root, textvariable=status, padding=12, wraplength=1016).pack(fill="x")

    def changed(*unused) -> None:
        nonlocal data
        data = None
        summary.set("未計算 — 設定変更後は計算して確認")
        status.set("設定を変更しました。計算して確認してください")
        if view.get() == "result":
            view.set("original")
        render()

    def refresh_ranges() -> None:
        range_rows.clear()
        range_list.delete(0, tk.END)
        for edge, name in (("left", "左"), ("right", "右")):
            for index, (first, last) in enumerate(reference_ranges[edge]):
                range_rows.append((edge, index))
                range_list.insert(tk.END, f"{name}  y={first}〜{last}")
        changed()

    def install_image(loaded, path, settings=None) -> None:
        nonlocal image, input_path, initial, cached_mask, cached_settings, height
        image = loaded
        input_path = path
        cached_mask = cached_settings = None
        height, width = image.shape[:2]
        file_text.set(f"{path.name} ({width}×{height})")
        initial = {
            "CANDIDATE_RECT": None,
            "BACKGROUND_RECTS": (),
            "FOREGROUND_RECTS": (),
        }
        reference_ranges["left"] = []
        reference_ranges["right"] = []
        start_var.set("0")
        end_var.set(str(height - 1))
        if settings is not None:
            for name in initial:
                initial[name] = settings[name]
            start_var.set(str(settings["START_Y"]))
            end_var.set(
                str(height - 1 if settings["END_Y"] is None else settings["END_Y"])
            )
            iterations_var.set(str(settings["ITERATIONS"]))
            seed_var.set(str(settings["RANDOM_SEED"]))
            inward_var.set(str(settings["MIN_INWARD_PX"]))
            rows_var.set(str(settings["MIN_ROWS"]))
            reference_ranges["left"] = list(settings["LEFT_REFERENCE_RANGES"])
            reference_ranges["right"] = list(settings["RIGHT_REFERENCE_RANGES"])
        view.set("original")
        refresh_ranges()

    def load_image() -> None:
        selected = filedialog.askopenfilename(
            parent=root,
            title="入力画像を選ぶ",
            initialdir=directory,
            filetypes=[
                ("画像", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff"),
                ("すべて", "*.*"),
            ],
        )
        if not selected:
            return
        try:
            path = Path(selected).resolve()
            loaded = cv.imdecode(
                np.frombuffer(path.read_bytes(), np.uint8), cv.IMREAD_COLOR
            )
            if loaded is None:
                raise ValueError("画像を読み込めません")
        except (OSError, ValueError, cv.error) as error:
            status.set(str(error))
            return
        install_image(loaded, path)
        status.set("01の初期指定を貼り付け、計測範囲をドラッグしてください")

    def load_script() -> None:
        selected = filedialog.askopenfilename(
            parent=root,
            title="03・05〜08のスクリプトを選ぶ",
            initialdir=directory,
            filetypes=[("Python", "*.py")],
        )
        if not selected:
            return
        try:
            script_path = Path(selected).resolve()
            values = read_settings(script_path.read_text(encoding="utf-8-sig"))
            if "INPUT_PATH" not in values or "CANDIDATE_RECT" not in values:
                raise ValueError("画像と初期指定のある03・05〜08を選んでください")
            path = (script_path.parent / values["INPUT_PATH"]).resolve()
            loaded = cv.imdecode(
                np.frombuffer(path.read_bytes(), np.uint8), cv.IMREAD_COLOR
            )
            if loaded is None:
                raise ValueError("スクリプトの入力画像を読み込めません")
            settings = {
                "INPUT_PATH": str(path),
                "CANDIDATE_RECT": None,
                "BACKGROUND_RECTS": (),
                "FOREGROUND_RECTS": (),
                "ITERATIONS": 5,
                "RANDOM_SEED": 0,
                "START_Y": 0,
                "END_Y": None,
                "LEFT_REFERENCE_RANGES": (),
                "RIGHT_REFERENCE_RANGES": (),
                "MIN_INWARD_PX": 5.0,
                "MIN_ROWS": 3,
            }
            settings.update(values)
            level = (
                2
                if "MIN_INWARD_PX" in values
                else 1
                if "LEFT_REFERENCE_RANGES" in values
                else 0
            )
            validate_settings(loaded, settings, level)
        except (OSError, SyntaxError, ValueError, TypeError, cv.error) as error:
            status.set(f"設定を読み込めません: {error}")
            return
        target.set(list(LEVELS)[level])
        install_image(loaded, path, settings)
        status.set(f"{script_path.name}の設定を読み込みました")

    def paste_initial() -> None:
        nonlocal initial
        if image is None:
            status.set("画像を読み込んでください")
            return
        try:
            values = read_settings(root.clipboard_get())
            replacement = {}
            for name in initial:
                if name not in values:
                    raise ValueError("01でコピーした矩形の3設定を貼り付けてください")
                replacement[name] = values[name]
            if replacement["CANDIDATE_RECT"] is None:
                raise ValueError("前景候補がありません")
            initial_labels(image, replacement)
        except (tk.TclError, SyntaxError, ValueError, TypeError) as error:
            status.set(f"初期指定を貼り付けられません: {error}")
            return
        initial = replacement
        changed()
        view.set("initial")
        render()
        status.set("初期指定を貼り付けました")

    def ui_settings(level) -> dict:
        if image is None or input_path is None:
            raise ValueError("画像を読み込んでください")
        try:
            values = {
                "INPUT_PATH": str(input_path),
                **initial,
                "START_Y": int(start_var.get()),
                "END_Y": int(end_var.get()),
                "ITERATIONS": int(iterations_var.get()),
                "RANDOM_SEED": int(seed_var.get()),
                "LEFT_REFERENCE_RANGES": tuple(reference_ranges["left"]),
                "RIGHT_REFERENCE_RANGES": tuple(reference_ranges["right"]),
            }
        except ValueError as error:
            raise ValueError(
                "開始・終了・反復回数・乱数シードは整数で入力してください"
            ) from error
        if level >= 2:
            try:
                values["MIN_INWARD_PX"] = float(inward_var.get())
                values["MIN_ROWS"] = int(rows_var.get())
            except ValueError as error:
                raise ValueError(
                    "偏差は数値、最小連続行数は整数で入力してください"
                ) from error
        return values

    def calculate() -> None:
        nonlocal cached_mask, cached_settings, data
        if image is None:
            status.set("画像を読み込んでください")
            return
        try:
            level = LEVELS[target.get()]
            settings = ui_settings(level)
            validate_settings(image, settings, level)
            signature = {}
            for name in SETTING_NAMES[1:6]:
                signature[name] = settings[name]
            status.set("計算中…")
            root.update_idletasks()
            if cached_mask is None or cached_settings != signature:
                cached_mask = extract_mask(image, settings)
                cached_settings = signature
            computed = analyze(image, cached_mask, settings, level)
        except (ValueError, TypeError, cv.error) as error:
            status.set(str(error))
            return
        data = computed
        widths = data["widths"]
        text = (
            f"側辺長: 左{data['left_length']:.2f} / 右{data['right_length']:.2f}px　|　"
        )
        text += f"幅: 最小{min(widths):.2f} / 平均{np.mean(widths):.2f} / 最大{max(widths):.2f}px"
        if level >= 2:
            left = right = 0
            maximum = span = 0.0
            for candidate in data["candidates"]:
                if candidate["edge"] == "left":
                    left += 1
                else:
                    right += 1
                maximum = max(maximum, candidate["max_inward_px"])
                span += candidate["span_along_reference_px"]
            text += f"\n仮の候補: 左{left} / 右{right}　|　最大偏差{maximum:.2f}px / 影響範囲{span:.2f}px"
        summary.set(text)
        view.set("result")
        render()
        status.set("計算結果を確認し、設定をコピーしてください")

    def render() -> None:
        nonlocal photo, display_bounds, drag_start
        drag_start = None
        canvas.delete("all")
        if image is None:
            return
        shown = image
        if view.get() == "initial":
            shown = cv.addWeighted(
                image, 0.65, PALETTE[initial_labels(image, initial)], 0.35, 0
            )
        elif view.get() == "result" and data is not None:
            shown = data["image"]
        height, width = image.shape[:2]
        scale = min(canvas.winfo_width() / width, canvas.winfo_height() / height, 1)
        dw, dh = max(1, int(width * scale)), max(1, int(height * scale))
        small = cv.resize(shown, (dw, dh), interpolation=cv.INTER_NEAREST)
        _, encoded = cv.imencode(".png", small)
        photo = tk.PhotoImage(master=root, data=encoded.tobytes(), format="PNG")
        x0, y0 = (canvas.winfo_width() - dw) // 2, (canvas.winfo_height() - dh) // 2
        display_bounds = (x0, y0, x0 + dw, y0 + dh)
        canvas.create_image(x0, y0, image=photo, anchor="nw")
        try:
            start, end = int(start_var.get()), int(end_var.get())
            if 0 <= start <= end < height:
                for y in (start, end):
                    py = y0 + (y + 0.5) / height * dh
                    canvas.create_line(x0, py, x0 + dw, py, fill="#facc15", width=2)
        except ValueError:
            pass  # 入力途中の空欄は描かず、計算・コピー時に検証する。
        selection = range_list.curselection()
        selected_range = range_rows[selection[0]] if selection else None
        for edge, color in (("left", "#22c55e"), ("right", "#22d3ee")):
            first_x = x0 if edge == "left" else x0 + dw / 2
            last_x = x0 + dw / 2 if edge == "left" else x0 + dw
            for index, (first, last) in enumerate(reference_ranges[edge]):
                canvas.create_rectangle(
                    first_x,
                    y0 + first / height * dh,
                    last_x,
                    y0 + (last + 1) / height * dh,
                    outline=color,
                    width=4 if selected_range == (edge, index) else 2,
                )
        # 候補番号は表示倍率にかかわらず読める大きさで重ねる。
        if view.get() == "result" and data is not None:
            for candidate in data["candidates"]:
                px = x0 + (candidate["peak_x"] + 0.5) / width * dw
                py = y0 + (candidate["peak_y"] + 0.5) / height * dh
                left_side = candidate["edge"] == "left"
                px += -8 if left_side else 8
                item = canvas.create_text(
                    px,
                    py,
                    text=candidate["candidate_id"],
                    anchor="e" if left_side else "w",
                    fill="white",
                    font=("TkDefaultFont", 10, "bold"),
                )
                bounds = canvas.bbox(item)
                if bounds is not None:
                    a, b, c, d = bounds
                    background = canvas.create_rectangle(
                        a - 2, b - 2, c + 2, d + 2, fill="#202020", outline=""
                    )
                    canvas.tag_lower(background, item)

    def image_y(event) -> int:
        _, y0, _, y1 = display_bounds
        return min(height - 1, max(0, int((event.y - y0) / (y1 - y0) * height)))

    def start_draw(event) -> None:
        nonlocal drag_start
        if image is None:
            return
        x0, y0, x1, y1 = display_bounds
        if x0 <= event.x < x1 and y0 <= event.y < y1:
            drag_start = image_y(event)

    def drag_draw(event) -> None:
        if drag_start is None:
            return
        x0, y0, x1, y1 = display_bounds
        first, last = sorted((drag_start, image_y(event)))
        if draw_kind.get() == "left":
            x1 = (x0 + x1) / 2
        elif draw_kind.get() == "right":
            x0 = (x0 + x1) / 2
        canvas.delete("drag")
        canvas.create_rectangle(
            x0,
            y0 + first / height * (y1 - y0),
            x1,
            y0 + (last + 1) / height * (y1 - y0),
            outline="white",
            width=2,
            tags="drag",
        )

    def end_draw(event) -> None:
        nonlocal drag_start
        if drag_start is None:
            return
        first, last = sorted((drag_start, image_y(event)))
        drag_start = None
        canvas.delete("drag")
        edge = draw_kind.get()
        if edge == "measurement":
            start_var.set(str(first))
            end_var.set(str(last))
        else:
            try:
                if not (int(start_var.get()) <= first <= last <= int(end_var.get())):
                    raise ValueError("正常部分は黄色の計測範囲内で選んでください")
                for a, b in reference_ranges[edge]:
                    if max(a, first) <= min(b, last):
                        raise ValueError("同じ側の正常部分は重ねないでください")
            except ValueError as error:
                status.set(str(error))
                return
            reference_ranges[edge].append((first, last))
            refresh_ranges()
        status.set(f"{first}〜{last}行を指定しました。必要なら数値で微調整できます")

    def full_range() -> None:
        if image is None:
            status.set("画像を読み込んでください")
            return
        start_var.set("0")
        end_var.set(str(image.shape[0] - 1))

    def delete_range() -> None:
        selection = range_list.curselection()
        if selection:
            edge, index = range_rows[selection[0]]
            del reference_ranges[edge][index]
            refresh_ranges()

    def clear_ranges() -> None:
        reference_ranges["left"].clear()
        reference_ranges["right"].clear()
        refresh_ranges()

    def copy_settings() -> None:
        if image is None:
            status.set("画像を読み込んでください")
            return
        try:
            level = LEVELS[target.get()]
            text = settings_text(image, ui_settings(level), level)
        except (ValueError, TypeError) as error:
            status.set(str(error))
            return
        root.clipboard_clear()
        root.clipboard_append(text)
        status.set(f"{target.get()}の設定をコピーしました")

    def save_preview() -> None:
        if data is None or input_path is None:
            status.set("計算して確認してから保存してください")
            return
        selected = filedialog.asksaveasfilename(
            parent=root,
            title="確認画像を保存",
            initialdir=input_path.parent,
            initialfile=f"{input_path.stem}_measurement.png",
            defaultextension=".png",
            filetypes=[("PNG画像", "*.png")],
            confirmoverwrite=True,
        )
        if not selected:
            return
        path = Path(selected).resolve()
        if path == input_path or path.suffix.lower() != ".png":
            status.set("入力画像と別の .png を指定してください")
            return
        try:
            success, encoded = cv.imencode(".png", data["image"])
            if not success:
                raise OSError("PNGを作成できません")
            path.write_bytes(encoded.tobytes())
        except OSError as error:
            status.set(str(error))
            return
        status.set(f"保存しました: {path.name}")

    for variable in (
        start_var,
        end_var,
        iterations_var,
        seed_var,
        inward_var,
        rows_var,
    ):
        variable.trace_add("write", changed)
    target_box.bind("<<ComboboxSelected>>", changed)
    range_list.bind("<<ListboxSelect>>", lambda event: render())
    canvas.bind("<Configure>", lambda event: render())
    canvas.bind("<ButtonPress-1>", start_draw)
    canvas.bind("<B1-Motion>", drag_draw)
    canvas.bind("<ButtonRelease-1>", end_draw)
    root.mainloop()


if __name__ == "__main__":
    main()
