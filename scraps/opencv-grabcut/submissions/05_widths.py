"""指定範囲の全行の幅を、CSVと折れ線グラフに保存する."""

import csv
from pathlib import Path

import cv2 as cv
import numpy as np
from matplotlib import pyplot as plt

# パスはこのスクリプトのフォルダが基準。
INPUT_PATH = r"input\赤茶色の床と剥離した金属帯.png"
OUTPUT_IMAGE_PATH = r"results/05_widths.png"
OUTPUT_CSV_PATH = r"results/05_widths.csv"
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

# 幅は左右の画素中心のx差。試料がない行は空欄にし、0pxとは扱わない。
width_rows = []
y_values = []
width_values = []
measured_widths = []
for y in range(START_Y, end_y + 1):
    xs = np.flatnonzero(mask[y])
    if len(xs) == 0:
        width_rows.append((y, "", "", ""))
        width_values.append(float("nan"))
    else:
        left_x = int(xs[0])
        right_x = int(xs[-1])
        width_px = right_x - left_x
        width_rows.append((y, left_x, right_x, width_px))
        width_values.append(float(width_px))
        measured_widths.append(width_px)
    y_values.append(y)

if not measured_widths:
    raise ValueError("指定した計測範囲に試料がありません")

plt.switch_backend("Agg")
figure, axes = plt.subplots(figsize=(9, 5), layout="constrained")
axes.plot(y_values, width_values)
axes.set_xlabel("Image y (px)")
axes.set_ylabel("Width between pixel centers (px)")
axes.set_title(f"Measurement range: y={START_Y}..{end_y}")
axes.grid(alpha=0.3)
output_image_path.parent.mkdir(parents=True, exist_ok=True)
figure.savefig(output_image_path, dpi=160)
plt.close(figure)

output_csv_path.parent.mkdir(parents=True, exist_ok=True)
with output_csv_path.open("w", encoding="utf-8", newline="") as output:
    writer = csv.writer(output)
    writer.writerow(("y", "left_x", "right_x", "width_px"))
    writer.writerows(width_rows)

print(
    f"幅: 最小{min(measured_widths):.2f} / 平均{np.mean(measured_widths):.2f} / 最大{max(measured_widths):.2f} px"
)
print(f"全{len(width_rows)}行 / 計測できた行{len(measured_widths)}行")
print(f"全行の幅CSV: {output_csv_path}")
print(f"幅の折れ線グラフ: {output_image_path}")
