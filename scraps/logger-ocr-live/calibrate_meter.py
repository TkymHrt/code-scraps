import sys
from pathlib import Path

import cv2
import numpy as np

SOURCE = 0  # カメラ番号、動画パス、または保存したPNG画像のパス。
REFLECTION = "horizontal"
SAMPLE_RADIUS = 1
SAMPLE_LENGTH_RADIUS = None  # 細長く読む場合は長手方向の半径を指定する。


def correct_reflection(frame):
    if REFLECTION == "horizontal":
        return cv2.flip(frame, 1)
    if REFLECTION == "vertical":
        return cv2.flip(frame, 0)
    if REFLECTION == "both":
        return cv2.flip(frame, -1)
    if REFLECTION == "none":
        return frame
    raise ValueError("REFLECTION の指定が不正です。")


def window_is_closed(window):
    try:
        return cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1
    except cv2.error:
        return True


def sample_radii(segment_index):
    if SAMPLE_LENGTH_RADIUS is None:
        return SAMPLE_RADIUS, SAMPLE_RADIUS
    if segment_index in (0, 3, 6):  # 上、下、中央の横線
        return SAMPLE_LENGTH_RADIUS, SAMPLE_RADIUS
    return SAMPLE_RADIUS, SAMPLE_LENGTH_RADIUS


def main():
    if not isinstance(SAMPLE_RADIUS, int) or SAMPLE_RADIUS < 0:
        raise ValueError("SAMPLE_RADIUSは0以上の整数にしてください。")
    if SAMPLE_LENGTH_RADIUS is not None and (
        not isinstance(SAMPLE_LENGTH_RADIUS, int)
        or SAMPLE_LENGTH_RADIUS < SAMPLE_RADIUS
    ):
        raise ValueError(
            "SAMPLE_LENGTH_RADIUSはNoneか、SAMPLE_RADIUS以上の整数にしてください。"
        )

    is_camera = isinstance(SOURCE, int)
    if is_camera:
        source = SOURCE
    else:
        source = str(SOURCE)
    is_snapshot = not is_camera and source.lower().endswith(".png")
    capture = None
    try:
        if is_snapshot:
            # Windowsでも日本語を含むパスを開けるように、PythonでPNGを読む。
            png_data = Path(source).read_bytes()
            if not png_data:
                raise RuntimeError("校正用PNGが空です: " + source)
            encoded = np.frombuffer(png_data, dtype=np.uint8)
            frame = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
            if frame is None:
                raise RuntimeError("校正用PNGを読み込めません: " + source)
        else:
            capture = cv2.VideoCapture(source)
            if not capture.isOpened():
                raise RuntimeError("カメラまたは動画を開けません: " + str(source))
            success, frame = capture.read()
            if not success:
                raise RuntimeError("最初の画像を取得できません。")
        image = correct_reflection(frame)

        window = "Calibration"
        cv2.namedWindow(window, cv2.WINDOW_NORMAL)
        frame_height, frame_width = frame.shape[:2]
        scale = min(1.0, 1280 / frame_width, 720 / frame_height)
        cv2.resizeWindow(
            window, round(frame_width * scale), round(frame_height * scale)
        )
        if is_camera or is_snapshot:
            cv2.setWindowTitle(window, "SPACE: select points   Q: cancel")
        else:
            cv2.setWindowTitle(
                window, "SPACE: select points   N: next video frame   Q: cancel"
            )
        while True:
            cv2.imshow(window, image)
            key = cv2.waitKey(30) & 0xFF
            if key in (27, ord("q")) or window_is_closed(window):
                return
            if key == ord(" "):
                break
            if not is_camera and not is_snapshot and key == ord("n"):
                success, next_frame = capture.read()
                if success:
                    image = correct_reflection(next_frame)
                else:
                    print(
                        "次の画像がありません。現在の画像で校正するかQで終了してください。",
                        file=sys.stderr,
                    )
            if is_camera:
                success, frame = capture.read()
                if not success:
                    raise RuntimeError("校正中にカメラ画像の取得に失敗しました。")
                image = correct_reflection(frame)

        image_height, image_width = image.shape[:2]
        segment_names = [
            "top",
            "upper-right",
            "lower-right",
            "bottom",
            "lower-left",
            "upper-left",
            "middle",
        ]
        selected_points = []

        def select_segment(event, x, y, flags, parameter):
            if event != cv2.EVENT_LBUTTONDOWN or len(selected_points) == 42:
                return
            x_radius, y_radius = sample_radii(len(selected_points) % 7)
            if not (
                x_radius <= x < image_width - x_radius
                and y_radius <= y < image_height - y_radius
            ):
                print(
                    "読み取り範囲が撮影画像からはみ出します。点を選び直してください。",
                    file=sys.stderr,
                )
                return
            selected_points.append([x, y])

        cv2.setMouseCallback(window, select_segment)
        line_thickness = max(1, round(1 / scale))
        font_scale = 0.4 / scale
        label_height = round(14 / scale)
        label_offset = round(3 / scale)
        while True:
            preview = image.copy()
            for index, (x, y) in enumerate(selected_points):
                x_radius, y_radius = sample_radii(index % 7)
                left = x - x_radius
                top = y - y_radius
                right = x + x_radius
                bottom = y + y_radius
                cv2.rectangle(
                    preview,
                    (left, top),
                    (right, bottom),
                    (0, 255, 255),
                    line_thickness,
                )
                cv2.putText(
                    preview,
                    f"{index // 7 + 1}.{index % 7 + 1}",
                    (left, max(label_height, top - label_offset)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    font_scale,
                    (0, 255, 255),
                    line_thickness,
                )
            if len(selected_points) == 42:
                message = "42/42  ENTER: finish   B: undo   Q / Esc: cancel"
            else:
                digit_index = len(selected_points) // 7
                segment_index = len(selected_points) % 7
                message = (
                    f"Digit {digit_index + 1}/6 - {segment_index + 1}/7 "
                    f"{segment_names[segment_index]}: CLICK red area   B: undo   Q / Esc: cancel"
                )
            cv2.setWindowTitle(window, message)
            cv2.imshow(window, preview)
            key = cv2.waitKey(30) & 0xFF
            if key in (27, ord("q")) or window_is_closed(window):
                return
            if key == ord("b") and selected_points:
                selected_points.pop()
            elif key in (10, 13) and len(selected_points) == 42:
                break

        segment_points = []
        for start in range(0, 42, 7):
            segment_points.append(selected_points[start : start + 7])
        print(
            "以下の5行をread_meter.py先頭の同名設定へ貼り付けてください。",
            file=sys.stderr,
        )
        print("FRAME_SIZE = " + repr([frame.shape[1], frame.shape[0]]))
        print("REFLECTION = " + repr(REFLECTION))
        print("SAMPLE_RADIUS = " + repr(SAMPLE_RADIUS))
        print("SAMPLE_LENGTH_RADIUS = " + repr(SAMPLE_LENGTH_RADIUS))
        print("SEGMENT_POINTS = " + repr(segment_points))
    finally:
        if capture is not None:
            capture.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("校正を中止しました。", file=sys.stderr)
