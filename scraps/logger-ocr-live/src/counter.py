import json
import math
import os
import sys
import time
from contextlib import ExitStack, closing, nullcontext
from datetime import UTC, datetime
from threading import Event, Thread

import cv2
import numpy as np

SOURCE = None

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
STABLE_FRAMES = 1

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


def main():
    stop_requested = Event()
    if "--managed" in sys.argv:
        Thread(target=watch_parent, args=(stop_requested,), daemon=True).start()
    show_segment_scores = "--segment-scores" in sys.argv

    with closing(
        read_counter(SOURCE, stop_requested, show_segment_scores=show_segment_scores)
    ) as readings:
        for message in readings:
            print(json.dumps(message, allow_nan=False), flush=True)


def read_counter(source, stop_requested, *, show_segment_scores=False):
    if source is None:
        raise ValueError("SOURCE未設定")
    source_is_teli = isinstance(source, tuple)
    if source_is_teli:
        camera_kind, camera_index = source
        if camera_kind != "teli":
            raise ValueError(f"SOURCEのカメラ種別は 'teli'（{camera_kind!r}）")
    if not 0 <= OFF_FRACTION < ON_FRACTION <= 1:
        raise ValueError("点灯率は 0 <= OFF_FRACTION < ON_FRACTION <= 1")
    if not isinstance(STABLE_FRAMES, int) or STABLE_FRAMES < 1:
        raise ValueError("STABLE_FRAMESは1以上の整数")
    if not (0 <= RED_MIN <= 255 and 0 < RED_MARGIN <= 255):
        raise ValueError("RED_MINは0〜255、RED_MARGINは0より大きく255以下")
    if not 0 <= WHITE_MIN <= 255:
        raise ValueError("WHITE_MINは0〜255")
    if RED_EXCESS_LIMITS is not None:
        off_limit, on_limit = RED_EXCESS_LIMITS
        if not -255 <= off_limit < on_limit <= 255:
            raise ValueError(
                f"RED_EXCESS_LIMITSは−255〜255で消灯上限 < 点灯下限（{RED_EXCESS_LIMITS!r}）"
            )
    sample_coordinates = prepare_samples(REFLECTION)

    video_frame_interval = None
    with ExitStack() as capture_resources:
        if source_is_teli:
            from camera_sdk import open_teli_camera

            read_frame = capture_resources.enter_context(
                open_teli_camera(camera_index, stop_requested)
            )
        else:
            source_is_webcam = isinstance(source, int)
            if source_is_webcam:
                capture_source = source
            else:
                capture_source = str(source)
            capture = cv2.VideoCapture(capture_source)
            capture_resources.callback(capture.release)
            if not capture.isOpened():
                raise RuntimeError(f"入力を開けない（{capture_source}）")
            if source_is_webcam:
                calibrated_width, calibrated_height = FRAME_SIZE
                capture.set(cv2.CAP_PROP_FRAME_WIDTH, calibrated_width)
                capture.set(cv2.CAP_PROP_FRAME_HEIGHT, calibrated_height)
            else:
                fps = capture.get(cv2.CAP_PROP_FPS)
                if not math.isfinite(fps) or fps <= 0:
                    raise RuntimeError(f"動画FPS不正（{fps}）")
                video_frame_interval = 1 / fps

            def read_opencv_frame():
                frame_read, frame = capture.read()
                if not frame_read:
                    frame = None
                return nullcontext(frame)

            read_frame = read_opencv_frame

        yield from read_frames(
            read_frame,
            sample_coordinates,
            stop_requested,
            video_frame_interval=video_frame_interval,
            show_segment_scores=show_segment_scores,
        )


def prepare_samples(reflection):
    if reflection not in ("none", "horizontal", "vertical", "both"):
        raise ValueError(f"REFLECTION不正（{reflection!r}）")
    if SAMPLE_RADIUS < 0:
        raise ValueError("SAMPLE_RADIUSは0以上")
    length_radius = SAMPLE_LENGTH_RADIUS
    if length_radius is None:
        length_radius = SAMPLE_RADIUS
    if length_radius < SAMPLE_RADIUS:
        raise ValueError("SAMPLE_LENGTH_RADIUSはSAMPLE_RADIUS以上")
    if len(SEGMENT_POINTS) != 6:
        raise ValueError("SEGMENT_POINTSは6桁分")

    frame_width, frame_height = FRAME_SIZE
    reverse_x = reflection in ("horizontal", "both")
    reverse_y = reflection in ("vertical", "both")
    sample_rows = []
    sample_columns = []
    for digit_points in SEGMENT_POINTS:
        if len(digit_points) != 7:
            raise ValueError("SEGMENT_POINTSは各桁7点")
        for segment_index, (calibrated_x, calibrated_y) in enumerate(digit_points):
            x_radius = SAMPLE_RADIUS
            y_radius = SAMPLE_RADIUS
            segment_is_horizontal = segment_index in (0, 3, 6)
            if segment_is_horizontal:
                x_radius = length_radius
            else:
                y_radius = length_radius

            x_fits = x_radius <= calibrated_x < frame_width - x_radius
            y_fits = y_radius <= calibrated_y < frame_height - y_radius
            if not x_fits or not y_fits:
                raise ValueError(
                    f"読み取り範囲が画像外（座標 {(calibrated_x, calibrated_y)}）"
                )

            center_x = calibrated_x
            center_y = calibrated_y
            if reverse_x:
                center_x = frame_width - 1 - calibrated_x
            if reverse_y:
                center_y = frame_height - 1 - calibrated_y

            first_row = center_y - y_radius
            last_row = center_y + y_radius
            first_column = center_x - x_radius
            last_column = center_x + x_radius
            segment_rows = []
            segment_columns = []
            for row in range(first_row, last_row + 1):
                for column in range(first_column, last_column + 1):
                    segment_rows.append(row)
                    segment_columns.append(column)
            sample_rows.append(segment_rows)
            sample_columns.append(segment_columns)

    return np.array(sample_rows), np.array(sample_columns)


def watch_parent(stop_requested):
    os.read(sys.stdin.fileno(), 1)
    stop_requested.set()


def read_frames(
    read_frame,
    sample_coordinates,
    stop_requested,
    *,
    video_frame_interval,
    show_segment_scores,
):
    calibrated_width, calibrated_height = FRAME_SIZE
    playing_video = video_frame_interval is not None
    previous_reading = None
    matching_frame_count = 0
    has_read_a_frame = False
    while not stop_requested.is_set():
        if playing_video:
            frame_started_at = time.monotonic()

        with read_frame() as frame:
            if frame is None:
                reached_video_end = playing_video and has_read_a_frame
                if stop_requested.is_set() or reached_video_end:
                    break
                raise RuntimeError("画像取得失敗")

            received_at = datetime.now(UTC).isoformat(timespec="milliseconds")
            acquired_mono_ns = time.monotonic_ns()
            has_read_a_frame = True
            frame_height, frame_width = frame.shape[:2]
            if [frame_width, frame_height] != FRAME_SIZE:
                raise ValueError(
                    f"解像度不一致（撮影 {frame_width}×{frame_height}、"
                    f"校正 {calibrated_width}×{calibrated_height}）"
                )
            bgr_shape = (frame_height, frame_width, 3)
            if frame.shape != bgr_shape or frame.dtype != np.uint8:
                raise ValueError("赤色判定には8ビットBGR画像が必要")
            reading = recognize_display(
                frame, sample_coordinates, show_segment_scores=show_segment_scores
            )

        if reading is None:
            matching_frame_count = 0
        elif reading == previous_reading:
            matching_frame_count += 1
        else:
            matching_frame_count = 1
        previous_reading = reading

        confirmed_value = None
        if matching_frame_count >= STABLE_FRAMES:
            confirmed_value = reading
        yield {
            "received_at": received_at,
            "acquired_mono_ns": acquired_mono_ns,
            "value": confirmed_value,
        }

        if playing_video:
            elapsed_seconds = time.monotonic() - frame_started_at
            remaining_seconds = video_frame_interval - elapsed_seconds
            stop_requested.wait(max(0, remaining_seconds))


def recognize_display(image, sample_coordinates, *, show_segment_scores=False):
    sample_rows, sample_columns = sample_coordinates
    sampled_pixels = image[sample_rows, sample_columns]
    signed_pixels = sampled_pixels.astype(np.int16)
    blue = signed_pixels[:, :, 0]
    green = signed_pixels[:, :, 1]
    red = signed_pixels[:, :, 2]
    strongest_other_color = np.maximum(blue, green)
    red_excess = red - strongest_other_color
    white_pixels = (blue >= WHITE_MIN) & (green >= WHITE_MIN) & (red >= WHITE_MIN)
    white_fraction_by_segment = np.mean(white_pixels, axis=1)
    segments_with_excess_white = white_fraction_by_segment > OFF_FRACTION

    use_median = RED_EXCESS_LIMITS is not None
    if use_median or show_segment_scores:
        median_red_excess_by_segment = np.median(red_excess, axis=1)
    if show_segment_scores:
        white_segment_numbers = np.flatnonzero(segments_with_excess_white) + 1
        print(
            f"red_excess={median_red_excess_by_segment.tolist()} "
            f"white_segments={white_segment_numbers.tolist()}",
            file=sys.stderr,
        )
    if np.any(segments_with_excess_white):
        return None

    if use_median:
        segment_scores = median_red_excess_by_segment
        off_limit, on_limit = RED_EXCESS_LIMITS
    else:
        red_pixels = (red >= RED_MIN) & (red_excess >= RED_MARGIN)
        segment_scores = np.mean(red_pixels, axis=1)
        off_limit = OFF_FRACTION
        on_limit = ON_FRACTION

    scores_by_digit = segment_scores.reshape(6, 7)
    display_text = ""
    for digit_scores in scores_by_digit:
        segment_pattern = ""
        for score in digit_scores:
            if score >= on_limit:
                segment_pattern += "1"
            elif score <= off_limit:
                segment_pattern += "0"
            else:
                return None

        digit = PATTERN_TO_DIGIT.get(segment_pattern)
        if digit is None:
            return None
        display_text += digit

    count_text = display_text.lstrip(" ")
    if not count_text.isdigit():
        return None
    return int(count_text) / 1000


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
