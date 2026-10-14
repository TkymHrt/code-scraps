"""固定したカメラ係数とChArUcoで画像を実寸補正し、03の長さをmm換算する."""

import csv
import math
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

import cv2 as cv
import numpy as np

# camera_calibration.pyの出力を、この3設定へ一度貼り付ける。
CALIBRATION_SIZE: tuple[int, int] | None = None
CAMERA_MATRIX: list[list[float]] | None = None
DIST_COEFFS: list[float] | None = None

# カメラ校正と同じ板を、試料の計測面と同じ高さに置く。
BOARD_SQUARES = (7, 5)
SQUARE_MM = 30.0
MARKER_MM = 18.0
MM_PER_PX = 0.25


def rectify_image(image: np.ndarray) -> dict:
    if CALIBRATION_SIZE is None or CAMERA_MATRIX is None or DIST_COEFFS is None:
        raise ValueError("コード冒頭へcamera_calibration.pyの3設定を貼り付けてください")
    height, width = image.shape[:2]
    if (width, height) != tuple(CALIBRATION_SIZE):
        raise ValueError("カメラ校正と同じ解像度・撮影モードの画像を選んでください")
    matrix = np.array(CAMERA_MATRIX, dtype=np.float64)
    distortion = np.array(DIST_COEFFS, dtype=np.float64)
    if (
        matrix.shape != (3, 3)
        or distortion.size != 5
        or not np.isfinite(matrix).all()
        or not np.isfinite(distortion).all()
        or matrix[0, 0] <= 0
        or matrix[1, 1] <= 0
        or not math.isfinite(MM_PER_PX)
        or MM_PER_PX <= 0
    ):
        raise ValueError("貼り付けたカメラ係数とMM_PER_PXを確認してください")
    undistorted = cv.undistort(image, matrix, distortion, None, matrix)
    dictionary = cv.aruco.getPredefinedDictionary(cv.aruco.DICT_4X4_50)
    board = cv.aruco.CharucoBoard(BOARD_SQUARES, SQUARE_MM, MARKER_MM, dictionary)
    detector = cv.aruco.CharucoDetector(board)
    corners, ids, _, _ = detector.detectBoard(undistorted)
    if ids is None or len(ids) < 6 or board.checkCharucoCornersCollinear(ids):
        raise ValueError("ChArUco板の角を縦横に6点以上読める画像を選んでください")
    all_board_points = np.array(board.getChessboardCorners(), dtype=np.float32)
    object_points = all_board_points[ids.astype(np.int32).ravel()]
    image_points = corners
    board_xy = object_points.reshape(-1, 3)[:, :2]
    detected_xy = image_points.reshape(-1, 2)
    # 板のmm座標へ写す。試料の形を基準に変形すると伸びを消すため、使わない。
    homography, _ = cv.findHomography(detected_xy, board_xy)
    if homography is None or not np.isfinite(homography).all():
        raise ValueError("板から遠近補正を求められません")
    predicted = cv.perspectiveTransform(
        board_xy.reshape(-1, 1, 2), np.linalg.inv(homography)
    ).reshape(-1, 2)
    error_px = float(np.sqrt(np.mean(np.sum((predicted - detected_xy) ** 2, axis=1))))
    if error_px > 2.0:
        raise ValueError(f"板の再投影誤差が大きいため保存しません: {error_px:.3f}px")

    frame_corners = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
        dtype=np.float64,
    )
    # 画面内に消失線がある場合、全体を有限の平面画像にはできない。
    denominators = frame_corners @ homography[2, :2] + homography[2, 2]
    if not (np.all(denominators > 0) or np.all(denominators < 0)):
        raise ValueError("撮影角度が浅すぎます。計測面へ向けて撮り直してください")
    world_corners = cv.perspectiveTransform(
        frame_corners.reshape(-1, 1, 2), homography
    ).reshape(-1, 2)
    pixel_corners = world_corners / MM_PER_PX
    if not np.isfinite(pixel_corners).all():
        raise ValueError("補正画像の範囲を求められません")
    minimum = np.floor(pixel_corners.min(axis=0))
    maximum = np.ceil(pixel_corners.max(axis=0))
    output_width = int(maximum[0] - minimum[0] + 1)
    output_height = int(maximum[1] - minimum[1] + 1)
    if (
        min(output_width, output_height) < 2
        or max(output_width, output_height) >= 32767
        or output_width * output_height > 20_000_000
    ):
        raise ValueError("補正画像が大きすぎます。撮影角度・板の寸法を確認してください")
    world_to_pixels = np.array(
        [[1 / MM_PER_PX, 0, -minimum[0]], [0, 1 / MM_PER_PX, -minimum[1]], [0, 0, 1]],
        dtype=np.float64,
    )
    transform = world_to_pixels @ homography
    corrected = cv.warpPerspective(
        undistorted, transform, (output_width, output_height), flags=cv.INTER_LINEAR
    )
    # 既知の板上の2点を、比較CSVと共通の校正根拠として保存する。
    reference_world = np.array([board_xy[0], board_xy[-1]], dtype=np.float64)
    reference_pixels = cv.perspectiveTransform(
        reference_world.reshape(-1, 1, 2), world_to_pixels
    ).reshape(-1, 2)
    reference_mm = float(np.linalg.norm(reference_world[1] - reference_world[0]))
    return {
        "image": corrected,
        "points": reference_pixels,
        "reference_mm": reference_mm,
        "reference_px": reference_mm / MM_PER_PX,
        "mm_per_px": MM_PER_PX,
        "corner_count": len(ids),
        "error_px": error_px,
    }


def convert_lengths(csv_path: Path, image_path: Path, correction: dict) -> dict:
    lengths = {}
    measurement_range = None
    with csv_path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        required = {"edge", "length_px", "start_y", "end_y"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("補正画像を03で測った長さCSVを選んでください")
        for values in reader:
            for column in required:
                if values[column] is None or not values[column].strip():
                    raise ValueError("CSVの長さ・計測範囲に空欄があります")
            edge = values["edge"]
            if edge not in ("left", "right", "total") or edge in lengths:
                raise ValueError("左・右・合計を1行ずつ指定してください")
            length = float(values["length_px"])
            start_y, end_y = int(values["start_y"]), int(values["end_y"])
            if not math.isfinite(length) or length <= 0:
                raise ValueError("長さは0より大きい有限値が必要です")
            if not 0 <= start_y < end_y < correction["image"].shape[0]:
                raise ValueError("CSVの計測範囲が補正画像に合いません")
            if measurement_range is not None and measurement_range != (start_y, end_y):
                raise ValueError("CSV内の計測範囲を揃えてください")
            measurement_range = (start_y, end_y)
            lengths[edge] = length
    if len(lengths) != 3 or measurement_range is None:
        raise ValueError("左・右・合計の3行が必要です")
    if abs(lengths["left"] + lengths["right"] - lengths["total"]) > 0.011:
        raise ValueError("左右の長さと合計が一致しません")
    points = correction["points"]
    height, width = correction["image"].shape[:2]
    row = {
        "input_csv": str(csv_path.resolve()),
        "image_path": str(image_path.resolve()),
        "reference_mm": correction["reference_mm"],
        "reference_px": correction["reference_px"],
        "mm_per_px": correction["mm_per_px"],
        "reference_x1": float(points[0, 0]),
        "reference_y1": float(points[0, 1]),
        "reference_x2": float(points[1, 0]),
        "reference_y2": float(points[1, 1]),
        "image_width": width,
        "image_height": height,
        "start_y": measurement_range[0],
        "end_y": measurement_range[1],
    }
    for edge in ("left", "right", "total"):
        row[f"{edge}_px"] = lengths[edge]
        row[f"{edge}_mm"] = lengths[edge] * correction["mm_per_px"]
    return row


def save_image(path: Path, correction: dict, source_path: Path) -> None:
    if path.suffix.lower() != ".png" or path.resolve() == source_path.resolve():
        raise ValueError("元画像と別のPNGへ保存してください")
    success, encoded = cv.imencode(".png", correction["image"])
    if not success:
        raise OSError("補正画像をPNGにできません")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded.tobytes())


def save_lengths(path: Path, row: dict, source_path: Path) -> None:
    protected = (Path(row["input_csv"]), Path(row["image_path"]), source_path.resolve())
    if path.suffix.lower() != ".csv" or path.resolve() in protected:
        raise ValueError("入力ファイルと別のCSVへ保存してください")
    saved = row.copy()
    for key, value in row.items():
        if isinstance(value, float):
            saved[key] = f"{value:.12g}"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(saved)


def main() -> None:
    directory = Path(__file__).resolve().parent
    root = tk.Tk()
    root.title("ChArUcoの画像補正とmm換算")
    root.geometry("1160x820")
    root.minsize(1000, 700)
    source_path = None
    corrected_path = None
    csv_path = None
    correction = None
    view = (0.0, 0.0, 1.0)
    pan_start = None
    photo = None
    row = {}
    image_name = tk.StringVar(value="未読込")
    csv_name = tk.StringVar(value="未読込")
    summary = tk.StringVar(value="未補正")
    status = tk.StringVar(
        value="校正係数をコードへ貼り付け、板を含む画像を選んでください"
    )

    def show_error(error, path: Path) -> None:
        message = str(error).replace(repr(str(path)), repr(path.name))
        status.set(message.replace(str(path), path.name))

    def clear_lengths() -> None:
        nonlocal csv_path, row
        csv_path, row = None, {}
        csv_name.set("未読込")
        table.delete(*table.get_children())
        save_csv_button.state(["disabled"])

    def draw_image(event=None) -> None:
        nonlocal photo
        canvas.delete("all")
        if correction is None:
            return
        offset_x, offset_y, scale = view
        transform = np.array([[scale, 0, offset_x], [0, scale, offset_y]], np.float64)
        size = (max(2, canvas.winfo_width()), max(2, canvas.winfo_height()))
        interpolation = cv.INTER_NEAREST if scale >= 1 else cv.INTER_LINEAR
        shown = cv.warpAffine(
            correction["image"],
            transform,
            size,
            flags=interpolation,
            borderValue=(36, 36, 36),
        )
        success, encoded = cv.imencode(".png", shown)
        if not success:
            status.set("表示用の画像を作れません")
            return
        photo = tk.PhotoImage(master=root, data=encoded.tobytes(), format="PNG")
        canvas.create_image(0, 0, image=photo, anchor="nw")

    def wheel(event) -> str:
        nonlocal view
        offset_x, offset_y, scale = view
        new_scale = min(16.0, max(0.01, scale * 1.1 ** (event.delta / 120)))
        change = new_scale / scale
        view = (
            event.x - (event.x - offset_x) * change,
            event.y - (event.y - offset_y) * change,
            new_scale,
        )
        draw_image()
        return "break"

    def focus_canvas(event) -> None:
        canvas.focus_set()

    def start_pan(event) -> None:
        nonlocal pan_start
        pan_start = (event.x, event.y)

    def pan(event) -> None:
        nonlocal view, pan_start
        if pan_start is None:
            return
        offset_x, offset_y, scale = view
        view = (
            offset_x + event.x - pan_start[0],
            offset_y + event.y - pan_start[1],
            scale,
        )
        pan_start = (event.x, event.y)
        draw_image()

    def end_pan(event) -> None:
        nonlocal pan_start
        pan_start = None

    def choose_image() -> None:
        nonlocal source_path, correction, corrected_path, view, pan_start
        selected = filedialog.askopenfilename(
            parent=root,
            title="板を含む撮影画像を選ぶ",
            initialdir=directory,
            filetypes=[("画像", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff")],
        )
        if not selected:
            return
        path = Path(selected).resolve()
        # 別画像で補正に失敗したとき、前の値をその画像の値として使わせない。
        correction, corrected_path, pan_start = None, None, None
        clear_lengths()
        save_image_button.state(["disabled"])
        csv_button.state(["disabled"])
        image_name.set(path.name)
        summary.set("未補正")
        draw_image()
        try:
            image = cv.imdecode(
                np.frombuffer(path.read_bytes(), np.uint8), cv.IMREAD_COLOR
            )
            if image is None:
                raise ValueError("画像を読み込めません")
            correction = rectify_image(image)
        except (OSError, ValueError, cv.error, np.linalg.LinAlgError) as error:
            show_error(error, path)
            return
        source_path = path
        height, width = correction["image"].shape[:2]
        image_name.set(f"{path.name} → {width} × {height} px")
        summary.set(
            f"検出した角: {correction['corner_count']}点\n"
            f"再投影誤差: {correction['error_px']:.3f}px\n"
            f"補正後: {correction['mm_per_px']:g}mm/px"
        )
        scale = min(
            1.0,
            max(2, canvas.winfo_width() - 24) / width,
            max(2, canvas.winfo_height() - 24) / height,
        )
        view = (
            (canvas.winfo_width() - width * scale) / 2,
            (canvas.winfo_height() - height * scale) / 2,
            scale,
        )
        draw_image()
        save_image_button.state(["!disabled"])
        status.set("補正PNGを保存し、その画像を03で計測してください")

    def save_corrected() -> None:
        nonlocal corrected_path
        if correction is None or source_path is None:
            return
        selected = filedialog.asksaveasfilename(
            parent=root,
            title="03で計測する補正画像を保存",
            initialdir=source_path.parent,
            initialfile=f"{source_path.stem}_rectified.png",
            defaultextension=".png",
            filetypes=[("PNG", "*.png")],
        )
        if not selected:
            return
        path = Path(selected).resolve()
        if csv_path is not None and path == csv_path:
            status.set("入力CSVと別の保存先を選んでください")
            return
        try:
            save_image(path, correction, source_path)
        except (OSError, ValueError, cv.error) as error:
            show_error(error, path)
            return
        corrected_path = path
        clear_lengths()
        csv_button.state(["!disabled"])
        status.set(
            f"保存しました: {path.name}。03で計測後、そのCSVを読み込んでください"
        )

    def update_lengths() -> None:
        nonlocal row
        row = {}
        table.delete(*table.get_children())
        save_csv_button.state(["disabled"])
        if csv_path is None or corrected_path is None or correction is None:
            return
        try:
            row = convert_lengths(csv_path, corrected_path, correction)
        except (OSError, ValueError, TypeError, csv.Error) as error:
            show_error(error, csv_path)
            return
        for edge, label in (("left", "左"), ("right", "右"), ("total", "左右合計")):
            table.insert("", "end", values=(label, f"{row[f'{edge}_mm']:.3f}"))
        save_csv_button.state(["!disabled"])
        status.set("mm換算しました。保存したCSVを長さ比較GUIへ渡してください")

    def choose_csv() -> None:
        nonlocal csv_path
        if corrected_path is None:
            return
        selected = filedialog.askopenfilename(
            parent=root,
            title="保存した補正画像を03で測ったCSVを選ぶ",
            initialdir=corrected_path.parent,
            filetypes=[("CSV", "*.csv")],
        )
        if not selected:
            return
        csv_path = Path(selected).resolve()
        csv_name.set(csv_path.name)
        update_lengths()

    def save_csv() -> None:
        if not row or csv_path is None or source_path is None:
            return
        selected = filedialog.asksaveasfilename(
            parent=root,
            title="mm換算済みの長さCSVを保存",
            initialdir=csv_path.parent,
            initialfile=f"{csv_path.stem}_calibrated.csv",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
        )
        if not selected:
            return
        update_lengths()
        if not row:
            return
        path = Path(selected).resolve()
        try:
            save_lengths(path, row, source_path)
        except (OSError, ValueError, csv.Error) as error:
            show_error(error, path)
            return
        status.set(f"保存しました: {path.name}")

    toolbar = ttk.Frame(root, padding=(12, 8))
    toolbar.pack(fill="x")
    toolbar.columnconfigure(1, weight=1)
    ttk.Button(toolbar, text="撮影画像を読み込む", width=24, command=choose_image).grid(
        row=0, column=0, sticky="w", pady=4
    )
    csv_button = ttk.Button(
        toolbar,
        text="補正後の03 CSVを読み込む",
        width=24,
        command=choose_csv,
        state="disabled",
    )
    csv_button.grid(row=1, column=0, sticky="w", pady=4)
    for index, name in enumerate((image_name, csv_name)):
        ttk.Label(toolbar, textvariable=name, wraplength=320).grid(
            row=index, column=1, sticky="w", padx=8, pady=4
        )
    ttk.Label(
        toolbar, textvariable=status, wraplength=380, justify="right", anchor="e"
    ).grid(row=0, column=2, rowspan=2, sticky="e", padx=(16, 0))
    body = ttk.Frame(root, padding=(12, 8, 12, 12))
    body.pack(fill="both", expand=True)
    sidebar = ttk.Frame(body, width=288)
    sidebar.pack(side="left", fill="y", padx=(0, 16))
    ttk.Label(sidebar, text="画像の補正結果").pack(anchor="w", pady=(0, 8))
    ttk.Label(sidebar, textvariable=summary, wraplength=288).pack(anchor="w")
    save_image_button = ttk.Button(
        sidebar,
        text="補正PNGを保存",
        command=save_corrected,
        state="disabled",
        padding=(12, 8),
    )
    save_image_button.pack(fill="x", pady=16)
    ttk.Label(sidebar, text="03の側辺長 (mm)").pack(anchor="w", pady=(16, 4))
    table = ttk.Treeview(sidebar, columns=("edge", "mm"), show="headings", height=3)
    for column, label, column_width in (
        ("edge", "側辺", 96),
        ("mm", "実寸長 (mm)", 192),
    ):
        table.heading(column, text=label)
        table.column(
            column,
            width=column_width,
            stretch=False,
            anchor="w" if column == "edge" else "e",
        )
    table.pack(fill="x", pady=8)
    save_csv_button = ttk.Button(
        sidebar,
        text="mm換算CSVを保存",
        command=save_csv,
        state="disabled",
        padding=(12, 8),
    )
    save_csv_button.pack(fill="x", pady=8)
    ttk.Label(
        sidebar,
        wraplength=288,
        text="1. 板を含む画像を読み込む\n2. 補正PNGを保存\n"
        "3. そのPNGを03で計測\n4. 03 CSVを読み込んでmm保存\n\n"
        "板の縦方向を圧延方向に揃えます。\n\n"
        "ホイール: 拡大・縮小\n右ドラッグ: 画像の移動",
    ).pack(anchor="w", pady=16)
    canvas = tk.Canvas(body, background="#242424", highlightthickness=0)
    canvas.pack(side="left", fill="both", expand=True)
    canvas.bind("<Configure>", draw_image)
    canvas.bind("<MouseWheel>", wheel)
    canvas.bind("<Enter>", focus_canvas)
    canvas.bind("<ButtonPress-3>", start_pan)
    canvas.bind("<B3-Motion>", pan)
    canvas.bind("<ButtonRelease-3>", end_pan)
    root.mainloop()


if __name__ == "__main__":
    main()
