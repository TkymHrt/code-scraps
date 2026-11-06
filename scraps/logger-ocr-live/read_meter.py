"""赤い6桁7セグの確定値を、カメラまたは動画から読み取ってJSONLで出力する。"""

import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from threading import Event, Thread

import cv2
import numpy as np

SOURCE = None  # カメラ番号（0など）または動画のパス

# 実機では既存のcalibrate_meter.pyで得た4項目を貼り付ける。
FRAME_SIZE = [960, 360]
REFLECTION = "horizontal"
SAMPLE_RADIUS = 1  # 1は3×3画素、2は5×5画素を読む。
# 各桁の上、右上、右下、下、左下、左上、中央の順に [x, y]。
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
WHITE_MIN = 200
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


def watch_parent(stop_requested):
    # 計算側が標準入力のパイプを閉じると、次の画像取得前に終了できる。
    os.read(sys.stdin.fileno(), 1)
    stop_requested.set()


def validate_segment_points():
    if not isinstance(SAMPLE_RADIUS, int) or SAMPLE_RADIUS < 0:
        raise ValueError("SAMPLE_RADIUSは0以上の整数にしてください。")
    if len(SEGMENT_POINTS) != 6:
        raise ValueError("SEGMENT_POINTSには6桁分の点を指定してください。")
    width, height = FRAME_SIZE
    for points in SEGMENT_POINTS:
        if len(points) != 7:
            raise ValueError("各桁に7個の点を指定してください。")
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
    # uint8のまま引くと負数が255付近に回り込む。
    blue = image[:, :, 0].astype(np.int16)
    green = image[:, :, 1].astype(np.int16)
    red = image[:, :, 2].astype(np.int16)
    red_excess = red - np.maximum(blue, green)
    red_pixels = (red >= RED_MIN) & (red_excess >= RED_MARGIN)
    white_pixels = (blue >= WHITE_MIN) & (green >= WHITE_MIN) & (red >= WHITE_MIN)

    display = ""
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
            # 白飛びした点灯を、消灯や別の数字として扱わない。
            if white_fraction > OFF_FRACTION:
                return None
            if red_fraction >= ON_FRACTION:
                pattern += "1"
            elif red_fraction <= OFF_FRACTION:
                pattern += "0"
            else:
                return None

        digit = PATTERN_TO_DIGIT.get(pattern)
        if digit is None:
            return None
        display += digit

    integer_part = display[:3].lstrip(" ")
    fraction_part = display[3:]
    if not integer_part.isdigit() or not fraction_part.isdigit():
        return None
    return float(f"{integer_part}.{fraction_part}")


def main():
    if SOURCE is None:
        raise ValueError("SOURCEにカメラ番号か動画のパスを指定してください。")
    validate_segment_points()
    flip_codes = {"horizontal": 1, "vertical": 0, "both": -1}
    if REFLECTION != "none" and REFLECTION not in flip_codes:
        raise ValueError("REFLECTIONの補正方向を確認してください。")
    if not 0 <= OFF_FRACTION < ON_FRACTION <= 1:
        raise ValueError(
            "点灯率のしきい値は0 <= OFF_FRACTION < ON_FRACTION <= 1にしてください。"
        )
    if not isinstance(STABLE_FRAMES, int) or STABLE_FRAMES < 1:
        raise ValueError("STABLE_FRAMESは1以上の整数にしてください。")
    if not (0 <= RED_MIN <= 255 and 0 < RED_MARGIN <= 255):
        raise ValueError("RED_MINとRED_MARGINは画素値の範囲内で指定してください。")
    if not 0 <= WHITE_MIN <= 255:
        raise ValueError("WHITE_MINは画素値の範囲内で指定してください。")

    stop_requested = Event()
    if "--managed" in sys.argv:
        Thread(target=watch_parent, args=(stop_requested,), daemon=True).start()

    is_camera = isinstance(SOURCE, int)
    source = SOURCE if is_camera else str(SOURCE)
    capture = cv2.VideoCapture(source)
    try:
        if not capture.isOpened():
            raise RuntimeError(f"カメラまたは動画を開けませんでした（{source}）。")
        frame_interval = None
        if is_camera:
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_SIZE[0])
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_SIZE[1])
        else:
            fps = capture.get(cv2.CAP_PROP_FPS)
            if not math.isfinite(fps) or fps <= 0:
                raise RuntimeError("動画のfpsを取得できませんでした。")
            frame_interval = 1 / fps

        previous_value = None
        consecutive_count = 0
        has_frame = False
        while not stop_requested.is_set():
            if frame_interval is not None:
                frame_started_at = time.monotonic()
            success, frame = capture.read()
            if not success:
                if is_camera or not has_frame:
                    raise RuntimeError("画像を取得できませんでした。")
                break
            received_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
            has_frame = True
            height, width = frame.shape[:2]
            if [width, height] != FRAME_SIZE:
                raise ValueError("撮影解像度が校正時と異なります。")
            if REFLECTION != "none":
                frame = cv2.flip(frame, flip_codes[REFLECTION])

            reading = recognize_display(frame)
            if reading is None:
                consecutive_count = 0
            elif reading == previous_value:
                consecutive_count += 1
            else:
                consecutive_count = 1
            previous_value = reading

            value = None
            if consecutive_count >= STABLE_FRAMES:
                value = reading
            message = {"received_at": received_at, "value": value}
            print(json.dumps(message, allow_nan=False), flush=True)
            if frame_interval is not None:
                processing_time = time.monotonic() - frame_started_at
                stop_requested.wait(max(0, frame_interval - processing_time))
    finally:
        capture.release()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("OCR取得を終了しました。", file=sys.stderr)
