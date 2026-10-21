"""補正画像の初期指定・区間を選び、DR・OP側辺長の画像とCSVを保存する."""

import math
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

import cv2 as cv
import numpy as np

from utils.file_io import check_output_path, encode_png, read_image
from utils.gui_parts import create_layout
from utils.measurement_csv import positive_value, write_csv
from workflow_settings import MM_PER_PX, OUTPUT_DIRECTORY, RECTIFIED_DIRECTORY

ITERATIONS = 5
RANDOM_SEED = 0
EVALUATION_INTERVAL_MM = 1.0
# 側辺に沿う窓の全幅。0なら平滑化しない。局所直線で画素の階段をならす。
SMOOTHING_WIDTH_MM = 2.0
# 前景指定の外側にも、背景の判定用に幅・高さの10%（最低10px）を残す。
GRABCUT_MARGIN_RATIO = 0.1

type PolygonRatios = list[tuple[float, float]]
type Axis = tuple[np.ndarray, np.ndarray]

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


def polygon_pixels(polygon: PolygonRatios, width: int, height: int) -> np.ndarray:
    points = np.asarray(polygon, dtype=np.float64)
    if (
        points.ndim != 2
        or points.shape[1] != 2
        or len(points) < 3
        or not np.isfinite(points).all()
        or np.any(points < 0)
        or np.any(points > 1)
    ):
        raise ValueError("多角形は画像内の異なる3点以上で囲んでください")
    pixels = np.rint(points * (width - 1, height - 1)).astype(np.int32)
    if cv.contourArea(pixels) < 1:
        raise ValueError("多角形の面積が不足しています。指定範囲を広げてください")
    return pixels


def initial_mask(
    image: np.ndarray, regions: dict[int, list[PolygonRatios]]
) -> np.ndarray:
    height, width = image.shape[:2]
    labels = np.full((height, width), cv.GC_PR_BGD, np.uint8)
    for label in (cv.GC_PR_FGD, cv.GC_BGD, cv.GC_FGD):
        for polygon in regions[label]:
            pixels = polygon_pixels(polygon, width, height)
            cv.fillPoly(labels, [pixels], label)
    return labels


def initial_overlay(
    image: np.ndarray, regions: dict[int, list[PolygonRatios]]
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


def extract_specimen(
    image: np.ndarray, regions: dict[int, list[PolygonRatios]]
) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    height, width = image.shape[:2]
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
    points = contour.reshape(-1, 2).astype(np.float64)
    points += (left, top)
    return points, (left, top, right, bottom)


def manual_axis(points: np.ndarray) -> Axis:
    points = np.asarray(points, dtype=np.float64)
    if points.shape != (2, 2) or not np.isfinite(points).all():
        raise ValueError("軸は画像上の2点で指定してください")
    direction = points[1] - points[0]
    length = float(np.linalg.norm(direction))
    if length < 1:
        raise ValueError("軸の2点を1px以上離してください")
    direction /= length
    # 上→下へ向きを固定し、クリック順によるDR/OPの逆転を防ぐ。
    if direction[1] < 0 or (direction[1] == 0 and direction[0] < 0):
        direction = -direction
    return points.mean(axis=0), direction


def interval_positions(interval_points: np.ndarray, axis: Axis) -> tuple[float, float]:
    points = np.asarray(interval_points, dtype=np.float64)
    if points.shape != (2, 2) or not np.isfinite(points).all():
        raise ValueError("区間の上側・下側を画像上の2点で指定してください")
    origin, direction = axis
    positions = (points - origin) @ direction
    start, end = sorted(positions)
    if end - start < 1:
        raise ValueError("上下断面を軸方向に1px以上離してください")
    return float(start), float(end)


def fixed_interval_points(
    center: np.ndarray, length_mm: float, axis: Axis
) -> np.ndarray:
    center = np.asarray(center, dtype=np.float64)
    if center.shape != (2,) or not np.isfinite(center).all():
        raise ValueError("区間の中心を画像上で指定してください")
    if not math.isfinite(MM_PER_PX) or MM_PER_PX <= 0:
        raise ValueError("MM_PER_PXを正の数値にしてください")
    length_mm = positive_value(length_mm, "基準区間長")
    length_px = length_mm / MM_PER_PX
    if not math.isfinite(length_px) or length_px < 1:
        raise ValueError("基準区間長は画像上で1px以上の長さにしてください")
    half_interval = axis[1] * length_px / 2
    return np.array([center - half_interval, center + half_interval])


def section_edges(
    contour: np.ndarray,
    bounds: tuple[int, int, int, int],
    axis: Axis,
    positions: np.ndarray,
    outermost: bool = False,
) -> np.ndarray:
    origin, direction = axis
    normal = np.array([direction[1], -direction[0]])
    relative = contour - origin
    along = relative @ direction
    across = relative @ normal
    next_along = np.roll(along, -1)
    next_across = np.roll(across, -1)
    edges = []
    left, top, right, bottom = bounds
    for position in positions:
        # 半開区間で判定し、輪郭の頂点を二重に数えない。
        crosses = ((along <= position) & (position < next_along)) | (
            (next_along <= position) & (position < along)
        )
        fraction = (position - along[crosses]) / (next_along[crosses] - along[crosses])
        intersections = across[crosses] + fraction * (
            next_across[crosses] - across[crosses]
        )
        intersections.sort()
        # 接するだけの頂点は同じ位置が2回現れる。長さ0の区間を除く。
        spans = intersections.reshape(-1, 2)
        spans = spans[spans[:, 1] - spans[:, 0] > 1e-7]
        if len(spans) == 0 or (len(spans) != 1 and not outermost):
            raise ValueError(
                "断面で左右1本ずつの側辺を取れません。区間・軸・抽出を確認してください"
            )
        side_edges = np.array([spans[0, 0], spans[-1, 1]])
        points = origin + position * direction + side_edges[:, None] * normal
        if (
            np.any(points[:, 0] <= left + 0.5)
            or np.any(points[:, 0] >= right - 1.5)
            or np.any(points[:, 1] <= top + 0.5)
            or np.any(points[:, 1] >= bottom - 1.5)
        ):
            raise ValueError(
                "試料が処理範囲の端に接しています。前景候補か画像範囲を広げてください"
            )
        edges.append(side_edges)
    return np.asarray(edges)


def estimate_axis(
    contour: np.ndarray,
    bounds: tuple[int, int, int, int],
    interval_points: np.ndarray,
    fixed_length_mm: float | None = None,
) -> Axis:
    # 区間の2点を仮の方向に使い、その区間内の断面中点で当てはめ直す。
    axis = manual_axis(interval_points)
    center = np.asarray(interval_points, dtype=np.float64).mean(axis=0)
    for _ in range(3):
        if fixed_length_mm is not None:
            # 軸を傾けても区間が投影で短くならないよう、断面を置き直す。
            interval_points = fixed_interval_points(center, fixed_length_mm, axis)
        start, end = interval_positions(interval_points, axis)
        count = min(101, max(3, math.ceil(end - start) + 1))
        positions = np.linspace(start, end, count)
        edges = section_edges(contour, bounds, axis, positions, outermost=True)
        origin, direction = axis
        normal = np.array([direction[1], -direction[0]])
        midpoints = (
            origin
            + positions[:, None] * direction
            + edges.mean(axis=1)[:, None] * normal
        )
        vx, vy, x, y = cv.fitLine(
            midpoints.astype(np.float32), cv.DIST_L2, 0, 0.01, 0.01
        ).ravel()
        fitted_points = np.array([[x, y], [x + vx * 100, y + vy * 100]])
        axis = manual_axis(fitted_points)
    return axis


def side_chains(
    contour: np.ndarray,
    bounds: tuple[int, int, int, int],
    interval_points: np.ndarray,
    axis: Axis,
) -> list[np.ndarray]:
    start, end = interval_positions(interval_points, axis)
    # 区間の両端では側辺を一意に切れることを確認する。
    section_edges(contour, bounds, axis, np.array([start, end]))
    origin, direction = axis
    along = (contour - origin) @ direction
    chains = []
    current_chain = []
    for index in range(len(contour)):
        next_index = (index + 1) % len(contour)
        point = contour[index]
        next_point = contour[next_index]
        first = along[index]
        last = along[next_index]
        if abs(last - first) < 1e-12:
            if not start <= first <= end:
                continue
            enter, leave = 0.0, 1.0
        else:
            first_cut = (start - first) / (last - first)
            last_cut = (end - first) / (last - first)
            enter = max(0.0, min(first_cut, last_cut))
            leave = min(1.0, max(first_cut, last_cut))
            if leave <= enter:
                continue
        clipped_start = point + enter * (next_point - point)
        clipped_end = point + leave * (next_point - point)
        if current_chain and not np.allclose(
            current_chain[-1], clipped_start, atol=1e-7, rtol=0
        ):
            chains.append(np.asarray(current_chain))
            current_chain = []
        if not current_chain:
            current_chain.append(clipped_start)
        current_chain.append(clipped_end)
    if current_chain:
        chains.append(np.asarray(current_chain))
    # findContoursの始点が計測区間内にある場合、末尾と先頭は同じ側辺。
    if len(chains) > 1 and np.allclose(chains[-1][-1], chains[0][0], atol=1e-7, rtol=0):
        chains[0] = np.concatenate((chains[-1], chains[0][1:]))
        chains.pop()
    if len(chains) != 2:
        raise ValueError(
            "上下断面を結ぶ側辺を2本取れません。区間・抽出を確認してください"
        )
    left, top, right, bottom = bounds
    for index, chain in enumerate(chains):
        if np.dot(chain[-1] - chain[0], direction) < 0:
            chain = chain[::-1]
        endpoints = (chain[[0, -1]] - origin) @ direction
        if not np.allclose(endpoints, [start, end], atol=1e-6, rtol=0):
            raise ValueError("上下断面の両方を通る区間を指定してください")
        if (
            np.any(chain[:, 0] <= left + 0.5)
            or np.any(chain[:, 0] >= right - 1.5)
            or np.any(chain[:, 1] <= top + 0.5)
            or np.any(chain[:, 1] >= bottom - 1.5)
        ):
            raise ValueError(
                "試料が処理範囲の端に接しています。前景候補か画像範囲を広げてください"
            )
        chains[index] = chain
    normal = np.array([direction[1], -direction[0]])
    if np.dot(chains[0][0] - chains[1][0], normal) > 0:
        chains.reverse()
    return chains


def smoothed_sides(contour, bounds, interval_points, axis) -> list[np.ndarray]:
    for value, name in (
        (MM_PER_PX, "MM_PER_PX"),
        (EVALUATION_INTERVAL_MM, "EVALUATION_INTERVAL_MM"),
    ):
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name}を正の数値にしてください")
    if not math.isfinite(SMOOTHING_WIDTH_MM) or SMOOTHING_WIDTH_MM < 0:
        raise ValueError("SMOOTHING_WIDTH_MMを0以上の数値にしてください")
    step = EVALUATION_INTERVAL_MM / MM_PER_PX
    half_window = SMOOTHING_WIDTH_MM / MM_PER_PX / 2
    origin, direction = axis
    start, end = interval_positions(interval_points, axis)
    sides = []
    for chain in side_chains(contour, bounds, interval_points, axis):
        raw_steps = np.linalg.norm(np.diff(chain, axis=0), axis=1)
        distances = np.concatenate(([0.0], np.cumsum(raw_steps)))
        positions = np.append(np.arange(0, distances[-1], step), distances[-1])
        if len(positions) < 3:
            raise ValueError(
                "側辺に評価点が3点以上入るよう、評価間隔を小さくしてください"
            )
        dense_count = max(3, math.ceil(distances[-1] / min(1.0, step)) + 1)
        dense_positions = np.linspace(0, distances[-1], dense_count)
        dense_points = np.column_stack(
            (
                np.interp(dense_positions, distances, chain[:, 0]),
                np.interp(dense_positions, distances, chain[:, 1]),
            )
        )
        points = np.empty((len(positions), 2), dtype=np.float64)
        for index, position in enumerate(positions):
            nearby = np.abs(dense_positions - position) <= half_window + 1e-8
            if half_window == 0 or np.count_nonzero(nearby) < 3:
                for coordinate in (0, 1):
                    points[index, coordinate] = np.interp(
                        position, distances, chain[:, coordinate]
                    )
                continue
            offsets = dense_positions[nearby] - position
            matrix = np.column_stack((np.ones(len(offsets)), offsets))
            # 端では窓を区間内に切り詰め、直線の方向を保つ局所直線を使う。
            coefficients, _, _, _ = np.linalg.lstsq(
                matrix, dense_points[nearby], rcond=None
            )
            points[index] = coefficients[0]
        # 平滑化後も両端を指定した断面上へ戻す。
        for index, position in ((0, start), (-1, end)):
            correction = position - np.dot(points[index] - origin, direction)
            points[index] += correction * direction
        sides.append(points)
    return sides


def measure_contour(
    contour: np.ndarray,
    bounds: tuple[int, int, int, int],
    interval_points: np.ndarray,
    axis: Axis,
) -> dict:
    sides = smoothed_sides(contour, bounds, interval_points, axis)
    start, end = interval_positions(interval_points, axis)
    interval_mm = (end - start) * MM_PER_PX
    row = {
        "mm_per_px": MM_PER_PX,
        "interval_length_mm": interval_mm,
        "evaluation_interval_mm": EVALUATION_INTERVAL_MM,
        "smoothing_width_mm": SMOOTHING_WIDTH_MM,
    }
    for side, name in ((0, "left"), (1, "right")):
        steps = np.diff(sides[side], axis=0)
        length_px = float(np.linalg.norm(steps, axis=1).sum())
        row[f"{name}_px"] = length_px
        row[f"{name}_mm"] = length_px * MM_PER_PX
        row[f"{name}_excess_percent"] = (length_px * MM_PER_PX / interval_mm - 1) * 100
    row["total_px"] = row["left_px"] + row["right_px"]
    row["total_mm"] = row["left_mm"] + row["right_mm"]
    return row


def draw_axis_and_sections(image: np.ndarray, interval_points: np.ndarray, axis: Axis):
    origin, direction = axis
    normal = np.array([direction[1], -direction[0]])
    start, end = interval_positions(interval_points, axis)
    reach = math.hypot(*image.shape[:2])
    for position in (start, end):
        center = origin + position * direction
        ends = np.rint([center - reach * normal, center + reach * normal]).astype(int)
        cv.line(image, tuple(ends[0]), tuple(ends[1]), (0, 255, 255), 1)
    ends = np.rint([origin + start * direction, origin + end * direction]).astype(int)
    cv.line(image, tuple(ends[0]), tuple(ends[1]), (255, 255, 0), 2)


def measurement_overlay(image, contour, bounds, interval_points, axis) -> np.ndarray:
    sides = smoothed_sides(contour, bounds, interval_points, axis)
    overlay = image.copy()
    for points in sides:
        cv.polylines(overlay, [np.rint(points).astype(np.int32)], False, (0, 0, 255), 2)
    draw_axis_and_sections(overlay, interval_points, axis)
    draw_edge_names(overlay)
    return overlay


def measure_lengths(image, regions, interval_points, axis) -> tuple[dict, np.ndarray]:
    contour, bounds = extract_specimen(image, regions)
    row = measure_contour(contour, bounds, interval_points, axis)
    row["image_height"], row["image_width"] = image.shape[:2]
    overlay = measurement_overlay(image, contour, bounds, interval_points, axis)
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
    regions: dict[int, list[PolygonRatios]] = {label: [] for label in REGION_NAMES}
    region_rows: list[tuple[int, int]] = []
    photo: tk.PhotoImage | None = None
    scale = 1.0
    offset_x = offset_y = 0.0
    pan_start: tuple[int, int] | None = None
    pending_polygon: PolygonRatios = []
    interval_center: tuple[float, float] | None = None
    interval_points: np.ndarray | None = None
    manual_points: list[tuple[float, float]] = []
    contour: np.ndarray | None = None
    bounds: tuple[int, int, int, int] | None = None
    axis: Axis | None = None

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

    length_text = tk.StringVar()
    axis_text = tk.StringVar(value="軸：未推定")

    def load_image() -> None:
        nonlocal image, input_path, height, width, interval_center
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
        interval_center = None
        clear_regions()
        fit_image()

    def on_regions_changed() -> None:
        nonlocal contour, bounds, axis, interval_points
        contour = bounds = axis = interval_points = None
        pending_polygon.clear()
        manual_points.clear()
        axis_text.set("軸：未推定")
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
        for polygons in regions.values():
            polygons.clear()
        on_regions_changed()

    def show_initial(_event=None) -> None:
        pending_polygon.clear()
        manual_points.clear()
        view.set("initial")
        selection_target.set("region")
        render()

    def render(_event=None) -> None:
        nonlocal photo
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
                    for polygon in regions[label]:
                        pixels = polygon_pixels(polygon, width, height)
                        pixels = np.rint(
                            pixels * scale
                            + (offset_x - display_left, offset_y - display_top)
                        ).astype(np.int32)
                        cv.fillPoly(preview_labels, [pixels], label)
                small = cv.addWeighted(small, 0.65, PALETTE[preview_labels], 0.35, 0)
            photo = tk.PhotoImage(master=root, data=encode_png(small), format="PNG")
            canvas.create_image(display_left, display_top, image=photo, anchor="nw")
        selection = region_list.curselection()
        if view.get() == "initial" and selection:
            label, index = region_rows[selection[0]]
            points = canvas_polygon(regions[label][index])
            canvas.create_polygon(
                *points,
                outline="yellow",
                width=2,
                fill="",
            )
        if pending_polygon:
            points = canvas_polygon(pending_polygon)
            if len(pending_polygon) > 1:
                canvas.create_line(*points, fill="white", width=2, dash=(5, 3))
            for x, y in zip(points[::2], points[1::2]):
                canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill="white")
        if interval_center is not None:
            x = offset_x + interval_center[0] * scale
            y = offset_y + interval_center[1] * scale
            canvas.create_oval(x - 4, y - 4, x + 4, y + 4, outline="yellow", width=2)
            canvas.create_text(x + 7, y, text="中心", fill="yellow", anchor="w")
        if axis is not None and interval_points is not None:
            origin, direction = axis
            normal = np.array([direction[1], -direction[0]])
            start, end = interval_positions(np.asarray(interval_points), axis)
            for position in (start, end):
                center = origin + position * direction
                reach = math.hypot(width, height)
                ends = np.array([center - reach * normal, center + reach * normal])
                ends = ends * scale + (offset_x, offset_y)
                canvas.create_line(
                    *ends.ravel(), fill="yellow", width=2, tags="interval"
                )
            ends = np.array([origin + start * direction, origin + end * direction])
            ends = ends * scale + (offset_x, offset_y)
            canvas.create_line(
                *ends.ravel(), fill="cyan", width=2, dash=(6, 3), tags="axis"
            )
        for point in manual_points:
            x = offset_x + point[0] * scale
            y = offset_y + point[1] * scale
            canvas.create_oval(x - 4, y - 4, x + 4, y + 4, outline="cyan", width=2)
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

    def canvas_polygon(polygon: PolygonRatios) -> list[float]:
        points = []
        for x_ratio, y_ratio in polygon:
            points.extend(
                (
                    offset_x + x_ratio * (width - 1) * scale,
                    offset_y + y_ratio * (height - 1) * scale,
                )
            )
        return points

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

    def click_image(event: tk.Event) -> None:
        nonlocal axis, interval_center, interval_points
        if image is None:
            return
        if (
            offset_x <= event.x < offset_x + width * scale
            and offset_y <= event.y < offset_y + height * scale
        ):
            target = selection_target.get()
            point = ((event.x - offset_x) / scale, (event.y - offset_y) / scale)
            point = (min(width - 1, point[0]), min(height - 1, point[1]))
            if target == "center":
                pending_polygon.clear()
                interval_center = point
                on_interval_changed()
                return
            if target == "axis":
                if contour is None or bounds is None or interval_center is None:
                    status.set("先に区間を指定し、試料抽出・軸を自動推定してください")
                    return
                clear_results()
                view.set("initial")
                manual_points.append(point)
                if len(manual_points) == 2:
                    axis = None
                    try:
                        proposed_axis = manual_axis(np.asarray(manual_points))
                        length_mm = positive_value(length_text.get(), "基準区間長")
                        interval_points = fixed_interval_points(
                            np.asarray(interval_center), length_mm, proposed_axis
                        )
                    except ValueError as error:
                        status.set(str(error))
                        axis_text.set("軸：未設定")
                    else:
                        axis = proposed_axis
                        axis_text.set("軸：手動2点")
                        status.set("")
                    manual_points.clear()
                else:
                    axis = None
                    interval_points = None
                    axis_text.set("手動軸：1点")
                    status.set("")
                render()
                return
            if view.get() != "initial":
                return
            clear_results()
            pending_polygon.append((point[0] / (width - 1), point[1] / (height - 1)))
            status.set(f"多角形：{len(pending_polygon)}点")
            render()

    def finish_polygon() -> None:
        if image is None or not pending_polygon:
            return
        try:
            polygon_pixels(pending_polygon, width, height)
        except ValueError as error:
            status.set(str(error))
            return
        regions[mode.get()].append(list(pending_polygon))
        on_regions_changed()

    def cancel_drawing() -> None:
        pending_polygon.clear()
        manual_points.clear()
        if axis is None:
            axis_text.set("軸：未推定")
        status.set("")
        render()

    def select_target() -> None:
        cancel_drawing()
        if selection_target.get() == "region":
            view.set("initial")
        render()

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
            result_table.set(item, "excess", "—")
        save_measurement_button.state(["disabled"])

    def on_interval_changed(*_args) -> None:
        nonlocal axis, interval_points
        axis = interval_points = None
        manual_points.clear()
        axis_text.set("軸：未推定")
        clear_results()
        if view.get() == "result":
            view.set("initial")
        if contour is not None and bounds is not None and interval_center is not None:
            fit_axis()
        else:
            status.set("")
        render()

    def fit_axis() -> None:
        nonlocal axis, interval_points
        axis = interval_points = None
        if contour is None or bounds is None or interval_center is None:
            return
        try:
            length_mm = positive_value(length_text.get(), "基準区間長")
            center = np.asarray(interval_center)
            seed_axis = (center, np.array([0.0, 1.0]))
            seed_points = fixed_interval_points(center, length_mm, seed_axis)
            fitted_axis = estimate_axis(
                contour, bounds, seed_points, fixed_length_mm=length_mm
            )
            interval_points = fixed_interval_points(center, length_mm, fitted_axis)
            axis = fitted_axis
        except (ValueError, cv.error) as error:
            axis_text.set("軸：自動推定失敗")
            status.set(str(error))
            return
        axis_text.set("軸：自動")
        status.set("")

    def extract_and_estimate() -> None:
        nonlocal contour, bounds, axis, interval_points
        clear_results()
        manual_points.clear()
        contour = bounds = axis = interval_points = None
        axis_text.set("軸：未推定")
        view.set("initial")
        if image is None:
            status.set("補正画像を読み込んでください")
            return
        if pending_polygon or interval_center is None:
            status.set("多角形を確定し、基準区間長と区間の中心を指定してください")
            return
        try:
            length_mm = positive_value(length_text.get(), "基準区間長")
            center = np.asarray(interval_center)
            fixed_interval_points(center, length_mm, (center, np.array([0.0, 1.0])))
        except ValueError as error:
            status.set(str(error))
            return
        status.set("試料抽出中…")
        root.update_idletasks()
        try:
            contour, bounds = extract_specimen(image, regions)
        except ValueError as error:
            status.set(str(error))
        except cv.error:
            status.set("試料を抽出できません。多角形を調整してください")
        else:
            fit_axis()
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
        if (
            pending_polygon
            or manual_points
            or contour is None
            or bounds is None
            or axis is None
            or interval_points is None
        ):
            status.set("多角形と区間を指定し、軸を推定・確認してから計測してください")
            return
        status.set("計測中…")
        root.update_idletasks()
        try:
            points = np.asarray(interval_points)
            measured = measure_contour(contour, bounds, points, axis)
            measured["image_height"], measured["image_width"] = image.shape[:2]
            overlay = measurement_overlay(image, contour, bounds, points, axis)
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
            if edge != "total":
                result_table.set(
                    edge, "excess", f"{measured[f'{edge}_excess_percent']:.3f}"
                )
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
            if axis is not None and interval_points is not None:
                draw_axis_and_sections(initial_image, np.asarray(interval_points), axis)
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
    for value, name in (
        ("region", "多角形"),
        ("center", "区間の中心"),
        ("axis", "手動軸2点"),
    ):
        ttk.Radiobutton(
            preview_tools,
            text=name,
            variable=selection_target,
            value=value,
            command=select_target,
        ).pack(side="left", padx=4)
    canvas = tk.Canvas(
        content, background="#242424", highlightthickness=0, cursor="crosshair"
    )
    canvas.pack(fill="both", expand=True)

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
    polygon_actions = ttk.Frame(sidebar)
    polygon_actions.pack(fill="x", pady=3)
    for name, action in (
        ("多角形を確定", finish_polygon),
        ("描画を取消", cancel_drawing),
    ):
        ttk.Button(polygon_actions, text=name, command=action).pack(
            side="left", expand=True, fill="x"
        )
    for name, action in (
        ("選択した多角形を削除", delete_region),
        ("多角形をすべて削除", clear_regions),
    ):
        ttk.Button(sidebar, text=name, padding=(12, 4), command=action).pack(
            fill="x", pady=3
        )

    interval_controls = ttk.Frame(sidebar)
    interval_controls.pack(fill="x", pady=(8, 3))
    ttk.Label(interval_controls, text="基準区間長 (mm)").pack(side="left")
    ttk.Entry(interval_controls, textvariable=length_text, width=10).pack(side="right")
    ttk.Button(
        sidebar, text="試料抽出・軸を自動推定", command=extract_and_estimate
    ).pack(fill="x", pady=3)
    ttk.Label(sidebar, textvariable=axis_text, wraplength=290).pack(anchor="w")
    ttk.Label(
        sidebar,
        text=f"評価間隔 {EVALUATION_INTERVAL_MM:g} mm / 平滑化幅 {SMOOTHING_WIDTH_MM:g} mm",
    ).pack(anchor="w")
    ttk.Button(sidebar, text="長さを計測", padding=(12, 7), command=calculate).pack(
        fill="x", pady=4
    )
    result_table = ttk.Treeview(
        sidebar,
        columns=("edge", "length", "excess"),
        show="headings",
        height=3,
        selectmode="none",
    )
    result_table.heading("edge", text="側辺")
    result_table.heading("length", text="長さ (mm)")
    result_table.heading("excess", text="超過率 (%)")
    result_table.column("edge", width=60, stretch=False)
    result_table.column("length", width=105, anchor="e")
    result_table.column("excess", width=95, anchor="e")
    for edge, label in (("left", "DR"), ("right", "OP"), ("total", "合計")):
        result_table.insert("", "end", iid=edge, values=(label, "—", "—"))
    result_table.pack(fill="x", pady=4)
    save_measurement_button = ttk.Button(
        sidebar, text="CSV・画像2枚を保存", padding=(12, 7), command=save_measurement
    )
    save_measurement_button.pack(fill="x", pady=4)
    view_tools = ttk.Frame(sidebar)
    view_tools.pack(fill="x")
    for value, name in (
        ("initial", "初期指定"),
        ("original", "元画像"),
        ("result", "計測結果"),
    ):
        ttk.Radiobutton(
            view_tools, text=name, variable=view, value=value, command=render
        ).pack(side="left")

    length_text.trace_add("write", on_interval_changed)
    canvas.bind("<Configure>", render)
    canvas.bind("<ButtonPress-1>", click_image)
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
