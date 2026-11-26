import csv
import json
import math
import sys
import tomllib
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

MEASUREMENTS_FILE = Path("measurements.csv")
CONDITIONS_FILE = Path("conditions.toml")
OUTPUT_ROOT = Path(".")

INPUT_COLUMNS = ["side", "width_mm", "load", "gap_mm", "measured_thickness_mm"]
SIDES = ("op", "dr")
FIT_TOLERANCE = math.sqrt(np.finfo(float).eps)


def read_conditions(path, measured_sides):
    conditions = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    for key in ("roll", "zero_reference", "load_unit"):
        value = conditions.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} が不正です")
    for side in SIDES:
        if side not in conditions and side not in measured_sides:
            continue
        settings = conditions.get(side)
        if not isinstance(settings, dict):
            raise ValueError(f"[{side}] が不正です")
        for key in ("p0", "reference_width_mm"):
            value = settings.get(key)
            if (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or (key == "reference_width_mm" and value <= 0)
            ):
                raise ValueError(f"{side}.{key} が不正です")
            settings[key] = float(value)
    return conditions


def read_measurements(path):
    measurements = []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = csv.reader(stream, strict=True)
        try:
            if next(rows, None) != INPUT_COLUMNS:
                raise ValueError
            for row in rows:
                if not row:
                    continue
                values = tuple(map(float, row[1:]))
                width, _, _, thickness = values
                if (
                    row[0] not in SIDES
                    or not all(map(math.isfinite, values))
                    or width <= 0
                    or thickness <= 0
                ):
                    raise ValueError
                measurements.append((row, values))
        except (ValueError, csv.Error):
            raise ValueError(f"{rows.line_num or 1}行目が不正です") from None
    if not measurements:
        raise ValueError("測定データがありません")
    return measurements


def fit_two_columns(matrix, target):
    coefficients, _, rank, _ = np.linalg.lstsq(matrix, target, rcond=FIT_TOLERANCE)
    if rank != 2:
        raise ValueError("当てはめに必要な独立したデータが不足しています")
    if not np.all(np.isfinite(coefficients)):
        raise ValueError("係数が有限値になりません")
    return coefficients


def fit_load_curve(points, p0):
    loads, gaps, thicknesses = np.array(points).T
    load_min, load_max = float(loads.min()), float(loads.max())
    if len(points) < 2 or math.isclose(
        load_min,
        load_max,
        rel_tol=FIT_TOLERANCE,
        abs_tol=FIT_TOLERANCE * abs(p0),
    ):
        raise ValueError("荷重を変えた測定点が不足しています")
    extension = thicknesses - gaps
    scale = float(np.max(np.abs(extension)))
    if scale == 0:
        raise ValueError("実測板厚と開き量の差がすべて0です")
    scaled = extension / scale
    matrix = np.column_stack((scaled, scaled**2))
    load_difference = loads - p0
    coefficients = fit_two_columns(matrix, load_difference)
    a = float(coefficients[0]) / scale
    b = float(coefficients[1]) / scale / scale
    stiffness = a + 2 * (b * extension)
    if not math.isfinite(a) or not math.isfinite(b) or a <= 0 or np.any(stiffness <= 0):
        raise ValueError("剛性が正になりません")
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
        raise ValueError("kbが正になりません")
    square = model["c1"] ** 2 + 2 * model["c2"] * (load / kb)
    if not math.isfinite(square) or square <= 0:
        raise ValueError("荷重に対する平方根の中身または剛性が正になりません")
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
            raise ValueError(f"板幅 {width:g} mm のkbが正になりません")
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
        raise ValueError("基準幅でkbを1に正規化できません")
    # 測定幅の間でもkbが正である必要があるため、二次式の最小値を調べる。
    check_widths = [width_min, width_max]
    if c5 > 0:
        vertex = -c4 / c5 * 500
        if width_min < vertex < width_max:
            check_widths.append(vertex)
    width_factors = [width_factor(width, full_model) for width in check_widths]
    if not all(math.isfinite(kb) and kb > 0 for kb in width_factors):
        raise ValueError("板幅範囲内にkbが正にならない幅があります")
    for width, curve in by_width.items():
        kb = width_factor(width, full_model)
        for load in (p0, *curve["load_range"]):
            stiffness_at_load(load, kb, full_model)
    return full_model


def fit_side(points_by_width, settings):
    p0 = settings.get("p0")
    reference = settings.get("reference_width_mm")
    diagnostics = {"reference_width_mm": reference, "reason": None, "by_width": {}}
    result = {"p0": p0, "model": None, "fit": diagnostics}
    by_width = diagnostics["by_width"]
    if not points_by_width:
        diagnostics["reason"] = "測定データがありません"
        return result
    if reference != max(points_by_width):
        diagnostics["reason"] = (
            f"基準幅 {reference:g} mm を測定データの最大板幅に揃えてください"
        )
        return result

    try:
        base_curve = fit_load_curve(points_by_width[reference], p0)
        base_curve["kb"] = 1.0
        by_width[reference] = base_curve
        a, b = base_curve["a"], base_curve["b"]
        square = a * a - 4 * b * p0
        if not math.isfinite(square) or square <= 0:
            raise ValueError("C1の平方根の中身が正になりません")
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
        for load in [p0, *base_model["load_range"]]:
            stiffness_at_load(load, 1.0, base_model)
    except (ValueError, ArithmeticError, np.linalg.LinAlgError) as error:
        diagnostics["reason"] = f"基準幅 {reference:g} mm の当てはめに失敗 ({error})"
        return result
    result["model"] = base_model

    if len(points_by_width) < 3:
        diagnostics["reason"] = "板幅補正には基準幅を含む3種類以上の板幅が必要です"
        return result
    try:
        for width, points in sorted(points_by_width.items()):
            if width != reference:
                try:
                    by_width[width] = fit_load_curve(points, p0)
                except (ValueError, ArithmeticError, np.linalg.LinAlgError) as error:
                    raise ValueError(f"板幅 {width:g} mm ({error})") from error
        result["model"] = fit_width_model(base_model, by_width, p0)
    except (ValueError, ArithmeticError, np.linalg.LinAlgError) as error:
        diagnostics["reason"] = f"板幅補正の当てはめに失敗 ({error})"
    return result


def compare_thickness(measurements, results):
    comparison = []
    errors = {side: [] for side in SIDES}
    for row, (width, load, gap, thickness) in measurements:
        side = row[0]
        model = results[side]["model"]
        if (
            model is None
            or not model["width_range_mm"][0] <= width <= model["width_range_mm"][1]
        ):
            comparison.append([*row, "", ""])
            continue
        p0 = results[side]["p0"]
        kb = width_factor(width, model)
        try:
            stiffness = stiffness_at_load(load, kb, model)
            zero_stiffness = stiffness_at_load(p0, kb, model)
        except (ValueError, ArithmeticError):
            comparison.append([*row, "", ""])
            continue
        # Sm(P)とSm(P0)を個別に引く際の桁落ちを避ける。
        predicted = gap + ((load - p0) / kb) * (2 / (stiffness + zero_stiffness))
        error = predicted - thickness
        if not math.isfinite(predicted) or not math.isfinite(error):
            comparison.append([*row, "", ""])
            continue
        comparison.append([*row, predicted, error])
        errors[side].append(error)
    return comparison, errors


def main():
    input_path = MEASUREMENTS_FILE
    try:
        measurements = read_measurements(input_path)
        input_path = CONDITIONS_FILE
        conditions = read_conditions(input_path, {row[0] for row, _ in measurements})
    except (OSError, ValueError, OverflowError) as error:
        reason = error.strerror if isinstance(error, OSError) else error
        print(f"{input_path}: {reason}", file=sys.stderr)
        return 2

    points = {side: {} for side in SIDES}
    for row, (width, load, gap, thickness) in measurements:
        points[row[0]].setdefault(width, []).append((load, gap, thickness))
    results = {key: conditions[key] for key in ("roll", "zero_reference", "load_unit")}
    with np.errstate(over="raise", invalid="raise", divide="raise"):
        for side in SIDES:
            results[side] = fit_side(points[side], conditions.get(side, {}))
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
        print(f"保存失敗 {OUTPUT_ROOT}", file=sys.stderr)
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
