"""GrabCut 半分縮小で板抽出、上下面を除いた左右端の長さを測る."""

import csv
import sys
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
if not contours:
    msg = "板の領域が見つかりません"
    raise ValueError(msg)
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

minimum_points = 2
if len(left_points) < minimum_points:
    msg = "長さの計測には板が2行以上必要です"
    raise ValueError(msg)

left_edge = np.array(left_points, dtype=np.int32)
right_edge = np.array(right_points, dtype=np.int32)
left_length = cv.arcLength(left_edge, closed=False)
right_length = cv.arcLength(right_edge, closed=False)
total_length = left_length + right_length

result = image.copy()
left_color = (0, 165, 255)
right_color = (255, 255, 0)

cv.polylines(
    result,
    [left_edge],
    isClosed=False,
    color=left_color,
    thickness=2,
)
cv.polylines(
    result,
    [right_edge],
    isClosed=False,
    color=right_color,
    thickness=2,
)

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

output_directory.mkdir(parents=True, exist_ok=True)
if not cv.imwrite(str(output_directory / "result_05.png"), result):
    msg = "result_05.png を保存できません"
    raise OSError(msg)

with (output_directory / "result_05.csv").open(
    "w", encoding="utf-8", newline=""
) as output:
    writer = csv.writer(output)
    writer.writerow(("edge", "length_px"))
    for label, length, _ in measurements:
        writer.writerow((label.lower(), f"{length:.2f}"))

sys.stdout.write(
    f"Left:  {left_length:.2f} px\n"
    f"Right: {right_length:.2f} px\n"
    f"Total: {total_length:.2f} px\n"
)
