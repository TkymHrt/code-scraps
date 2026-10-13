"""前処理の単独・組み合わせで、抽出結果と左右側辺長を比較する."""

import csv
import math
from pathlib import Path

import cv2 as cv
import numpy as np

# パスはこのスクリプトのフォルダが基準。
INPUT_PATH = r"../submissions/input/赤茶色の床と剥離した金属帯.png"
OUTPUT_DIRECTORY = r"results/preprocess_comparison"
ITERATIONS = 5
RANDOM_SEED = 0
START_Y = 0
END_Y = None

# 04と比較するときは、入力・初期指定・計測範囲を揃える。
CANDIDATE_RECT = (0.30522088353413657, 0.0017825311942959, 0.6974564926372155, 1.0)
BACKGROUND_RECTS = (
    (0.0, 0.0, 0.30120481927710846, 1.0),
    (0.7028112449799196, 0.0017825311942959, 1.0, 1.0),
)
FOREGROUND_RECTS = ((0.4002677376171352, 0.0, 0.6010709504685409, 1.0),)

# タプルの左から順に適用する。originalの空タプルは無処理の基準。
CASES = {
    "original": (),
    "blur": ("blur",),
    "clahe": ("clahe",),
    "gamma": ("gamma",),
    "sharp": ("sharp",),
    "blur_clahe": ("blur", "clahe"),
    "clahe_blur": ("clahe", "blur"),
}
BLUR_SIZE = 3  # blurとsharpで使う、正の奇数の窓サイズ。
CLAHE_CLIP_LIMIT = 2.0
CLAHE_GRID_SIZE = (8, 8)
GAMMA = 0.8  # 1は無補正、1未満で暗い部分を明るくする。
SHARP_AMOUNT = 0.5  # 0は無補正。大きくすると輪郭の強調が増す。


def preprocess(image: np.ndarray, steps: tuple[str, ...]) -> np.ndarray:
    result = image.copy()
    for step in steps:
        if step == "blur":
            result = cv.GaussianBlur(result, (BLUR_SIZE, BLUR_SIZE), 0)
        elif step == "clahe":
            # 色の成分を保ち、Labの明るさ成分だけを補正する。
            lab = cv.cvtColor(result, cv.COLOR_BGR2LAB)
            clahe = cv.createCLAHE(CLAHE_CLIP_LIMIT, CLAHE_GRID_SIZE)
            lab[:, :, 0] = clahe.apply(lab[:, :, 0])
            result = cv.cvtColor(lab, cv.COLOR_LAB2BGR)
        elif step == "gamma":
            if GAMMA <= 0:
                raise ValueError("GAMMAは0より大きくしてください")
            values = np.arange(256) / 255
            table = np.round(values**GAMMA * 255).astype(np.uint8)
            result = cv.LUT(result, table)
        elif step == "sharp":
            if SHARP_AMOUNT < 0:
                raise ValueError("SHARP_AMOUNTは0以上にしてください")
            blurred = cv.GaussianBlur(result, (BLUR_SIZE, BLUR_SIZE), 0)
            result = cv.addWeighted(result, 1 + SHARP_AMOUNT, blurred, -SHARP_AMOUNT, 0)
        else:
            raise ValueError(f"未知の前処理です: {step}")
    return result


directory = Path(__file__).resolve().parent
input_path = (directory / INPUT_PATH).resolve()
output_directory = (directory / OUTPUT_DIRECTORY).resolve()
summary_path = (output_directory / "comparison.csv").resolve()
if CASES.get("original") != ():
    raise ValueError("CASESには無処理の original: () を残してください")
if ITERATIONS < 1:
    raise ValueError("GrabCutの反復回数は1以上にしてください")

# ケース名による保存先の逸脱、出力同士の衝突、入力の上書きを防ぐ。
output_paths = [summary_path]
for case in CASES:
    case_directory = (output_directory / case).resolve()
    if Path(case).name != case or case_directory.parent != output_directory:
        raise ValueError("ケース名にはフォルダ名1つだけを指定してください")
    output_paths.extend(
        (case_directory / name).resolve()
        for name in ("processed.png", "mask.png", "overlay.png")
    )
if len({input_path, *output_paths}) != len(output_paths) + 1:
    raise ValueError("入力画像と各出力は別々のパスにしてください")

image = cv.imdecode(
    np.frombuffer(input_path.read_bytes(), dtype=np.uint8), cv.IMREAD_COLOR
)
if image is None:
    raise OSError(f"入力画像を読み込めません: {input_path}")
height, width = image.shape[:2]
end_y = height - 1 if END_Y is None else END_Y
if not (0 <= START_Y <= end_y < height):
    raise ValueError("計測範囲は画像内で、0 <= START_Y <= END_Yにしてください")

# 全ケースに同じ初期指定を渡す。未指定部分は背景候補。
initial_labels = np.full((height, width), cv.GC_PR_BGD, np.uint8)
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
        initial_labels[y0:y1, x0:x1] = label

measurements: dict[str, tuple[float, float, float]] = {}
for case, steps in CASES.items():
    processed = preprocess(image, steps)
    # 前ケースの抽出結果やモデルを引き継がず、同じ条件から始める。
    labels = initial_labels.copy()
    background = np.zeros((1, 65), np.float64)
    foreground = np.zeros((1, 65), np.float64)
    cv.setRNGSeed(RANDOM_SEED)
    cv.grabCut(
        processed,
        labels,
        (0, 0, 0, 0),
        background,
        foreground,
        ITERATIONS,
        cv.GC_INIT_WITH_MASK,
    )
    raw_mask = np.isin(labels, (cv.GC_FGD, cv.GC_PR_FGD)).astype(np.uint8) * 255

    # 04と同じ最大外側輪郭を選び、内部を塗りつぶして計測する。
    contours, _ = cv.findContours(raw_mask, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise ValueError(f"{case}: 試料の領域が見つかりません")
    contour = max(contours, key=cv.contourArea)
    mask = np.zeros((height, width), np.uint8)
    cv.drawContours(mask, [contour], -1, 255, thickness=-1)
    edge_rows = []
    for y in range(START_Y, end_y + 1):
        xs = np.flatnonzero(mask[y])
        if len(xs) > 0:
            edge_rows.append((y, int(xs[0]), int(xs[-1])))
    if len(edge_rows) < 2:
        raise ValueError(f"{case}: 長さを測るには、計測範囲に試料が2行以上必要です")

    left_length = 0.0
    right_length = 0.0
    for (y0, left_x0, right_x0), (y1, left_x1, right_x1) in zip(
        edge_rows, edge_rows[1:]
    ):
        left_length += math.hypot(left_x1 - left_x0, y1 - y0)
        right_length += math.hypot(right_x1 - right_x0, y1 - y0)
    total_length = left_length + right_length
    measurements[case] = (left_length, right_length, total_length)

    # 加工前の元画像に端線を重ね、前処理で境界が動いた場所を見比べる。
    overlay = image.copy()
    for area in (overlay[:START_Y], overlay[end_y + 1 :]):
        if area.size > 0:
            area[:] = cv.addWeighted(area, 0.4, np.full_like(area, 220), 0.6, 0)
    for y in (START_Y, end_y):
        cv.line(overlay, (0, y), (width - 1, y), (0, 255, 255), thickness=1)
    left_edge = np.array([(left_x, y) for y, left_x, right_x in edge_rows], np.int32)
    right_edge = np.array([(right_x, y) for y, left_x, right_x in edge_rows], np.int32)
    cv.polylines(
        overlay, [left_edge, right_edge], isClosed=False, color=(0, 0, 255), thickness=2
    )

    case_directory = output_directory / case
    case_directory.mkdir(parents=True, exist_ok=True)
    for name, saved_image in (
        ("processed.png", processed),
        ("mask.png", raw_mask),
        ("overlay.png", overlay),
    ):
        output_path = case_directory / name
        success, encoded = cv.imencode(".png", saved_image)
        if not success:
            raise OSError(f"画像を保存できません: {output_path}")
        output_path.write_bytes(encoded.tobytes())
    print(
        f"{case}: left={left_length:.2f}, right={right_length:.2f}, total={total_length:.2f} px"
    )

# 差は丸める前に計算し、基準が辞書の最後でも同じ比較になるようにする。
base_left, base_right, base_total = measurements["original"]
with summary_path.open("w", encoding="utf-8", newline="") as output:
    writer = csv.writer(output)
    writer.writerow(
        (
            "case",
            "steps",
            "left_px",
            "right_px",
            "total_px",
            "delta_left_px",
            "delta_right_px",
            "delta_total_px",
            "start_y",
            "end_y",
        )
    )
    for case, (left, right, total) in measurements.items():
        writer.writerow(
            (
                case,
                " -> ".join(CASES[case]),
                f"{left:.2f}",
                f"{right:.2f}",
                f"{total:.2f}",
                f"{left - base_left:.2f}",
                f"{right - base_right:.2f}",
                f"{total - base_total:.2f}",
                START_Y,
                end_y,
            )
        )
print(f"比較CSV: {summary_path}")
