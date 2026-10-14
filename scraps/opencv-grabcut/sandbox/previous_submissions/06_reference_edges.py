"""人が選んだ正常部分から基準線を作り、左右端の内向き偏差を保存する."""

import csv
from pathlib import Path

import cv2 as cv
import numpy as np

# パスはこのスクリプトのフォルダが基準。
INPUT_PATH = r"input\赤茶色の床と剥離した金属帯.png"
OUTPUT_IMAGE_PATH = r"results/06_reference_edges.png"
OUTPUT_CSV_PATH = r"results/06_reference_edges.csv"
ITERATIONS = 5
RANDOM_SEED = 0

# 元画像のy座標で計測範囲を指定する。終了行も含む。Noneは画像の最終行。
# 仮入力の画像で上下端付近を除く設定。使う画像に合わせて変更する。
START_Y = 80
END_Y = 1000

# 左・上・右・下を、画像全体に対する0〜1の割合で指定する。
CANDIDATE_RECT = (0.30522088353413657, 0.0017825311942959, 0.6974564926372155, 1.0)
BACKGROUND_RECTS = (
    (0.0, 0.0, 0.30120481927710846, 1.0),
    (0.7028112449799196, 0.0017825311942959, 1.0, 1.0),
)
FOREGROUND_RECTS = ((0.4002677376171352, 0.0, 0.6010709504685409, 1.0),)

# 元画像のy座標で、正常端とみなす範囲を左右別に選ぶ。終了行も含む。
# 生成画像で比較的変動が小さい区間を仮に選んだ値。正常の正解ではない。
LEFT_REFERENCE_RANGES = ((180, 200), (800, 825))
RIGHT_REFERENCE_RANGES = ((180, 200), (810, 835))


def fit_reference(edge_rows, column, ranges, start_y, end_y):
    """指定した正常部分の点に、x = slope * y + intercept の直線を当てる."""
    x_by_y = {}
    for row in edge_rows:
        x_by_y[row[0]] = row[column]
    ys = []
    xs = []
    for first_y, last_y in ranges:
        if not (start_y <= first_y <= last_y <= end_y):
            raise ValueError("正常部分の範囲は計測範囲内で、開始 <= 終了にしてください")
        for y in range(first_y, last_y + 1):
            if y not in x_by_y:
                raise ValueError(f"正常部分のy={y}に試料がありません")
            if y in ys:
                raise ValueError("正常部分の範囲は重ねないでください")
            ys.append(y)
            xs.append(x_by_y[y])
    if len(ys) < 2:
        raise ValueError("基準線には正常部分の点が2行以上必要です")
    mean_y = float(np.mean(ys))
    mean_x = float(np.mean(xs))
    numerator = 0.0
    denominator = 0.0
    for y, x in zip(ys, xs):
        numerator += (y - mean_y) * (x - mean_x)
        denominator += (y - mean_y) ** 2
    slope = numerator / denominator
    intercept = mean_x - slope * mean_y
    return slope, intercept, ys


directory = Path(__file__).resolve().parent
input_path = (directory / INPUT_PATH).resolve()
output_image_path = (directory / OUTPUT_IMAGE_PATH).resolve()
output_csv_path = (directory / OUTPUT_CSV_PATH).resolve()
if len({input_path, output_image_path, output_csv_path}) != 3:
    raise ValueError("入力画像・結果画像・CSVは別々のパスにしてください")
if ITERATIONS < 1:
    raise ValueError("GrabCutの反復回数は1以上にしてください")
# ファイルはPythonで読み、OpenCVには画像のバイト列を渡す。
image = cv.imdecode(
    np.frombuffer(input_path.read_bytes(), dtype=np.uint8),
    cv.IMREAD_COLOR,
)
if image is None:
    raise OSError(f"入力画像を読み込めません: {input_path}")
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

# 最大外側輪郭を選び、内部を塗りつぶす。
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
if len(edge_rows) < 2:
    raise ValueError("指定した計測範囲で長さを測るには、試料が2行以上必要です")

left_slope, left_intercept, left_reference_ys = fit_reference(
    edge_rows, 1, LEFT_REFERENCE_RANGES, START_Y, end_y
)
right_slope, right_intercept, right_reference_ys = fit_reference(
    edge_rows, 2, RIGHT_REFERENCE_RANGES, START_Y, end_y
)

# 偏差は水平方向の距離。左は実際の端 - 基準、右は基準 - 実際の端。
# 正なら内向き、負なら外向き。板厚方向の深さではない。
deviation_rows = []
for y, left_x, right_x in edge_rows:
    left_reference = left_slope * y + left_intercept
    right_reference = right_slope * y + right_intercept
    if left_reference >= right_reference:
        raise ValueError("左右の基準線が交差します。正常部分の指定を確認してください")
    left_inward = left_x - left_reference
    right_inward = right_reference - right_x
    deviation_rows.append(
        (y, left_x, right_x, left_reference, right_reference, left_inward, right_inward)
    )

result = image.copy()
for area in (result[:START_Y], result[end_y + 1 :]):
    if area.size > 0:
        area[:] = cv.addWeighted(area, 0.4, np.full_like(area, 220), 0.6, 0)
for y in (START_Y, end_y):
    cv.line(result, (0, y), (image.shape[1] - 1, y), (0, 255, 255), 1)
for column, slope, intercept, reference_ys in (
    (1, left_slope, left_intercept, left_reference_ys),
    (2, right_slope, right_intercept, right_reference_ys),
):
    edge_points = []
    for row in edge_rows:
        edge_points.append((row[column], row[0]))
    cv.polylines(result, [np.array(edge_points, np.int32)], False, (0, 0, 255), 2)
    first = (round(slope * START_Y + intercept), START_Y)
    last = (round(slope * end_y + intercept), end_y)
    cv.line(result, first, last, (255, 255, 0), 1)
    for row in edge_rows:
        if row[0] in reference_ys:
            cv.circle(result, (row[column], row[0]), 2, (0, 255, 0), -1)
cv.putText(
    result,
    "Red: edge / Cyan: reference / Green: reference samples",
    (12, 28),
    cv.FONT_HERSHEY_SIMPLEX,
    0.6,
    (0, 0, 0),
    2,
)
output_image_path.parent.mkdir(parents=True, exist_ok=True)
success, encoded = cv.imencode(output_image_path.suffix, result)
if not success:
    raise OSError(f"画像を保存できません: {output_image_path}")
output_image_path.write_bytes(encoded.tobytes())

output_csv_path.parent.mkdir(parents=True, exist_ok=True)
with output_csv_path.open("w", encoding="utf-8", newline="") as output:
    writer = csv.writer(output)
    writer.writerow(
        (
            "y",
            "left_x",
            "right_x",
            "left_reference_x",
            "right_reference_x",
            "left_inward_px",
            "right_inward_px",
            "left_reference_sample",
            "right_reference_sample",
        )
    )
    for row in deviation_rows:
        (
            y,
            left_x,
            right_x,
            left_reference,
            right_reference,
            left_inward,
            right_inward,
        ) = row
        writer.writerow(
            (
                y,
                left_x,
                right_x,
                f"{left_reference:.4f}",
                f"{right_reference:.4f}",
                f"{left_inward:.4f}",
                f"{right_inward:.4f}",
                int(y in left_reference_ys),
                int(y in right_reference_ys),
            )
        )

print(f"左の基準: x = {left_slope:.6f} * y + {left_intercept:.6f}")
print(f"右の基準: x = {right_slope:.6f} * y + {right_intercept:.6f}")
print(f"基準線と正常部分の確認画像: {output_image_path}")
print(f"全計測行の内向き偏差CSV: {output_csv_path}")
