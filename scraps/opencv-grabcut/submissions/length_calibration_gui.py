"""元画像の既知寸法で校正し、03の長さをmm換算したCSVに保存する."""

import csv
import math
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

import cv2 as cv
import numpy as np


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


def calibrate_lengths(csv_path: Path, calibration: dict) -> dict:
    csv_path = csv_path.resolve()
    lengths, measurement_range = read_lengths(csv_path)
    scale = calibration_from_points(
        calibration["reference_mm"],
        calibration["points"],
        (calibration["image_width"], calibration["image_height"]),
    )
    start_y, end_y = measurement_range
    if end_y >= scale["image_height"]:
        raise ValueError("CSVの計測範囲が校正画像の高さを超えています")
    row = {
        "input_csv": str(csv_path),
        "image_path": str(Path(calibration["image_path"]).resolve()),
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
    }
    for edge in ("left", "right", "total"):
        measured_mm = lengths[edge] * scale["mm_per_px"]
        row[f"{edge}_px"] = lengths[edge]
        row[f"{edge}_mm"] = positive_value(measured_mm, f"{edge}の実寸側辺長")
    return row


def write_csv(path: Path, row: dict) -> None:
    if not row:
        raise ValueError("校正してmm換算した後に保存してください")
    path = path.resolve()
    if path.suffix.lower() != ".csv":
        raise ValueError("保存先の拡張子は .csv にしてください")
    if path in (Path(row["input_csv"]), Path(row["image_path"])):
        raise ValueError("入力CSV・校正画像と別の保存先を選んでください")
    saved = row.copy()
    for column, value in row.items():
        if isinstance(value, float):
            saved[column] = f"{value:.12g}"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(saved)


def main() -> None:
    directory = Path(__file__).resolve().parent
    root = tk.Tk()
    root.title("画像ごとの校正と長さのmm換算")
    root.geometry("920x460")
    root.minsize(800, 440)
    csv_path = None
    image_path = None
    calibration = None
    row = {}
    selected_csv = tk.StringVar()
    selected_image = tk.StringVar()
    scale_text = tk.StringVar(value="未校正")
    status = tk.StringVar(value="03の長さCSVと、それを計測した元画像を選んでください")

    def invalidate_result() -> None:
        row.clear()
        table.delete(*table.get_children())
        save_button.state(["disabled"])

    def update_result() -> None:
        nonlocal row
        invalidate_result()
        if csv_path is None or calibration is None:
            return
        try:
            row = calibrate_lengths(csv_path, calibration)
        except (OSError, ValueError, csv.Error) as error:
            status.set(str(error))
            return
        for edge, label in (("left", "左"), ("right", "右"), ("total", "左右合計")):
            table.insert(
                "",
                "end",
                values=(label, f"{row[f'{edge}_px']:.3f}", f"{row[f'{edge}_mm']:.3f}"),
            )
        save_button.state(["!disabled"])
        status.set("mm換算しました。校正済みCSVを保存して比較GUIへ渡してください")

    def choose_csv() -> None:
        nonlocal csv_path, image_path, calibration
        selected = filedialog.askopenfilename(
            parent=root,
            title="03の長さCSVを選ぶ",
            initialdir=directory,
            filetypes=[("CSV", "*.csv")],
        )
        if not selected:
            return
        path = Path(selected).resolve()
        try:
            read_lengths(path)
        except (OSError, ValueError, csv.Error) as error:
            status.set(str(error))
            return
        if path != csv_path:
            image_path = None
            calibration = None
            selected_image.set("")
            scale_text.set("未校正")
        csv_path = path
        selected_csv.set(str(path))
        status.set("このCSVを計測した元画像を選び、既知寸法から校正してください")
        update_result()

    def choose_image() -> None:
        nonlocal image_path, calibration
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
        path = Path(selected).resolve()
        try:
            image = cv.imdecode(
                np.frombuffer(path.read_bytes(), np.uint8), cv.IMREAD_COLOR
            )
            if image is None or min(image.shape[:2]) < 2:
                raise ValueError(f"校正できる画像を読み込めません: {path}")
        except (OSError, ValueError) as error:
            status.set(str(error))
            return
        image_path = path
        calibration = None
        selected_image.set(str(path))
        scale_text.set("未校正")
        invalidate_result()
        status.set("既知寸法から校正を押して、定規などの両端と実寸を指定してください")

    def calibrate() -> None:
        nonlocal calibration
        if csv_path is None or image_path is None:
            status.set("03の長さCSVと元画像を選んでください")
            return
        try:
            result = calibrate_image(root, image_path, calibration)
        except (OSError, ValueError) as error:
            status.set(str(error))
            return
        if result is None:
            return
        calibration = result
        scale_text.set(
            f"{calibration['reference_mm']:g}mm / "
            f"{calibration['reference_px']:.3f}px = "
            f"{calibration['mm_per_px']:.8g}mm/px"
        )
        update_result()

    def save() -> None:
        if not row or csv_path is None:
            return
        selected = filedialog.asksaveasfilename(
            parent=root,
            title="校正済みの長さCSVを保存",
            initialdir=csv_path.parent,
            initialfile="calibrated_lengths.csv",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
        )
        if not selected:
            return
        # 元の長さCSVを読み直し、保存時にも現在の測定値を使う。
        update_result()
        if not row:
            return
        try:
            write_csv(Path(selected), row)
        except (OSError, ValueError, csv.Error) as error:
            status.set(str(error))
            return
        status.set(f"保存しました: {selected}")

    ttk.Label(
        root,
        text="画像ごとに既知寸法で校正し、03のpx測定値をmmへ換算します。",
        padding=12,
    ).pack(anchor="w")
    for label, variable, command in (
        ("03の長さCSV", selected_csv, choose_csv),
        ("計測した元画像", selected_image, choose_image),
    ):
        frame = ttk.Frame(root, padding=(12, 4))
        frame.pack(fill="x")
        ttk.Label(frame, text=label, width=16).pack(side="left")
        ttk.Entry(frame, textvariable=variable, state="readonly").pack(
            side="left", fill="x", expand=True, padx=8
        )
        ttk.Button(frame, text="選ぶ", command=command).pack(side="left")
    controls = ttk.Frame(root, padding=12)
    controls.pack(fill="x")
    ttk.Button(
        controls, text="既知寸法から校正", command=calibrate, padding=(12, 8)
    ).pack(side="left")
    ttk.Label(controls, textvariable=scale_text, padding=(16, 0)).pack(side="left")
    frame = ttk.Frame(root, padding=(12, 0))
    frame.pack(fill="both", expand=True)
    table = ttk.Treeview(frame, columns=("edge", "px", "mm"), show="headings", height=3)
    for column, label in (
        ("edge", "側辺"),
        ("px", "測定長 (px)"),
        ("mm", "実寸長 (mm)"),
    ):
        table.heading(column, text=label)
        table.column(column, width=200, anchor="w" if column == "edge" else "e")
    table.pack(fill="both", expand=True)
    actions = ttk.Frame(root, padding=12)
    actions.pack(fill="x")
    save_button = ttk.Button(
        actions,
        text="校正済みCSVを保存",
        command=save,
        state="disabled",
        padding=(12, 8),
    )
    save_button.pack(side="left")
    ttk.Label(root, textvariable=status, padding=12, wraplength=780).pack(fill="x")
    root.mainloop()


if __name__ == "__main__":
    main()
