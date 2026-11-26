import json
from pathlib import Path

import cv2
import numpy as np

FOLDER = Path(__file__).resolve().parent
FRAME = FOLDER / "captures/run-01/frame-000000.npy"
OUTPUT_DIR = FOLDER / "results/snapshot-01"
THRESHOLD = 50
CALIBRATION = None


DIGITS = {
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
OFF_FRACTION = 0.15
ON_FRACTION = 0.65


def read_display(binary, points, radius, length_radius):
    height, width = binary.shape
    display = ""
    for digit in points:
        pattern = ""
        for segment, (x, y) in enumerate(digit):
            rx, ry = radius, length_radius
            if segment in (0, 3, 6):
                rx, ry = length_radius, radius
            if not (rx <= x < width - rx and ry <= y < height - ry):
                raise ValueError(f"校正点の読み取り範囲が画像外（{x}, {y}）")
            sample = binary[y - ry : y + ry + 1, x - rx : x + rx + 1]
            fraction = np.mean(sample != 0)
            if fraction >= ON_FRACTION:
                pattern += "1"
            elif fraction <= OFF_FRACTION:
                pattern += "0"
            else:
                return "欠測 (ambiguous)"
        if pattern not in DIGITS:
            return "欠測 (invalid_pattern)"
        display += DIGITS[pattern]
    if not display.lstrip().isdigit():
        return "欠測 (invalid_display)"
    return f"{display!r} (ok)"


def main():
    raw = np.load(FRAME, allow_pickle=False)
    gray = cv2.cvtColor(raw, cv2.COLOR_BayerBGGR2GRAY)
    _, binary = cv2.threshold(gray, THRESHOLD, 255, cv2.THRESH_BINARY)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=False)
    for name, image in (("gray.png", gray), ("binary.png", binary)):
        path = OUTPUT_DIR / name
        success, encoded = cv2.imencode(".png", image)
        if not success:
            raise RuntimeError(f"PNG作成失敗（{path}）")
        path.write_bytes(encoded.tobytes())
        print(path)

    if CALIBRATION is None:
        return
    calibration = json.loads(CALIBRATION.read_text(encoding="utf-8-sig"))
    if calibration["frame_size_px"] != list(binary.shape[::-1]):
        raise ValueError(f"撮影と校正の画像サイズが不一致（{CALIBRATION}）")
    reflection = calibration["reflection"]
    if reflection != "none":
        binary = cv2.flip(
            binary, {"horizontal": 1, "vertical": 0, "both": -1}[reflection]
        )
    radius = calibration["sample_radius_px"]
    length_radius = calibration["sample_length_radius_px"]
    if length_radius is None:
        length_radius = radius
    for side in ("op", "dr"):
        reading = read_display(
            binary, calibration[f"{side}_points_px"], radius, length_radius
        )
        print(f"{side.upper()} {reading}")


if __name__ == "__main__":
    main()
