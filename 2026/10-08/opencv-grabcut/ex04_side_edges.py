"""GrabCut 半分縮小で板抽出、左右端だけ赤線で描く."""

import cv2 as cv
import numpy as np

image = cv.imread("input.png")
if image is None:
    msg = "input.png が見つかりません"
    raise FileNotFoundError(msg)
h, w = image.shape[:2]
small = cv.resize(image, None, fx=0.5, fy=0.5, interpolation=cv.INTER_AREA)
sh, sw = small.shape[:2]

mask = np.full((sh, sw), cv.GC_PR_BGD, np.uint8)
mask[:, : int(sw * 0.33)] = cv.GC_BGD
mask[:, int(sw * 0.72) :] = cv.GC_BGD
mask[:, int(sw * 0.34) : int(sw * 0.705)] = cv.GC_PR_FGD
mask[:, int(sw * 0.48) : int(sw * 0.56)] = cv.GC_FGD

background = np.zeros((1, 65), np.float64)
foreground = np.zeros((1, 65), np.float64)

cv.grabCut(small, mask, (0, 0, 1, 1), background, foreground, 5, cv.GC_INIT_WITH_MASK)

mask = np.isin(mask, (cv.GC_FGD, cv.GC_PR_FGD)).astype(np.uint8) * 255

mask = cv.resize(mask, (w, h), interpolation=cv.INTER_NEAREST)

contours, _ = cv.findContours(mask, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
largest = max(contours, key=cv.contourArea)

mask = np.zeros((h, w), np.uint8)
cv.drawContours(mask, [largest], -1, 255, thickness=-1)

left_points: list[list[int]] = []
right_points: list[list[int]] = []

for y in range(h):
    xs = np.where(mask[y] > 0)[0]

    if len(xs) == 0:
        continue

    left_points.append([int(xs[0]), y])
    right_points.append([int(xs[-1]), y])

result = image.copy()

if left_points:
    cv.polylines(
        result,
        [np.array(left_points, dtype=np.int32)],
        isClosed=False,
        color=(0, 0, 255),
        thickness=2,
    )
if right_points:
    cv.polylines(
        result,
        [np.array(right_points, dtype=np.int32)],
        isClosed=False,
        color=(0, 0, 255),
        thickness=2,
    )

cv.imwrite("result_04.png", result)
