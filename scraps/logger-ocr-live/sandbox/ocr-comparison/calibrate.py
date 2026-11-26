import json
import sys
from pathlib import Path

import cv2
import numpy as np

FOLDER = Path(__file__).resolve().parent
SOURCE = FOLDER / "results/snapshot-01/binary.png"
OUTPUT = FOLDER / "calibration.json"
REFLECTION = "none"

SIDES = ("op", "dr")
SEGMENT_NAMES = (
    "top",
    "upper-right",
    "lower-right",
    "bottom",
    "lower-left",
    "upper-left",
    "middle",
)


def main():
    if OUTPUT.exists():
        raise FileExistsError(f"校正保存先が既に存在（{OUTPUT}）")
    encoded = np.frombuffer(SOURCE.read_bytes(), dtype=np.uint8)
    image = None
    if encoded.size:
        image = cv2.imdecode(encoded, cv2.IMREAD_UNCHANGED)
    if (
        image is None
        or image.ndim != 2
        or image.dtype != np.uint8
        or np.any((image != 0) & (image != 255))
    ):
        raise ValueError(f"校正には固定しきい値で保存した二値画像が必要（{SOURCE}）")
    if REFLECTION != "none":
        image = cv2.flip(
            image, {"horizontal": 1, "vertical": 0, "both": -1}[REFLECTION]
        )
    height, width = image.shape

    points = select_points(cv2.cvtColor(image, cv2.COLOR_GRAY2BGR))
    if points is None:
        print("校正中止。保存していません。", file=sys.stderr)
        return

    settings = {
        "frame_size_px": [width, height],
        "reflection": REFLECTION,
        "op_points_px": np.array(points[:42]).reshape(6, 7, 2).tolist(),
        "dr_points_px": np.array(points[42:]).reshape(6, 7, 2).tolist(),
    }
    contents = json.dumps(settings, ensure_ascii=False, indent=2)
    with OUTPUT.open("x", encoding="utf-8") as output:
        output.write(contents + "\n")
    print(f"校正保存: {OUTPUT}")


def select_points(image):
    height, width = image.shape[:2]
    points = []
    pressed = False
    dragged = False

    def on_mouse(event, x, y, flags, _parameter):
        nonlocal pressed, dragged
        if event == cv2.EVENT_LBUTTONDOWN:
            pressed = True
            dragged = False
            return
        if event == cv2.EVENT_MOUSEMOVE and pressed:
            if flags & cv2.EVENT_FLAG_LBUTTON:
                dragged = True
            else:
                pressed = False
            return
        if event == cv2.EVENT_MOUSEWHEEL:
            pressed = False
            return
        if event != cv2.EVENT_LBUTTONUP:
            return
        select = pressed and not dragged
        pressed = False
        # Qtは左ドラッグで移動するため、押した瞬間ではなくクリック完了で点を選ぶ。
        if not select or len(points) == 84:
            return
        if not (0 <= x < width and 0 <= y < height):
            print(f"校正点が画像外（{x}, {y}）。別の点を選択", file=sys.stderr)
            return
        # Qtが拡大・移動を戻した元画像座標を渡すので、ここで再変換しない。
        points.append([x, y])

    window = "OP / DR calibration - OpenCV Qt"
    try:
        cv2.namedWindow(window, cv2.WINDOW_AUTOSIZE | cv2.WINDOW_GUI_EXPANDED)
        cv2.setMouseCallback(window, on_mouse)
        while True:
            preview = image.copy()
            for index, (x, y) in enumerate(points):
                preview[y, x] = (0, 255, 255) if index < 42 else (255, 255, 0)
            if len(points) == 84:
                title = "84/84 - ENTER: save calibration"
            else:
                side = SIDES[len(points) // 42].upper()
                digit = len(points) % 42 // 7 + 1
                segment = SEGMENT_NAMES[len(points) % 7]
                title = (
                    f"{len(points)}/84 - {side} digit {digit}/6 {segment}: CLICK center"
                )
            cv2.setWindowTitle(
                window, title + " | Wheel: zoom  Drag: pan  B: undo  Q: cancel"
            )
            cv2.imshow(window, preview)
            key = cv2.waitKey(30) & 0xFF
            try:
                closed = cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1
            except cv2.error:
                closed = True
            if key in (27, ord("q")) or closed:
                return None
            if key == ord("b") and points:
                points.pop()
            if key in (10, 13) and len(points) == 84:
                return points
    finally:
        cv2.destroyAllWindows()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("校正中止", file=sys.stderr)
