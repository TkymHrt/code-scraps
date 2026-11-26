import csv
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

MEASUREMENTS_FILE = Path("measurements.csv")
OUTPUT_ROOT = Path(".")
CONDITIONS = {
    "roll": "",
    "zero_reference": "",
    "load_unit": "",
}

INPUT_COLUMNS = ["side", "width_mm", "load", "gap_mm", "measured_thickness_mm"]
CONDITION_KEYS = ("roll", "zero_reference", "load_unit")
SIDES = ("op", "dr")
FIT_TOLERANCE = math.sqrt(np.finfo(float).eps)


def validate_conditions(points_by_side):
    for key in CONDITION_KEYS:
        value = CONDITIONS.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} が不正")
    for side in SIDES:
        if side not in CONDITIONS and not points_by_side[side]:
            continue
        settings = CONDITIONS.get(side)
        if not isinstance(settings, dict):
            raise ValueError(f"{side} の条件が不正")
        for key in ("p0", "reference_width_mm"):
            value = settings.get(key)
            if (
                type(value) not in (int, float)
                or not -sys.float_info.max <= value <= sys.float_info.max
                or (key == "reference_width_mm" and value <= 0)
            ):
                raise ValueError(f"{side}.{key} が不正")


def read_measurements(path):
    measurements = []
    points_by_side = {side: {} for side in SIDES}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = csv.reader(stream, strict=True)
        try:
            if next(rows, None) != INPUT_COLUMNS:
                raise ValueError
            for row in rows:
                if not row:
                    continue
                side, *fields = row
                values = tuple(map(float, fields))
                width, load, gap, thickness = values
                if (
                    side not in SIDES
                    or not all(map(math.isfinite, values))
                    or width <= 0
                    or thickness <= 0
                ):
                    raise ValueError
                measurements.append((row, values))
                points_by_side[side].setdefault(width, []).append(
                    (load, gap, thickness)
                )
        except (ValueError, csv.Error):
            raise ValueError(f"{rows.line_num or 1}行目が不正") from None
    if not measurements:
        raise ValueError("測定データなし")
    return measurements, points_by_side


def fit_two_columns(matrix, target):
    coefficients, _, rank, _ = np.linalg.lstsq(matrix, target, rcond=FIT_TOLERANCE)
    if rank != 2:
        raise ValueError("行列の階数不足")
    if not np.all(np.isfinite(coefficients)):
        raise ValueError("係数が非有限")
    return coefficients


def fit_load_curve(points, p0):
    loads, gaps, thicknesses = np.array(points).T
    load_min, load_max = float(loads.min()), float(loads.max())
    if math.isclose(
        load_min,
        load_max,
        rel_tol=FIT_TOLERANCE,
        abs_tol=FIT_TOLERANCE * abs(p0),
    ):
        raise ValueError("荷重差不足")
    extension = thicknesses - gaps
    scale = float(np.max(np.abs(extension)))
    if scale == 0:
        raise ValueError("実測板厚と開き量の差が全点で0")
    scaled = extension / scale
    matrix = np.column_stack((scaled, scaled**2))
    load_difference = loads - p0
    coefficients = fit_two_columns(matrix, load_difference)
    a = float(coefficients[0]) / scale
    b = float(coefficients[1]) / scale / scale
    stiffness = a + 2 * (b * extension)
    if not math.isfinite(a) or not math.isfinite(b) or a <= 0 or np.any(stiffness <= 0):
        raise ValueError("剛性が不正")
    return {
        "rows": len(points),
        "load_range": [load_min, load_max],
        "a": a,
        "b": b,
        "max_abs_load_error": float(
            np.max(np.abs(matrix @ coefficients - load_difference))
        ),
    }


def width_factor(width_mm, model):
    if model["c3"] is None:
        return 1.0
    x = width_mm / 1000
    return model["c3"] + x * (model["c4"] + x * model["c5"])


def stiffness_at_load(load, kb, model):
    if not math.isfinite(kb) or kb <= 0:
        raise ValueError("kbが不正")
    square = model["c1"] ** 2 + 2 * model["c2"] * (load / kb)
    if not math.isfinite(square) or square <= 0:
        raise ValueError("剛性が非正または非有限")
    return math.sqrt(square)


def fit_width_model(model, by_width, p0):
    c1, c2 = model["c1"], model["c2"]
    reference = model["reference_width_mm"]
    d = c2 * p0
    widths, factors = [], []
    for width, curve in by_width.items():
        if width == reference:
            continue
        a = curve["a"]
        if c2 == 0:
            kb = a / c1
        else:
            root = math.hypot(d, c1 * a)
            kb = a * a / (root + d) if d >= 0 else (root - d) / (c1 * c1)
        if not math.isfinite(kb) or kb <= 0:
            raise ValueError(f"板幅 {width:g} mm のkbが不正")
        curve["kb"] = kb
        widths.append(width)
        factors.append(kb)

    x_reference = reference / 1000
    x = np.array(widths) / 1000
    difference = x - x_reference
    matrix = np.column_stack((difference, difference * (x + x_reference)))
    c4, c5 = map(float, fit_two_columns(matrix, np.array(factors) - 1))
    c3 = 1 - x_reference * (c4 + x_reference * c5)
    width_min, width_max = min(by_width), max(by_width)
    load_min = min(curve["load_range"][0] for curve in by_width.values())
    load_max = max(curve["load_range"][1] for curve in by_width.values())
    full_model = model | {
        "c3": c3,
        "c4": c4,
        "c5": c5,
        "width_range_mm": [width_min, width_max],
        "load_range": [load_min, load_max],
    }
    if not math.isclose(
        width_factor(reference, full_model), 1.0, rel_tol=FIT_TOLERANCE
    ):
        raise ValueError("基準幅のkbが1にならない")
    check_widths = [width_min, width_max]
    if c5 > 0:
        vertex = -c4 / c5 * 500
        if width_min < vertex < width_max:
            check_widths.append(vertex)
    width_factors = [width_factor(width, full_model) for width in check_widths]
    if not all(math.isfinite(kb) and kb > 0 for kb in width_factors):
        raise ValueError("測定幅範囲内でkbが不正")
    for width, curve in by_width.items():
        kb = width_factor(width, full_model)
        for load in (p0, *curve["load_range"]):
            stiffness_at_load(load, kb, full_model)
    return full_model


def fit_side(points_by_width, settings):
    p0 = float(settings["p0"]) if settings else None
    reference = float(settings["reference_width_mm"]) if settings else None
    by_width = {}
    diagnostics = {
        "reference_width_mm": reference,
        "reason": None,
        "by_width": by_width,
    }
    result = {"p0": p0, "model": None, "fit": diagnostics}
    if not points_by_width:
        diagnostics["reason"] = "測定データなし"
        return result
    if reference != max(points_by_width):
        diagnostics["reason"] = f"基準幅 {reference:g} mm が最大板幅と不一致"
        return result

    stage = f"基準幅 {reference:g} mm"
    try:
        base_curve = fit_load_curve(points_by_width[reference], p0)
        base_curve["kb"] = 1.0
        by_width[reference] = base_curve
        a, b = base_curve["a"], base_curve["b"]
        square = a * a - 4 * b * p0
        if not math.isfinite(square) or square <= 0:
            raise ValueError("C1が非正または非有限")
        base_model = {
            "c1": math.sqrt(square),
            "c2": 2 * b,
            "c3": None,
            "c4": None,
            "c5": None,
            "reference_width_mm": reference,
            "width_range_mm": [reference, reference],
            "load_range": base_curve["load_range"],
        }
        for load in (p0, *base_model["load_range"]):
            stiffness_at_load(load, 1.0, base_model)
        result["model"] = base_model

        if len(points_by_width) < 3:
            diagnostics["reason"] = "板幅補正には板幅が3種類以上必要"
            return result
        for width, points in sorted(points_by_width.items()):
            if width != reference:
                stage = f"板幅 {width:g} mm"
                by_width[width] = fit_load_curve(points, p0)
        stage = "板幅補正"
        result["model"] = fit_width_model(base_model, by_width, p0)
    except (ArithmeticError, np.linalg.LinAlgError):
        diagnostics["reason"] = f"{stage}: 数値計算失敗"
    except ValueError as error:
        diagnostics["reason"] = f"{stage}: {error}"
    return result


def compare_thickness(measurements, results):
    comparison = []
    errors = {side: [] for side in SIDES}
    for row, (width, load, gap, thickness) in measurements:
        comparison_row = [*row, "", ""]
        comparison.append(comparison_row)
        side = row[0]
        model = results[side]["model"]
        if (
            model is None
            or not model["width_range_mm"][0] <= width <= model["width_range_mm"][1]
        ):
            continue
        p0 = results[side]["p0"]
        kb = width_factor(width, model)
        try:
            stiffness = stiffness_at_load(load, kb, model)
            zero_stiffness = stiffness_at_load(p0, kb, model)
        except (ValueError, ArithmeticError):
            continue
        predicted = gap + ((load - p0) / kb) * (2 / (stiffness + zero_stiffness))
        error = predicted - thickness
        if math.isfinite(predicted) and math.isfinite(error):
            comparison_row[-2:] = predicted, error
            errors[side].append(error)
    return comparison, errors


def main():
    try:
        measurements, points_by_side = read_measurements(MEASUREMENTS_FILE)
    except OSError:
        print(f"{MEASUREMENTS_FILE}: 読込失敗", file=sys.stderr)
        return 2
    except ValueError as error:
        print(f"{MEASUREMENTS_FILE}: {error}", file=sys.stderr)
        return 2
    try:
        validate_conditions(points_by_side)
    except ValueError as error:
        print(f"CONDITIONS: {error}", file=sys.stderr)
        return 2

    results = {key: CONDITIONS[key] for key in CONDITION_KEYS}
    with np.errstate(over="raise", invalid="raise", divide="raise"):
        for side in SIDES:
            results[side] = fit_side(points_by_side[side], CONDITIONS.get(side, {}))
    comparison, errors = compare_thickness(measurements, results)

    try:
        output_root = OUTPUT_ROOT.resolve()
        output_dir = output_root / f"fit-{datetime.now():%Y%m%d-%H%M%S-%f}"
        output_root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".fit-", dir=output_root) as staging:
            staged_results = Path(staging) / output_dir.name
            staged_results.mkdir()
            with (staged_results / "comparison.csv").open(
                "w", encoding="utf-8", newline=""
            ) as stream:
                writer = csv.writer(stream)
                writer.writerow([*INPUT_COLUMNS, "predicted_thickness_mm", "error_mm"])
                writer.writerows(comparison)
            (staged_results / "coefficients.json").write_text(
                json.dumps(results, ensure_ascii=False, indent=2, allow_nan=False)
                + "\n",
                encoding="utf-8",
            )
            staged_results.rename(output_dir)
    except (OSError, ValueError):
        print(f"{OUTPUT_ROOT}: 保存失敗", file=sys.stderr)
        return 2

    for side in SIDES:
        result = results[side]
        model = result["model"]
        if model is not None:
            coefficients = [
                f"{key.upper()}={model[key]:.8g}"
                for key in ("c1", "c2", "c3", "c4", "c5")
                if model[key] is not None
            ]
            print(f"{side.upper()} {'  '.join(coefficients)}")
        if reason := result["fit"]["reason"]:
            print(f"{side.upper()} {reason}")
        side_errors = errors[side]
        print(f"{side.upper()} 評価 {len(side_errors)} 件", end="")
        if side_errors:
            average = math.fsum(error / len(side_errors) for error in side_errors)
            largest = max(map(abs, side_errors))
            print(f"  平均誤差 {average:.6g} mm  最大絶対誤差 {largest:.6g} mm", end="")
        print()
    print(f"保存先 {output_dir}")
    return int(all(results[side]["model"] is None for side in SIDES))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.exit(main())
