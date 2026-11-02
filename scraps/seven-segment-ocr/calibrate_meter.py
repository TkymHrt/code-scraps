"""撮影画像から各桁7個の領域を選び、read_meter.pyへ貼る設定を表示する。"""

import sys

import cv2

# カメラは整数。録画を使う場合は下の行へ切り替える。
SOURCE = 0
# SOURCE = r"C:\measurement\recorded.avi"
REFLECTION = "horizontal"  # "none", "horizontal", "vertical", "both"


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


def main():
    is_camera = isinstance(SOURCE, int)
    if is_camera:
        source = SOURCE
    else:
        source = str(SOURCE)
    capture = cv2.VideoCapture(source)
    try:
        if not capture.isOpened():
            raise RuntimeError("カメラまたは動画を開けません: " + str(source))
        success, frame = capture.read()
        if not success:
            raise RuntimeError("最初の画像を取得できません。")

        window = "Calibration"
        cv2.namedWindow(window, cv2.WINDOW_NORMAL)
        frame_height, frame_width = frame.shape[:2]
        scale = min(1.0, 1280 / frame_width, 720 / frame_height)
        cv2.resizeWindow(
            window, round(frame_width * scale), round(frame_height * scale)
        )
        while True:
            corrected = correct_reflection(frame)
            preview = corrected.copy()
            cv2.putText(
                preview,
                "SPACE: freeze   N: next video frame   Q: cancel",
                (10, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 255),
                2,
            )
            cv2.imshow(window, preview)
            delay = 0
            if is_camera:
                delay = 30
            key = cv2.waitKey(delay) & 0xFF
            if key in (27, ord("q")):
                return
            if key == ord(" "):
                break
            if not is_camera and key == ord("n"):
                success, next_frame = capture.read()
                if success:
                    frame = next_frame
                else:
                    print(
                        "動画の最後です。現在の画像で校正するかQで終了してください。",
                        file=sys.stderr,
                    )
            if is_camera:
                success, frame = capture.read()
                if not success:
                    raise RuntimeError("校正中にカメラ画像の取得に失敗しました。")

        image = corrected
        image_height, image_width = image.shape[:2]
        cv2.destroyWindow(window)
        segment_names = [
            "top",
            "upper-right",
            "lower-right",
            "bottom",
            "lower-left",
            "upper-left",
            "middle",
        ]
        segment_boxes = []
        for digit_index in range(6):
            boxes = []
            segment_boxes.append(boxes)
            while len(boxes) < 7:
                preview = image.copy()
                for selected_boxes in segment_boxes:
                    for left, top, right, bottom in selected_boxes:
                        cv2.rectangle(
                            preview,
                            (left, top),
                            (right - 1, bottom - 1),
                            (0, 255, 255),
                            1,
                        )
                segment_index = len(boxes)
                title = (
                    f"Digit {digit_index + 1}/6 - {segment_index + 1}/7 "
                    f"{segment_names[segment_index]}: ENTER confirm, C cancel"
                )
                x, y, width, height = cv2.selectROI(title, preview, showCrosshair=True)
                cv2.destroyWindow(title)
                if width == 0 or height == 0:
                    return
                right = x + width
                bottom = y + height
                if not (
                    0 <= x < right <= image_width and 0 <= y < bottom <= image_height
                ):
                    print(
                        "セグメント枠を撮影画像内に選び直してください。",
                        file=sys.stderr,
                    )
                    continue
                boxes.append([x, y, right, bottom])

        print(
            "以下の3行をread_meter.py先頭の同名設定へ貼り付けてください。",
            file=sys.stderr,
        )
        print("FRAME_SIZE = " + repr([frame.shape[1], frame.shape[0]]))
        print("REFLECTION = " + repr(REFLECTION))
        print("SEGMENT_BOXES = " + repr(segment_boxes))
    finally:
        capture.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("校正を中止しました。", file=sys.stderr)
