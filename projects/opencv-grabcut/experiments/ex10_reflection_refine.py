"""細い張り出しとローラー反射帯が重なる部分を背景指定して再判定する."""

import sys
from pathlib import Path

import cv2 as cv
import numpy as np

INPUT_PATH = "input_ai.png"
OUTPUT_PREFIX = "result_10"
ITERATIONS = 5
REFINE_ITERATIONS = 3
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
EDGE_WINDOW = 101
MIN_EXTENSION = 10
EDGE_MARGIN = 3
ROLLER_LEFT = (0.25, 0.35)
ROLLER_RIGHT = (0.70, 0.84)
PROFILE_WINDOW = 81
MIN_ROLLER_CONTRAST = 14
MIN_BRIGHTNESS = 150
BAND_MARGIN = 5
REFINE_MARGIN = 7

for size in (VERTICAL_SIZE, EDGE_WINDOW, PROFILE_WINDOW):
    if size < 1 or size % 2 == 0:
        msg = "カーネルと窓の大きさは1以上の奇数にしてください"
        raise ValueError(msg)
if not (0 <= EDGE_MARGIN < MIN_EXTENSION and BAND_MARGIN >= 0 and REFINE_MARGIN >= 0):
    msg = "0 <= EDGE_MARGIN < MIN_EXTENSION、各MARGIN >= 0にしてください"
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

valid = np.any(before_mask > 0, axis=1)
rows = np.arange(h)
left_edge = np.argmax(before_mask, axis=1)
right_edge = w - 1 - np.argmax(before_mask[:, ::-1], axis=1)
left_edge = np.interp(rows, rows[valid], left_edge[valid])
right_edge = np.interp(rows, rows[valid], right_edge[valid])
smooth_edges: list[np.ndarray] = []
for edge in (left_edge, right_edge):
    padded = np.pad(edge, EDGE_WINDOW // 2, mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, EDGE_WINDOW)
    smooth_edges.append(np.median(windows, axis=1))
median_left, median_right = smooth_edges
left_spike = valid & (median_left - left_edge >= MIN_EXTENSION)
right_spike = valid & (right_edge - median_right >= MIN_EXTENSION)
columns = np.arange(w)[None, :]
outside = (left_spike[:, None] & (columns < median_left[:, None] - EDGE_MARGIN)) | (
    right_spike[:, None] & (columns > median_right[:, None] + EDGE_MARGIN)
)
kernel = cv.getStructuringElement(cv.MORPH_RECT, (1, VERTICAL_SIZE))
opened = cv.morphologyEx(before_mask, cv.MORPH_OPEN, kernel)
thin = (before_mask > 0) & (opened == 0)

gray = cv.cvtColor(image, cv.COLOR_BGR2GRAY)
profiles: list[np.ndarray] = []
for left, right in (ROLLER_LEFT, ROLLER_RIGHT):
    if not (0 <= left < right <= 1 and int(w * left) < int(w * right)):
        msg = "ローラー参照範囲は0〜1で指定し、1画素以上の幅を残してください"
        raise ValueError(msg)
    strip = gray[:, int(w * left) : int(w * right)]
    profiles.append(np.percentile(strip, 65, axis=1))
roller_rows = np.zeros(h, dtype=np.uint8)
for profile in profiles:
    padded = np.pad(profile, PROFILE_WINDOW // 2, mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, PROFILE_WINDOW)
    local_background = np.median(windows, axis=1)
    bright_rows = (profile >= MIN_BRIGHTNESS) & (
        profile - local_background >= MIN_ROLLER_CONTRAST
    )
    roller_rows[bright_rows] = 255
band_kernel = cv.getStructuringElement(cv.MORPH_RECT, (1, 2 * BAND_MARGIN + 1))
roller_rows = cv.dilate(roller_rows[:, None], band_kernel)[:, 0]
candidates = (
    thin
    & outside
    & (roller_rows[:, None] > 0)
    & (gray >= MIN_BRIGHTNESS)
    & (labels != cv.GC_FGD)
).astype(np.uint8) * 255
candidate_overlay = image.copy()
candidate_overlay[candidates > 0] = (255, 0, 255)
bands = image.copy()
for left, right in (ROLLER_LEFT, ROLLER_RIGHT):
    x0, x1 = int(w * left), int(w * right)
    strip = bands[:, x0:x1]
    strip[roller_rows > 0] = (0, 165, 255)

if np.any(candidates):
    labels[candidates > 0] = cv.GC_BGD
    cv.grabCut(
        image,
        labels,
        (0, 0, 1, 1),
        background,
        foreground,
        REFINE_ITERATIONS,
        cv.GC_INIT_WITH_MASK,
    )
refined = np.isin(labels, (cv.GC_FGD, cv.GC_PR_FGD)).astype(np.uint8) * 255
review_kernel = cv.getStructuringElement(
    cv.MORPH_ELLIPSE, (2 * REFINE_MARGIN + 1, 2 * REFINE_MARGIN + 1)
)
review_region = (
    (cv.dilate(candidates, review_kernel) > 0) & outside & (roller_rows[:, None] > 0)
)
mask = before_mask.copy()
mask[review_region] = refined[review_region]
removed = ((before_mask > 0) & (mask == 0)).astype(np.uint8) * 255
added = ((before_mask == 0) & (mask > 0)).astype(np.uint8) * 255
changes = image.copy()
changes[removed > 0] = (255, 0, 255)
changes[added > 0] = (0, 255, 0)
contours, _ = cv.findContours(mask, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
outline = image.copy()
cv.drawContours(outline, contours, -1, (0, 0, 255), 2)
cutout = cv.bitwise_and(image, image, mask=mask)

outputs = {
    "initial": initial,
    "raw_mask": raw_mask,
    "before_mask": before_mask,
    "bands": bands,
    "candidates": candidates,
    "candidate_overlay": candidate_overlay,
    "review_region": review_region.astype(np.uint8) * 255,
    "mask": mask,
    "removed": removed,
    "added": added,
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
    f"{OUTPUT_PREFIX}: candidates={np.count_nonzero(candidates)} px, "
    f"removed={np.count_nonzero(removed)} px, added={np.count_nonzero(added)} px\n"
)
