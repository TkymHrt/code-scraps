"""GrabCutに渡す初期指定を元画像へ重ねて保存する."""

from pathlib import Path

import cv2 as cv
import numpy as np

# パスはこのスクリプトのフォルダが基準。
INPUT_PATH = r"input.png"
OUTPUT_PATH = r"results/01_initial_regions.png"

# 左・上・右・下を、画像全体に対する0〜1の割合で指定する。
CANDIDATE_RECT = (0.34, 0.0, 0.705, 1.0)
BACKGROUND_RECTS = ((0.0, 0.0, 0.33, 1.0), (0.72, 0.0, 1.0, 1.0))
FOREGROUND_RECTS = ((0.48, 0.4, 0.56, 0.6),)

directory = Path(__file__).resolve().parent
input_path = (directory / INPUT_PATH).resolve()
output_path = (directory / OUTPUT_PATH).resolve()
if output_path == input_path:
    raise ValueError("保存先を入力画像とは別のパスにしてください")
# ファイルはPythonで読み、OpenCVには画像のバイト列を渡す。
image = cv.imdecode(
    np.frombuffer(input_path.read_bytes(), dtype=np.uint8),
    cv.IMREAD_COLOR,
)
if image is None:
    raise OSError(f"入力画像を読み込めません: {input_path}")
height, width = image.shape[:2]

# 背景候補で始め、前景候補・確実な背景・確実な前景の順で重ねる。
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

# OpenCVの色はBGR順。青=背景、緑=前景、灰=背景候補、橙=前景候補。
palette = np.array(
    [(255, 80, 0), (0, 255, 0), (64, 64, 64), (0, 165, 255)], dtype=np.uint8
)
result = cv.addWeighted(image, 0.65, palette[labels], 0.35, 0)

output_path.parent.mkdir(parents=True, exist_ok=True)
success, encoded = cv.imencode(output_path.suffix, result)
if not success:
    raise OSError(f"画像を保存できません: {output_path}")
output_path.write_bytes(encoded.tobytes())
print(f"初期指定の重ね画像: {output_path}")
