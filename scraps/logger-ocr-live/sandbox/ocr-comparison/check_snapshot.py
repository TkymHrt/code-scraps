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


def read_display(binary, points, side):
    height, width = binary.shape
    points = np.asarray(points)
    if points.shape != (6, 7, 2) or points.dtype.kind not in "iu":
        raise ValueError(f"{side}: 校正点は各42点の整数座標が必要")
    columns, rows = points[:, :, 0], points[:, :, 1]
    if np.any((columns < 0) | (columns >= width) | (rows < 0) | (rows >= height)):
        raise ValueError(f"{side}: 校正点が画像外")

    # shortcut: 各点は中心1画素。隣接画素とのばらつきで誤読する場合に範囲を広げる。
    lit = binary[rows, columns] != 0
    display = ""
    for digit in lit:
        pattern = "".join("1" if segment else "0" for segment in digit)
        decoded = DIGITS.get(pattern)
        if decoded is None:
            return None
        display += decoded
    return int(display) if display.lstrip().isdigit() else None


def main():
    raw = np.load(FRAME, allow_pickle=False)
    if (
        not isinstance(raw, np.ndarray)
        or raw.ndim != 2
        or raw.dtype != np.uint8
        or min(raw.shape) < 3
    ):
        raise ValueError(f"BayerBG8は縦横3画素以上の2次元uint8配列が必要（{FRAME}）")
    if not 0 <= THRESHOLD <= 255:
        raise ValueError(f"THRESHOLDは0～255（{THRESHOLD}）")
    gray = cv2.cvtColor(raw, cv2.COLOR_BayerBGGR2GRAY)
    _, binary = cv2.threshold(gray, THRESHOLD, 255, cv2.THRESH_BINARY)
    readings = {}
    if CALIBRATION is not None:
        calibration = json.loads(CALIBRATION.read_text(encoding="utf-8-sig"))
        if calibration["frame_size_px"] != list(binary.shape[::-1]):
            raise ValueError(f"撮影と校正の画像サイズが不一致（{CALIBRATION}）")
        reflection = calibration["reflection"]
        aligned = binary
        if reflection != "none":
            aligned = cv2.flip(
                binary, {"horizontal": 1, "vertical": 0, "both": -1}[reflection]
            )
        for side in ("op", "dr"):
            readings[side] = read_display(
                aligned, calibration[f"{side}_points_px"], side
            )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=False)
    for name, image in (("gray.png", gray), ("binary.png", binary)):
        path = OUTPUT_DIR / name
        success, encoded = cv2.imencode(".png", image)
        if not success:
            raise RuntimeError(f"PNG作成失敗（{path}）")
        path.write_bytes(encoded.tobytes())
        print(path)

    for side, value in readings.items():
        print(f"{side.upper()} {'欠測' if value is None else value}")


if __name__ == "__main__":
    main()
