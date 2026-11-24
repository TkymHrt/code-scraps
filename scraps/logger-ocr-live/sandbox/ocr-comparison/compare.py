import json
import time
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

FOLDER = Path(__file__).resolve().parent
SOURCE = FOLDER / "captures/run-01"
CALIBRATION = FOLDER / "calibration.json"
OUTPUT_DIR = FOLDER / "results/run-01"

THRESHOLDS = {
    "op": {"binary": 111, "block_size": 25, "c": 0, "off_red": 30, "on_red": 70},
    "dr": {"binary": 111, "block_size": 25, "c": 0, "off_red": 30, "on_red": 70},
}
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


def prepare_samples(calibration, side):
    width, height = calibration["frame_size_px"]
    reflection = calibration["reflection"]
    if reflection not in ("none", "horizontal", "vertical", "both"):
        raise ValueError(f"reflection不正（{reflection}）")
    radius = calibration["sample_radius_px"]
    length_radius = calibration["sample_length_radius_px"]
    if length_radius is None:
        length_radius = radius
    if type(radius) is not int or radius < 0:
        raise ValueError("sample_radius_pxは0以上の整数")
    if type(length_radius) is not int or length_radius < radius:
        raise ValueError("sample_length_radius_pxはnullかsample_radius_px以上の整数")
    points = np.asarray(calibration[f"{side}_points_px"])
    if points.shape != (6, 7, 2) or not np.issubdtype(points.dtype, np.integer):
        raise ValueError(f"{side}_points_pxは6桁×7点の整数座標")

    sample_rows, sample_columns = [], []
    for index, (x, y) in enumerate(points.reshape(42, 2)):
        x_radius, y_radius = radius, length_radius
        if index % 7 in (0, 3, 6):
            x_radius, y_radius = length_radius, radius
        if reflection in ("horizontal", "both"):
            x = width - 1 - x
        if reflection in ("vertical", "both"):
            y = height - 1 - y
        if not (x_radius <= x < width - x_radius and y_radius <= y < height - y_radius):
            raise ValueError(f"{side}の読み取り範囲が画像外（セグメント{index + 1}）")
        columns, rows = np.meshgrid(
            np.arange(x - x_radius, x + x_radius + 1),
            np.arange(y - y_radius, y + y_radius + 1),
        )
        sample_rows.append(rows.ravel())
        sample_columns.append(columns.ravel())
    return np.array(sample_rows), np.array(sample_columns)


def decode_segments(scores, off_limit, on_limit):
    display = ""
    reason = "ok"
    for digit_scores in scores.reshape(6, 7):
        pattern = ""
        for score in digit_scores:
            if score >= on_limit:
                pattern += "1"
            elif score <= off_limit:
                pattern += "0"
            else:
                reason = "ambiguous"
                break
        digit = PATTERN_TO_DIGIT.get(pattern)
        if reason != "ok" or digit is None:
            reason = "ambiguous" if reason != "ok" else "invalid_pattern"
            display = None
            break
        display += digit
    raw_value = None
    if reason == "ok":
        digits = display.lstrip(" ")
        if digits.isdigit():
            raw_value = int(digits)
        else:
            reason = "invalid_display"
    return {
        "display": display,
        "raw_value": raw_value,
        "value": None if raw_value is None else raw_value / 1000,
        "reason": reason,
        "segment_scores": scores.tolist(),
    }


def read_image(path):
    encoded = np.frombuffer(path.read_bytes(), dtype=np.uint8)
    image = None
    if encoded.size:
        image = cv2.imdecode(encoded, cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
    if image is None:
        raise ValueError(f"画像を読めない（{path}）")
    return image


def main():
    if OUTPUT_DIR.exists():
        raise FileExistsError(f"比較保存先が既に存在（{OUTPUT_DIR}）")
    if not 0 <= OFF_FRACTION < ON_FRACTION <= 1:
        raise ValueError("0 <= OFF_FRACTION < ON_FRACTION <= 1")
    for side, values in THRESHOLDS.items():
        if not 0 <= values["binary"] <= 255:
            raise ValueError(f"{side}: binaryは0〜255")
        block_size = values["block_size"]
        if type(block_size) is not int or block_size < 3 or block_size % 2 == 0:
            raise ValueError(f"{side}: block_sizeは3以上の奇数")
        if not np.isfinite(values["c"]):
            raise ValueError(f"{side}: cは有限値")
        if not 0 <= values["off_red"] < values["on_red"] <= 255:
            raise ValueError(f"{side}: 0 <= off_red < on_red <= 255")

    calibration = json.loads(CALIBRATION.read_text(encoding="utf-8-sig"))
    width, height = calibration["frame_size_px"]
    coordinates = {side: prepare_samples(calibration, side) for side in ("op", "dr")}
    use_bayer = SOURCE.is_dir()
    session = None
    if use_bayer:
        session = json.loads((SOURCE / "session.json").read_text(encoding="utf-8-sig"))
        if session["pixel_format"] != "BayerBG8":
            raise ValueError("保存画像はBayerBG8が必要")
        if (
            session["reverse_x"]
            or session["reverse_y"]
            or any(n % 2 for n in session["offset"])
        ):
            raise ValueError("Bayer配列はReverseX/Y=Off、OffsetX/Y=偶数が必要")
        if session["frame_size"] != [width, height]:
            raise ValueError("撮影と校正のframe_size_pxが不一致")
        records = [
            json.loads(line)
            for line in (SOURCE / "frames.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        if not records:
            raise ValueError("frames.jsonlに画像の記録なし")
        for record in records:
            name = record["file"]
            if Path(name).name != name or not name.endswith(".npy"):
                raise ValueError(f"Bayer画像のファイル名不正（{name}）")
    else:
        records = [{"file": SOURCE.name}]

    red_coordinates = {}
    bounds = {}
    for side, (rows, columns) in coordinates.items():
        # 適応二値化の近傍が切れないよう、読み取り領域の外側も含める。
        margin = THRESHOLDS[side]["block_size"] // 2
        bounds[side] = [
            max(0, int(columns.min()) - margin),
            max(0, int(rows.min()) - margin),
            min(width, int(columns.max()) + margin + 1),
            min(height, int(rows.max()) + margin + 1),
        ]
        if use_bayer:
            selected = []
            for index, (segment_rows, segment_columns) in enumerate(
                zip(rows, columns, strict=True)
            ):
                # 反転前のBayerBG8は、奇数行・奇数列が赤画素。
                red = (segment_rows % 2 == 1) & (segment_columns % 2 == 1)
                if not np.any(red):
                    raise ValueError(f"{side}の赤画素なし（セグメント{index + 1}）")
                selected.append((segment_rows[red], segment_columns[red]))
            red_coordinates[side] = selected

    OUTPUT_DIR.mkdir(parents=True)
    settings = {
        "source": str(SOURCE.resolve()),
        "session": session,
        "calibration": calibration,
        "thresholds": THRESHOLDS,
        "off_fraction": OFF_FRACTION,
        "on_fraction": ON_FRACTION,
        "preview_bounds_px": bounds,
    }
    (OUTPUT_DIR / "settings.json").write_text(
        json.dumps(settings, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    counts = {}
    with (OUTPUT_DIR / "results.jsonl").open("x", encoding="utf-8") as output:
        for frame_index, record in enumerate(records):
            started = time.perf_counter()
            raw = None
            if use_bayer:
                raw = np.load(SOURCE / record["file"], allow_pickle=False)
                if raw.shape != (height, width) or raw.dtype != np.uint8:
                    raise ValueError(
                        f"Bayer画像の形状・型が不正（{record['file']}: {raw.shape}, {raw.dtype}）"
                    )
            else:
                image = read_image(SOURCE)
                if image.shape[:2] != (height, width):
                    raise ValueError(f"撮影と校正のframe_size_pxが不一致（{SOURCE}）")
            load_ms = (time.perf_counter() - started) * 1000
            started = time.perf_counter()
            if use_bayer:
                image = cv2.cvtColor(raw, cv2.COLOR_BayerBGGR2BGR)
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            bgr_gray_ms = (time.perf_counter() - started) * 1000

            for side, (rows, columns) in coordinates.items():
                left, top, right, bottom = bounds[side]
                crop = gray[top:bottom, left:right]
                values = THRESHOLDS[side]
                methods = (
                    ("binary", "adaptive", "bayer_red")
                    if use_bayer
                    else ("binary", "adaptive")
                )
                for method in methods:
                    started = time.perf_counter()
                    mask = None
                    if method == "bayer_red":
                        scores = np.array(
                            [np.median(raw[r, c]) for r, c in red_coordinates[side]]
                        )
                        result = decode_segments(
                            scores, values["off_red"], values["on_red"]
                        )
                    else:
                        if method == "binary":
                            _, mask = cv2.threshold(
                                crop, values["binary"], 255, cv2.THRESH_BINARY
                            )
                        else:
                            mask = cv2.adaptiveThreshold(
                                crop,
                                255,
                                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                cv2.THRESH_BINARY,
                                values["block_size"],
                                values["c"],
                            )
                        scores = np.mean(mask[rows - top, columns - left] != 0, axis=1)
                        result = decode_segments(scores, OFF_FRACTION, ON_FRACTION)
                    process_ms = (time.perf_counter() - started) * 1000
                    result.update(
                        {
                            "file": record["file"],
                            "block_id": record.get("block_id"),
                            "received_at": record.get("received_at"),
                            "timestamp_ticks": record.get("timestamp_ticks"),
                            "side": side,
                            "method": method,
                            "load_ms": load_ms,
                            "bgr_gray_ms": bgr_gray_ms,
                            "process_ms": process_ms,
                        }
                    )
                    output.write(json.dumps(result, allow_nan=False) + "\n")
                    counts.setdefault(f"{side}/{method}", Counter())[
                        result["reason"]
                    ] += 1
                    if frame_index == 0 and mask is not None:
                        encoded, png = cv2.imencode(".png", mask)
                        if not encoded:
                            raise RuntimeError(
                                f"二値化画像の保存失敗（{side}/{method}）"
                            )
                        (OUTPUT_DIR / f"{side}-{method}.png").write_bytes(png.tobytes())
            output.flush()

    summary = {"frames": len(records), "counts": counts}
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(f"比較保存: {OUTPUT_DIR}")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
