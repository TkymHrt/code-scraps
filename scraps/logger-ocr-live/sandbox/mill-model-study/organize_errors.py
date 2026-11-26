import argparse
import csv
import math
from pathlib import Path
from statistics import fmean

MODELS = {
    "fit_old_thickness_mm": "Historical stiffness",
    "fit_kb1_thickness_mm": "No width correction",
    "fit_staged_thickness_mm": "Current width correction",
}
INPUT_COLUMNS = ("source_line", "side", "width_mm", "load", "measured_thickness_mm")
POINT_COLUMNS = (
    "source_line",
    "width_mm",
    "load_tf",
    "model",
    "measured_mm",
    "predicted_mm",
    "error_mm",
)


def main():
    parser = argparse.ArgumentParser(
        description="Organize the first three thickness comparisons."
    )
    parser.add_argument(
        "points_csv", type=Path, help="points.csv from compare_mill_models.py"
    )
    parser.add_argument(
        "output_dir", type=Path, help="new directory for the two tables"
    )
    args = parser.parse_args()

    points = []
    with args.points_csv.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, strict=True)
        missing = [
            key
            for key in (*INPUT_COLUMNS, *MODELS)
            if key not in (reader.fieldnames or [])
        ]
        if missing:
            parser.error(f"{args.points_csv}: missing columns: {', '.join(missing)}")
        for row in reader:
            try:
                source_line = int(row["source_line"])
                width = float(row["width_mm"])
                load = float(row["load"])
                measured = float(row["measured_thickness_mm"])
                if row["side"] != "op" or not all(
                    map(math.isfinite, (width, load, measured))
                ):
                    raise ValueError
                if width <= 0 or measured <= 0 or load < 0:
                    raise ValueError
                for column, model in MODELS.items():
                    value = row[column].strip()
                    if value:
                        predicted = float(value)
                        error = predicted - measured
                        if not math.isfinite(error):
                            raise ValueError
                    else:
                        predicted = error = None
                    points.append(
                        (source_line, width, load, model, measured, predicted, error)
                    )
            except (ValueError, TypeError, AttributeError):
                parser.error(
                    f"{args.points_csv}:{reader.line_num}: invalid OP measurement or prediction"
                )
    if not points:
        parser.error(f"{args.points_csv}: no measurements")

    widths = sorted({point[1] for point in points})
    bands = {
        "P <= 25 tf": [point for point in points if point[2] <= 25],
        "25 < P <= 68 tf": [point for point in points if 25 < point[2] <= 68],
        "P > 68 tf": [point for point in points if point[2] > 68],
    }
    by_width = {
        f"{width:g} mm": [point for point in points if point[1] == width]
        for width in widths
    }
    common_low = max(min(point[2] for point in rows) for rows in by_width.values())
    common_high = min(max(point[2] for point in rows) for rows in by_width.values())
    groups = [
        ("overall", "All widths", points),
        *(("width", label, rows) for label, rows in by_width.items()),
        *(("load_band", label, rows) for label, rows in bands.items()),
    ]
    if common_low <= common_high:
        common = [point for point in points if common_low <= point[2] <= common_high]
        groups.append(("common_load", f"{common_low:g} to {common_high:g} tf", common))

    summary = []
    for group, label, rows in groups:
        for model in MODELS.values():
            model_rows = [point for point in rows if point[3] == model]
            errors = [point[-1] for point in model_rows if point[-1] is not None]
            bias = fmean(errors) if errors else None
            mae = fmean(map(abs, errors)) if errors else None
            maximum = max(map(abs, errors)) if errors else None
            summary.append(
                (group, label, model, len(model_rows), len(errors), bias, mae, maximum)
            )

    args.output_dir.mkdir(parents=True, exist_ok=False)
    with (args.output_dir / "errors.csv").open(
        "x", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.writer(stream)
        writer.writerow(POINT_COLUMNS)
        writer.writerows(points)
    with (args.output_dir / "summary.csv").open(
        "x", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.writer(stream)
        writer.writerow(
            (
                "group",
                "label",
                "model",
                "rows",
                "predicted_rows",
                "bias_mm",
                "mae_mm",
                "max_abs_mm",
            )
        )
        writer.writerows(summary)
    print(args.output_dir.resolve())


if __name__ == "__main__":
    main()
