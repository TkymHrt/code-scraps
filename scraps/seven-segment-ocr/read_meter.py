"""赤い6桁7セグを読み、固定小数3桁の値をJSONLとCSVに出力する。"""

import csv
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

# ここを変更して、このスクリプトをそのまま実行する。
BASE_DIR = Path(__file__).resolve().parent
SOURCE = BASE_DIR / "outputs/simulation/meter.avi"  # 実機ではカメラ番号の0などに変更
CSV_FILE = BASE_DIR / "outputs/readings.csv"
SHOW_PREVIEW = True

# 実機ではcalibrate_meter.pyが表示した4項目をここへ貼り付ける。
FRAME_SIZE = [960, 360]
REFLECTION = "horizontal"  # horizontal / vertical / both / none
DISPLAY_CORNERS = [[110, 92], [846, 61], [866, 289], [91, 309]]
# 補正後の画像の絶対座標 [左, 上, 右, 下]。右・下の画素は含めない。
# 左の桁から6組。各組は上、右上、右下、下、左下、左上、中央の順。
SEGMENT_BOXES = [
    [
        [42, 15, 78, 25],
        [95, 41, 104, 76],
        [95, 124, 104, 159],
        [42, 175, 78, 185],
        [16, 124, 25, 159],
        [16, 41, 25, 76],
        [42, 95, 78, 105],
    ],
    [
        [162, 15, 198, 25],
        [215, 41, 224, 76],
        [215, 124, 224, 159],
        [162, 175, 198, 185],
        [136, 124, 145, 159],
        [136, 41, 145, 76],
        [162, 95, 198, 105],
    ],
    [
        [282, 15, 318, 25],
        [335, 41, 344, 76],
        [335, 124, 344, 159],
        [282, 175, 318, 185],
        [256, 124, 265, 159],
        [256, 41, 265, 76],
        [282, 95, 318, 105],
    ],
    [
        [402, 15, 438, 25],
        [455, 41, 464, 76],
        [455, 124, 464, 159],
        [402, 175, 438, 185],
        [376, 124, 385, 159],
        [376, 41, 385, 76],
        [402, 95, 438, 105],
    ],
    [
        [522, 15, 558, 25],
        [575, 41, 584, 76],
        [575, 124, 584, 159],
        [522, 175, 558, 185],
        [496, 124, 505, 159],
        [496, 41, 505, 76],
        [522, 95, 558, 105],
    ],
    [
        [642, 15, 678, 25],
        [695, 41, 704, 76],
        [695, 124, 704, 159],
        [642, 175, 678, 185],
        [616, 124, 625, 159],
        [616, 41, 625, 76],
        [642, 95, 678, 105],
    ],
]

RED_MIN = 70
RED_MARGIN = 40
WHITE_MIN = 200  # B・G・Rのすべてがこの値以上なら白飛び候補
RED_SEED_FRACTION = 0.05  # 白飛びを補う連結領域に必要な赤色の面積 / 選択枠の面積
OFF_FRACTION = 0.15
ON_FRACTION = 0.65
STABLE_FRAMES = 3

DISPLAY_WIDTH = 720
DISPLAY_HEIGHT = 200

PATTERN_TO_DIGIT = {
    "1111110": "0",
    "0110000": "1",
    "1101101": "2",
    "1111001": "3",
    "0110011": "4",
    "1011011": "5",
    "1011111": "6",
    "1110000": "7",
    "1111111": "8",
    "1111011": "9",
    "0000000": " ",
}


def validate_corners(points, width, height):
    corners = np.array(points, dtype=np.float32)
    if corners.shape != (4, 2) or not np.isfinite(corners).all():
        raise ValueError("DISPLAY_CORNERSは4個の有限な座標にしてください。")
    if (corners[:, 0] < 0).any() or (corners[:, 0] >= width).any():
        raise ValueError("四隅のx座標が撮影画像からはみ出しています。")
    if (corners[:, 1] < 0).any() or (corners[:, 1] >= height).any():
        raise ValueError("四隅のy座標が撮影画像からはみ出しています。")
    if (
        not cv2.isContourConvex(corners)
        or cv2.contourArea(corners, oriented=True) < 100
    ):
        raise ValueError("四隅を左上→右上→右下→左下の順に選び直してください。")


def correct_reflection(frame):
    if REFLECTION == "horizontal":
        return cv2.flip(frame, 1)
    if REFLECTION == "vertical":
        return cv2.flip(frame, 0)
    if REFLECTION == "both":
        return cv2.flip(frame, -1)
    if REFLECTION == "none":
        return frame
    raise ValueError("反射方向が不正です。")


def validate_segment_boxes():
    if len(SEGMENT_BOXES) != 6:
        raise ValueError("SEGMENT_BOXESは消灯桁も含め6桁分必要です。")
    for boxes in SEGMENT_BOXES:
        if len(boxes) != 7:
            raise ValueError("各桁のセグメント枠は7個必要です。")
        for box in boxes:
            if len(box) != 4:
                raise ValueError("各枠は[左, 上, 右, 下]の4座標にしてください。")
            for coordinate in box:
                if not isinstance(coordinate, int):
                    raise ValueError("セグメント枠の座標は整数にしてください。")
            left, top, right, bottom = box
            if not (0 <= left < right <= DISPLAY_WIDTH):
                raise ValueError("セグメント枠の横範囲を補正画像内にしてください。")
            if not (0 <= top < bottom <= DISPLAY_HEIGHT):
                raise ValueError("セグメント枠の縦範囲を補正画像内にしてください。")


def rectify_display(frame):
    height, width = frame.shape[:2]
    if [width, height] != FRAME_SIZE:
        raise ValueError(
            "撮影解像度が校正時と異なります。現在の解像度で校正し直してください。"
        )
    corrected = correct_reflection(frame)
    source = np.float32(DISPLAY_CORNERS)
    destination = np.float32([[0, 0], [719, 0], [719, 199], [0, 199]])
    transform = cv2.getPerspectiveTransform(source, destination)
    return cv2.warpPerspective(corrected, transform, (DISPLAY_WIDTH, DISPLAY_HEIGHT))


def recognize_display(image):
    # uint8のまま引くと負数が255付近に回り込むため、先に型を変える。
    blue = image[:, :, 0].astype(np.int16)
    green = image[:, :, 1].astype(np.int16)
    red = image[:, :, 2].astype(np.int16)
    red_excess = red - np.maximum(blue, green)
    red_pixels = (red >= RED_MIN) & (red_excess >= RED_MARGIN)
    white_pixels = (blue >= WHITE_MIN) & (green >= WHITE_MIN) & (red >= WHITE_MIN)
    mask = red_pixels.astype(np.uint8) * 255

    display = ""
    all_fractions = []
    all_patterns = []
    for boxes in SEGMENT_BOXES:
        pattern = ""
        fractions = []
        for left, top, right, bottom in boxes:
            region_red = red_pixels[top:bottom, left:right]
            region_white = white_pixels[top:bottom, left:right]
            region_lit = region_red.copy()
            candidates = (region_red | region_white).astype(np.uint8)
            component_count, labels = cv2.connectedComponents(
                candidates, connectivity=8
            )
            minimum_red_count = math.ceil(region_red.size * RED_SEED_FRACTION)
            # 白い反射が別のセグメントから入り込まないよう、枠ごとに補う。
            for component_index in range(1, component_count):
                component = labels == component_index
                red_count = np.count_nonzero(region_red & component)
                if red_count >= minimum_red_count:
                    region_lit |= component

            region_mask = mask[top:bottom, left:right]
            region_mask[region_lit] = 255
            fraction = np.count_nonzero(region_lit) / region_lit.size
            unsupported_white = region_white & ~region_lit
            unsupported_fraction = np.count_nonzero(unsupported_white) / region_lit.size
            fractions.append(fraction)
            if fraction >= ON_FRACTION:
                pattern += "1"
            elif unsupported_fraction > OFF_FRACTION:
                # 赤が完全に失われた点灯を消灯にすると、8を0などと誤読する。
                pattern += "?"
            elif fraction <= OFF_FRACTION:
                pattern += "0"
            else:
                pattern += "?"
        display += PATTERN_TO_DIGIT.get(pattern, "?")
        all_fractions.append(fractions)
        all_patterns.append(pattern)

    raw_value = None
    reason = ""
    integer_part = display[:3].lstrip(" ")
    fraction_part = display[3:]
    if "?" in display:
        reason = "uncertain_segments"
    elif display == "      ":
        reason = "all_blank"
    elif not integer_part.isdigit() or not fraction_part.isdigit():
        reason = "misplaced_blank"
    else:
        # floatを介さず文字列で作り、0.001や末尾の0をそのまま保存する。
        raw_value = str(int(integer_part)) + "." + fraction_part
    reading = {
        "display": display,
        "raw_value": raw_value,
        "reason": reason,
        "fractions": all_fractions,
        "patterns": all_patterns,
    }
    return reading, mask


def draw_preview(image, mask, reading, status):
    annotated = image.copy()
    for digit_index, boxes in enumerate(SEGMENT_BOXES):
        for segment_index, box in enumerate(boxes):
            left, top, right, bottom = box
            state = reading["patterns"][digit_index][segment_index]
            color = (0, 200, 0)
            if state == "?":
                color = (0, 200, 255)
            elif state == "0":
                color = (160, 160, 160)
            cv2.rectangle(annotated, (left, top), (right - 1, bottom - 1), color, 1)
    mask_bgr = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
    panel = np.vstack([annotated, mask_bgr])
    label = f"{status}: [{reading['display']}] {reading['reason']}   Q: quit"
    cv2.putText(
        panel, label, (8, 218), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 1
    )
    return panel


def main():
    validate_corners(DISPLAY_CORNERS, FRAME_SIZE[0], FRAME_SIZE[1])
    validate_segment_boxes()
    if not (0 <= WHITE_MIN <= 255 and 0 < RED_SEED_FRACTION <= 1):
        raise ValueError("WHITE_MINは0〜255、RED_SEED_FRACTIONは0より大きく1以下です。")
    if not 0 <= OFF_FRACTION < ON_FRACTION <= 1 or STABLE_FRAMES < 1:
        raise ValueError("点灯率の大小関係とSTABLE_FRAMESを確認してください。")
    if CSV_FILE.exists():
        raise FileExistsError("CSVは上書きしません。先頭のCSV_FILEを変更してください。")

    is_camera = isinstance(SOURCE, int)
    if is_camera:
        source = SOURCE
    else:
        source = str(SOURCE)
    capture = cv2.VideoCapture(source)
    csv_file = None
    try:
        if not capture.isOpened():
            raise RuntimeError("カメラまたは動画を開けません: " + str(source))
        # カメラが対応する場合、校正時の解像度を要求する。実際のサイズも毎フレーム照合する。
        if is_camera:
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_SIZE[0])
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_SIZE[1])
        success, frame = capture.read()
        if not success:
            raise RuntimeError("最初の画像を取得できません。")
        fps = capture.get(cv2.CAP_PROP_FPS)
        if not is_camera and (not math.isfinite(fps) or fps <= 0):
            raise RuntimeError(
                "動画のfpsを取得できません。時刻を付けられないため停止します。"
            )
        CSV_FILE.parent.mkdir(parents=True, exist_ok=True)
        csv_file = CSV_FILE.open("x", encoding="utf-8", newline="")
        fields = [
            "frame_index",
            "captured_at",
            "source_time_seconds",
            "status",
            "display",
            "raw_value",
            "value",
            "reason",
        ]
        writer = csv.DictWriter(csv_file, fieldnames=fields)
        writer.writeheader()
        previous_value = None
        consecutive_count = 0
        frame_index = 0
        start_time = time.monotonic()
        while True:
            captured_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
            if is_camera:
                source_time = time.monotonic() - start_time
            else:
                source_time = frame_index / fps
            image = rectify_display(frame)
            reading, mask = recognize_display(image)
            raw_value = reading["raw_value"]
            value = None
            if raw_value is None:
                previous_value = None
                consecutive_count = 0
                status = "invalid"
            else:
                if raw_value == previous_value:
                    consecutive_count += 1
                else:
                    previous_value = raw_value
                    consecutive_count = 1
                status = "warming_up"
                if consecutive_count >= STABLE_FRAMES:
                    status = "ok"
                    value = raw_value
            row = {
                "frame_index": frame_index,
                "captured_at": captured_at,
                "source_time_seconds": round(source_time, 6),
                "status": status,
                "display": reading["display"],
                "raw_value": raw_value,
                "value": value,
                "reason": reading["reason"],
            }
            writer.writerow(row)
            csv_file.flush()
            print(json.dumps(row, ensure_ascii=True), flush=True)
            if SHOW_PREVIEW:
                cv2.imshow(
                    "Seven segment OCR",
                    draw_preview(image, mask, reading, status),
                )
                delay = 1
                if not is_camera:
                    delay = max(1, round(1000 / fps))
                key = cv2.waitKey(delay) & 0xFF
                if key in (27, ord("q")):
                    break
            success, frame = capture.read()
            if not success:
                if is_camera:
                    raise RuntimeError(
                        "カメラ画像の取得に失敗しました。収集を停止します。"
                    )
                break
            frame_index += 1
    finally:
        capture.release()
        if csv_file is not None:
            csv_file.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("収集を停止しました。", file=sys.stderr)
