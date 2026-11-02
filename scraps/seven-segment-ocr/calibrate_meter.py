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


def window_is_closed(window):
    try:
        return cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1
    except cv2.error:
        # 閉じた直後は、ウィンドウ自体が既に存在しない場合もある。
        return True


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
        cv2.setWindowTitle(window, "SPACE: freeze   N: next video frame   Q: cancel")
        while True:
            corrected = correct_reflection(frame)
            cv2.imshow(window, corrected)
            key = cv2.waitKey(30) & 0xFF
            if key in (27, ord("q")) or window_is_closed(window):
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
        segment_names = [
            "top",
            "upper-right",
            "lower-right",
            "bottom",
            "lower-left",
            "upper-left",
            "middle",
        ]
        selected_boxes = []
        reviewing = False
        line_thickness = max(1, round(1 / scale))
        font_scale = 0.4 / scale
        label_height = round(14 / scale)
        label_offset = round(3 / scale)
        while True:
            preview = image.copy()
            for index, (left, top, right, bottom) in enumerate(selected_boxes):
                cv2.rectangle(
                    preview, (left, top), (right - 1, bottom - 1),
                    (0, 255, 255), line_thickness,
                )
                cv2.putText(
                    preview, f"{index // 7 + 1}.{index % 7 + 1}",
                    (left, max(label_height, top - label_offset)),
                    cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 255, 255),
                    line_thickness,
                )
            if len(selected_boxes) == 42:
                reviewing = True
            if reviewing:
                action = "resume"
                if len(selected_boxes) == 42:
                    action = "finish"
                message = f"{len(selected_boxes)}/42  ENTER: {action}   B: undo   Q: cancel"
                cv2.setWindowTitle(window, message)
                cv2.imshow(window, preview)
                key = cv2.waitKey(30) & 0xFF
                if key in (27, ord("q")) or window_is_closed(window):
                    return
                if key == ord("b") and selected_boxes:
                    selected_boxes.pop()
                elif key in (10, 13):
                    if len(selected_boxes) == 42:
                        break
                    reviewing = False
                continue

            digit_index = len(selected_boxes) // 7
            segment_index = len(selected_boxes) % 7
            message = (
                f"Digit {digit_index + 1}/6 - {segment_index + 1}/7 "
                f"{segment_names[segment_index]}: ENTER select, C review"
            )
            cv2.setWindowTitle(window, message)
            x, y, width, height = cv2.selectROI(
                window, preview, showCrosshair=True, printNotice=False
            )
            if window_is_closed(window):
                return
            if width == 0 or height == 0:
                reviewing = True
                continue
            right = x + width
            bottom = y + height
            if not (
                0 <= x < right <= image_width and 0 <= y < bottom <= image_height
            ):
                print(
                    "セグメント枠を撮影画像内に選び直してください。", file=sys.stderr
                )
                continue
            selected_boxes.append([x, y, right, bottom])

        segment_boxes = []
        for start in range(0, 42, 7):
            segment_boxes.append(selected_boxes[start : start + 7])
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
