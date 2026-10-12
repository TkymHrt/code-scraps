"""初期指定を改善したGrabCutに縦オープニングを追加して比較する."""

import sys
from pathlib import Path

import cv2 as cv
import numpy as np

INPUT_PATH = "input_ai.png"
OUTPUT_PREFIX = "result_09"
ITERATIONS = 5
RANDOM_SEED = 0
LEFT = 0.33
RIGHT = 0.72
TOP = 0.0
BOTTOM = 1.0
FOREGROUND_RECTS = (
    (0.49, 0.12, 0.55, 0.20),
    (0.49, 0.58, 0.55, 0.66),
    (0.49, 0.88, 0.55, 0.94),
)
BACKGROUND_RECTS = (
    (0.34, 0.0, 0.365, 1.0),
    (0.675, 0.0, 0.71, 1.0),
)
VERTICAL_SIZE = 41

if VERTICAL_SIZE < 1 or VERTICAL_SIZE % 2 == 0:
    msg = "VERTICAL_SIZEは1以上の奇数にしてください"
    raise ValueError(msg)
directory = Path(__file__).resolve().parent
image = cv.imread(str(directory / INPUT_PATH))
if image is None:
    msg = f"入力画像が見つかりません: {directory / INPUT_PATH}"
    raise FileNotFoundError(msg)
h, w = image.shape[:2]
labels = np.full((h, w), cv.GC_BGD, np.uint8)
for label, rectangles in (
    (cv.GC_PR_FGD, ((LEFT, TOP, RIGHT, BOTTOM),)),
    (cv.GC_BGD, BACKGROUND_RECTS),
    (cv.GC_FGD, FOREGROUND_RECTS),
):
    for left, top, right, bottom in rectangles:
        if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
            msg = "矩形は0〜1の範囲で左 < 右、上 < 下にしてください"
            raise ValueError(msg)
        x0, y0 = int(w * left), int(h * top)
        x1, y1 = int(w * right), int(h * bottom)
        if x0 >= x1 or y0 >= y1:
            msg = "指定した矩形が1画素未満になっています"
            raise ValueError(msg)
        labels[y0:y1, x0:x1] = label
palette = np.array(
    [(255, 80, 0), (0, 255, 0), (64, 64, 64), (0, 165, 255)], dtype=np.uint8
)
initial = cv.addWeighted(image, 0.65, palette[labels], 0.35, 0)

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
count, components, stats, _ = cv.connectedComponentsWithStats(raw_mask)
if count <= 1:
    msg = "試料の領域が見つかりません"
    raise ValueError(msg)
largest = int(np.argmax(stats[1:, cv.CC_STAT_AREA])) + 1
before_mask = (components == largest).astype(np.uint8) * 255
kernel = cv.getStructuringElement(cv.MORPH_RECT, (1, VERTICAL_SIZE))
opened = cv.morphologyEx(before_mask, cv.MORPH_OPEN, kernel)
count, components, stats, _ = cv.connectedComponentsWithStats(opened)
if count <= 1:
    msg = "オープニング後に試料が消えました。VERTICAL_SIZEを小さくしてください"
    raise ValueError(msg)
largest = int(np.argmax(stats[1:, cv.CC_STAT_AREA])) + 1
mask = (components == largest).astype(np.uint8) * 255
removed = ((before_mask > 0) & (mask == 0)).astype(np.uint8) * 255
changes = image.copy()
changes[removed > 0] = (255, 0, 255)
contours, _ = cv.findContours(mask, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
outline = image.copy()
cv.drawContours(outline, contours, -1, (0, 0, 255), 2)
cutout = cv.bitwise_and(image, image, mask=mask)

outputs = {
    "initial": initial,
    "raw_mask": raw_mask,
    "before_mask": before_mask,
    "mask": mask,
    "removed": removed,
    "changes": changes,
    "outline": outline,
    "cutout": cutout,
}
output_directory = directory / "results"
output_directory.mkdir(parents=True, exist_ok=True)
for suffix, output in outputs.items():
    path = output_directory / f"{OUTPUT_PREFIX}_{suffix}.png"
    if not cv.imwrite(str(path), output):
        msg = f"画像を保存できません: {path}"
        raise OSError(msg)
sys.stdout.write(
    f"{OUTPUT_PREFIX}: foreground={np.count_nonzero(mask)} px, "
    f"removed={np.count_nonzero(removed)} px\n"
)
