import json
import math
import os
import sys
import time
from contextlib import ExitStack, nullcontext
from datetime import UTC, datetime
from threading import Event, Thread

import cv2
import numpy as np

SOURCE = None
# SOURCE = 0  # Webカメラの番号
# SOURCE = r"C:\measurement\recorded.avi"  # 動画ファイル
# SOURCE = ("teli", 0)  # TeliCamSDKで検出した東芝テリー製カメラの番号

FRAME_SIZE = [960, 360]
REFLECTION = "horizontal"
SAMPLE_RADIUS = 1
SAMPLE_LENGTH_RADIUS = None
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
RED_EXCESS_LIMITS = None
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
    os.read(sys.stdin.fileno(), 1)
    stop_requested.set()


def prepare_samples(reflection):
    if reflection not in ("none", "horizontal", "vertical", "both"):
        raise ValueError(f"REFLECTION: {reflection!r}")
    reverse_x = reflection in ("horizontal", "both")
    reverse_y = reflection in ("vertical", "both")
    if SAMPLE_RADIUS < 0:
        raise ValueError("SAMPLE_RADIUSが負です。")
    if SAMPLE_LENGTH_RADIUS is not None and SAMPLE_LENGTH_RADIUS < SAMPLE_RADIUS:
        raise ValueError("SAMPLE_LENGTH_RADIUSがSAMPLE_RADIUSより小さいです。")
    if len(SEGMENT_POINTS) != 6:
        raise ValueError("SEGMENT_POINTSは6桁分必要です。")
    width, height = FRAME_SIZE
    rows = []
    columns = []
    for points in SEGMENT_POINTS:
        if len(points) != 7:
            raise ValueError("各桁に7点必要です。")
        for segment_index, (x, y) in enumerate(points):
            x_radius = SAMPLE_RADIUS
            y_radius = SAMPLE_RADIUS
            if SAMPLE_LENGTH_RADIUS is not None:
                if segment_index in (0, 3, 6):  # 上、下、中央の横線
                    x_radius = SAMPLE_LENGTH_RADIUS
                else:
                    y_radius = SAMPLE_LENGTH_RADIUS
            if not (
                x_radius <= x < width - x_radius and y_radius <= y < height - y_radius
            ):
                raise ValueError(f"読み取り範囲が画像外です。座標 {(x, y)}")

            # 元画像の座標に戻し、毎フレームの画像反転を省く。
            if reverse_x:
                x = width - 1 - x
            if reverse_y:
                y = height - 1 - y
            segment_rows = []
            segment_columns = []
            for row in range(y - y_radius, y + y_radius + 1):
                for column in range(x - x_radius, x + x_radius + 1):
                    segment_rows.append(row)
                    segment_columns.append(column)
            rows.append(segment_rows)
            columns.append(segment_columns)
    return np.array(rows), np.array(columns)


def recognize_display(image, sample_coordinates, *, show_segment_scores=False):
    rows, columns = sample_coordinates
    # uint8のまま引くと負の差が回り込む。
    pixels = image[rows, columns].astype(np.int16)
    blue = pixels[:, :, 0]
    green = pixels[:, :, 1]
    red = pixels[:, :, 2]
    red_excess = red - np.maximum(blue, green)
    white_pixels = (blue >= WHITE_MIN) & (green >= WHITE_MIN) & (red >= WHITE_MIN)
    white_fractions = np.mean(white_pixels, axis=1)
    white_segments = white_fractions > OFF_FRACTION

    if RED_EXCESS_LIMITS is not None or show_segment_scores:
        red_excess_medians = np.median(red_excess, axis=1)
    if show_segment_scores:
        blocked_segments = np.flatnonzero(white_segments) + 1
        print(
            f"red_excess={red_excess_medians.tolist()} "
            f"white_segments={blocked_segments.tolist()}",
            file=sys.stderr,
        )
    if np.any(white_segments):
        return None

    if RED_EXCESS_LIMITS is None:
        red_pixels = (red >= RED_MIN) & (red_excess >= RED_MARGIN)
        segment_scores = np.mean(red_pixels, axis=1)
        off_limit = OFF_FRACTION
        on_limit = ON_FRACTION
    else:
        segment_scores = red_excess_medians
        off_limit, on_limit = RED_EXCESS_LIMITS

    display = ""
    for digit_scores in segment_scores.reshape(6, 7):
        pattern = ""
        for score in digit_scores:
            if score >= on_limit:
                pattern += "1"
            elif score <= off_limit:
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
        raise ValueError("SOURCEが未設定です。")
    is_teli = isinstance(SOURCE, tuple)
    if is_teli:
        camera_kind, camera_index = SOURCE
        if camera_kind != "teli":
            raise ValueError(f"SOURCE: {SOURCE!r}")
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
    if RED_EXCESS_LIMITS is not None:
        off_limit, on_limit = RED_EXCESS_LIMITS
        if not -255 <= off_limit < on_limit <= 255:
            raise ValueError(f"RED_EXCESS_LIMITS: {RED_EXCESS_LIMITS!r}")
    sample_coordinates = prepare_samples(REFLECTION)

    stop_requested = Event()
    if "--managed" in sys.argv:
        Thread(target=watch_parent, args=(stop_requested,), daemon=True).start()
    show_segment_scores = "--segment-scores" in sys.argv

    frame_interval = None
    with ExitStack() as resources:
        if is_teli:
            from teli_camera import open_teli_camera

            read_frame = resources.enter_context(
                open_teli_camera(camera_index, stop_requested)
            )
        else:
            is_webcam = isinstance(SOURCE, int)
            source = SOURCE if is_webcam else str(SOURCE)
            capture = cv2.VideoCapture(source)
            resources.callback(capture.release)
            if not capture.isOpened():
                raise RuntimeError(f"カメラまたは動画を開けませんでした（{source}）。")
            if is_webcam:
                capture.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_SIZE[0])
                capture.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_SIZE[1])
            else:
                fps = capture.get(cv2.CAP_PROP_FPS)
                if not math.isfinite(fps) or fps <= 0:
                    raise RuntimeError("動画のfpsを取得できませんでした。")
                frame_interval = 1 / fps

            def read_frame():
                success, frame = capture.read()
                return nullcontext(frame if success else None)

        previous_value = None
        consecutive_count = 0
        has_frame = False
        while not stop_requested.is_set():
            if frame_interval is not None:
                frame_started_at = time.monotonic()
            with read_frame() as frame:
                if frame is None:
                    if stop_requested.is_set() or (
                        frame_interval is not None and has_frame
                    ):
                        break
                    raise RuntimeError("画像を取得できませんでした。")
                received_at = datetime.now(UTC).isoformat(timespec="milliseconds")
                has_frame = True
                height, width = frame.shape[:2]
                if [width, height] != FRAME_SIZE:
                    raise ValueError(
                        f"撮影解像度 {width}×{height} が校正時の "
                        f"{FRAME_SIZE[0]}×{FRAME_SIZE[1]} と異なります。"
                    )
                if frame.shape != (height, width, 3) or frame.dtype != np.uint8:
                    raise ValueError("赤色判定には8ビットBGRのカラー画像が必要です。")
                reading = recognize_display(
                    frame, sample_coordinates, show_segment_scores=show_segment_scores
                )

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


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
