"""GrabCut で板の領域を推定する試し書き."""

import cv2 as cv
import numpy as np

# 1. 元の解像度のまま画像を読み込む
image = cv.imread("input.png")
if image is None:
    msg = "input.png が見つかりません"
    raise FileNotFoundError(msg)
h, w = image.shape[:2]

# 2. 中央が板、左右端が背景という初期情報を与える
mask = np.full((h, w), cv.GC_PR_BGD, np.uint8)
mask[:, : int(w * 0.33)] = cv.GC_BGD
mask[:, int(w * 0.72) :] = cv.GC_BGD
mask[:, int(w * 0.34) : int(w * 0.705)] = cv.GC_PR_FGD
mask[:, int(w * 0.48) : int(w * 0.56)] = cv.GC_FGD

# 3. GrabCutで板の領域を推定する
background = np.zeros((1, 65), np.float64)
foreground = np.zeros((1, 65), np.float64)

# GC_INIT_WITH_MASK では rect は無視されるが、型スタブ上は rect が必須なためダミーを渡す
cv.grabCut(image, mask, (0, 0, 1, 1), background, foreground, 5, cv.GC_INIT_WITH_MASK)

# 4. 板の候補だけを白くして、最大の輪郭を使う
mask = np.isin(mask, (cv.GC_FGD, cv.GC_PR_FGD)).astype(np.uint8) * 255

contours, _ = cv.findContours(mask, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
largest = max(contours, key=cv.contourArea)

result = image.copy()
cv.drawContours(result, [largest], -1, (0, 0, 255), 2)

cv.imwrite("result_03.png", result)
