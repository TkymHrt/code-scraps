"""補正画像の初期指定・区間を選び、DR・OP側辺長の画像とCSVを保存する."""

import math
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

import cv2 as cv
import numpy as np

from utils.file_io import check_output_path, encode_png, read_image
from utils.gui_parts import create_layout
from utils.measurement_csv import write_csv
from workflow_settings import MM_PER_PX, OUTPUT_DIRECTORY, RECTIFIED_DIRECTORY

ITERATIONS = 5
RANDOM_SEED = 0
# 前景指定の外側にも、背景の判定用に幅・高さの10%（最低10px）を残す。
GRABCUT_MARGIN_RATIO = 0.1

type RectRatios = tuple[float, float, float, float]

# OpenCVの色指定はBGR順。
PALETTE = np.zeros((4, 3), dtype=np.uint8)
PALETTE[cv.GC_BGD] = (255, 80, 0)
PALETTE[cv.GC_FGD] = (0, 255, 0)
PALETTE[cv.GC_PR_BGD] = (64, 64, 64)
PALETTE[cv.GC_PR_FGD] = (0, 165, 255)
REGION_NAMES = {
    cv.GC_PR_FGD: "前景候補（橙）",
    cv.GC_BGD: "確実な背景（青）",
    cv.GC_FGD: "確実な前景（緑）",
}


def initial_mask(image: np.ndarray, regions: dict[int, list[RectRatios]]) -> np.ndarray:
    height, width = image.shape[:2]
    labels = np.full((height, width), cv.GC_PR_BGD, np.uint8)
    for label in (cv.GC_PR_FGD, cv.GC_BGD, cv.GC_FGD):
        for left_ratio, top_ratio, right_ratio, bottom_ratio in regions[label]:
            if not (
                0 <= left_ratio < right_ratio <= 1
                and 0 <= top_ratio < bottom_ratio <= 1
            ):
                raise ValueError("矩形は0〜1の範囲で、左 < 右、上 < 下にしてください")
            left_px = int(width * left_ratio)
            top_px = int(height * top_ratio)
            right_px = int(width * right_ratio)
            bottom_px = int(height * bottom_ratio)
            if left_px == right_px or top_px == bottom_px:
                raise ValueError("矩形が1画素未満です。指定範囲を広げてください")
            labels[top_px:bottom_px, left_px:right_px] = label
    return labels


def initial_overlay(
    image: np.ndarray, regions: dict[int, list[RectRatios]]
) -> np.ndarray:
    labels = initial_mask(image, regions)
    color_mask = PALETTE[labels]
    overlay = cv.addWeighted(image, 0.65, color_mask, 0.35, 0)
    draw_edge_names(overlay)
    return overlay


def draw_edge_names(image: np.ndarray) -> None:
    height, width = image.shape[:2]
    for name, x in (("DR", 8), ("OP", width - 42)):
        cv.rectangle(image, (x - 4, 4), (x + 34, 31), (0, 0, 0), cv.FILLED)
        cv.putText(
            image,
            name,
            (x, min(25, height - 1)),
            cv.FONT_HERSHEY_SIMPLEX,
            0.65,
            (255, 255, 255),
            1,
            cv.LINE_AA,
        )


def measure_lengths(
    image: np.ndarray, regions: dict[int, list[RectRatios]], start_y: int, end_y: int
) -> tuple[dict, np.ndarray]:
    height, width = image.shape[:2]
    if not math.isfinite(MM_PER_PX) or MM_PER_PX <= 0:
        raise ValueError("MM_PER_PXを正の数値にしてください")
    if not 0 <= start_y < end_y < height:
        raise ValueError(f"計測区間を0 ≤ 開始y < 終了y ≤ {height - 1}にしてください")
    labels = initial_mask(image, regions)
    initial_foreground = (labels == cv.GC_FGD) | (labels == cv.GC_PR_FGD)
    if not initial_foreground.any() or initial_foreground.all():
        raise ValueError("試料の前景候補と、その外の背景を指定してください")
    foreground_y = np.flatnonzero(initial_foreground.any(axis=1))
    foreground_x = np.flatnonzero(initial_foreground.any(axis=0))
    left = int(foreground_x.min())
    right = int(foreground_x.max()) + 1
    top = int(foreground_y.min())
    bottom = int(foreground_y.max()) + 1
    margin_x = max(10, math.ceil((right - left) * GRABCUT_MARGIN_RATIO))
    margin_y = max(10, math.ceil((bottom - top) * GRABCUT_MARGIN_RATIO))
    left = max(0, left - margin_x)
    right = min(width, right + margin_x)
    top = max(0, top - margin_y)
    bottom = min(height, bottom + margin_y)
    if start_y < top or end_y >= bottom:
        raise ValueError("計測区間全体が入るように前景候補を広げてください")
    working_image = image[top:bottom, left:right].copy()
    labels = labels[top:bottom, left:right].copy()
    background_model = np.zeros((1, 65), np.float64)
    foreground_model = np.zeros((1, 65), np.float64)
    cv.setRNGSeed(RANDOM_SEED)
    labels, _, _ = cv.grabCut(
        working_image,
        labels,
        (0, 0, 0, 0),
        background_model,
        foreground_model,
        ITERATIONS,
        cv.GC_INIT_WITH_MASK,
    )
    extracted_foreground = (labels == cv.GC_FGD) | (labels == cv.GC_PR_FGD)
    raw_mask = np.zeros(labels.shape, np.uint8)
    raw_mask[extracted_foreground] = 255
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
    mask = np.zeros(labels.shape, np.uint8)
    cv.drawContours(mask, [contour], -1, 255, cv.FILLED)

    left_points = []
    right_points = []
    for y in range(start_y, end_y + 1):
        xs = np.flatnonzero(mask[y - top])
        if len(xs) == 0:
            raise ValueError(
                f"y={y}に試料がありません。区間か初期指定を調整してください"
            )
        if xs[0] == 0 or xs[-1] == mask.shape[1] - 1:
            raise ValueError(
                "試料が処理範囲の端に接しています。前景候補を広げてください"
            )
        left_points.append((int(xs[0]) + left, y))
        right_points.append((int(xs[-1]) + left, y))
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
    draw_edge_names(overlay)
    return row, overlay


def write_measurement(
    path: Path,
    image_path: Path,
    measurement: dict,
    initial_image: np.ndarray,
    result_image: np.ndarray,
) -> None:
    path = check_output_path(path, ".csv", [image_path])
    initial_path = path.with_name(f"{path.stem}_initial.png")
    result_path = path.with_suffix(".png")
    check_output_path(initial_path, ".png", [image_path])
    check_output_path(result_path, ".png", [image_path])
    # 2枚のPNGを作れることを確認してから、CSVと画像を書き出す。
    initial_data = encode_png(initial_image)
    result_data = encode_png(result_image)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_csv(path, image_path, measurement)
    initial_path.write_bytes(initial_data)
    result_path.write_bytes(result_data)


def main() -> None:
    output_directory = OUTPUT_DIRECTORY
    root = tk.Tk()
    input_path: Path | None = None
    image: np.ndarray | None = None
    height = width = 1
    regions: dict[int, list[RectRatios]] = {label: [] for label in REGION_NAMES}
    region_rows: list[tuple[int, int]] = []
    photo: tk.PhotoImage | None = None
    scale = 1.0
    offset_x = offset_y = 0.0
    pan_start: tuple[int, int] | None = None
    drag_start_ratios: tuple[float, float] | None = None

    measurement: dict | None = None
    result_image: np.ndarray | None = None
    root.title("初期指定と長さの計測")
    root.geometry("1120x800")
    root.minsize(1000, 760)
    mode = tk.IntVar(value=cv.GC_PR_FGD)
    selection_target = tk.StringVar(value="region")
    view = tk.StringVar(value="initial")
    status = tk.StringVar()
    file_text = tk.StringVar(value="未読込")

    start_text = tk.StringVar(value="0")
    end_text = tk.StringVar()
    interval_text = tk.StringVar(value="区間長：—")

    def load_image() -> None:
        nonlocal image, input_path, height, width
        selected = filedialog.askopenfilename(
            parent=root,
            title="補正画像を選ぶ",
            initialdir=RECTIFIED_DIRECTORY,
            filetypes=[
                ("画像", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff"),
                ("すべて", "*.*"),
            ],
        )
        if not selected:
            return
        try:
            loaded = read_image(Path(selected))
        except ValueError as error:
            status.set(str(error))
            return
        image = loaded
        input_path = Path(selected).resolve()
        height, width = image.shape[:2]
        file_text.set(f"{input_path.name}  ({width} × {height} px)")
        start_text.set("0")
        end_text.set(str(height - 1))
        clear_regions()
        fit_image()

    def on_regions_changed() -> None:
        region_rows.clear()
        region_list.delete(0, tk.END)
        for label, name in REGION_NAMES.items():
            for index in range(len(regions[label])):
                region_rows.append((label, index))
                region_list.insert(tk.END, f"{name} {index + 1}")
        clear_results()
        view.set("initial")
        status.set("")
        render()

    def clear_regions() -> None:
        for rectangles in regions.values():
            rectangles.clear()
        on_regions_changed()

    def show_initial(_event=None) -> None:
        view.set("initial")
        selection_target.set("region")
        render()

    def render(_event=None) -> None:
        nonlocal photo, drag_start_ratios
        drag_start_ratios = None
        canvas.delete("all")
        if image is None:
            return
        canvas_width = max(1, canvas.winfo_width())
        canvas_height = max(1, canvas.winfo_height())
        preview_image = image
        if view.get() == "result" and result_image is not None:
            preview_image = result_image
        display_left = max(0, math.floor(offset_x))
        display_top = max(0, math.floor(offset_y))
        display_right = min(canvas_width, math.ceil(offset_x + width * scale))
        display_bottom = min(canvas_height, math.ceil(offset_y + height * scale))
        display_width = display_right - display_left
        display_height = display_bottom - display_top
        if display_width > 0 and display_height > 0:
            transform = np.array(
                [
                    [scale, 0, offset_x - display_left],
                    [0, scale, offset_y - display_top],
                ],
                dtype=np.float64,
            )
            # 表示する画素だけを作り、巨大な画像全体への色重ねを避ける。
            small = cv.warpAffine(
                preview_image,
                transform,
                (display_width, display_height),
                flags=cv.INTER_NEAREST,
                borderValue=(36, 36, 36),
            )
            if view.get() == "initial":
                preview_labels = np.full(
                    (display_height, display_width), cv.GC_PR_BGD, np.uint8
                )
                for label in (cv.GC_PR_FGD, cv.GC_BGD, cv.GC_FGD):
                    for left, top, right, bottom in regions[label]:
                        x0 = max(
                            0,
                            round(offset_x + int(left * width) * scale - display_left),
                        )
                        y0 = max(
                            0, round(offset_y + int(top * height) * scale - display_top)
                        )
                        x1 = max(
                            0,
                            round(offset_x + int(right * width) * scale - display_left),
                        )
                        y1 = max(
                            0,
                            round(
                                offset_y + int(bottom * height) * scale - display_top
                            ),
                        )
                        preview_labels[y0:y1, x0:x1] = label
                small = cv.addWeighted(small, 0.65, PALETTE[preview_labels], 0.35, 0)
            photo = tk.PhotoImage(master=root, data=encode_png(small), format="PNG")
            canvas.create_image(display_left, display_top, image=photo, anchor="nw")
        selection = region_list.curselection()
        if view.get() == "initial" and selection:
            label, index = region_rows[selection[0]]
            left_ratio, top_ratio, right_ratio, bottom_ratio = regions[label][index]
            canvas.create_rectangle(
                offset_x + left_ratio * width * scale,
                offset_y + top_ratio * height * scale,
                offset_x + right_ratio * width * scale,
                offset_y + bottom_ratio * height * scale,
                outline="yellow",
                width=2,
            )
        for name, value in (("開始", start_text), ("終了", end_text)):
            try:
                row_y = int(value.get())
            except ValueError:
                continue
            if not 0 <= row_y < height:
                continue
            # 行番号を画像上の画素中心へ合わせる。
            line_y = offset_y + (row_y + 0.5) * scale
            if not 0 <= line_y < canvas_height or display_width <= 0:
                continue
            canvas.create_line(
                display_left,
                line_y,
                display_right,
                line_y,
                fill="yellow",
                width=2,
                tags="interval",
            )
            canvas.create_text(
                display_left + 8,
                max(38, line_y - 3),
                text=f"{name} y={row_y}",
                fill="yellow",
                anchor="sw",
                tags="interval",
            )
        for name, x, anchor in (("DR", 8, "nw"), ("OP", canvas_width - 8, "ne")):
            item = canvas.create_text(
                x,
                8,
                text=name,
                fill="white",
                anchor=anchor,
                font=("TkDefaultFont", 12, "bold"),
                tags="edge_name",
            )
            box = canvas.bbox(item)
            if box is not None:
                background = canvas.create_rectangle(box, fill="#242424", outline="")
                canvas.tag_lower(background, item)

    def fit_image() -> None:
        nonlocal scale, offset_x, offset_y, pan_start
        if image is None:
            return
        scale = min(canvas.winfo_width() / width, canvas.winfo_height() / height, 1)
        offset_x = math.floor((canvas.winfo_width() - width * scale) / 2)
        offset_y = math.floor((canvas.winfo_height() - height * scale) / 2)
        pan_start = None
        render()

    def zoom(event: tk.Event) -> str:
        nonlocal scale, offset_x, offset_y
        if image is None or event.delta == 0:
            return "break"
        image_x = (event.x - offset_x) / scale
        image_y = (event.y - offset_y) / scale
        factor = 1.2 ** (event.delta / 120)
        scale = min(16.0, max(0.01, scale * factor))
        offset_x = event.x - image_x * scale
        offset_y = event.y - image_y * scale
        render()
        return "break"

    def start_pan(event: tk.Event) -> None:
        nonlocal pan_start
        if image is not None:
            pan_start = (event.x, event.y)
            canvas.configure(cursor="fleur")

    def pan(event: tk.Event) -> None:
        nonlocal offset_x, offset_y, pan_start
        if pan_start is None:
            return
        offset_x += event.x - pan_start[0]
        offset_y += event.y - pan_start[1]
        pan_start = (event.x, event.y)
        render()

    def end_pan(_event=None) -> None:
        nonlocal pan_start
        pan_start = None
        canvas.configure(cursor="crosshair")

    def image_ratios(event: tk.Event) -> tuple[float, float]:
        x_ratio = (event.x - offset_x) / (width * scale)
        y_ratio = (event.y - offset_y) / (height * scale)
        x_ratio = min(1.0, max(0.0, x_ratio))
        y_ratio = min(1.0, max(0.0, y_ratio))
        return x_ratio, y_ratio

    def start_draw(event: tk.Event) -> None:
        nonlocal drag_start_ratios
        if image is None:
            return
        if (
            offset_x <= event.x < offset_x + width * scale
            and offset_y <= event.y < offset_y + height * scale
        ):
            target = selection_target.get()
            if target in ("start", "end"):
                row_y = min(height - 1, int((event.y - offset_y) / scale))
                if target == "start":
                    start_text.set(str(row_y))
                else:
                    end_text.set(str(row_y))
                return
            if view.get() != "initial":
                return
            drag_start_ratios = image_ratios(event)

    def drag_draw(event: tk.Event) -> None:
        if drag_start_ratios is None:
            return
        start_x_ratio, start_y_ratio = drag_start_ratios
        end_x_ratio, end_y_ratio = image_ratios(event)
        start_canvas_x = offset_x + start_x_ratio * width * scale
        start_canvas_y = offset_y + start_y_ratio * height * scale
        end_canvas_x = offset_x + end_x_ratio * width * scale
        end_canvas_y = offset_y + end_y_ratio * height * scale
        canvas.delete("drag")
        canvas.create_rectangle(
            start_canvas_x,
            start_canvas_y,
            end_canvas_x,
            end_canvas_y,
            outline="white",
            width=2,
            dash=(5, 3),
            tags="drag",
        )

    def end_draw(event: tk.Event) -> None:
        nonlocal drag_start_ratios
        if drag_start_ratios is None:
            return
        start_x_ratio, start_y_ratio = drag_start_ratios
        end_x_ratio, end_y_ratio = image_ratios(event)
        left_ratio, right_ratio = sorted((start_x_ratio, end_x_ratio))
        top_ratio, bottom_ratio = sorted((start_y_ratio, end_y_ratio))
        drag_start_ratios = None
        canvas.delete("drag")
        left_px = int(width * left_ratio)
        right_px = int(width * right_ratio)
        top_px = int(height * top_ratio)
        bottom_px = int(height * bottom_ratio)
        if left_px >= right_px or top_px >= bottom_px:
            status.set("矩形を1画素以上に広げてください")
            return
        rect = (left_ratio, top_ratio, right_ratio, bottom_ratio)
        label = mode.get()
        regions[label].append(rect)
        on_regions_changed()

    def delete_region() -> None:
        selection = region_list.curselection()
        if selection:
            label, index = region_rows[selection[0]]
            del regions[label][index]
            on_regions_changed()

    def clear_results() -> None:
        nonlocal measurement, result_image
        measurement = None
        result_image = None
        for item in result_table.get_children():
            result_table.set(item, "length", "—")
        save_measurement_button.state(["disabled"])

    def on_interval_changed(*_args) -> None:
        interval_text.set("区間長：—")
        try:
            start_y = int(start_text.get())
            end_y = int(end_text.get())
        except ValueError:
            start_y = end_y = -1
        if (
            image is not None
            and 0 <= start_y < end_y < height
            and math.isfinite(MM_PER_PX)
            and MM_PER_PX > 0
        ):
            interval_mm = (end_y - start_y) * MM_PER_PX
            interval_text.set(f"区間長：{interval_mm:.3f} mm")
        clear_results()
        if view.get() == "result":
            view.set("initial")
        status.set("")
        render()

    def calculate() -> None:
        nonlocal measurement, result_image
        clear_results()
        if view.get() == "result":
            view.set("initial")
        render()
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
        except ValueError as error:
            status.set(str(error))
            return
        except cv.error:
            status.set("計測できません")
            return
        measurement = measured
        result_image = overlay
        for edge in ("left", "right", "total"):
            length_mm = measured[f"{edge}_mm"]
            result_table.set(edge, "length", f"{length_mm:.3f}")
        view.set("result")
        save_measurement_button.state(["!disabled"])
        render()
        status.set("計測完了")

    def save_measurement() -> None:
        if (
            measurement is None
            or input_path is None
            or image is None
            or result_image is None
        ):
            status.set("計測してから保存してください")
            return
        selected = filedialog.asksaveasfilename(
            parent=root,
            title="CSV・画像2枚の保存先",
            initialdir=output_directory,
            initialfile=f"{input_path.stem}_lengths.csv",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            confirmoverwrite=False,
        )
        if not selected:
            return
        csv_path = Path(selected).resolve()
        try:
            initial_image = initial_overlay(image, regions)
            write_measurement(
                csv_path, input_path, measurement, initial_image, result_image
            )
        except ValueError as error:
            status.set(str(error))
            return
        except OSError, cv.error:
            status.set("保存失敗: CSV・PNGを確認してください")
            return
        status.set(f"保存: {csv_path.name} / PNG2枚")

    header, sidebar, content = create_layout(root)
    ttk.Button(
        header, text="補正画像を読み込む", padding=(12, 8), command=load_image
    ).pack(side="left")
    ttk.Label(header, textvariable=file_text).pack(side="left", padx=8)
    ttk.Label(header, textvariable=status, wraplength=320).pack(side="right")
    preview_tools = ttk.Frame(content)
    preview_tools.pack(fill="x", pady=(0, 4))
    ttk.Button(preview_tools, text="全体表示", command=fit_image).pack(side="left")
    for value, name in (("region", "矩形"), ("start", "開始y"), ("end", "終了y")):
        ttk.Radiobutton(
            preview_tools, text=name, variable=selection_target, value=value
        ).pack(side="left", padx=4)
    ttk.Label(
        content,
        text="ホイール：拡大縮小　右ドラッグ：移動　開始y・終了y：クリックで指定",
    ).pack(anchor="w")
    canvas = tk.Canvas(
        content, background="#242424", highlightthickness=0, cursor="crosshair"
    )
    canvas.pack(fill="both", expand=True)

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
    region_list.pack(fill="x", pady=4)
    for name, action in (
        ("選択した矩形を削除", delete_region),
        ("矩形をすべて削除", clear_regions),
    ):
        ttk.Button(sidebar, text=name, padding=(12, 5), command=action).pack(
            fill="x", pady=3
        )

    ttk.Label(sidebar, text="計測する区間（補正画像のy）").pack(anchor="w", pady=(8, 4))
    for label, variable in (("開始y", start_text), ("終了y", end_text)):
        row_frame = ttk.Frame(sidebar)
        row_frame.pack(fill="x", pady=3)
        ttk.Label(row_frame, text=label).pack(side="left")
        ttk.Entry(row_frame, textvariable=variable, width=12).pack(side="right")
    ttk.Label(sidebar, textvariable=interval_text).pack(anchor="w", pady=1)
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
    for edge, label in (("left", "DR"), ("right", "OP"), ("total", "合計")):
        result_table.insert("", "end", iid=edge, values=(label, "—"))
    result_table.pack(fill="x", pady=4)
    save_measurement_button = ttk.Button(
        sidebar, text="CSV・画像2枚を保存", padding=(12, 8), command=save_measurement
    )
    save_measurement_button.pack(fill="x", pady=4)
    for value, name in (
        ("initial", "初期指定"),
        ("original", "元画像"),
        ("result", "計測結果"),
    ):
        ttk.Radiobutton(
            sidebar, text=name, variable=view, value=value, command=render
        ).pack(anchor="w")

    start_text.trace_add("write", on_interval_changed)
    end_text.trace_add("write", on_interval_changed)
    canvas.bind("<Configure>", render)
    canvas.bind("<ButtonPress-1>", start_draw)
    canvas.bind("<B1-Motion>", drag_draw)
    canvas.bind("<ButtonRelease-1>", end_draw)
    canvas.bind("<MouseWheel>", zoom)
    canvas.bind("<ButtonPress-3>", start_pan)
    canvas.bind("<B3-Motion>", pan)
    canvas.bind("<ButtonRelease-3>", end_pan)
    region_list.bind("<<ListboxSelect>>", show_initial)
    output_directory.mkdir(parents=True, exist_ok=True)
    on_regions_changed()
    root.mainloop()


if __name__ == "__main__":
    main()
