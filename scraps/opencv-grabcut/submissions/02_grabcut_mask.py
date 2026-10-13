"""元画像と初期指定からGrabCutを実行し、2値マスクだけを保存する."""

from pathlib import Path

import cv2 as cv
import numpy as np

# パスはこのスクリプトのフォルダが基準。
INPUT_PATH = r"input.png"
OUTPUT_PATH = r"results/02_grabcut_mask.png"
ITERATIONS = 5
RANDOM_SEED = 0

# 左・上・右・下を、画像全体に対する0〜1の割合で指定する。
CANDIDATE_RECT = (0.34, 0.0, 0.705, 1.0)
BACKGROUND_RECTS = ((0.0, 0.0, 0.33, 1.0), (0.72, 0.0, 1.0, 1.0))
FOREGROUND_RECTS = ((0.48, 0.4, 0.56, 0.6),)

directory = Path(__file__).resolve().parent
input_path = (directory / INPUT_PATH).resolve()
output_path = (directory / OUTPUT_PATH).resolve()
if output_path == input_path:
    raise ValueError("保存先を入力画像とは別のパスにしてください")
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

# 01と同じ初期マスクを、この1本の中で作る。
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

# 矩形モードではなく、4種類のラベルを持つマスクで初期化する。
# 第3引数の矩形は、このモードでは使われない。
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

# 前景と前景候補を白、背景と背景候補を黒にする。
# 最大領域の選択や穴埋めはせず、GrabCut直後の結果を残す。
mask = np.isin(labels, (cv.GC_FGD, cv.GC_PR_FGD)).astype(np.uint8) * 255

output_path.parent.mkdir(parents=True, exist_ok=True)
success, encoded = cv.imencode(output_path.suffix, mask)
if not success:
    raise OSError(f"画像を保存できません: {output_path}")
output_path.write_bytes(encoded.tobytes())
print(f"GrabCut後の2値マスク: {output_path}")
