"""先頭の数値で探索範囲を変え、GrabCutのマスクを画像で見比べる."""

from pathlib import Path

import cv2 as cv
import numpy as np

INPUT_PATH = "input.png"
OUTPUT_PREFIX = "result_06"
LEFT = 0.30
RIGHT = 0.75
TOP = 0.00
BOTTOM = 1.00
SCALE = 0.5
ITERATIONS = 5

directory = Path(__file__).resolve().parent
output_directory = directory / "results"
image = cv.imread(str(directory / INPUT_PATH))
if image is None:
    msg = f"入力画像が見つかりません: {INPUT_PATH}"
    raise FileNotFoundError(msg)
h, w = image.shape[:2]
small = cv.resize(image, None, fx=SCALE, fy=SCALE, interpolation=cv.INTER_AREA)
sh, sw = small.shape[:2]

mask = np.zeros((sh, sw), np.uint8)
mask[int(sh * TOP) : int(sh * BOTTOM), int(sw * LEFT) : int(sw * RIGHT)] = cv.GC_PR_FGD

initial_mask = (mask == cv.GC_PR_FGD).astype(np.uint8) * 255
initial_mask = cv.resize(initial_mask, (w, h), interpolation=cv.INTER_NEAREST)
initial = cv.bitwise_and(image, image, mask=initial_mask)
output_directory.mkdir(parents=True, exist_ok=True)
cv.imwrite(str(output_directory / f"{OUTPUT_PREFIX}_initial.png"), initial)

background = np.zeros((1, 65), np.float64)
foreground = np.zeros((1, 65), np.float64)
cv.grabCut(
    small,
    mask,
    (0, 0, 1, 1),
    background,
    foreground,
    ITERATIONS,
    cv.GC_INIT_WITH_MASK,
)

mask = np.isin(mask, (cv.GC_FGD, cv.GC_PR_FGD)).astype(np.uint8) * 255
mask = cv.resize(mask, (w, h), interpolation=cv.INTER_NEAREST)
result = cv.bitwise_and(image, image, mask=mask)

cv.imwrite(str(output_directory / f"{OUTPUT_PREFIX}_mask.png"), mask)
cv.imwrite(str(output_directory / f"{OUTPUT_PREFIX}.png"), result)
