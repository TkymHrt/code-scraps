"""元画像から試料の左右端を取得し、重ね画像と座標CSVを保存する."""

import csv
from pathlib import Path

import cv2 as cv
import numpy as np

# パスはこのスクリプトのフォルダが基準。
INPUT_PATH = "input.png"
OUTPUT_IMAGE_PATH = "results/03_side_edges.png"
OUTPUT_CSV_PATH = "results/03_side_edges.csv"
ITERATIONS = 5
RANDOM_SEED = 0

# 元画像のy座標で計測範囲を指定する。終了行も含む。Noneは画像の最終行。
# 初期値は画像全体。上下端面を避ける位置へ、人が変更する。
START_Y = 0
END_Y = None

# 左・上・右・下を、画像全体に対する0〜1の割合で指定する。
CANDIDATE_RECT = (0.34, 0.0, 0.705, 1.0)
BACKGROUND_RECTS = ((0.0, 0.0, 0.33, 1.0), (0.72, 0.0, 1.0, 1.0))
FOREGROUND_RECTS = ((0.48, 0.4, 0.56, 0.6),)

directory = Path(__file__).resolve().parent
input_path = (directory / INPUT_PATH).resolve()
output_image_path = (directory / OUTPUT_IMAGE_PATH).resolve()
output_csv_path = (directory / OUTPUT_CSV_PATH).resolve()
if len({input_path, output_image_path, output_csv_path}) != 3:
    raise ValueError("入力画像・結果画像・CSVは別々のパスにしてください")
if ITERATIONS < 1:
    raise ValueError("GrabCutの反復回数は1以上にしてください")
image = cv.imread(str(input_path))
if image is None:
    raise FileNotFoundError(f"入力画像を読み込めません: {input_path}")
height, width = image.shape[:2]
end_y = height - 1 if END_Y is None else END_Y
if not (0 <= START_Y <= end_y < height):
    raise ValueError("計測範囲は画像内で、0 <= START_Y <= END_Yにしてください")

# 01・02と同じ初期指定を、この1本の中で作る。
labels = np.full((height, width), cv.GC_PR_BGD, np.uint8)
for label, rectangles in (
    (cv.GC_PR_FGD, (CANDIDATE_RECT,)),
    (cv.GC_BGD, BACKGROUND_RECTS),
    (cv.GC_FGD, FOREGROUND_RECTS),
):
    for left, top, right, bottom in rectangles:
        if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
            raise ValueError("矩形は0〜1の範囲で、左 < 右、上 < 下にしてください")
        x0, y0 = int(width * left), int(height * top)
        x1, y1 = int(width * right), int(height * bottom)
        if x0 == x1 or y0 == y1:
            raise ValueError("矩形が1画素未満です。指定範囲を広げてください")
        labels[y0:y1, x0:x1] = label

# マスクモードでは、第3引数の矩形は使われない。
background = np.zeros((1, 65), np.float64)
foreground = np.zeros((1, 65), np.float64)
cv.setRNGSeed(RANDOM_SEED)
cv.grabCut(
    image,
    labels,
    (0, 0, 0, 0),
    background,
    foreground,
    ITERATIONS,
    cv.GC_INIT_WITH_MASK,
)
raw_mask = np.isin(labels, (cv.GC_FGD, cv.GC_PR_FGD)).astype(np.uint8) * 255

# 最大の外側輪郭を試料として選び、その内部を塗りつぶす。
# 離れた小領域を除き、内部の穴は外形の左右端に含めない。
contours, _ = cv.findContours(raw_mask, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
if not contours:
    raise ValueError("試料の領域が見つかりません。初期指定を確認してください")
contour = max(contours, key=cv.contourArea)
mask = np.zeros((height, width), np.uint8)
cv.drawContours(mask, [contour], -1, 255, thickness=-1)

# 指定した範囲だけを調べ、元画像の座標のまま左右端を集める。
edge_rows = []
for y in range(START_Y, end_y + 1):
    xs = np.flatnonzero(mask[y])
    if len(xs) > 0:
        edge_rows.append((y, int(xs[0]), int(xs[-1])))
if not edge_rows:
    raise ValueError("指定した計測範囲に試料がありません。範囲を確認してください")

# CSVと同じ点を赤い線で結ぶ。上下辺は結ばない。
left_edge = np.array([(left_x, y) for y, left_x, right_x in edge_rows], np.int32)
right_edge = np.array([(right_x, y) for y, left_x, right_x in edge_rows], np.int32)
result = image.copy()
# 範囲外を灰色で薄くし、上下の境界を黄色で示す。
for area in (result[:START_Y], result[end_y + 1 :]):
    if area.size > 0:
        area[:] = cv.addWeighted(area, 0.4, np.full_like(area, 220), 0.6, 0)
for y in (START_Y, end_y):
    cv.line(result, (0, y), (width - 1, y), (0, 255, 255), thickness=1)
# 境界行でも、実際に取得した端の画素が赤く見えるよう最後に描く。
if len(edge_rows) == 1:
    y, left_x, right_x = edge_rows[0]
    result[y, [left_x, right_x]] = (0, 0, 255)
else:
    cv.polylines(
        result, [left_edge, right_edge], isClosed=False, color=(0, 0, 255), thickness=2
    )

output_image_path.parent.mkdir(parents=True, exist_ok=True)
if not cv.imwrite(str(output_image_path), result):
    raise OSError(f"画像を保存できません: {output_image_path}")
output_csv_path.parent.mkdir(parents=True, exist_ok=True)
with output_csv_path.open("w", encoding="utf-8", newline="") as output:
    writer = csv.writer(output)
    writer.writerow(("y", "left_x", "right_x"))
    writer.writerows(edge_rows)

print(f"左右端の重ね画像: {output_image_path}")
print(f"左右端の座標CSV: {output_csv_path}")
print(f"計測範囲: y={START_Y}〜{end_y}（両端を含む）")
