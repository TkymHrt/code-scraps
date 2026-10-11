"""元の解像度で試料を抽出し、左右側辺の長さを計測する."""

import csv
import json
import sys
from pathlib import Path

import cv2 as cv
import numpy as np

# 変更する設定はここにまとめる。パスはこのスクリプトのフォルダが基準。
INPUT_PATH = "input.png"
OUTPUT_DIRECTORY = "results"
ITERATIONS = 5
RANDOM_SEED = 0

# 矩形は左・上・右・下の順。画像全体に対する0〜1の割合で指定する。
CANDIDATE_RECT = (0.34, 0.0, 0.705, 1.0)
BACKGROUND_RECTS = (
    (0.0, 0.0, 0.33, 1.0),
    (0.72, 0.0, 1.0, 1.0),
)
FOREGROUND_RECTS = ((0.48, 0.0, 0.56, 1.0),)

# 元の大きさのまま画像を読む。
directory = Path(__file__).resolve().parent
input_path = (directory / INPUT_PATH).resolve()
output_directory = (directory / OUTPUT_DIRECTORY).resolve()
image = cv.imread(str(input_path))
if image is None:
    msg = f"入力画像を読み込めません: {input_path}"
    raise FileNotFoundError(msg)
height, width = image.shape[:2]

# 設定した矩形をGrabCutの初期マスクに書き込む。
labels = np.full((height, width), cv.GC_PR_BGD, np.uint8)
for label, rectangles in (
    (cv.GC_PR_FGD, (CANDIDATE_RECT,)),
    (cv.GC_BGD, BACKGROUND_RECTS),
    (cv.GC_FGD, FOREGROUND_RECTS),
):
    for left, top, right, bottom in rectangles:
        x0, y0 = int(width * left), int(height * top)
        x1, y1 = int(width * right), int(height * bottom)
        labels[y0:y1, x0:x1] = label

palette = np.array(
    [(255, 80, 0), (0, 255, 0), (64, 64, 64), (0, 165, 255)], dtype=np.uint8
)
initial = cv.addWeighted(image, 0.65, palette[labels], 0.35, 0)

# 同じ乱数シードと反復回数でGrabCutを実行する。
background = np.zeros((1, 65), np.float64)
foreground = np.zeros((1, 65), np.float64)
cv.setRNGSeed(RANDOM_SEED)
cv.grabCut(
    image,
    labels,
    (0, 0, 1, 1),
    background,
    foreground,
    ITERATIONS,
    cv.GC_INIT_WITH_MASK,
)
raw_mask = np.isin(labels, (cv.GC_FGD, cv.GC_PR_FGD)).astype(np.uint8) * 255

# 最も面積の大きい外側輪郭を選び、内部を塗りつぶす。
contours, _ = cv.findContours(raw_mask, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
if not contours:
    msg = "試料の領域が見つかりません。初期指定を確認してください"
    raise ValueError(msg)
contour = max(contours, key=cv.contourArea)
mask = np.zeros((height, width), np.uint8)
cv.drawContours(mask, [contour], -1, 255, thickness=-1)

# 上から1行ずつ調べ、その行にある試料の左端と右端を集める。
left_points = []
right_points = []
for y in range(height):
    xs = np.where(mask[y] > 0)[0]
    if len(xs) > 0:
        left_points.append((int(xs[0]), y))
        right_points.append((int(xs[-1]), y))

left_edge = np.array(left_points, dtype=np.int32)
right_edge = np.array(right_points, dtype=np.int32)

# 左右の点列を閉じずに測り、元画像に線と長さを表示する。
left_length = cv.arcLength(left_edge, closed=False)
right_length = cv.arcLength(right_edge, closed=False)
total_length = left_length + right_length

result = image.copy()
left_color = (0, 165, 255)
right_color = (255, 255, 0)
cv.polylines(result, [left_edge], isClosed=False, color=left_color, thickness=2)
cv.polylines(result, [right_edge], isClosed=False, color=right_color, thickness=2)
measurements = (
    ("Left", left_length, left_color),
    ("Right", right_length, right_color),
    ("Total", total_length, (255, 255, 255)),
)
cv.rectangle(result, (12, 12), (440, 152), (0, 0, 0), thickness=-1)
for row, (label, length, color) in enumerate(measurements):
    cv.putText(
        result,
        f"{label}: {length:.2f} px",
        (24, 48 + row * 42),
        cv.FONT_HERSHEY_SIMPLEX,
        0.8,
        color,
        thickness=2,
        lineType=cv.LINE_AA,
    )

# 結果画像、確認用マスク、実行した条件を保存する。
output_directory.mkdir(parents=True, exist_ok=True)
for filename, output_image in (
    ("result_05.png", result),
    ("result_05_initial.png", initial),
    ("result_05_raw_mask.png", raw_mask),
    ("result_05_mask.png", mask),
):
    path = output_directory / filename
    cv.imwrite(str(path), output_image)

conditions = {
    "input_path": str(input_path),
    "image_width_px": width,
    "image_height_px": height,
    "processing_scale": 1.0,
    "iterations": ITERATIONS,
    "random_seed": RANDOM_SEED,
    "candidate_rect": CANDIDATE_RECT,
    "background_rects": BACKGROUND_RECTS,
    "foreground_rects": FOREGROUND_RECTS,
    "initial_default": "probable_background",
    "selection": "largest_external_contour_area",
    "fill_internal_holes": True,
    "morphology": None,
    "smoothing": None,
    "side_edge_method": "outermost_pixel_each_row",
    "length_unit": "px",
    "opencv_version": cv.__version__,
    "numpy_version": np.__version__,
}
path = output_directory / "result_05_conditions.json"
path.write_text(
    json.dumps(conditions, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)

# 左・右・合計の長さをCSVとターミナルにも出す。
path = output_directory / "result_05.csv"
with path.open("w", encoding="utf-8", newline="") as output:
    writer = csv.writer(output)
    writer.writerow(("edge", "length_px"))
    for label, length, _ in measurements:
        writer.writerow((label.lower(), f"{length:.2f}"))

sys.stdout.write(
    f"Left:  {left_length:.2f} px\n"
    f"Right: {right_length:.2f} px\n"
    f"Total: {total_length:.2f} px\n"
)
