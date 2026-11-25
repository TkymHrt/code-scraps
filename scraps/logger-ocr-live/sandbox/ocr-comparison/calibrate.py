import json
import sys
from pathlib import Path

import cv2
import numpy as np

FOLDER = Path(__file__).resolve().parent
SOURCE = FOLDER / "results/snapshot-01/binary.png"
OUTPUT = FOLDER / "calibration.json"
REFLECTION = "none"
SAMPLE_RADIUS = 1
SAMPLE_LENGTH_RADIUS = None

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
    if type(SAMPLE_RADIUS) is not int or SAMPLE_RADIUS < 0:
        raise ValueError(f"SAMPLE_RADIUSは0以上の整数（{SAMPLE_RADIUS}）")
    length_radius = SAMPLE_LENGTH_RADIUS
    if length_radius is None:
        length_radius = SAMPLE_RADIUS
    if type(length_radius) is not int or length_radius < SAMPLE_RADIUS:
        raise ValueError("SAMPLE_LENGTH_RADIUSはNoneかSAMPLE_RADIUS以上の整数")
    if REFLECTION not in ("none", "horizontal", "vertical", "both"):
        raise ValueError(f"REFLECTION不正（{REFLECTION}）")

    encoded = np.frombuffer(SOURCE.read_bytes(), dtype=np.uint8)
    image = None
    if encoded.size:
        image = cv2.imdecode(encoded, cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
    if image is None:
        raise ValueError(f"校正画像を読めない（{SOURCE}）")
    if REFLECTION != "none":
        image = cv2.flip(
            image, {"horizontal": 1, "vertical": 0, "both": -1}[REFLECTION]
        )
    height, width = image.shape[:2]

    points = select_points(image, SAMPLE_RADIUS, length_radius)
    if points is None:
        print("校正中止。保存していません。", file=sys.stderr)
        return

    settings = {
        "source_image": str(SOURCE.resolve()),
        "frame_size_px": [width, height],
        "reflection": REFLECTION,
        "sample_radius_px": SAMPLE_RADIUS,
        "sample_length_radius_px": SAMPLE_LENGTH_RADIUS,
        "op_points_px": np.array(points[:42]).reshape(6, 7, 2).tolist(),
        "dr_points_px": np.array(points[42:]).reshape(6, 7, 2).tolist(),
    }
    contents = json.dumps(settings, ensure_ascii=False, indent=2)
    with OUTPUT.open("x", encoding="utf-8") as output:
        output.write(contents + "\n")
    print(f"校正保存: {OUTPUT}")


def select_points(image, radius, length_radius):
    backend = cv2.currentUIFramework()
    if backend != "QT":
        raise RuntimeError(
            f"Qt版OpenCVが必要（現在: {backend}）。READMEのQt環境で起動してください"
        )
    height, width = image.shape[:2]
    points = []
    pressed = False
    dragged = False
    radii = [
        (length_radius, radius) if segment in (0, 3, 6) else (radius, length_radius)
        for segment in range(7)
    ]

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
        x_radius, y_radius = radii[len(points) % 7]
        if not (x_radius <= x < width - x_radius and y_radius <= y < height - y_radius):
            print(f"読み取り範囲が画像外（{x}, {y}）。別の点を選択", file=sys.stderr)
            return
        # Qtが拡大・移動を戻した元画像座標を渡すので、ここで再変換しない。
        points.append([x, y])

    window = "OP / DR calibration - OpenCV Qt"
    scale = min(1.0, 1280 / width, 720 / height)
    thickness = max(1, round(1 / scale))
    try:
        cv2.namedWindow(window, cv2.WINDOW_NORMAL | cv2.WINDOW_GUI_EXPANDED)
        cv2.resizeWindow(window, round(width * scale), round(height * scale))
        cv2.setMouseCallback(window, on_mouse)
        while True:
            preview = image.copy()
            for index, (x, y) in enumerate(points):
                side = SIDES[index // 42].upper()
                digit = index % 42 // 7 + 1
                segment = index % 7
                x_radius, y_radius = radii[segment]
                color = (0, 255, 255) if side == "OP" else (255, 255, 0)
                left, top = x - x_radius, y - y_radius
                cv2.rectangle(
                    preview, (left, top), (x + x_radius, y + y_radius), color, thickness
                )
                cv2.putText(
                    preview,
                    f"{side} {digit}.{segment + 1}",
                    (left, max(round(14 / scale), top - round(3 / scale))),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.4 / scale,
                    color,
                    thickness,
                )
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
