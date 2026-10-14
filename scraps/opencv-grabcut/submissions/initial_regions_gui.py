"""補正画像の初期指定・区間を選び、左右側辺長の画像とCSVを保存する."""

import csv
import math
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

import cv2 as cv
import numpy as np

# rectify_image.pyで出力した補正画像と同じ倍率にする。
MM_PER_PX = 0.25
OUTPUT_DIRECTORY = "output"
ITERATIONS = 5
RANDOM_SEED = 0

type Rect = tuple[float, float, float, float]

# 未指定部分は背景候補（灰）。後から重ねる確実な指定を優先する。
PALETTE = np.array(
    [(255, 80, 0), (0, 255, 0), (64, 64, 64), (0, 165, 255)], dtype=np.uint8
)
REGION_NAMES = {
    cv.GC_PR_FGD: "前景候補（橙）",
    cv.GC_BGD: "確実な背景（青）",
    cv.GC_FGD: "確実な前景（緑）",
}


def initial_mask(image: np.ndarray, regions: dict[int, list[Rect]]) -> np.ndarray:
    height, width = image.shape[:2]
    labels = np.full((height, width), cv.GC_PR_BGD, np.uint8)
    for label in REGION_NAMES:
        for left, top, right, bottom in regions[label]:
            if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
                raise ValueError("矩形は0〜1の範囲で、左 < 右、上 < 下にしてください")
            x0, y0 = int(width * left), int(height * top)
            x1, y1 = int(width * right), int(height * bottom)
            if x0 == x1 or y0 == y1:
                raise ValueError("矩形が1画素未満です。指定範囲を広げてください")
            labels[y0:y1, x0:x1] = label
    return labels


def initial_overlay(image: np.ndarray, regions: dict[int, list[Rect]]) -> np.ndarray:
    labels = initial_mask(image, regions)
    return cv.addWeighted(image, 0.65, PALETTE[labels], 0.35, 0)


def measure_lengths(
    image: np.ndarray, regions: dict[int, list[Rect]], start_y: int, end_y: int
) -> tuple[dict, np.ndarray]:
    height, width = image.shape[:2]
    if not math.isfinite(MM_PER_PX) or MM_PER_PX <= 0:
        raise ValueError("コード冒頭のMM_PER_PXを正の有限値にしてください")
    if not 0 <= start_y < end_y < height:
        raise ValueError(f"計測区間を0 ≤ 開始y < 終了y ≤ {height - 1}にしてください")
    labels = initial_mask(image, regions)
    foreground = (labels == cv.GC_FGD) | (labels == cv.GC_PR_FGD)
    if not foreground.any() or foreground.all():
        raise ValueError("試料の前景候補と、その外の背景を指定してください")
    background_model = np.zeros((1, 65), np.float64)
    foreground_model = np.zeros((1, 65), np.float64)
    cv.setRNGSeed(RANDOM_SEED)
    cv.grabCut(
        image,
        labels,
        (0, 0, 0, 0),
        background_model,
        foreground_model,
        ITERATIONS,
        cv.GC_INIT_WITH_MASK,
    )
    raw_mask = ((labels == cv.GC_FGD) | (labels == cv.GC_PR_FGD)).astype(np.uint8) * 255
    contours, _ = cv.findContours(raw_mask, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_NONE)
    if not contours:
        raise ValueError("試料を抽出できません。初期指定を調整してください")
    contour = contours[0]
    largest_area = cv.contourArea(contour)
    for candidate in contours[1:]:
        area = cv.contourArea(candidate)
        if area > largest_area:
            contour = candidate
            largest_area = area
    mask = np.zeros((height, width), np.uint8)
    cv.drawContours(mask, [contour], -1, 255, cv.FILLED)

    left_points = []
    right_points = []
    for y in range(start_y, end_y + 1):
        xs = np.flatnonzero(mask[y])
        if len(xs) == 0:
            raise ValueError(
                f"y={y}に試料がありません。区間か初期指定を調整してください"
            )
        left_points.append((int(xs[0]), y))
        right_points.append((int(xs[-1]), y))
    left_px = 0.0
    right_px = 0.0
    for index in range(1, len(left_points)):
        previous_left = left_points[index - 1]
        current_left = left_points[index]
        previous_right = right_points[index - 1]
        current_right = right_points[index]
        left_px += math.hypot(
            current_left[0] - previous_left[0], current_left[1] - previous_left[1]
        )
        right_px += math.hypot(
            current_right[0] - previous_right[0], current_right[1] - previous_right[1]
        )
    total_px = left_px + right_px
    row = {
        "image_width": width,
        "image_height": height,
        "mm_per_px": MM_PER_PX,
        "start_y": start_y,
        "end_y": end_y,
        "left_px": left_px,
        "left_mm": left_px * MM_PER_PX,
        "right_px": right_px,
        "right_mm": right_px * MM_PER_PX,
        "total_px": total_px,
        "total_mm": total_px * MM_PER_PX,
    }
    overlay = image.copy()
    overlay[:start_y] //= 2
    overlay[end_y + 1 :] //= 2
    for y in (start_y, end_y):
        cv.line(overlay, (0, y), (width - 1, y), (0, 255, 255), 1)
    for points in (left_points, right_points):
        cv.polylines(overlay, [np.array(points, np.int32)], False, (0, 0, 255), 2)
    return row, overlay


def write_csv(path: Path, image_path: Path, measurement: dict) -> None:
    if path.resolve() == image_path.resolve():
        raise ValueError("入力画像とは別の保存先を選んでください")
    if path.suffix.lower() != ".csv":
        raise ValueError("保存先の拡張子は .csv にしてください")
    row = {"image_path": str(image_path.resolve())}
    row.update(measurement)
    for column, value in row.items():
        if isinstance(value, float):
            row[column] = f"{value:.12g}"
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)


def main() -> None:
    directory = Path(__file__).resolve().parent
    output_directory = directory / OUTPUT_DIRECTORY
    root = tk.Tk()
    input_path: Path | None = None
    image: np.ndarray | None = None
    height = width = 1
    regions: dict[int, list[Rect]] = {label: [] for label in REGION_NAMES}
    region_rows: list[tuple[int, int]] = []
    photo: tk.PhotoImage | None = None
    display_bounds = (0, 0, 1, 1)
    drag_start: tuple[float, float] | None = None

    measurement: dict | None = None
    result_image: np.ndarray | None = None
    root.title("初期指定と長さの計測")
    root.geometry("1120x800")
    root.minsize(1000, 760)
    mode = tk.IntVar(value=cv.GC_PR_FGD)
    view = tk.StringVar(value="initial")
    status = tk.StringVar()
    file_text = tk.StringVar(value="未読込")

    start_text = tk.StringVar(value="0")
    end_text = tk.StringVar()

    def load_image() -> None:
        nonlocal image, input_path, height, width
        selected = filedialog.askopenfilename(
            parent=root,
            title="補正画像を選ぶ",
            initialdir=directory / "output/rectified",
            filetypes=[
                ("画像", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff"),
                ("すべて", "*.*"),
            ],
        )
        if not selected:
            return
        # 日本語のパスにも対応するため、画像のバイト列を読み込む。
        try:
            loaded = cv.imdecode(np.fromfile(selected, np.uint8), cv.IMREAD_COLOR)
            if loaded is None:
                raise ValueError("画像を読み込めません")
        except (OSError, ValueError, cv.error) as error:
            status.set(str(error))
            return
        image = loaded
        input_path = Path(selected).resolve()
        height, width = image.shape[:2]
        file_text.set(f"{input_path.name}  ({width} × {height} px)")
        start_text.set("0")
        end_text.set(str(height - 1))
        clear_regions()

    def refresh_regions() -> None:
        region_rows.clear()
        region_list.delete(0, tk.END)
        for label, name in REGION_NAMES.items():
            for index in range(len(regions[label])):
                region_rows.append((label, index))
                region_list.insert(tk.END, f"{name} {index + 1}")
        view.set("initial")
        invalidate()

    def clear_regions() -> None:
        for rectangles in regions.values():
            rectangles.clear()
        refresh_regions()

    def show_initial(_event=None) -> None:
        view.set("initial")
        render()

    def render(_event=None) -> None:
        nonlocal photo, display_bounds, drag_start
        drag_start = None
        canvas.delete("all")
        if image is None:
            return
        shown = image
        if view.get() == "initial":
            shown = initial_overlay(image, regions)
        elif view.get() == "result" and result_image is not None:
            shown = result_image
        scale = min(canvas.winfo_width() / width, canvas.winfo_height() / height, 1)
        display_width = max(1, int(width * scale))
        display_height = max(1, int(height * scale))
        small = cv.resize(
            shown, (display_width, display_height), interpolation=cv.INTER_NEAREST
        )
        _, encoded = cv.imencode(".png", small)
        photo = tk.PhotoImage(master=root, data=encoded.tobytes(), format="PNG")
        x = (canvas.winfo_width() - display_width) // 2
        y = (canvas.winfo_height() - display_height) // 2
        display_bounds = (x, y, x + display_width, y + display_height)
        canvas.create_image(x, y, image=photo, anchor="nw")
        selection = region_list.curselection()
        if view.get() == "initial" and selection:
            label, index = region_rows[selection[0]]
            left, top, right, bottom = regions[label][index]
            canvas.create_rectangle(
                x + left * display_width,
                y + top * display_height,
                x + right * display_width,
                y + bottom * display_height,
                outline="yellow",
                width=2,
            )

    def image_point(event: tk.Event) -> tuple[float, float]:
        x0, y0, x1, y1 = display_bounds
        return (
            min(1.0, max(0.0, (event.x - x0) / (x1 - x0))),
            min(1.0, max(0.0, (event.y - y0) / (y1 - y0))),
        )

    def start_draw(event: tk.Event) -> None:
        nonlocal drag_start
        if image is None or view.get() != "initial":
            return
        x0, y0, x1, y1 = display_bounds
        if x0 <= event.x <= x1 and y0 <= event.y <= y1:
            drag_start = image_point(event)

    def drag_draw(event: tk.Event) -> None:
        if drag_start is None:
            return
        x0, y0, x1, y1 = display_bounds
        x, y = image_point(event)
        canvas.delete("drag")
        canvas.create_rectangle(
            x0 + drag_start[0] * (x1 - x0),
            y0 + drag_start[1] * (y1 - y0),
            x0 + x * (x1 - x0),
            y0 + y * (y1 - y0),
            outline="white",
            width=2,
            dash=(5, 3),
            tags="drag",
        )

    def end_draw(event: tk.Event) -> None:
        nonlocal drag_start
        if drag_start is None:
            return
        x, y = image_point(event)
        left, right = sorted((drag_start[0], x))
        top, bottom = sorted((drag_start[1], y))
        drag_start = None
        canvas.delete("drag")
        if int(width * left) >= int(width * right) or int(height * top) >= int(
            height * bottom
        ):
            status.set("矩形が1画素未満です。指定範囲を広げてください。")
            return
        rect = (left, top, right, bottom)
        label = mode.get()
        if label == cv.GC_PR_FGD:
            regions[label] = [rect]
        else:
            regions[label].append(rect)
        refresh_regions()

    def delete_region() -> None:
        selection = region_list.curselection()
        if selection:
            label, index = region_rows[selection[0]]
            del regions[label][index]
            refresh_regions()

    def save_image() -> None:
        if image is None or input_path is None:
            status.set("画像を読み込んでください")
            return
        selected = filedialog.asksaveasfilename(
            parent=root,
            title="確認画像の保存先を選ぶ",
            initialdir=output_directory,
            initialfile=f"{input_path.stem}_measurement.png",
            defaultextension=".png",
            filetypes=[("PNG画像", "*.png")],
            confirmoverwrite=True,
        )
        if not selected:
            return
        output_path = Path(selected).resolve()
        if output_path == input_path:
            status.set("保存先を入力画像とは別のパスにしてください")
            return
        if output_path.suffix.lower() != ".png":
            status.set("保存先の拡張子は .png にしてください")
            return
        try:
            shown = result_image
            if shown is None:
                shown = initial_overlay(image, regions)
            success, encoded = cv.imencode(".png", shown)
            if not success:
                raise OSError("PNG画像を作成できません")
            encoded.tofile(output_path)
        except (OSError, ValueError, cv.error) as error:
            status.set(str(error))
            return
        status.set(f"保存しました: {output_path.name}")

    def invalidate(*_args) -> None:
        nonlocal measurement, result_image
        measurement = None
        result_image = None
        for item in result_table.get_children():
            result_table.set(item, "length", "—")
        save_csv_button.state(["disabled"])
        if view.get() == "result":
            view.set("initial")
        status.set("")
        render()

    def calculate() -> None:
        nonlocal measurement, result_image
        invalidate()
        if image is None:
            status.set("補正画像を読み込んでください")
            return
        try:
            start_y = int(start_text.get())
            end_y = int(end_text.get())
        except ValueError:
            status.set("開始yと終了yは整数で入力してください")
            return
        status.set("計測中…")
        root.update_idletasks()
        try:
            measured, overlay = measure_lengths(image, regions, start_y, end_y)
        except (ValueError, cv.error) as error:
            status.set(str(error))
            return
        measurement = measured
        result_image = overlay
        for edge in ("left", "right", "total"):
            length_mm = measured[f"{edge}_mm"]
            result_table.set(edge, "length", f"{length_mm:.3f}")
        view.set("result")
        save_csv_button.state(["!disabled"])
        render()
        status.set("計測しました。赤い側辺と黄色の区間を確認してください")

    def save_csv() -> None:
        if measurement is None or input_path is None:
            status.set("計測してから保存してください")
            return
        selected = filedialog.asksaveasfilename(
            parent=root,
            title="長さCSVの保存先",
            initialdir=output_directory,
            initialfile=f"{input_path.stem}_lengths.csv",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            confirmoverwrite=True,
        )
        if not selected:
            return
        try:
            write_csv(Path(selected), input_path, measurement)
        except (OSError, ValueError) as error:
            status.set(str(error))
            return
        status.set(f"保存しました: {Path(selected).name}")

    file_toolbar = ttk.Frame(root, padding=12)
    file_toolbar.pack(fill="x")
    ttk.Button(
        file_toolbar, text="補正画像を読み込む", padding=(12, 8), command=load_image
    ).pack(side="left")
    ttk.Label(file_toolbar, textvariable=file_text).pack(side="left", padx=8)
    ttk.Label(file_toolbar, textvariable=status, wraplength=320).pack(side="right")
    body = ttk.Frame(root, padding=(12, 0, 12, 12))
    body.pack(fill="both", expand=True)
    sidebar = ttk.Frame(body)
    sidebar.pack(side="left", fill="y", padx=(0, 16))
    canvas = tk.Canvas(body, background="#242424", highlightthickness=0)
    canvas.pack(side="left", fill="both", expand=True)

    ttk.Label(sidebar, text="矩形の種類（画像を左ドラッグ）").pack(anchor="w")
    swatches: list[tk.PhotoImage] = []
    for label, name in REGION_NAMES.items():
        blue, green, red = PALETTE[label]
        swatch = tk.PhotoImage(master=root, width=16, height=16)
        swatch.put(f"#{red:02x}{green:02x}{blue:02x}", to=(0, 0, 16, 16))
        swatches.append(swatch)
        ttk.Radiobutton(
            sidebar,
            text=name,
            image=swatch,
            compound="left",
            variable=mode,
            value=label,
            padding=4,
            command=show_initial,
        ).pack(anchor="w", pady=2)
    region_list = tk.Listbox(sidebar, width=32, height=4, exportselection=False)
    region_list.pack(fill="x", pady=8)
    for name, action in (
        ("選択した矩形を削除", delete_region),
        ("矩形をすべて削除", clear_regions),
    ):
        ttk.Button(sidebar, text=name, padding=(12, 6), command=action).pack(
            fill="x", pady=3
        )

    ttk.Label(sidebar, text="対応する材料区間（補正画像のy）").pack(
        anchor="w", pady=(12, 4)
    )
    for label, variable in (("開始y", start_text), ("終了y", end_text)):
        row_frame = ttk.Frame(sidebar)
        row_frame.pack(fill="x", pady=3)
        ttk.Label(row_frame, text=label).pack(side="left")
        ttk.Entry(row_frame, textvariable=variable, width=12).pack(side="right")
    ttk.Button(sidebar, text="長さを計測", padding=(12, 8), command=calculate).pack(
        fill="x", pady=4
    )
    result_table = ttk.Treeview(
        sidebar,
        columns=("edge", "length"),
        show="headings",
        height=3,
        selectmode="none",
    )
    result_table.heading("edge", text="側辺")
    result_table.heading("length", text="長さ (mm)")
    result_table.column("edge", width=60, stretch=False)
    result_table.column("length", width=130, anchor="e")
    for edge, label in (("left", "左"), ("right", "右"), ("total", "左右合計")):
        result_table.insert("", "end", iid=edge, values=(label, "—"))
    result_table.pack(fill="x", pady=8)
    save_csv_button = ttk.Button(
        sidebar, text="長さCSVを保存", padding=(12, 8), command=save_csv
    )
    save_csv_button.pack(fill="x", pady=4)
    ttk.Button(
        sidebar, text="確認画像を保存", padding=(12, 8), command=save_image
    ).pack(fill="x", pady=4)
    for value, name in (
        ("initial", "初期指定"),
        ("original", "元画像"),
        ("result", "計測結果"),
    ):
        ttk.Radiobutton(
            sidebar, text=name, variable=view, value=value, command=render
        ).pack(anchor="w")

    start_text.trace_add("write", invalidate)
    end_text.trace_add("write", invalidate)
    canvas.bind("<Configure>", render)
    canvas.bind("<ButtonPress-1>", start_draw)
    canvas.bind("<B1-Motion>", drag_draw)
    canvas.bind("<ButtonRelease-1>", end_draw)
    region_list.bind("<<ListboxSelect>>", show_initial)
    output_directory.mkdir(parents=True, exist_ok=True)
    refresh_regions()
    root.mainloop()


if __name__ == "__main__":
    main()
