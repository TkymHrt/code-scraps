"""03の長さCSVと画像ごとの換算係数CSVを読み、mm換算済みのCSVを保存する."""

import csv
import math
from pathlib import Path

INPUT_CSV_PATH = "results/03_side_lengths.csv"
CALIBRATION_CSV_PATH = "results/image_calibration.csv"
OUTPUT_CSV_PATH = "results/calibrated_lengths.csv"


def calibrate_lengths(
    input_path: Path, calibration_path: Path, output_path: Path
) -> dict:
    input_path = input_path.resolve()
    calibration_path = calibration_path.resolve()
    output_path = output_path.resolve()
    if output_path.suffix.lower() != ".csv":
        raise ValueError("保存先の拡張子は .csv にしてください")
    if output_path in (input_path, calibration_path):
        raise ValueError("入力CSV・換算係数CSVと別の保存先を指定してください")

    with calibration_path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        calibration_columns = (
            "source_image_path",
            "image_path",
            "reference_mm",
            "reference_px",
            "mm_per_px",
            "reference_x1",
            "reference_y1",
            "reference_x2",
            "reference_y2",
            "image_width",
            "image_height",
        )
        if not set(calibration_columns).issubset(reader.fieldnames or []):
            raise ValueError(
                "rectify_image.pyのimage_calibration.csvを指定してください"
            )
        rows = list(reader)
    if len(rows) != 1:
        raise ValueError("換算係数CSVは1画像につき1行が必要です")
    stored = rows[0]
    calibration: dict = {}
    for column in calibration_columns:
        value = stored[column]
        if value is None or not value.strip():
            raise ValueError(f"換算係数CSVに空欄があります: {column}")
        calibration[column] = value
    for column in (
        "reference_mm",
        "reference_px",
        "mm_per_px",
        "reference_x1",
        "reference_y1",
        "reference_x2",
        "reference_y2",
    ):
        value = float(calibration[column])
        if not math.isfinite(value):
            raise ValueError("換算係数・基準点は有限値が必要です")
        calibration[column] = value
    for column in ("reference_mm", "reference_px", "mm_per_px"):
        if calibration[column] <= 0:
            raise ValueError("換算係数・基準寸法は0より大きい値が必要です")
    width, height = int(calibration["image_width"]), int(calibration["image_height"])
    if min(width, height) < 2:
        raise ValueError("画像の縦横は2画素以上が必要です")
    for number in (1, 2):
        x, y = calibration[f"reference_x{number}"], calibration[f"reference_y{number}"]
        if not (0 <= x < width and 0 <= y < height):
            raise ValueError("換算係数CSVの基準点が画像の範囲外です")
    distance_px = math.hypot(
        calibration["reference_x2"] - calibration["reference_x1"],
        calibration["reference_y2"] - calibration["reference_y1"],
    )
    scale = calibration["mm_per_px"]
    if not math.isclose(
        distance_px, calibration["reference_px"], rel_tol=1e-8, abs_tol=1e-6
    ):
        raise ValueError("基準点の距離と基準pxが一致しません")
    if not math.isclose(
        calibration["reference_mm"],
        calibration["reference_px"] * scale,
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        raise ValueError("基準寸法と換算係数が一致しません")
    source_image = Path(calibration["source_image_path"]).resolve()
    image_path = Path(calibration["image_path"]).resolve()
    if output_path in (source_image, image_path):
        raise ValueError("元画像・補正画像と別の保存先を指定してください")

    lengths = {}
    measurement_range = None
    with input_path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        length_columns = ("edge", "length_px", "start_y", "end_y")
        if not set(length_columns).issubset(reader.fieldnames or []):
            raise ValueError("補正画像を03で測った長さCSVを指定してください")
        for values in reader:
            for column in length_columns:
                if values[column] is None or not values[column].strip():
                    raise ValueError("長さCSVに空欄があります")
            edge = values["edge"]
            if edge not in ("left", "right", "total") or edge in lengths:
                raise ValueError("左・右・合計を1行ずつ指定してください")
            length = float(values["length_px"])
            start_y, end_y = int(values["start_y"]), int(values["end_y"])
            if not math.isfinite(length) or length <= 0:
                raise ValueError("長さは0より大きい有限値が必要です")
            if not 0 <= start_y < end_y < height:
                raise ValueError("CSVの計測範囲が補正画像に合いません")
            if measurement_range is not None and measurement_range != (start_y, end_y):
                raise ValueError("CSV内の計測範囲を揃えてください")
            measurement_range = (start_y, end_y)
            lengths[edge] = length
    if len(lengths) != 3 or measurement_range is None:
        raise ValueError("左・右・合計の3行が必要です")
    # 03は丸める前に合計するため、左右の和と最大0.01pxずれる。
    if abs(lengths["left"] + lengths["right"] - lengths["total"]) > 0.011:
        raise ValueError("左右の長さと合計が一致しません")
    row = {"input_csv": str(input_path)}
    row.update(calibration)
    row["source_image_path"] = str(source_image)
    row["image_path"] = str(image_path)
    row["image_width"], row["image_height"] = width, height
    row["start_y"], row["end_y"] = measurement_range
    for edge in ("left", "right", "total"):
        measured_mm = lengths[edge] * scale
        if not math.isfinite(measured_mm) or measured_mm <= 0:
            raise ValueError("換算した長さは0より大きい有限値が必要です")
        row[f"{edge}_px"] = lengths[edge]
        row[f"{edge}_mm"] = measured_mm
    saved = row.copy()
    for column, value in row.items():
        if isinstance(value, float):
            saved[column] = f"{value:.12g}"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(saved)
    return row


def main() -> None:
    directory = Path(__file__).resolve().parent
    row = calibrate_lengths(
        directory / INPUT_CSV_PATH,
        directory / CALIBRATION_CSV_PATH,
        directory / OUTPUT_CSV_PATH,
    )
    for edge in ("left", "right", "total"):
        print(f"{edge}: {row[f'{edge}_mm']:.3f}mm")
    print(f"校正済みCSV: {(directory / OUTPUT_CSV_PATH).resolve()}")


if __name__ == "__main__":
    main()
