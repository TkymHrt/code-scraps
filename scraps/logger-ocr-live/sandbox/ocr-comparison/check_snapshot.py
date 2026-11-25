import json
from pathlib import Path

import cv2
import numpy as np
from compare import OFF_FRACTION, ON_FRACTION, decode_segments, prepare_samples

FOLDER = Path(__file__).resolve().parent
FRAME = FOLDER / "captures/run-01/frame-000000.npy"
OUTPUT_DIR = FOLDER / "results/snapshot-01"
THRESHOLD = 50
CALIBRATION = None


def main():
    if not 0 <= THRESHOLD <= 255:
        raise ValueError(f"THRESHOLDは0〜255（{THRESHOLD}）")

    session_path = FRAME.parent / "session.json"
    session = json.loads(session_path.read_text(encoding="utf-8-sig"))
    if (
        session["pixel_format"] != "BayerBG8"
        or session["reverse_x"]
        or session["reverse_y"]
    ):
        raise ValueError(f"BayerBG8、ReverseX/Y=Offの撮影記録が必要（{session_path}）")
    if any(offset % 2 for offset in session["offset"]):
        raise ValueError(f"OffsetX/Yは偶数が必要（{session_path}）")
    width, height = session["frame_size"]
    raw = np.load(FRAME, allow_pickle=False)
    if raw.dtype != np.uint8 or raw.shape != (height, width):
        raise ValueError(
            f"BayerBG8画像の形状・型が不正（{FRAME}: {raw.shape}, {raw.dtype}）"
        )

    gray = cv2.cvtColor(raw, cv2.COLOR_BayerBGGR2GRAY)
    _, binary = cv2.threshold(gray, THRESHOLD, 255, cv2.THRESH_BINARY)
    readings = []
    if CALIBRATION:
        calibration = json.loads(CALIBRATION.read_text(encoding="utf-8-sig"))
        if calibration["frame_size_px"] != [width, height]:
            raise ValueError(f"撮影と校正の画像サイズが不一致（{CALIBRATION}）")
        for side in ("op", "dr"):
            rows, columns = prepare_samples(calibration, side)
            scores = np.mean(binary[rows, columns] != 0, axis=1)
            result = decode_segments(scores, OFF_FRACTION, ON_FRACTION)
            display = repr(result["display"]) if result["reason"] == "ok" else "欠測"
            readings.append(f"{side.upper()} {display} ({result['reason']})")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=False)
    for name, image in (("gray.png", gray), ("binary.png", binary)):
        path = OUTPUT_DIR / name
        success, encoded = cv2.imencode(".png", image)
        if not success:
            raise RuntimeError(f"PNG作成失敗（{path}）")
        path.write_bytes(encoded.tobytes())
        print(path)
    for reading in readings:
        print(reading)


if __name__ == "__main__":
    main()
