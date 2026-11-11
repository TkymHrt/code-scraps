import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

OFF_RED = 30
ON_RED = 70

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
    if reflection not in ("none", "horizontal", "vertical", "both"):
        raise ValueError(f"REFLECTION不正（{reflection}）")
    radius = calibration["SAMPLE_RADIUS"]
    length_radius = calibration["SAMPLE_LENGTH_RADIUS"]
    if length_radius is None:
        length_radius = radius
    if type(radius) is not int or radius < 0:
        raise ValueError("SAMPLE_RADIUSは0以上の整数")
    if type(length_radius) is not int or length_radius < radius:
        raise ValueError("SAMPLE_LENGTH_RADIUSはSAMPLE_RADIUS以上の整数")
    points = np.asarray(calibration["SEGMENT_POINTS"])
    if points.shape != (6, 7, 2) or not np.issubdtype(points.dtype, np.integer):
        raise ValueError("SEGMENT_POINTSは6桁×7点の整数座標")
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
    medians = []
    for rows, columns in sample_coordinates:
        medians.append(float(np.median(image[rows, columns])))
    scores = np.array(medians)
    raw_value, display_text, reason = decode_segments(scores, OFF_RED, ON_RED)
    return raw_value, display_text, reason, scores


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="保存したBayerBG8の赤画素の中央値で各フレームを判定する"
    )
    parser.add_argument("capture_dir", type=Path)
    parser.add_argument("--calibration", type=Path, required=True)
    args = parser.parse_args(argv)
    if not 0 <= OFF_RED < ON_RED <= 255:
        raise ValueError("0 <= OFF_RED < ON_RED <= 255")

    session = json.loads(
        (args.capture_dir / "session.json").read_text(encoding="utf-8-sig")
    )
    if session["pixel_format"] != "BayerBG8":
        raise ValueError("対応する保存形式はBayerBG8")
    if session["reverse_x"] or session["reverse_y"]:
        raise ValueError("カメラのReverseX・ReverseYはOffの記録が必要")
    if any(offset % 2 for offset in session["offset"]):
        raise ValueError("カメラのOffsetX・OffsetYは偶数の記録が必要")
    width, height = session["frame_size"]
    if width < 4 or height < 4:
        raise ValueError("画像サイズは4×4以上")
    calibration = json.loads(args.calibration.read_text(encoding="utf-8-sig"))
    sample_coordinates = prepare_samples(calibration, session["frame_size"])
    red_coordinates = []
    for segment_index, (rows, columns) in enumerate(
        zip(*sample_coordinates, strict=True)
    ):
        red_positions = (rows % 2 == 1) & (columns % 2 == 1)
        if not np.any(red_positions):
            raise ValueError(
                f"赤画素なし（セグメント{segment_index + 1}、校正領域を拡大）"
            )
        red_coordinates.append((rows[red_positions], columns[red_positions]))
    sample_coordinates = red_coordinates
    print(
        json.dumps(
            {
                "method": "bayer_red",
                "thresholds": {"off_red": OFF_RED, "on_red": ON_RED},
                "calibration": calibration,
                "samples_per_segment": [
                    len(rows) for rows, columns in sample_coordinates
                ],
            }
        ),
        file=sys.stderr,
    )

    frame_count = 0
    readable_count = 0
    timings = []
    manifest_path = args.capture_dir / "frames.jsonl"
    with manifest_path.open(encoding="utf-8-sig") as manifest:
        for line in manifest:
            frame_info = json.loads(line)
            filename = frame_info["file"]
            if Path(filename).name != filename or not filename.endswith(".npy"):
                raise ValueError(f"画像ファイル名不正（{filename}）")
            load_started = time.perf_counter()
            raw = np.load(args.capture_dir / filename, allow_pickle=False)
            load_ms = (time.perf_counter() - load_started) * 1000
            if raw.shape != (height, width) or raw.dtype != np.uint8:
                raise ValueError(
                    f"BayerBG8画像不正（{filename}: {raw.shape}, {raw.dtype}）"
                )
            convert_ms = 0.0
            recognize_started = time.perf_counter()
            raw_value, display_text, reason, scores = recognize_display(
                raw, sample_coordinates
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
        "method": "bayer_red",
        "frames": frame_count,
        "readable": readable_count,
        "unreadable": frame_count - readable_count,
        "timing_columns": ["load_ms", "convert_ms", "recognize_ms"],
        "median_ms": np.median(timings, axis=0).tolist(),
        "p95_ms": np.percentile(timings, 95, axis=0).tolist(),
    }
    print(json.dumps(summary, allow_nan=False), file=sys.stderr)


if __name__ == "__main__":
    main()
