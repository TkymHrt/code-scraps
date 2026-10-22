"""計測CSVの書込・読込・数値の検証と、区間長・100mm換算。"""

import csv
import math
from pathlib import Path

from utils.file_io import check_output_path


def positive_value(value: float | str | None, name: str) -> float:
    try:
        number = float(value) if value is not None else math.nan
    except ValueError as error:
        raise ValueError(f"{name}は正の数値にしてください") from error
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name}は正の数値にしてください")
    return number


def read_lengths(path: Path) -> dict:
    required = (
        "image_path",
        "mm_per_px",
        "interval_length_mm",
        "left_mm",
        "right_mm",
        "left_excess_percent",
        "right_excess_percent",
        "evaluation_interval_mm",
        "smoothing_width_mm",
    )
    try:
        with path.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            columns = reader.fieldnames or []
            missing_columns = []
            for column in required:
                if column not in columns:
                    missing_columns.append(column)
            if missing_columns:
                missing_text = ", ".join(missing_columns)
                raise ValueError(
                    f"計測CSVの列が不足しています: {path.resolve()}\n"
                    f"不足列: {missing_text}"
                )
            saved_rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as error:
        raise ValueError(f"CSVを読み込めません: {path.name}") from error
    if len(saved_rows) != 1:
        raise ValueError(f"CSVは1行の計測データにしてください: {path.name}")
    saved = saved_rows[0]
    for column in required:
        value = saved[column]
        if value is None or not value.strip():
            raise ValueError(f"空欄を確認してください: {column}: {path.name}")
    scale = positive_value(saved["mm_per_px"], f"{path.name}: mm_per_px")
    interval_mm = positive_value(
        saved["interval_length_mm"], f"{path.name}: interval_length_mm"
    )
    evaluation_interval_mm = positive_value(
        saved["evaluation_interval_mm"], f"{path.name}: evaluation_interval_mm"
    )
    try:
        smoothing_width_mm = float(saved["smoothing_width_mm"])
    except ValueError as error:
        raise ValueError(f"平滑化幅は0以上の数値にしてください: {path.name}") from error
    if not math.isfinite(smoothing_width_mm) or smoothing_width_mm < 0:
        raise ValueError(f"平滑化幅は0以上の数値にしてください: {path.name}")
    image_path = (path.parent / saved["image_path"]).resolve()
    row = {
        "image_path": str(image_path),
        "image_name": image_path.name,
        "mm_per_px": scale,
        "interval_length_mm": interval_mm,
        "evaluation_interval_mm": evaluation_interval_mm,
        "smoothing_width_mm": smoothing_width_mm,
    }
    for edge in ("left", "right"):
        length_mm = positive_value(saved[f"{edge}_mm"], f"{path.name}: {edge}_mm")
        if length_mm < interval_mm and not math.isclose(
            length_mm, interval_mm, rel_tol=1e-10, abs_tol=1e-10
        ):
            raise ValueError(f"側辺長が区間長より短くなっています: {path.name}")
        per_100mm = length_mm / interval_mm * 100
        if not math.isfinite(per_100mm):
            raise ValueError(f"100mm換算を計算できません: {path.name}")
        row[f"{edge}_mm"] = length_mm
        row[f"{edge}_per_100mm"] = per_100mm
        excess_percent = (length_mm / interval_mm - 1) * 100
        try:
            saved_excess = float(saved[f"{edge}_excess_percent"])
        except ValueError as error:
            raise ValueError(f"超過率は数値にしてください: {path.name}") from error
        if not math.isfinite(saved_excess) or not math.isclose(
            saved_excess, excess_percent, rel_tol=1e-8, abs_tol=1e-8
        ):
            raise ValueError(f"側辺長と超過率が一致しません: {path.name}")
        row[f"{edge}_excess_percent"] = excess_percent
    return row


def write_csv(path: Path, image_path: Path, measurement: dict) -> None:
    path = check_output_path(path, ".csv", [image_path])
    row = {"image_path": str(image_path.resolve()), "image_name": image_path.name}
    row.update(measurement)
    for column, value in row.items():
        if isinstance(value, float):
            row[column] = f"{value:.12g}"
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
