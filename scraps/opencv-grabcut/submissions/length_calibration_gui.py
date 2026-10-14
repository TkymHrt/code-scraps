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
    x: float, y: float, view: tuple, image_size: tuple[int, int]
) -> tuple[float, float] | None:
    offset_x, offset_y, scale = view
    width, height = image_size
    image_x = (x - offset_x) / scale
    image_y = (y - offset_y) / scale
    if 0 <= image_x <= width - 1 and 0 <= image_y <= height - 1:
        return image_x, image_y
    return None


def zoomed_view(view: tuple, anchor: tuple, factor: float) -> tuple:
    offset_x, offset_y, scale = view
    anchor_x, anchor_y = anchor
    new_scale = min(16.0, max(0.01, scale * factor))
    change = new_scale / scale
    # カーソル直下の元画像座標を、拡大・縮小の前後で同じ位置に保つ。
    new_x = anchor_x - (anchor_x - offset_x) * change
    new_y = anchor_y - (anchor_y - offset_y) * change
    return new_x, new_y, new_scale


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
    root.geometry("1160x820")
    root.minsize(1000, 700)
    csv_path = None
    image_path = None
    image = None
    width, height = 0, 0
    points = []
    view = (0.0, 0.0, 1.0)
    photo = None
    pan_start = None
    row = {}
    selected_csv = tk.StringVar(value="未読込")
    selected_image = tk.StringVar(value="未読込")
    reference = tk.StringVar()
    scale_text = tk.StringVar(value="未校正")
    status = tk.StringVar(value="03の長さCSVと、それを計測した元画像を選んでください")

    def update_result(*args) -> None:
        nonlocal row
        row = {}
        table.delete(*table.get_children())
        save_button.state(["disabled"])
        scale_text.set("未校正")
        if csv_path is None or image is None:
            status.set("03の長さCSVと元画像を選んでください")
            return
        if len(points) != 2:
            status.set(f"既知寸法の両端をクリックしてください（{len(points)}/2点）")
            return
        try:
            calibration = {
                "reference_mm": reference.get(),
                "points": points,
                "image_width": width,
                "image_height": height,
                "image_path": str(image_path),
            }
            row = calibrate_lengths(csv_path, calibration)
        except (OSError, ValueError, csv.Error) as error:
            message = str(error)
            message = message.replace(str(csv_path), csv_path.name)
            message = message.replace(repr(str(csv_path)), repr(csv_path.name))
            status.set(message)
            return
        scale_text.set(
            f"基準物: {row['reference_mm']:g}mm\n"
            f"画像上: {row['reference_px']:.3f}px\n"
            f"換算値: {row['mm_per_px']:.8g}mm/px"
        )
        for edge, label in (("left", "左"), ("right", "右"), ("total", "左右合計")):
            table.insert(
                "",
                "end",
                values=(label, f"{row[f'{edge}_px']:.3f}", f"{row[f'{edge}_mm']:.3f}"),
            )
        save_button.state(["!disabled"])
        status.set("mm換算しました。校正済みCSVを保存して比較GUIへ渡してください")

    def draw_points() -> None:
        canvas.delete("reference")
        offset_x, offset_y, scale = view
        display_points = []
        for index, (x, y) in enumerate(points):
            display_x = offset_x + x * scale
            display_y = offset_y + y * scale
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

    def draw_image(event=None) -> None:
        nonlocal photo
        canvas.delete("all")
        if image is None:
            photo = None
            return
        canvas_width = max(2, canvas.winfo_width())
        canvas_height = max(2, canvas.winfo_height())
        offset_x, offset_y, scale = view
        transform = np.array(
            [[scale, 0, offset_x], [0, scale, offset_y]], dtype=np.float64
        )
        interpolation = cv.INTER_NEAREST if scale >= 1 else cv.INTER_LINEAR
        # 表示範囲だけを作り、大きく拡大しても巨大な画像を確保しない。
        shown = cv.warpAffine(
            image,
            transform,
            (canvas_width, canvas_height),
            flags=interpolation,
            borderValue=(36, 36, 36),
        )
        success, encoded = cv.imencode(".png", shown)
        if not success:
            raise ValueError("画像の表示データを作れません")
        photo = tk.PhotoImage(master=root, data=encoded.tobytes(), format="PNG")
        canvas.create_image(0, 0, image=photo, anchor="nw", tags="source")
        canvas.create_rectangle(
            offset_x,
            offset_y,
            offset_x + (width - 1) * scale,
            offset_y + (height - 1) * scale,
            outline="#666666",
            tags="image_bounds",
        )
        draw_points()

    def wheel(event) -> str:
        nonlocal view
        if image is not None:
            view = zoomed_view(view, (event.x, event.y), 1.1 ** (event.delta / 120))
            draw_image()
        return "break"

    def focus_canvas(event) -> None:
        canvas.focus_set()

    def start_pan(event) -> None:
        nonlocal pan_start
        if image is not None:
            pan_start = (event.x, event.y)

    def pan(event) -> None:
        nonlocal view, pan_start
        if pan_start is None:
            return
        offset_x, offset_y, scale = view
        moved_x = offset_x + event.x - pan_start[0]
        moved_y = offset_y + event.y - pan_start[1]
        view = (moved_x, moved_y, scale)
        pan_start = (event.x, event.y)
        draw_image()

    def end_pan(event) -> None:
        nonlocal pan_start
        pan_start = None

    def click(event) -> None:
        if image is None:
            return
        point = point_on_image(event.x, event.y, view, (width, height))
        if point is None:
            return
        if len(points) == 2:
            points.clear()
        points.append(point)
        draw_points()
        update_result()

    def choose_csv() -> None:
        nonlocal csv_path, image_path, image, pan_start
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
            message = str(error)
            message = message.replace(str(path), path.name)
            message = message.replace(repr(str(path)), repr(path.name))
            status.set(message)
            return
        if path != csv_path:
            image_path = None
            image = None
            pan_start = None
            points.clear()
            selected_image.set("未読込")
            reference.set("")
            draw_image()
        csv_path = path
        selected_csv.set(path.name)
        update_result()

    def choose_image() -> None:
        nonlocal image_path, image, width, height, view, pan_start
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
            loaded = cv.imdecode(
                np.frombuffer(path.read_bytes(), np.uint8), cv.IMREAD_COLOR
            )
            if loaded is None or min(loaded.shape[:2]) < 2:
                raise ValueError(f"校正できる画像を読み込めません: {path}")
        except (OSError, ValueError) as error:
            message = str(error)
            message = message.replace(str(path), path.name)
            message = message.replace(repr(str(path)), repr(path.name))
            status.set(message)
            return
        image_path = path
        image = loaded
        height, width = image.shape[:2]
        pan_start = None
        points.clear()
        selected_image.set(f"{path.name}  ({width} × {height} px)")
        reference.set("")
        # 読み込んだときだけ全体を収め、以後は手動で倍率・位置を調整する。
        scale = min(
            1.0,
            max(2, canvas.winfo_width() - 24) / width,
            max(2, canvas.winfo_height() - 24) / height,
        )
        offset_x = (canvas.winfo_width() - 1 - (width - 1) * scale) / 2
        offset_y = (canvas.winfo_height() - 1 - (height - 1) * scale) / 2
        view = (offset_x, offset_y, scale)
        draw_image()
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
        destination = Path(selected)
        try:
            write_csv(destination, row)
        except (OSError, ValueError, csv.Error) as error:
            message = str(error)
            message = message.replace(str(destination), destination.name)
            message = message.replace(repr(str(destination)), repr(destination.name))
            status.set(message)
            return
        status.set(f"保存しました: {destination.name}")

    file_toolbar = ttk.Frame(root, padding=(12, 8))
    file_toolbar.pack(fill="x")
    file_toolbar.columnconfigure(1, weight=1)
    for row_number, (label, variable, command) in enumerate(
        (
            ("03の長さCSVを読み込む", selected_csv, choose_csv),
            ("画像を読み込む", selected_image, choose_image),
        )
    ):
        ttk.Button(file_toolbar, text=label, width=24, command=command).grid(
            row=row_number, column=0, sticky="w", pady=4
        )
        ttk.Label(file_toolbar, textvariable=variable, wraplength=320).grid(
            row=row_number, column=1, sticky="w", padx=8, pady=4
        )
    ttk.Label(
        file_toolbar,
        textvariable=status,
        wraplength=380,
        justify="right",
        anchor="e",
    ).grid(row=0, column=2, rowspan=2, sticky="e", padx=(16, 0))
    body = ttk.Frame(root, padding=(12, 8, 12, 12))
    body.pack(fill="both", expand=True)
    sidebar = ttk.Frame(body)
    sidebar.pack(side="left", fill="y", padx=(0, 16))
    ttk.Label(sidebar, text="基準物の実寸 (mm)").pack(anchor="w", pady=(0, 4))
    ttk.Entry(sidebar, textvariable=reference).pack(fill="x", pady=(0, 16))
    ttk.Label(sidebar, text="校正結果").pack(anchor="w", pady=(16, 4))
    ttk.Label(sidebar, textvariable=scale_text, wraplength=288).pack(anchor="w")
    table = ttk.Treeview(
        sidebar, columns=("edge", "px", "mm"), show="headings", height=3
    )
    for column, label, column_width in (
        ("edge", "側辺", 64),
        ("px", "測定長 (px)", 112),
        ("mm", "実寸長 (mm)", 112),
    ):
        table.heading(column, text=label)
        table.column(
            column,
            width=column_width,
            stretch=False,
            anchor="w" if column == "edge" else "e",
        )
    table.pack(fill="x", pady=8)
    save_button = ttk.Button(
        sidebar,
        text="校正済みCSVを保存",
        command=save,
        state="disabled",
        padding=(12, 8),
    )
    save_button.pack(fill="x", pady=8)
    ttk.Label(
        sidebar,
        text="左クリック: 基準点\nホイール: 拡大・縮小\n右ドラッグ: 画像の移動\n\n"
        "2点指定後は、次のクリックから指定し直せます。",
        wraplength=288,
    ).pack(anchor="w", pady=8)
    canvas = tk.Canvas(
        body, background="#242424", highlightthickness=0, cursor="crosshair"
    )
    canvas.pack(side="left", fill="both", expand=True)
    canvas.bind("<Button-1>", click)
    canvas.bind("<Configure>", draw_image)
    canvas.bind("<MouseWheel>", wheel)
    canvas.bind("<Enter>", focus_canvas)
    canvas.bind("<ButtonPress-3>", start_pan)
    canvas.bind("<B3-Motion>", pan)
    canvas.bind("<ButtonRelease-3>", end_pan)
    reference.trace_add("write", update_result)
    root.mainloop()


if __name__ == "__main__":
    main()
