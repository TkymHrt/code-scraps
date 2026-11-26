import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

FOLDER = Path(__file__).resolve().parent
CAPTURE_DIR = FOLDER / "captures/run-01"
CALIBRATION = FOLDER / "calibration-single.json"

RED_MIN = 70
RED_MARGIN = 40
WHITE_MIN = 200
OFF_FRACTION = 0.15
ON_FRACTION = 0.65

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


def prepare_samples(calibration, frame_size):
    if calibration["FRAME_SIZE"] != frame_size:
        raise ValueError("撮影と校正のFRAME_SIZEが不一致")
    reflection = calibration["REFLECTION"]
    radius = calibration["SAMPLE_RADIUS"]
    length_radius = calibration["SAMPLE_LENGTH_RADIUS"]
    if length_radius is None:
        length_radius = radius
    points = np.asarray(calibration["SEGMENT_POINTS"])
    width, height = frame_size
    sample_rows = []
    sample_columns = []
    for segment_index, (x, y) in enumerate(points.reshape(42, 2)):
        x_radius = radius
        y_radius = radius
        if segment_index % 7 in (0, 3, 6):
            x_radius = length_radius
        else:
            y_radius = length_radius
        if reflection in ("horizontal", "both"):
            x = width - 1 - x
        if reflection in ("vertical", "both"):
            y = height - 1 - y
        if not (x_radius <= x < width - x_radius and y_radius <= y < height - y_radius):
            raise ValueError(f"読み取り領域が画像外（セグメント{segment_index + 1}）")
        columns, rows = np.meshgrid(
            np.arange(x - x_radius, x + x_radius + 1),
            np.arange(y - y_radius, y + y_radius + 1),
        )
        sample_rows.append(rows.ravel())
        sample_columns.append(columns.ravel())
    return np.array(sample_rows), np.array(sample_columns)


def decode_segments(segment_scores, off_limit, on_limit):
    display_text = ""
    for digit_scores in segment_scores.reshape(6, 7):
        pattern = ""
        for score in digit_scores:
            if score >= on_limit:
                pattern += "1"
            elif score <= off_limit:
                pattern += "0"
            else:
                return None, None, "ambiguous"
        digit = PATTERN_TO_DIGIT.get(pattern)
        if digit is None:
            return None, None, "invalid_pattern"
        display_text += digit
    count_text = display_text.lstrip(" ")
    if not count_text.isdigit():
        return None, display_text, "invalid_display"
    return int(count_text), display_text, "ok"


def recognize_display(image, sample_coordinates):
    rows, columns = sample_coordinates
    pixels = image[rows, columns].astype(np.int16)
    blue = pixels[:, :, 0]
    green = pixels[:, :, 1]
    red = pixels[:, :, 2]
    red_excess = red - np.maximum(green, blue)
    red_pixels = (red >= RED_MIN) & (red_excess >= RED_MARGIN)
    scores = np.mean(red_pixels, axis=1)
    white_pixels = (blue >= WHITE_MIN) & (green >= WHITE_MIN) & (red >= WHITE_MIN)
    if np.any(np.mean(white_pixels, axis=1) > OFF_FRACTION):
        return None, None, "white", scores
    raw_value, display_text, reason = decode_segments(scores, OFF_FRACTION, ON_FRACTION)
    return raw_value, display_text, reason, scores


def main(capture_dir, calibration_file):
    session = json.loads((capture_dir / "session.json").read_text(encoding="utf-8-sig"))
    if session["pixel_format"] != "BayerBG8":
        raise ValueError("対応する保存形式はBayerBG8")
    if session["reverse_x"] or session["reverse_y"]:
        raise ValueError("カメラのReverseX・ReverseYはOffの記録が必要")
    if any(offset % 2 for offset in session["offset"]):
        raise ValueError("カメラのOffsetX・OffsetYは偶数の記録が必要")
    width, height = session["frame_size"]
    calibration = json.loads(calibration_file.read_text(encoding="utf-8-sig"))
    sample_coordinates = prepare_samples(calibration, session["frame_size"])

    print(
        json.dumps(
            {
                "method": "bgr_fraction",
                "thresholds": {
                    "red_min": RED_MIN,
                    "red_margin": RED_MARGIN,
                    "white_min": WHITE_MIN,
                    "off_fraction": OFF_FRACTION,
                    "on_fraction": ON_FRACTION,
                },
                "calibration": calibration,
                "samples_per_segment": [sample_coordinates[0].shape[1]] * 42,
            }
        ),
        file=sys.stderr,
    )

    frame_count = 0
    readable_count = 0
    timings = []
    manifest_path = capture_dir / "frames.jsonl"
    with manifest_path.open(encoding="utf-8-sig") as manifest:
        for line in manifest:
            frame_info = json.loads(line)
            filename = frame_info["file"]
            if Path(filename).name != filename or not filename.endswith(".npy"):
                raise ValueError(f"画像ファイル名不正（{filename}）")
            load_started = time.perf_counter()
            raw = np.load(capture_dir / filename, allow_pickle=False)
            load_ms = (time.perf_counter() - load_started) * 1000
            if raw.shape != (height, width) or raw.dtype != np.uint8:
                raise ValueError(
                    f"BayerBG8画像不正（{filename}: {raw.shape}, {raw.dtype}）"
                )
            convert_started = time.perf_counter()
            image = cv2.cvtColor(raw, cv2.COLOR_BayerBGGR2BGR)
            convert_ms = (time.perf_counter() - convert_started) * 1000
            recognize_started = time.perf_counter()
            raw_value, display_text, reason, scores = recognize_display(
                image, sample_coordinates
            )
            recognize_ms = (time.perf_counter() - recognize_started) * 1000
            value = None
            if raw_value is not None:
                value = raw_value / 1000
                readable_count += 1
            result = {
                "file": filename,
                "received_at": frame_info["received_at"],
                "block_id": frame_info["block_id"],
                "timestamp_ticks": frame_info["timestamp_ticks"],
                "display": display_text,
                "raw_value": raw_value,
                "value": value,
                "reason": reason,
                "segment_scores": scores.tolist(),
                "load_ms": load_ms,
                "convert_ms": convert_ms,
                "recognize_ms": recognize_ms,
            }
            print(json.dumps(result, allow_nan=False))
            timings.append([load_ms, convert_ms, recognize_ms])
            frame_count += 1

    if frame_count == 0:
        raise ValueError("frames.jsonlに記録なし")
    summary = {
        "method": "bgr_fraction",
        "frames": frame_count,
        "readable": readable_count,
        "unreadable": frame_count - readable_count,
        "timing_columns": ["load_ms", "convert_ms", "recognize_ms"],
        "median_ms": np.median(timings, axis=0).tolist(),
        "p95_ms": np.percentile(timings, 95, axis=0).tolist(),
    }
    print(json.dumps(summary, allow_nan=False), file=sys.stderr)


if __name__ == "__main__":
    main(CAPTURE_DIR, CALIBRATION)
