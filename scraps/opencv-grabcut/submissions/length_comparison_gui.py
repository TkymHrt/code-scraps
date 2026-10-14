"""対応区間の理想スラブと、既知寸法でmm換算した複数撮影の側辺長を比較する."""

import csv
import math
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

import cv2 as cv
import numpy as np
from matplotlib import rcParams
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


def read_lengths(path: Path) -> tuple[dict[str, float], tuple[int, int]]:
    lengths = {}
    measurement_range = None
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        required = {"edge", "length_px", "start_y", "end_y"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"03_side_lengths.csvの形式を選んでください: {path}")
        for row in reader:
            for column in required:
                if row[column] is None or not row[column].strip():
                    raise ValueError(f"空欄のある行を確認してください: {path}")
            edge = row["edge"]
            if edge not in ("left", "right", "total") or edge in lengths:
                raise ValueError(f"左・右・合計を1行ずつ指定してください: {path}")
            try:
                length = float(row["length_px"])
                start_y = int(row["start_y"])
                end_y = int(row["end_y"])
            except ValueError as error:
                raise ValueError(
                    f"長さ・計測範囲の数値を確認してください: {path}"
                ) from error
            if not math.isfinite(length) or length <= 0:
                raise ValueError(f"長さは0より大きい有限値が必要です: {path}")
            if not 0 <= start_y < end_y:
                raise ValueError(f"長さを測れる計測範囲が必要です: {path}")
            row_range = (start_y, end_y)
            if measurement_range is not None and row_range != measurement_range:
                raise ValueError(f"CSV内の計測範囲が一致しません: {path}")
            measurement_range = row_range
            lengths[edge] = length
    if len(lengths) != 3 or measurement_range is None:
        raise ValueError(f"左・右・合計の3行が必要です: {path}")
    # 03は丸める前に合計を求めるため、左右の和と最大0.01pxずれる。
    if abs(lengths["left"] + lengths["right"] - lengths["total"]) > 0.011:
        raise ValueError(f"左右の長さと合計が一致しません: {path}")
    return lengths, measurement_range


def positive_value(value: float | str | None, name: str) -> float:
    try:
        number = float(value) if value is not None else math.nan
    except ValueError as error:
        raise ValueError(f"{name}は0より大きい数値で入力してください") from error
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name}は0より大きい有限値が必要です")
    return number


def calibration_from_points(
    reference_mm: float | str, points: list | tuple, image_size: tuple[int, int]
) -> dict:
    reference_mm = positive_value(reference_mm, "基準物の実寸 (mm)")
    width, height = image_size
    if width < 2 or height < 2:
        raise ValueError("校正画像は縦横2画素以上が必要です")
    if len(points) != 2:
        raise ValueError("既知寸法の両端を2点指定してください")
    converted = []
    for x, y in points:
        x, y = float(x), float(y)
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("基準点は有限の座標で指定してください")
        if not (0 <= x <= width - 1 and 0 <= y <= height - 1):
            raise ValueError("基準点を校正画像の中に指定してください")
        converted.append((x, y))
    first, second = converted
    reference_px = math.hypot(second[0] - first[0], second[1] - first[1])
    reference_px = positive_value(reference_px, "画像上の基準物の長さ (px)")
    mm_per_px = positive_value(reference_mm / reference_px, "mm/px")
    return {
        "reference_mm": reference_mm,
        "reference_px": reference_px,
        "mm_per_px": mm_per_px,
        "points": tuple(converted),
        "image_width": width,
        "image_height": height,
    }


def point_on_image(
    x: float, y: float, bounds: tuple, image_size: tuple[int, int]
) -> tuple[float, float] | None:
    x0, y0, display_width, display_height = bounds
    if not (x0 <= x <= x0 + display_width - 1 and y0 <= y <= y0 + display_height - 1):
        return None
    width, height = image_size
    image_x = (x - x0) * (width - 1) / (display_width - 1)
    image_y = (y - y0) * (height - 1) / (display_height - 1)
    return image_x, image_y


def calibrate_image(
    parent, image_path: Path, previous: dict | None = None
) -> dict | None:
    image_path = image_path.resolve()
    image = cv.imdecode(
        np.frombuffer(image_path.read_bytes(), np.uint8), cv.IMREAD_COLOR
    )
    if image is None:
        raise ValueError(f"校正画像を読み込めません: {image_path}")
    height, width = image.shape[:2]
    if width < 2 or height < 2:
        raise ValueError("校正画像は縦横2画素以上が必要です")
    window = tk.Toplevel(parent)
    window.title("既知寸法から画像を校正")
    window.geometry(
        f"{min(1100, parent.winfo_screenwidth() - 80)}x"
        f"{min(760, parent.winfo_screenheight() - 120)}+40+20"
    )
    window.minsize(800, 580)
    window.transient(parent)
    points = []
    reference = tk.StringVar(master=window)
    if (
        previous is not None
        and previous["image_path"] == str(image_path)
        and previous["image_width"] == width
        and previous["image_height"] == height
    ):
        points = list(previous["points"])
        reference.set(str(previous["reference_mm"]))
    mode = tk.StringVar(master=window, value="全体")
    status = tk.StringVar(
        master=window, value="定規などの既知寸法の両端をクリックしてください"
    )
    result = None
    photo = None
    bounds = (0, 0, 2, 2)

    def draw_points() -> None:
        canvas.delete("reference")
        x0, y0, display_width, display_height = bounds
        display_points = []
        for index, (x, y) in enumerate(points):
            display_x = x0 + x * (display_width - 1) / (width - 1)
            display_y = y0 + y * (display_height - 1) / (height - 1)
            display_points.append((display_x, display_y))
            canvas.create_oval(
                display_x - 5,
                display_y - 5,
                display_x + 5,
                display_y + 5,
                outline="#00ff88",
                width=2,
                tags="reference",
            )
            canvas.create_text(
                display_x + 9,
                display_y - 9,
                text=f"P{index + 1}",
                anchor="sw",
                fill="#00ff88",
                tags="reference",
            )
        if len(display_points) == 2:
            canvas.create_line(
                *display_points[0],
                *display_points[1],
                fill="#00ff88",
                width=2,
                tags="reference",
            )
            update_scale()

    def update_scale(*args) -> None:
        if len(points) != 2:
            return
        try:
            calibration = calibration_from_points(
                reference.get(), points, (width, height)
            )
        except ValueError as error:
            status.set(str(error))
            return
        status.set(
            f"画像上の距離: {calibration['reference_px']:.3f}px / "
            f"実寸: {calibration['reference_mm']:g}mm → "
            f"{calibration['mm_per_px']:.8g}mm/px"
        )

    def draw_image(event=None) -> None:
        nonlocal photo, bounds
        canvas_width = max(32, canvas.winfo_width())
        canvas_height = max(32, canvas.winfo_height())
        scale = 1.0
        if mode.get() == "全体":
            scale = min(1.0, (canvas_width - 24) / width, (canvas_height - 24) / height)
        display_width = max(2, round(width * scale))
        display_height = max(2, round(height * scale))
        small = cv.resize(
            image, (display_width, display_height), interpolation=cv.INTER_AREA
        )
        success, encoded = cv.imencode(".png", small)
        if not success:
            raise ValueError("画像の表示データを作れません")
        photo = tk.PhotoImage(master=window, data=encoded.tobytes(), format="PNG")
        x0 = max(12, (canvas_width - display_width) / 2)
        y0 = max(12, (canvas_height - display_height) / 2)
        bounds = (x0, y0, display_width, display_height)
        canvas.delete("all")
        canvas.create_image(x0, y0, image=photo, anchor="nw", tags="source")
        canvas.configure(
            scrollregion=(
                0,
                0,
                max(canvas_width, x0 + display_width + 12),
                max(canvas_height, y0 + display_height + 12),
            )
        )
        draw_points()

    def click(event) -> None:
        point = point_on_image(
            canvas.canvasx(event.x), canvas.canvasy(event.y), bounds, (width, height)
        )
        if point is None:
            return
        if len(points) == 2:
            points.clear()
        points.append(point)
        if len(points) == 1:
            status.set("もう一方の端をクリックしてください")
        draw_points()

    def clear_points() -> None:
        points.clear()
        draw_points()
        status.set("既知寸法の両端をクリックしてください")

    def change_mode(event=None) -> None:
        canvas.xview_moveto(0)
        canvas.yview_moveto(0)
        draw_image()

    def apply() -> None:
        nonlocal result
        try:
            result = calibration_from_points(reference.get(), points, (width, height))
        except ValueError as error:
            status.set(str(error))
            return
        result["image_path"] = str(image_path)
        window.destroy()

    ttk.Label(window, text=str(image_path), padding=(12, 8), wraplength=1000).pack(
        fill="x"
    )
    controls = ttk.Frame(window, padding=(12, 0))
    controls.pack(fill="x")
    ttk.Label(controls, text="基準物の実寸 (mm)").pack(side="left", padx=(0, 8))
    ttk.Entry(controls, textvariable=reference, width=16).pack(side="left")
    ttk.Label(controls, text="表示").pack(side="left", padx=(16, 8))
    mode_box = ttk.Combobox(
        controls, textvariable=mode, values=("全体", "100%"), state="readonly", width=8
    )
    mode_box.pack(side="left")
    ttk.Button(controls, text="点を消す", command=clear_points).pack(
        side="left", padx=8
    )
    frame = ttk.Frame(window, padding=12)
    frame.pack(fill="both", expand=True)
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    canvas = tk.Canvas(frame, background="#242424", highlightthickness=0)
    canvas.grid(row=0, column=0, sticky="nsew")
    vertical = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
    vertical.grid(row=0, column=1, sticky="ns")
    horizontal = ttk.Scrollbar(frame, orient="horizontal", command=canvas.xview)
    horizontal.grid(row=1, column=0, sticky="ew")
    canvas.configure(xscrollcommand=horizontal.set, yscrollcommand=vertical.set)
    ttk.Label(window, textvariable=status, padding=(12, 0), wraplength=1000).pack(
        fill="x"
    )
    actions = ttk.Frame(window, padding=12)
    actions.pack(fill="x")
    ttk.Button(actions, text="この校正を使う", command=apply, padding=(12, 8)).pack(
        side="left"
    )
    ttk.Button(
        actions, text="キャンセル", command=window.destroy, padding=(12, 8)
    ).pack(side="left", padx=8)
    canvas.bind("<Button-1>", click)
    canvas.bind("<Configure>", draw_image)
    mode_box.bind("<<ComboboxSelected>>", change_mode)
    reference.trace_add("write", update_scale)
    window.grab_set()
    window.wait_window()
    return result


def compare_lengths(
    samples: list[dict],
    initial_length_mm: float | str | None,
    initial_thickness_mm: float | str | None,
) -> list[dict]:
    initial_length_mm = positive_value(initial_length_mm, "初期区間長 (mm)")
    initial_thickness_mm = positive_value(initial_thickness_mm, "初期厚さ (mm)")
    if not samples:
        raise ValueError("03の長さCSVを1枚以上追加してください")
    names = []
    paths = []
    rows = []
    previous = None
    for sample in samples:
        name = sample["sample_id"].strip()
        if not name or name in names:
            raise ValueError("撮影名は空欄にせず、重複しない名前にしてください")
        path = Path(sample["csv_path"]).resolve()
        if path in paths:
            raise ValueError("同じCSVを重複して指定しないでください")
        names.append(name)
        paths.append(path)
        thickness = positive_value(sample["thickness_mm"], f"{name}の厚さ (mm)")
        calibration = sample["calibration"]
        if calibration is None:
            raise ValueError(f"{name}: 元画像の既知寸法から校正してください")
        scale = calibration_from_points(
            calibration["reference_mm"],
            calibration["points"],
            (calibration["image_width"], calibration["image_height"]),
        )
        lengths, measurement_range = read_lengths(path)
        start_y, end_y = measurement_range
        if end_y >= scale["image_height"]:
            raise ValueError(f"{name}: CSVの計測範囲が校正画像の高さを超えています")
        elongation = positive_value(
            initial_thickness_mm / thickness, f"{name}の伸び倍率"
        )
        ideal_length = positive_value(
            initial_length_mm * elongation, f"{name}の理想区間長"
        )
        row = {
            "sample_id": name,
            "input_csv": str(path),
            "image_path": str(Path(calibration["image_path"]).resolve()),
            "initial_length_mm": initial_length_mm,
            "initial_thickness_mm": initial_thickness_mm,
            "thickness_mm": thickness,
            "elongation": elongation,
            "ideal_length_mm": ideal_length,
            "reference_mm": scale["reference_mm"],
            "reference_px": scale["reference_px"],
            "mm_per_px": scale["mm_per_px"],
            "reference_x1": scale["points"][0][0],
            "reference_y1": scale["points"][0][1],
            "reference_x2": scale["points"][1][0],
            "reference_y2": scale["points"][1][1],
            "image_width": scale["image_width"],
            "image_height": scale["image_height"],
            "start_y": start_y,
            "end_y": end_y,
            "previous_id": previous["sample_id"] if previous is not None else "",
        }
        for edge in ("left", "right", "total"):
            measured = positive_value(
                lengths[edge] * scale["mm_per_px"], f"{name}の実寸側辺長"
            )
            ideal = ideal_length * 2 if edge == "total" else ideal_length
            ideal = positive_value(ideal, f"{name}の理想側辺長")
            difference = measured - ideal
            ratio = difference / ideal * 100
            if not math.isfinite(ratio):
                raise ValueError(f"{name}: 理想長との差率を計算できません")
            previous_difference = None
            if previous is not None:
                previous_difference = measured - previous[f"{edge}_mm"]
            row[f"{edge}_px"] = lengths[edge]
            row[f"{edge}_mm"] = measured
            row[f"delta_{edge}_mm"] = difference
            row[f"delta_{edge}_pct"] = ratio
            row[f"previous_delta_{edge}_mm"] = previous_difference
        rows.append(row)
        previous = row
    return rows


def check_output(path: Path, rows: list[dict], suffix: str) -> Path:
    if not rows:
        raise ValueError("比較してから保存してください")
    path = path.resolve()
    if path.suffix.lower() != suffix:
        raise ValueError(f"保存先の拡張子は {suffix} にしてください")
    for row in rows:
        if path in (Path(row["input_csv"]), Path(row["image_path"])):
            raise ValueError("入力CSV・校正画像と別の保存先を選んでください")
    return path


def write_csv(path: Path, rows: list[dict]) -> None:
    path = check_output(path, rows, ".csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            saved = row.copy()
            for column, value in row.items():
                if value is None:
                    saved[column] = ""
                elif isinstance(value, float):
                    saved[column] = f"{value:.12g}"
            writer.writerow(saved)


def create_graph(rows: list[dict]) -> Figure:
    rcParams["font.sans-serif"] = ["Meiryo", "DejaVu Sans"]
    figure = Figure(figsize=(max(8, len(rows) * 0.9), 9), layout="constrained")
    axes = figure.subplots(3, 1, sharex=True)
    positions = list(range(len(rows)))
    names = []
    ideal_lengths = []
    for row in rows:
        names.append(row["sample_id"])
        ideal_lengths.append(row["ideal_length_mm"])
    for axis, prefix, suffix, title in (
        (axes[0], "", "mm", "実寸側辺長と理想区間長"),
        (axes[1], "delta_", "pct", "理想長との差率"),
        (axes[2], "previous_delta_", "mm", "前回からの実寸側辺長の変化"),
    ):
        for edge, label in (("left", "左"), ("right", "右"), ("total", "左右合計")):
            if not prefix and edge == "total":
                continue
            values = []
            for row in rows:
                value = row[f"{prefix}{edge}_{suffix}"]
                values.append(math.nan if value is None else value)
            axis.plot(positions, values, marker="o", label=label)
        if not prefix:
            axis.plot(
                positions,
                ideal_lengths,
                linestyle="--",
                color="black",
                marker="s",
                label="理想区間長",
            )
            axis.set_ylim(bottom=0)
            axis.set_ylabel("長さ (mm)")
        else:
            axis.axhline(0, color="gray", linewidth=1)
            axis.set_ylabel("差率 (%)" if suffix == "pct" else "差 (mm)")
        axis.set_title(title)
        axis.grid(alpha=0.3)
        axis.legend()
    axes[2].set_xticks(
        positions,
        names,
        rotation=45 if len(rows) > 4 else 0,
        ha="right" if len(rows) > 4 else "center",
    )
    axes[2].set_xlabel("撮影順（対応する同じ材料区間）")
    figure.suptitle(
        f"幅一定・体積一定の基準スラブ | 初期区間長 {rows[0]['initial_length_mm']:g}mm / "
        f"初期厚さ {rows[0]['initial_thickness_mm']:g}mm"
    )
    return figure


def write_graph(path: Path, rows: list[dict]) -> None:
    path = check_output(path, rows, ".png")
    figure = create_graph(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=160)


def main() -> None:
    directory = Path(__file__).resolve().parent
    root = tk.Tk()
    root.title("スラブ基準と画像ごとの実寸比較")
    root.geometry("1160x820")
    root.minsize(1060, 760)
    samples = []
    rows = []
    graph_window = None
    initial_length = tk.StringVar()
    initial_thickness = tk.StringVar()
    sample_name = tk.StringVar()
    sample_thickness = tk.StringVar()
    selected_csv = tk.StringVar()
    selected_image = tk.StringVar()
    status = tk.StringVar(
        value="初期区間長・初期厚さを入れ、対応する同じ材料区間のCSVを追加してください"
    )

    def invalidate_result() -> None:
        nonlocal graph_window
        if graph_window is not None:
            graph_window.destroy()
            graph_window = None
        rows.clear()
        for table in result_tables.values():
            table.delete(*table.get_children())
        for button in (preview_button, csv_button, graph_button):
            button.state(["disabled"])

    def model_changed(*args) -> None:
        invalidate_result()
        status.set("初期スラブの条件を変更しました。比較し直してください")

    def select_sample(event=None) -> None:
        selection = input_table.selection()
        if len(selection) == 1:
            sample = samples[int(selection[0])]
            sample_name.set(sample["sample_id"])
            thickness = sample["thickness_mm"]
            sample_thickness.set("" if thickness is None else f"{thickness:g}")
            selected_csv.set(str(sample["csv_path"]))
            calibration = sample["calibration"]
            selected_image.set(
                calibration["image_path"] if calibration is not None else ""
            )
        else:
            sample_name.set("")
            sample_thickness.set("")
            selected_csv.set("")
            selected_image.set("")

    def refresh_inputs(selection: int | None = None) -> None:
        input_table.delete(*input_table.get_children())
        for index, sample in enumerate(samples):
            path = sample["csv_path"]
            short_path = f"{path.parent.parent.name}/{path.parent.name}/{path.name}"
            thickness = sample["thickness_mm"]
            calibration = sample["calibration"]
            factor = (
                "未校正" if calibration is None else f"{calibration['mm_per_px']:.8g}"
            )
            input_table.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    index + 1,
                    sample["sample_id"],
                    "未入力" if thickness is None else f"{thickness:g}",
                    factor,
                    short_path,
                ),
            )
        if selection is not None:
            input_table.selection_set(str(selection))
            input_table.see(str(selection))
        select_sample()

    def add_csvs() -> None:
        selected = filedialog.askopenfilenames(
            parent=root,
            title="対応する同じ材料区間の03のCSVを選ぶ",
            initialdir=directory,
            filetypes=[("CSV", "*.csv")],
        )
        if not selected:
            return
        existing_paths = []
        names = []
        for sample in samples:
            existing_paths.append(sample["csv_path"])
            names.append(sample["sample_id"])
        new_paths = []
        try:
            for filename in selected:
                path = Path(filename).resolve()
                if path in existing_paths or path in new_paths:
                    continue
                read_lengths(path)
                new_paths.append(path)
        except (OSError, ValueError, csv.Error) as error:
            status.set(str(error))
            return
        if not new_paths:
            status.set("同じCSVは重複して追加しません")
            return
        for path in new_paths:
            number = len(samples) + 1
            name = f"撮影{number:02d}"
            while name in names:
                number += 1
                name = f"撮影{number:02d}"
            samples.append(
                {
                    "sample_id": name,
                    "csv_path": path,
                    "thickness_mm": None,
                    "calibration": None,
                }
            )
            names.append(name)
        refresh_inputs()
        invalidate_result()
        status.set(
            "各行を選び、厚さを入力・適用し、その画像の既知寸法から校正してください"
        )

    def remove_samples() -> None:
        selection = input_table.selection()
        if not selection:
            status.set("削除する行を選んでください")
            return
        indices = []
        for item in selection:
            indices.append(int(item))
        for index in sorted(indices, reverse=True):
            del samples[index]
        refresh_inputs()
        invalidate_result()
        status.set(f"選択したCSVを削除しました。残り{len(samples)}枚です")

    def move_sample(direction: int) -> None:
        selection = input_table.selection()
        if len(selection) != 1:
            status.set("移動する行を1つ選んでください")
            return
        index = int(selection[0])
        new_index = index + direction
        if not 0 <= new_index < len(samples):
            return
        moved = samples[index]
        samples[index] = samples[new_index]
        samples[new_index] = moved
        refresh_inputs(new_index)
        invalidate_result()
        status.set("撮影順を変更しました。比較し直してください")

    def move_up() -> None:
        move_sample(-1)

    def move_down() -> None:
        move_sample(1)

    def apply_sample() -> None:
        selection = input_table.selection()
        if len(selection) != 1:
            status.set("条件を設定する行を1つ選んでください")
            return
        index = int(selection[0])
        name = sample_name.get().strip()
        if not name:
            status.set("撮影名を入力してください")
            return
        for other_index, sample in enumerate(samples):
            if other_index != index and sample["sample_id"] == name:
                status.set("撮影名が重複しています")
                return
        try:
            thickness = positive_value(sample_thickness.get(), "撮影時の厚さ (mm)")
        except ValueError as error:
            status.set(str(error))
            return
        if (
            samples[index]["sample_id"] == name
            and samples[index]["thickness_mm"] == thickness
        ):
            return
        samples[index]["sample_id"] = name
        samples[index]["thickness_mm"] = thickness
        refresh_inputs(index)
        invalidate_result()
        status.set("撮影名と厚さを設定しました。比較し直してください")

    def calibrate_sample() -> None:
        selection = input_table.selection()
        if len(selection) != 1:
            status.set("校正する行を1つ選んでください")
            return
        index = int(selection[0])
        selected = filedialog.askopenfilename(
            parent=root,
            title="選択したCSVを計測した元画像を選ぶ",
            initialdir=directory,
            filetypes=[
                ("画像", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff"),
                ("すべて", "*.*"),
            ],
        )
        if not selected:
            return
        try:
            calibration = calibrate_image(
                root, Path(selected), samples[index]["calibration"]
            )
        except (OSError, ValueError) as error:
            status.set(str(error))
            return
        if calibration is None:
            return
        samples[index]["calibration"] = calibration
        refresh_inputs(index)
        invalidate_result()
        status.set(
            f"画像を校正しました: {calibration['mm_per_px']:.8g}mm/px。比較し直してください"
        )

    def compare() -> None:
        nonlocal rows
        invalidate_result()
        try:
            rows = compare_lengths(
                samples, initial_length.get(), initial_thickness.get()
            )
        except (OSError, ValueError, csv.Error) as error:
            status.set(str(error))
            return
        for row in rows:
            for key, table in result_tables.items():
                values = [row["sample_id"]]
                if key == "length":
                    values.append(f"{row['ideal_length_mm']:.3f}")
                    prefix, suffix = "", "mm"
                elif key == "ideal":
                    prefix, suffix = "delta_", "mm"
                elif key == "ratio":
                    prefix, suffix = "delta_", "pct"
                else:
                    prefix, suffix = "previous_delta_", "mm"
                for edge in ("left", "right", "total"):
                    value = row[f"{prefix}{edge}_{suffix}"]
                    if value is None:
                        text = "—"
                    elif prefix:
                        text = f"{value:+.3f}"
                    else:
                        text = f"{value:.3f}"
                    values.append(text)
                table.insert("", "end", values=values)
        for button in (preview_button, csv_button, graph_button):
            button.state(["!disabled"])
        status.set(
            "比較しました。理想との差は「実寸 − 理想」、前回差は「実寸 − 前回の実寸」です"
        )

    def save(suffix: str) -> None:
        if not rows:
            return
        selected = filedialog.asksaveasfilename(
            parent=root,
            title="スラブ基準の比較結果を保存",
            initialdir=directory,
            initialfile=f"slab_length_comparison{suffix}",
            defaultextension=suffix,
            filetypes=[("比較結果", f"*{suffix}")],
        )
        if not selected:
            return
        try:
            if suffix == ".csv":
                write_csv(Path(selected), rows)
            else:
                write_graph(Path(selected), rows)
        except (OSError, ValueError, csv.Error) as error:
            status.set(str(error))
            return
        status.set(f"保存しました: {selected}")

    def save_csv() -> None:
        save(".csv")

    def save_graph() -> None:
        save(".png")

    def show_graph() -> None:
        nonlocal graph_window
        if not rows:
            return
        if graph_window is not None:
            graph_window.lift()
            return
        window = tk.Toplevel(root)
        graph_window = window
        window.title("理想スラブと実寸の推移")
        width = min(1100, root.winfo_screenwidth() - 80)
        height = min(900, root.winfo_screenheight() - 120)
        left = max(0, (root.winfo_screenwidth() - width) // 2)
        window.geometry(f"{width}x{height}+{left}+20")
        window.minsize(800, 650)
        figure = create_graph(rows)
        canvas = FigureCanvasTkAgg(figure, master=window)
        canvas.get_tk_widget().pack(fill="both", expand=True)
        window.update_idletasks()
        canvas.draw()

        def close_graph() -> None:
            nonlocal graph_window
            window.destroy()
            graph_window = None

        window.protocol("WM_DELETE_WINDOW", close_graph)

    model = ttk.Frame(root, padding=12)
    model.pack(fill="x")
    ttk.Label(model, text="初期区間長 (mm)").pack(side="left", padx=(0, 8))
    ttk.Entry(model, textvariable=initial_length, width=16).pack(side="left")
    ttk.Label(model, text="初期厚さ (mm)").pack(side="left", padx=(24, 8))
    ttk.Entry(model, textvariable=initial_thickness, width=16).pack(side="left")
    ttk.Label(
        root,
        text="理想の片側長 = 初期区間長 × 初期厚さ ÷ 各回の厚さ（幅一定・体積一定）",
        padding=(12, 0),
    ).pack(anchor="w")
    toolbar = ttk.Frame(root, padding=(12, 8))
    toolbar.pack(fill="x")
    for label, command in (
        ("CSVを追加", add_csvs),
        ("選択を削除", remove_samples),
        ("上へ", move_up),
        ("下へ", move_down),
        ("比較する", compare),
    ):
        ttk.Button(toolbar, text=label, command=command, padding=(12, 8)).pack(
            side="left", padx=(0, 8)
        )
    ttk.Label(
        root,
        text="撮影順（上から順に。同じ材料区間を各画像で計測。Ctrl・Shiftで複数削除）",
        padding=(12, 0),
    ).pack(anchor="w")
    input_frame = ttk.Frame(root, padding=(12, 8))
    input_frame.pack(fill="both", expand=True)
    input_table = ttk.Treeview(
        input_frame,
        columns=("order", "name", "thickness", "scale", "path"),
        show="headings",
        selectmode="extended",
        height=4,
    )
    for column, label, width in (
        ("order", "順番", 50),
        ("name", "撮影名", 140),
        ("thickness", "厚さ (mm)", 100),
        ("scale", "mm/px", 130),
        ("path", "計測CSV", 620),
    ):
        input_table.heading(column, text=label)
        input_table.column(column, width=width, stretch=column == "path")
    input_table.pack(side="left", fill="both", expand=True)
    input_scroll = ttk.Scrollbar(
        input_frame, orient="vertical", command=input_table.yview
    )
    input_scroll.pack(side="right", fill="y")
    input_table.configure(yscrollcommand=input_scroll.set)
    for label, variable in (
        ("選択中のCSV", selected_csv),
        ("校正した元画像", selected_image),
    ):
        frame = ttk.Frame(root, padding=(12, 2))
        frame.pack(fill="x")
        ttk.Label(frame, text=label, width=14).pack(side="left", padx=(0, 8))
        ttk.Entry(frame, textvariable=variable, state="readonly").pack(
            side="left", fill="x", expand=True
        )
    editor = ttk.Frame(root, padding=(12, 8))
    editor.pack(fill="x")
    ttk.Label(editor, text="撮影名").pack(side="left", padx=(0, 8))
    ttk.Entry(editor, textvariable=sample_name, width=20).pack(side="left")
    ttk.Label(editor, text="撮影時の厚さ (mm)").pack(side="left", padx=(16, 8))
    ttk.Entry(editor, textvariable=sample_thickness, width=12).pack(side="left")
    ttk.Button(editor, text="撮影名・厚さを適用", command=apply_sample).pack(
        side="left", padx=8
    )
    ttk.Button(editor, text="既知寸法から校正", command=calibrate_sample).pack(
        side="left", padx=8
    )
    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=12, pady=8)
    result_tables = {}
    for key, title, unit in (
        ("length", "実寸 (mm)", "mm"),
        ("ideal", "理想との差 (mm)", "mm"),
        ("ratio", "理想との差率 (%)", "%"),
        ("previous", "前回との差 (mm)", "mm"),
    ):
        frame = ttk.Frame(notebook)
        notebook.add(frame, text=title)
        columns = ["name"]
        if key == "length":
            columns.append("ideal")
        columns.extend(("left", "right", "total"))
        table = ttk.Treeview(frame, columns=columns, show="headings", height=5)
        for column in columns:
            if column == "name":
                label = "撮影名"
            elif column == "ideal":
                label = "理想片側長 (mm)"
            else:
                labels = {"left": "左", "right": "右", "total": "左右合計"}
                label = f"{labels[column]} ({unit})"
            table.heading(column, text=label)
            table.column(column, width=200, anchor="w" if column == "name" else "e")
        table.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=table.yview)
        scrollbar.pack(side="right", fill="y")
        table.configure(yscrollcommand=scrollbar.set)
        result_tables[key] = table
    actions = ttk.Frame(root, padding=(12, 8))
    actions.pack(fill="x")
    preview_button = ttk.Button(
        actions,
        text="推移グラフを表示",
        command=show_graph,
        state="disabled",
        padding=(12, 8),
    )
    preview_button.pack(side="left", padx=(0, 8))
    csv_button = ttk.Button(
        actions,
        text="比較CSVを保存",
        command=save_csv,
        state="disabled",
        padding=(12, 8),
    )
    csv_button.pack(side="left")
    graph_button = ttk.Button(
        actions,
        text="推移グラフを保存",
        command=save_graph,
        state="disabled",
        padding=(12, 8),
    )
    graph_button.pack(side="left", padx=8)
    ttk.Label(root, textvariable=status, padding=12, wraplength=1020).pack(fill="x")
    input_table.bind("<<TreeviewSelect>>", select_sample)
    initial_length.trace_add("write", model_changed)
    initial_thickness.trace_add("write", model_changed)
    root.mainloop()


if __name__ == "__main__":
    main()
