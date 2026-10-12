"""GrabCut フル解像度で板抽出、最大輪郭を赤縁で描く."""

from pathlib import Path

import cv2 as cv
import numpy as np

directory = Path(__file__).resolve().parent
output_directory = directory / "results"
image = cv.imread(str(directory / "input.png"))
if image is None:
    msg = "input.png が見つかりません"
    raise FileNotFoundError(msg)
h, w = image.shape[:2]

mask = np.full((h, w), cv.GC_PR_BGD, np.uint8)
mask[:, : int(w * 0.33)] = cv.GC_BGD
mask[:, int(w * 0.72) :] = cv.GC_BGD
mask[:, int(w * 0.34) : int(w * 0.705)] = cv.GC_PR_FGD
mask[:, int(w * 0.48) : int(w * 0.56)] = cv.GC_FGD

background = np.zeros((1, 65), np.float64)
foreground = np.zeros((1, 65), np.float64)

cv.grabCut(image, mask, (0, 0, 1, 1), background, foreground, 5, cv.GC_INIT_WITH_MASK)

mask = np.isin(mask, (cv.GC_FGD, cv.GC_PR_FGD)).astype(np.uint8) * 255

contours, _ = cv.findContours(mask, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
largest = max(contours, key=cv.contourArea)

result = image.copy()
cv.drawContours(result, [largest], -1, (0, 0, 255), 2)

output_directory.mkdir(parents=True, exist_ok=True)
cv.imwrite(str(output_directory / "result_03.png"), result)
