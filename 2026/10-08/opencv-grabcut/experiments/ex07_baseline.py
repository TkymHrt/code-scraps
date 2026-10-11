"""中央の縦帯を確実な前景にした元方式をAI画像で比較する."""

import sys
from pathlib import Path

import cv2 as cv
import numpy as np

INPUT_PATH = "input_ai.png"
OUTPUT_PREFIX = "result_07"
ITERATIONS = 5
RANDOM_SEED = 0

directory = Path(__file__).resolve().parent
image = cv.imread(str(directory / INPUT_PATH))
if image is None:
    msg = f"入力画像が見つかりません: {directory / INPUT_PATH}"
    raise FileNotFoundError(msg)
h, w = image.shape[:2]

labels = np.full((h, w), cv.GC_PR_BGD, np.uint8)
labels[:, : int(w * 0.33)] = cv.GC_BGD
labels[:, int(w * 0.72) :] = cv.GC_BGD
labels[:, int(w * 0.34) : int(w * 0.705)] = cv.GC_PR_FGD
labels[:, int(w * 0.48) : int(w * 0.56)] = cv.GC_FGD
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
mask = (components == largest).astype(np.uint8) * 255
contours, _ = cv.findContours(mask, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
outline = image.copy()
cv.drawContours(outline, contours, -1, (0, 0, 255), 2)
cutout = cv.bitwise_and(image, image, mask=mask)

outputs = {
    "initial": initial,
    "raw_mask": raw_mask,
    "mask": mask,
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
sys.stdout.write(f"{OUTPUT_PREFIX}: foreground={np.count_nonzero(mask)} px\n")
