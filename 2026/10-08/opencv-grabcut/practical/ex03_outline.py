"""元の解像度で試料を抽出し、外側の輪郭を描く."""

import json
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

# 元画像に外側の輪郭を赤で描く。
result = image.copy()
cv.drawContours(result, [contour], -1, (0, 0, 255), thickness=2)

# 結果画像、確認用マスク、実行した条件を保存する。
output_directory.mkdir(parents=True, exist_ok=True)
for filename, output_image in (
    ("result_03.png", result),
    ("result_03_initial.png", initial),
    ("result_03_raw_mask.png", raw_mask),
    ("result_03_mask.png", mask),
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
path = output_directory / "result_03_conditions.json"
path.write_text(
    json.dumps(conditions, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
