"""CSVに並べた画像を同じ条件で抽出し、左右側辺の長さを保存する."""

import csv
import json
import math
import sys
from pathlib import Path

import cv2 as cv
import numpy as np

# パスはこのスクリプトのフォルダが基準。画像のパスは入力CSVが基準。
INPUT_CSV = "samples.csv"
OUTPUT_DIRECTORY = "results"
ITERATIONS = 5
RANDOM_SEED = 0
MEASURE_Y_RANGE = (0.0, 1.0)  # 画像の高さに対する測定範囲。下端は含まない。

# ex05と同じ初期値。実画像に合わせ、確実な前景を試料内部に収める。
CANDIDATE_RECT = (0.34, 0.0, 0.705, 1.0)
BACKGROUND_RECTS = ((0.0, 0.0, 0.33, 1.0), (0.72, 0.0, 1.0, 1.0))
FOREGROUND_RECTS = ((0.48, 0.0, 0.56, 1.0),)

directory = Path(__file__).resolve().parent
input_csv = (directory / INPUT_CSV).resolve()
output_directory = (directory / OUTPUT_DIRECTORY).resolve()
with input_csv.open(encoding="utf-8-sig", newline="") as source:
    samples = list(csv.DictReader(source))
if not samples:
    msg = "入力CSVに画像を1枚以上指定してください"
    raise ValueError(msg)

# IDを結果フォルダ名に使うので、空欄・重複・パスの指定だけを止める。
sample_ids = [sample["sample_id"] for sample in samples]
if len({sample_id.casefold() for sample_id in sample_ids}) != len(sample_ids):
    msg = "sample_idが重複しています"
    raise ValueError(msg)
for sample_id in sample_ids:
    if not sample_id or Path(sample_id).name != sample_id or sample_id in (".", ".."):
        msg = "sample_idにはフォルダ名として使えるIDを指定してください"
        raise ValueError(msg)

measurements = []
for sample in samples:
    sample_id = sample["sample_id"]
    image_path = (input_csv.parent / sample["image_path"]).resolve()
    scale_text = sample["mm_per_px"].strip()
    mm_per_px = float(scale_text) if scale_text else None
    if mm_per_px is not None and (not math.isfinite(mm_per_px) or mm_per_px <= 0):
        msg = f"{sample_id}: mm_per_pxは正の有限値、または空欄にしてください"
        raise ValueError(msg)

    # 元の解像度で読み、全画像へ同じGrabCutの初期指定を適用する。
    image = cv.imread(str(image_path))
    if image is None:
        msg = f"入力画像を読み込めません: {image_path}"
        raise FileNotFoundError(msg)
    height, width = image.shape[:2]
    labels = np.full((height, width), cv.GC_PR_BGD, np.uint8)
    for label, rectangles in (
        (cv.GC_PR_FGD, (CANDIDATE_RECT,)),
        (cv.GC_BGD, BACKGROUND_RECTS),
        (cv.GC_FGD, FOREGROUND_RECTS),
    ):
        for left, top, right, bottom in rectangles:
            x0, y0 = int(width * left), int(height * top)
            x1, y1 = int(width * right), int(height * bottom)
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

    # 最大の外側輪郭を塗りつぶす。平滑化や反射除去は加えない。
    contours, _ = cv.findContours(raw_mask, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
    if not contours:
        msg = f"{sample_id}: 試料の領域が見つかりません"
        raise ValueError(msg)
    contour = max(contours, key=cv.contourArea)
    mask = np.zeros((height, width), np.uint8)
    cv.drawContours(mask, [contour], -1, 255, thickness=-1)

    # 評価範囲内の各行から左右端を集める。上下辺は結ばない。
    left_points = []
    right_points = []
    y0, y1 = (int(height * fraction) for fraction in MEASURE_Y_RANGE)
    for y in range(y0, y1):
        xs = np.where(mask[y] > 0)[0]
        if len(xs) > 0:
            left_points.append((int(xs[0]), y))
            right_points.append((int(xs[-1]), y))
    if len(left_points) <= 1:
        msg = f"{sample_id}: 測定範囲内に試料のある行が2行以上必要です"
        raise ValueError(msg)
    left_edge = np.array(left_points, dtype=np.int32)
    right_edge = np.array(right_points, dtype=np.int32)
    if np.any(np.diff(left_edge[:, 1]) != 1):
        msg = f"{sample_id}: 行が途切れています。測定範囲とマスクを確認してください"
        raise ValueError(msg)
    left_length = cv.arcLength(left_edge, closed=False)
    right_length = cv.arcLength(right_edge, closed=False)
    total_length = left_length + right_length

    # 確認画像と点列を残す。比較コードは画像を再抽出せず、この点列を読む。
    result = image.copy()
    cv.polylines(result, [left_edge], isClosed=False, color=(0, 165, 255), thickness=2)
    cv.polylines(result, [right_edge], isClosed=False, color=(255, 255, 0), thickness=2)
    sample_directory = output_directory / sample_id
    sample_directory.mkdir(parents=True, exist_ok=True)
    for filename, output_image in (
        ("sides.png", result),
        ("initial.png", initial),
        ("raw_mask.png", raw_mask),
        ("mask.png", mask),
    ):
        cv.imwrite(str(sample_directory / filename), output_image)
    with (sample_directory / "edges.csv").open(
        "w", encoding="utf-8", newline=""
    ) as output:
        writer = csv.writer(output)
        writer.writerow(("y_px", "left_x_px", "right_x_px"))
        for (left_x, y), (right_x, _) in zip(left_points, right_points, strict=True):
            writer.writerow((y, left_x, right_x))

    measurements.append(
        {
            "sample_id": sample_id,
            "image_path": str(image_path),
            "edges_path": f"{sample_id}/edges.csv",
            "image_width_px": width,
            "image_height_px": height,
            "mm_per_px": mm_per_px if mm_per_px is not None else "",
            "y_start_px": left_points[0][1],
            "y_end_px": left_points[-1][1],
            "vertical_span_px": left_points[-1][1] - left_points[0][1],
            "left_px": f"{left_length:.6f}",
            "right_px": f"{right_length:.6f}",
            "total_px": f"{total_length:.6f}",
            "left_mm": (
                f"{left_length * mm_per_px:.6f}" if mm_per_px is not None else ""
            ),
            "right_mm": (
                f"{right_length * mm_per_px:.6f}" if mm_per_px is not None else ""
            ),
            "total_mm": (
                f"{total_length * mm_per_px:.6f}" if mm_per_px is not None else ""
            ),
        }
    )
    sys.stdout.write(
        f"{sample_id}: left={left_length:.2f}, right={right_length:.2f} px\n"
    )

# 全画像を測れた後に一覧を更新する。再実行すると同じ保存先は上書きする。
with (output_directory / "measurements.csv").open(
    "w", encoding="utf-8", newline=""
) as output:
    writer = csv.DictWriter(output, fieldnames=list(measurements[0]))
    writer.writeheader()
    writer.writerows(measurements)
conditions = {
    "input_csv": str(input_csv),
    "processing_scale": 1.0,
    "iterations": ITERATIONS,
    "random_seed": RANDOM_SEED,
    "measure_y_range": MEASURE_Y_RANGE,
    "candidate_rect": CANDIDATE_RECT,
    "background_rects": BACKGROUND_RECTS,
    "foreground_rects": FOREGROUND_RECTS,
    "selection": "largest_external_contour_area",
    "fill_internal_holes": True,
    "side_edge_method": "outermost_pixel_each_row",
    "smoothing": None,
    "opencv_version": cv.__version__,
    "numpy_version": np.__version__,
}
(output_directory / "conditions.json").write_text(
    json.dumps(conditions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
