import sys
from pathlib import Path

import cv2
import numpy as np

SOURCE = 0
REFLECTION = "horizontal"
SAMPLE_RADIUS = 1
SAMPLE_LENGTH_RADIUS = None

DIGIT_COUNT = 6
SEGMENT_NAMES_IN_CLICK_ORDER = (
    "top",
    "upper-right",
    "lower-right",
    "bottom",
    "lower-left",
    "upper-left",
    "middle",
)
SEGMENTS_PER_DIGIT = len(SEGMENT_NAMES_IN_CLICK_ORDER)
REQUIRED_POINTS = DIGIT_COUNT * SEGMENTS_PER_DIGIT


def main():
    if not isinstance(SAMPLE_RADIUS, int) or SAMPLE_RADIUS < 0:
        raise ValueError("SAMPLE_RADIUSは0以上の整数")
    if SAMPLE_LENGTH_RADIUS is not None and (
        not isinstance(SAMPLE_LENGTH_RADIUS, int)
        or SAMPLE_LENGTH_RADIUS < SAMPLE_RADIUS
    ):
        raise ValueError("SAMPLE_LENGTH_RADIUSはNoneかSAMPLE_RADIUS以上の整数")

    is_camera = isinstance(SOURCE, int)
    if is_camera:
        source = SOURCE
        is_png = False
    else:
        source = str(SOURCE)
        is_png = source.lower().endswith(".png")
    is_video = not is_camera and not is_png

    capture = None
    try:
        if is_png:
            png_data = Path(source).read_bytes()
            if not png_data:
                raise RuntimeError(f"校正用PNGが空（{source}）")
            encoded_png = np.frombuffer(png_data, dtype=np.uint8)
            frame = cv2.imdecode(encoded_png, cv2.IMREAD_COLOR)
            if frame is None:
                raise RuntimeError(f"校正用PNG読込失敗（{source}）")
        else:
            capture = cv2.VideoCapture(source)
            if not capture.isOpened():
                raise RuntimeError(f"入力を開けない（{source}）")
            frame_read, frame = capture.read()
            if not frame_read:
                raise RuntimeError("最初の画像の取得失敗")
        calibration_image = correct_reflection(frame)

        window_name = "Calibration"
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
        frame_height, frame_width = frame.shape[:2]
        window_scale = min(1.0, 1280 / frame_width, 720 / frame_height)
        window_width = round(frame_width * window_scale)
        window_height = round(frame_height * window_scale)
        cv2.resizeWindow(window_name, window_width, window_height)
        if is_video:
            cv2.setWindowTitle(
                window_name, "SPACE: select points   N: next video frame   Q: cancel"
            )
        else:
            cv2.setWindowTitle(window_name, "SPACE: select points   Q: cancel")

        while True:
            cv2.imshow(window_name, calibration_image)
            key = cv2.waitKey(30) & 0xFF
            if key in (27, ord("q")) or window_is_closed(window_name):
                return
            if key == ord(" "):
                break
            if is_camera:
                frame_read, frame = capture.read()
                if not frame_read:
                    raise RuntimeError("校正中のカメラ画像取得失敗")
                calibration_image = correct_reflection(frame)
            elif is_video and key == ord("n"):
                frame_read, next_frame = capture.read()
                if frame_read:
                    calibration_image = correct_reflection(next_frame)
                else:
                    print("次の画像なし（Spaceで校正、Qで終了）", file=sys.stderr)

        selected_points = select_segment_points(
            window_name, calibration_image, window_scale
        )
        if selected_points is None:
            return

        points_by_digit = []
        for digit_index in range(DIGIT_COUNT):
            first_point = digit_index * SEGMENTS_PER_DIGIT
            after_last_point = first_point + SEGMENTS_PER_DIGIT
            digit_points = selected_points[first_point:after_last_point]
            points_by_digit.append(digit_points)

        frame_height, frame_width = frame.shape[:2]
        frame_size = [frame_width, frame_height]
        print(
            "以下の5行をread_meter.py先頭の同名設定へ貼り付けてください。",
            file=sys.stderr,
        )
        print("FRAME_SIZE = " + repr(frame_size))
        print("REFLECTION = " + repr(REFLECTION))
        print("SAMPLE_RADIUS = " + repr(SAMPLE_RADIUS))
        print("SAMPLE_LENGTH_RADIUS = " + repr(SAMPLE_LENGTH_RADIUS))
        print("SEGMENT_POINTS = " + repr(points_by_digit))
    finally:
        if capture is not None:
            capture.release()
        cv2.destroyAllWindows()


def correct_reflection(frame):
    if REFLECTION == "horizontal":
        return cv2.flip(frame, 1)
    if REFLECTION == "vertical":
        return cv2.flip(frame, 0)
    if REFLECTION == "both":
        return cv2.flip(frame, -1)
    if REFLECTION == "none":
        return frame
    raise ValueError(f"REFLECTION不正（{REFLECTION!r}）")


def window_is_closed(window_name):
    try:
        visible = cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE)
        return visible < 1
    except cv2.error:
        return True


def select_segment_points(window_name, calibration_image, window_scale):
    image_height, image_width = calibration_image.shape[:2]
    selected_points = []

    def record_segment_click(event, x, y, _flags, _parameter):
        if event != cv2.EVENT_LBUTTONDOWN or len(selected_points) == REQUIRED_POINTS:
            return

        segment_index = len(selected_points) % SEGMENTS_PER_DIGIT
        x_radius, y_radius = sample_radii(segment_index)
        x_fits = x_radius <= x < image_width - x_radius
        y_fits = y_radius <= y < image_height - y_radius
        if not x_fits or not y_fits:
            print("読み取り範囲が画像外。別の点を選択", file=sys.stderr)
            return
        selected_points.append([x, y])

    cv2.setMouseCallback(window_name, record_segment_click)
    line_thickness = max(1, round(1 / window_scale))
    font_scale = 0.4 / window_scale
    label_height = round(14 / window_scale)
    label_offset = round(3 / window_scale)
    highlight_color = (0, 255, 255)

    while True:
        preview = calibration_image.copy()
        for point_index, (x, y) in enumerate(selected_points):
            digit_number = point_index // SEGMENTS_PER_DIGIT + 1
            segment_index = point_index % SEGMENTS_PER_DIGIT
            segment_number = segment_index + 1
            x_radius, y_radius = sample_radii(segment_index)
            left = x - x_radius
            top = y - y_radius
            right = x + x_radius
            bottom = y + y_radius
            label_y = max(label_height, top - label_offset)
            cv2.rectangle(
                preview,
                (left, top),
                (right, bottom),
                highlight_color,
                line_thickness,
            )
            cv2.putText(
                preview,
                f"{digit_number}.{segment_number}",
                (left, label_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                font_scale,
                highlight_color,
                line_thickness,
            )

        points_selected = len(selected_points)
        if points_selected == REQUIRED_POINTS:
            message = (
                f"{points_selected}/{REQUIRED_POINTS}  "
                "ENTER: finish   B: undo   Q / Esc: cancel"
            )
        else:
            digit_number = points_selected // SEGMENTS_PER_DIGIT + 1
            segment_index = points_selected % SEGMENTS_PER_DIGIT
            segment_number = segment_index + 1
            segment_name = SEGMENT_NAMES_IN_CLICK_ORDER[segment_index]
            message = (
                f"Digit {digit_number}/{DIGIT_COUNT} - "
                f"{segment_number}/{SEGMENTS_PER_DIGIT} {segment_name}: "
                "CLICK red area   B: undo   Q / Esc: cancel"
            )
        cv2.setWindowTitle(window_name, message)
        cv2.imshow(window_name, preview)

        key = cv2.waitKey(30) & 0xFF
        if key in (27, ord("q")) or window_is_closed(window_name):
            return None
        if key == ord("b") and selected_points:
            selected_points.pop()
        elif key in (10, 13) and len(selected_points) == REQUIRED_POINTS:
            return selected_points


def sample_radii(segment_index):
    if SAMPLE_LENGTH_RADIUS is None:
        return SAMPLE_RADIUS, SAMPLE_RADIUS
    segment_name = SEGMENT_NAMES_IN_CLICK_ORDER[segment_index]
    if segment_name in ("top", "bottom", "middle"):
        return SAMPLE_LENGTH_RADIUS, SAMPLE_RADIUS
    return SAMPLE_RADIUS, SAMPLE_LENGTH_RADIUS


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("校正中止", file=sys.stderr)
