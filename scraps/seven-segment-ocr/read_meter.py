"""赤い6桁7セグを読み、連携用JSONLと診断用CSVに出力する。"""

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
CSV_DIR = BASE_DIR / "outputs"
SHOW_PREVIEW = True

# 実機ではcalibrate_meter.pyが表示した4項目をここへ貼り付ける。
FRAME_SIZE = [960, 360]
REFLECTION = "horizontal"  # horizontal / vertical / both / none
SAMPLE_RADIUS = 1  # 1は3×3画素、2は5×5画素を読む。
# 鏡像を戻した撮影画像上の点 [x, y]。点灯時に白飛びしない赤い箇所を選ぶ。
# 左の桁から6組。各組は上、右上、右下、下、左下、左上、中央の順。
SEGMENT_POINTS = [
    [
        [167, 110],
        [203, 150],
        [197, 241],
        [154, 285],
        [117, 243],
        [125, 153],
        [160, 196],
    ],
    [
        [286, 106],
        [324, 145],
        [320, 237],
        [278, 282],
        [239, 239],
        [244, 148],
        [282, 192],
    ],
    [
        [407, 101],
        [447, 141],
        [446, 233],
        [404, 278],
        [363, 236],
        [366, 144],
        [405, 188],
    ],
    [
        [530, 96],
        [572, 136],
        [574, 229],
        [532, 275],
        [490, 232],
        [489, 139],
        [531, 183],
    ],
    [
        [656, 90],
        [700, 131],
        [705, 225],
        [664, 271],
        [618, 228],
        [616, 134],
        [659, 179],
    ],
    [
        [784, 85],
        [830, 126],
        [838, 221],
        [797, 268],
        [750, 224],
        [744, 129],
        [790, 174],
    ],
]

RED_MIN = 70
RED_MARGIN = 40
WHITE_MIN = 200  # B・G・Rのすべてがこの値以上なら白飛びとみなす。
OFF_FRACTION = 0.15
ON_FRACTION = 0.65
STABLE_FRAMES = 3

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


def prepare_frame(frame):
    height, width = frame.shape[:2]
    if [width, height] != FRAME_SIZE:
        raise ValueError(
            "撮影解像度が校正時と異なります。現在の解像度で校正し直してください。"
        )
    if REFLECTION == "horizontal":
        return cv2.flip(frame, 1)
    if REFLECTION == "vertical":
        return cv2.flip(frame, 0)
    if REFLECTION == "both":
        return cv2.flip(frame, -1)
    if REFLECTION == "none":
        return frame
    raise ValueError("反射方向が不正です。")


def validate_segment_points():
    if not isinstance(SAMPLE_RADIUS, int) or SAMPLE_RADIUS < 0:
        raise ValueError("SAMPLE_RADIUSは0以上の整数にしてください。")
    if len(SEGMENT_POINTS) != 6:
        raise ValueError("SEGMENT_POINTSは消灯桁も含め6桁分必要です。")
    width, height = FRAME_SIZE
    for points in SEGMENT_POINTS:
        if len(points) != 7:
            raise ValueError("各桁の点は7個必要です。")
        for point in points:
            if len(point) != 2:
                raise ValueError("各点は [x, y] の2座標にしてください。")
            for coordinate in point:
                if not isinstance(coordinate, int):
                    raise ValueError("点の座標は整数にしてください。")
            x, y = point
            if not (
                SAMPLE_RADIUS <= x < width - SAMPLE_RADIUS
                and SAMPLE_RADIUS <= y < height - SAMPLE_RADIUS
            ):
                raise ValueError("点の周囲の読み取り範囲を撮影画像内にしてください。")


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
    all_patterns = []
    for points in SEGMENT_POINTS:
        pattern = ""
        for x, y in points:
            left = x - SAMPLE_RADIUS
            top = y - SAMPLE_RADIUS
            right = x + SAMPLE_RADIUS + 1
            bottom = y + SAMPLE_RADIUS + 1
            region_red = red_pixels[top:bottom, left:right]
            region_white = white_pixels[top:bottom, left:right]
            red_fraction = np.count_nonzero(region_red) / region_red.size
            white_fraction = np.count_nonzero(region_white) / region_white.size
            if white_fraction > OFF_FRACTION:
                # 白飛びした点灯を、消灯や別の数字として扱わない。
                pattern += "?"
            elif red_fraction >= ON_FRACTION:
                pattern += "1"
            elif red_fraction <= OFF_FRACTION:
                pattern += "0"
            else:
                pattern += "?"
        display += PATTERN_TO_DIGIT.get(pattern, "?")
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
        "patterns": all_patterns,
    }
    return reading, mask


def draw_preview(image, mask, reading, line_thickness):
    annotated = image.copy()
    for digit_index, points in enumerate(SEGMENT_POINTS):
        for segment_index, (x, y) in enumerate(points):
            left = x - SAMPLE_RADIUS
            top = y - SAMPLE_RADIUS
            right = x + SAMPLE_RADIUS + 1
            bottom = y + SAMPLE_RADIUS + 1
            state = reading["patterns"][digit_index][segment_index]
            color = (0, 200, 0)
            if state == "?":
                color = (0, 200, 255)
            elif state == "0":
                color = (160, 160, 160)
            cv2.rectangle(
                annotated, (left, top), (right - 1, bottom - 1), color, line_thickness
            )
    mask_bgr = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
    return np.vstack([annotated, mask_bgr])


def main():
    validate_segment_points()
    if not (0 <= RED_MIN <= 255 and 0 < RED_MARGIN <= 255):
        raise ValueError("RED_MINは0〜255、RED_MARGINは0より大きく255以下です。")
    if not 0 <= WHITE_MIN <= 255:
        raise ValueError("WHITE_MINは0〜255です。")
    if not 0 <= OFF_FRACTION < ON_FRACTION <= 1:
        raise ValueError("点灯率は0 <= OFF_FRACTION < ON_FRACTION <= 1にしてください。")
    if not isinstance(STABLE_FRAMES, int) or STABLE_FRAMES < 1:
        raise ValueError("STABLE_FRAMESは1以上の整数にしてください。")

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
        received_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        received_time = time.monotonic()
        start_time = received_time
        image = prepare_frame(frame)
        fps = capture.get(cv2.CAP_PROP_FPS)
        if not is_camera and (not math.isfinite(fps) or fps <= 0):
            raise RuntimeError(
                "動画のfpsを取得できません。時刻を付けられないため停止します。"
            )
        window = "Seven segment OCR"
        if SHOW_PREVIEW:
            cv2.namedWindow(window, cv2.WINDOW_NORMAL)
            height, width = image.shape[:2]
            panel_height = height * 2
            scale = min(1.0, 1280 / width, 720 / panel_height)
            cv2.resizeWindow(window, round(width * scale), round(panel_height * scale))
            line_thickness = max(1, round(1 / scale))
        CSV_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        csv_path = CSV_DIR / f"readings_{timestamp}.csv"
        csv_file = csv_path.open("x", encoding="utf-8", newline="")
        print("CSV: " + str(csv_path), file=sys.stderr)
        fields = [
            "frame_index",
            "received_at",
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
        while True:
            if is_camera:
                source_time = received_time - start_time
            else:
                source_time = frame_index / fps
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
                "received_at": received_at,
                "source_time_seconds": round(source_time, 6),
                "status": status,
                "display": reading["display"],
                "raw_value": raw_value,
                "value": value,
                "reason": reading["reason"],
            }
            writer.writerow(row)
            csv_file.flush()
            message = {
                "received_at": row["received_at"],
                "source_time_seconds": row["source_time_seconds"],
                "value": None,
            }
            # CSVは小数3桁を保ち、連携ではそのまま計算できる数値を渡す。
            if value is not None:
                message["value"] = float(value)
            print(json.dumps(message, ensure_ascii=True), flush=True)
            if SHOW_PREVIEW:
                cv2.setWindowTitle(
                    window,
                    f"{status}: {raw_value or '---'} {reading['reason']}   Q / Esc: quit",
                )
                cv2.imshow(window, draw_preview(image, mask, reading, line_thickness))
                delay = 1
                if not is_camera:
                    delay = max(1, round(1000 / fps))
                key = cv2.waitKey(delay) & 0xFF
                if key in (27, ord("q")):
                    break
                if cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                    break
            success, frame = capture.read()
            if not success:
                if is_camera:
                    raise RuntimeError(
                        "カメラ画像の取得に失敗しました。収集を停止します。"
                    )
                break
            received_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
            received_time = time.monotonic()
            image = prepare_frame(frame)
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
