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

# 実機では既存のcalibrate_meter.pyで得た3項目を貼り付ける。
FRAME_SIZE = [960, 360]
REFLECTION = "horizontal"
# 各桁の上、右上、右下、下、左下、左上、中央の順に [左, 上, 右, 下]。
SEGMENT_BOXES = [
    [
        [149, 105, 185, 116],
        [198, 131, 209, 169],
        [192, 221, 203, 261],
        [135, 279, 173, 292],
        [111, 224, 123, 263],
        [119, 134, 131, 172],
        [142, 190, 179, 202],
    ],
    [
        [268, 100, 304, 112],
        [319, 126, 329, 164],
        [315, 217, 326, 257],
        [259, 276, 297, 288],
        [234, 220, 245, 259],
        [239, 129, 250, 167],
        [263, 186, 301, 198],
    ],
    [
        [389, 95, 426, 107],
        [442, 122, 452, 160],
        [442, 213, 451, 253],
        [385, 272, 423, 285],
        [358, 216, 369, 256],
        [361, 125, 371, 163],
        [387, 182, 424, 194],
    ],
    [
        [512, 90, 549, 102],
        [567, 117, 578, 155],
        [569, 209, 580, 250],
        [513, 269, 552, 281],
        [485, 212, 495, 252],
        [485, 120, 494, 158],
        [512, 177, 551, 190],
    ],
    [
        [637, 84, 675, 97],
        [694, 112, 706, 151],
        [699, 205, 711, 246],
        [644, 265, 684, 278],
        [613, 208, 624, 248],
        [611, 115, 621, 154],
        [640, 173, 679, 185],
    ],
    [
        [764, 79, 804, 92],
        [824, 107, 837, 146],
        [831, 201, 845, 242],
        [777, 262, 818, 274],
        [744, 204, 756, 244],
        [738, 110, 750, 149],
        [770, 168, 811, 181],
    ],
]

RED_MIN = 70
RED_MARGIN = 40
WHITE_MIN = 200
RED_SEED_FRACTION = 0.05
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


def validate_segment_boxes():
    if len(SEGMENT_BOXES) != 6:
        raise ValueError("SEGMENT_BOXESには6桁分の枠を指定してください。")
    width, height = FRAME_SIZE
    for boxes in SEGMENT_BOXES:
        if len(boxes) != 7:
            raise ValueError("各桁に7個のセグメント枠を指定してください。")
        for left, top, right, bottom in boxes:
            if not (0 <= left < right <= width and 0 <= top < bottom <= height):
                raise ValueError("セグメント枠を撮影画像内に指定してください。")


def recognize_display(image):
    # uint8のまま引くと負数が255付近に回り込む。
    blue = image[:, :, 0].astype(np.int16)
    green = image[:, :, 1].astype(np.int16)
    red = image[:, :, 2].astype(np.int16)
    red_excess = red - np.maximum(blue, green)
    red_pixels = (red >= RED_MIN) & (red_excess >= RED_MARGIN)
    white_pixels = (blue >= WHITE_MIN) & (green >= WHITE_MIN) & (red >= WHITE_MIN)

    display = ""
    for boxes in SEGMENT_BOXES:
        pattern = ""
        for left, top, right, bottom in boxes:
            region_red = red_pixels[top:bottom, left:right]
            region_white = white_pixels[top:bottom, left:right]
            region_lit = region_red.copy()
            # 同じ枠の中で十分な赤につながる白飛びだけを点灯に含める。
            candidates = (region_red | region_white).astype(np.uint8)
            component_count, labels = cv2.connectedComponents(
                candidates, connectivity=8
            )
            minimum_red_count = math.ceil(region_red.size * RED_SEED_FRACTION)
            for component_index in range(1, component_count):
                component = labels == component_index
                red_count = np.count_nonzero(region_red & component)
                if red_count >= minimum_red_count:
                    region_lit |= component

            lit_fraction = np.count_nonzero(region_lit) / region_lit.size
            unsupported_white = region_white & ~region_lit
            white_fraction = np.count_nonzero(unsupported_white) / region_lit.size
            if lit_fraction >= ON_FRACTION:
                pattern += "1"
            elif lit_fraction <= OFF_FRACTION and white_fraction <= OFF_FRACTION:
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
    validate_segment_boxes()
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
    if not (0 <= WHITE_MIN <= 255 and 0 < RED_SEED_FRACTION <= 1):
        raise ValueError("WHITE_MINとRED_SEED_FRACTIONを確認してください。")

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
