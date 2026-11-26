import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import least_squares

HERE = Path(__file__).resolve().parent
HISTORICAL = HERE / "historical.csv"
sys.path.insert(0, str(HERE.parents[1] / "src"))
import fit_mill_model as legacy  # noqa: E402

OLD_STIFFNESS = {178: 133, 302: 139, 393: 141, 557: 164}
INPUT = [
    "width_mm",
    "gap_mm",
    "reported_extension_mm",
    "reported_sum_load_t",
    "measured_thickness_mm",
]
MODEL_LABELS = {
    "gap": "Gap only",
    "old": "Historical stiffness",
    "old_printed": "Historical printed quadratic",
    "old_refit": "Historical refitted quadratic",
    "spring": "Constant stiffness",
    "linear_width": "Linear compliance",
    "empirical": "Empirical load quadratic",
    "kb1": "Reference curve, kb = 1",
    "old_ratio": "Reference curve, historical ratio",
    "staged": "Current staged fit",
    "joint_linear": "Joint thickness fit, linear width",
    "joint_quadratic": "Joint thickness fit, quadratic width",
    "joint_robust": "Robust thickness fit, linear width",
}
PLOT_MODELS = ("staged", "kb1", "joint_linear", "joint_robust")
COLORS = dict(
    zip(PLOT_MODELS, ("#bd382b", "#2665a3", "#09785d", "#8254a3"), strict=True)
)
HISTORICAL_MODELS = {"old", "old_printed", "old_refit", "old_ratio"}
ROBUST_SCALE_MM = 0.05


def read_points(path):
    points, excluded = [], []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, strict=True)
        if reader.fieldnames != INPUT:
            raise ValueError(f"{path}: expected columns {','.join(INPUT)}")
        for row in reader:
            line = reader.line_num
            try:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError
                width = float(row["width_mm"])
                gap = float(row["gap_mm"])
                recorded = row["reported_extension_mm"].strip()
                sum_load = row["reported_sum_load_t"].strip()
                thickness = row["measured_thickness_mm"].strip()
                values = [
                    width,
                    gap,
                    *map(float, filter(None, (recorded, sum_load, thickness))),
                ]
                if not all(map(math.isfinite, values)) or width <= 0:
                    raise ValueError
                if (sum_load and float(sum_load) < 0) or (
                    thickness and float(thickness) <= 0
                ):
                    raise ValueError
            except ValueError:
                raise ValueError(f"{path}:{line}: invalid measurement") from None
            if not sum_load or not thickness:
                missing = [key for key in INPUT[-2:] if not row[key].strip()]
                excluded.append(
                    [line, *(row[key] for key in INPUT), ", ".join(missing)]
                )
                continue
            points.append(
                [
                    line,
                    width,
                    float(sum_load) / 2,
                    gap,
                    float(thickness),
                    float(recorded) if recorded else np.nan,
                ]
            )
    data = np.array(points, dtype=float)
    if len(points) == 0 or len(np.unique(data[:, 1])) < 3:
        raise ValueError("at least three widths with usable measurements are required")
    return data, excluded


def predict_curve(load, kb, c1, c2, p0):
    with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
        s = np.sqrt(c1**2 + 2 * c2 * load / kb)
        s0 = np.sqrt(c1**2 + 2 * c2 * p0 / kb)
        return np.where(
            (kb > 0) & (s > 0) & (s0 > 0), 2 * (load - p0) / kb / (s + s0), np.nan
        )


def fit_predictions(data, train, p0, historical):
    _, width, load, gap, thickness, _ = data.T
    extension = thickness - gap
    pred = {"gap": gap}
    params = {}
    if historical:
        stiffness = np.array([OLD_STIFFNESS[w] for w in width])
        printed = [0.0002, -0.0785, 140.84]
        refit = np.polyfit(list(OLD_STIFFNESS), list(OLD_STIFFNESS.values()), 2)
        pred["old"] = gap + 2 * (load - p0) / stiffness
        pred["old_printed"] = gap + 2 * (load - p0) / np.polyval(printed, width)
        pred["old_refit"] = gap + 2 * (load - p0) / np.polyval(refit, width)
        params["old_refit_coefficients"] = refit.tolist()

    groups = defaultdict(list)
    for w, p, s, h in data[train, 1:5]:
        groups[w].append((p, s, h))
    if not groups:
        return pred, params

    reference = max(groups)
    current = legacy.fit_side(groups, {"p0": p0, "reference_width_mm": reference})
    params["staged"] = current
    if model := current["model"]:
        c1, c2 = model["c1"], model["c2"]
        pred["kb1"] = gap + predict_curve(load, 1, c1, c2, p0)
        if model["c3"] is not None:
            kb = legacy.width_factor(width, model)
            pred["staged"] = gap + predict_curve(load, kb, c1, c2, p0)
        else:
            pred["staged"] = np.where(width == reference, pred["kb1"], np.nan)
        if historical:
            pred["old_ratio"] = gap + predict_curve(
                load, stiffness / OLD_STIFFNESS[reference], c1, c2, p0
            )

    q = load - p0
    x = (width - max(width)) / 1000
    design = np.column_stack((q, q * x, q**2 / 100))
    for name, cols in (("spring", 1), ("linear_width", 2), ("empirical", 3)):
        matrix = design[:, :cols]
        coef, _, rank, _ = np.linalg.lstsq(matrix[train], extension[train], rcond=None)
        if rank == cols:
            pred[name] = gap + matrix @ coef
            params[name] = coef.tolist()

    z = (width - min(width)) / np.ptp(width)
    for name, basis, loss in (
        ("joint_linear", np.column_stack((1 - z, z)), "linear"),
        (
            "joint_quadratic",
            np.column_stack(((1 - z) ** 2, 2 * z * (1 - z), z**2)),
            "linear",
        ),
        ("joint_robust", np.column_stack((1 - z, z)), "soft_l1"),
    ):
        degree = basis.shape[1] - 1
        if len(groups) < degree + 1 or train.sum() < degree + 2:
            continue

        def predicted_extension(values, basis=basis):
            kb = basis @ np.r_[values[2:], 1.0]
            return predict_curve(load, kb, values[0], values[1], p0)

        result = least_squares(
            lambda values: (predicted_extension(values) - extension)[train],
            [50, 30, *([1] * degree)],
            bounds=([1e-5, 0, *([1e-5] * degree)], np.inf),
            x_scale="jac",
            loss=loss,
            f_scale=ROBUST_SCALE_MM,
        )
        if not result.success or np.linalg.matrix_rank(result.jac) < degree + 2:
            params[name] = {
                "reason": result.message if not result.success else "rank deficient"
            }
            continue
        pred[name] = gap + predicted_extension(result.x)
        weights = np.r_[result.x[2:], 1.0]
        kb_by_z = [weights[0], 1 - weights[0], 0]
        if degree == 2:
            kb_by_z = [
                weights[0],
                2 * (weights[1] - weights[0]),
                1 - 2 * weights[1] + weights[0],
            ]
        z_by_x = np.polynomial.Polynomial(
            [-min(width) / np.ptp(width), 1000 / np.ptp(width)]
        )
        polynomial = np.polynomial.Polynomial(kb_by_z)(z_by_x).coef
        c3, c4, c5 = np.pad(polynomial, (0, 3 - len(polynomial)))
        np.testing.assert_allclose(
            legacy.width_factor(width, {"c3": c3, "c4": c4, "c5": c5}), basis @ weights
        )
        params[name] = {
            "c1": result.x[0],
            "c2": result.x[1],
            "c3": c3,
            "c4": c4,
            "c5": c5,
            "reference_width_mm": max(width),
        }
    return pred, params


def metric_rows(evaluation, predictions, thickness, subsets):
    for subset, mask in subsets:
        for name in MODEL_LABELS:
            if name not in predictions:
                continue
            error = (predictions[name] - thickness)[mask]
            error = error[np.isfinite(error)]
            metrics = (
                (
                    float(error.mean()),
                    float(np.abs(error).mean()),
                    float(np.sqrt((error**2).mean())),
                    float(np.abs(error).max()),
                    int(np.count_nonzero(np.abs(error) <= 0.1 + 1e-10)),
                )
                if len(error)
                else ("", "", "", "", 0)
            )
            yield [evaluation, subset, name, int(mask.sum()), len(error), *metrics]


def validate(data, cases, p0, historical, model_names):
    predictions = {name: np.full(len(data), np.nan) for name in model_names}
    diagnostics = []
    for label, test, train in cases:
        assert not np.any(test & train) and np.any(test), label
        pred, params = fit_predictions(data, train, p0, historical)
        for name, values in pred.items():
            if name in predictions:
                predictions[name][test] = values[test]
        diagnostics.append(
            {
                "fold": label,
                "test_source_lines": data[test, 0].astype(int).tolist(),
                "train_source_lines": data[train, 0].astype(int).tolist(),
                "staged_reason": params.get("staged", {}).get("fit", {}).get("reason"),
                "predicted": {
                    name: int(np.isfinite(values[test]).sum())
                    for name, values in predictions.items()
                },
            }
        )
    return predictions, diagnostics


def write_csv(path, header, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)


def save_plots(folder, data, predictions, scores, p0):
    _, width, load, gap, thickness, _ = data.T
    widths = np.unique(width)
    plt.rcParams.update(
        {"font.size": 10, "axes.spines.top": False, "axes.spines.right": False}
    )
    for filename, heading, ylabel in (
        ("residuals.png", "Thickness error by width", "Prediction − measured (mm)"),
        ("extension.png", "Measured and fitted mill extension", "Thickness − gap (mm)"),
    ):
        fig, axes = plt.subplots(
            math.ceil(len(widths) / 2),
            2,
            figsize=(10, 3.4 * math.ceil(len(widths) / 2)),
            sharex=True,
            sharey=True,
            layout="constrained",
        )
        for w, axis in zip(widths, list(axes.flat)[: len(widths)], strict=True):
            rows = np.flatnonzero(width == w)
            rows = rows[np.argsort(load[rows])]
            axis.set_title(f"{w:g} mm  ·  n={len(rows)}")
            if filename == "residuals.png":
                axis.axhline(0, color="#808080", linewidth=0.9, linestyle="--")
            else:
                axis.scatter(
                    load[rows],
                    (thickness - gap)[rows],
                    marker="x",
                    color="#252525",
                    label="Measured",
                )
            for name, marker in zip(
                (*PLOT_MODELS, "old"), ("o", "D", "^", "s", "x"), strict=True
            ):
                if name not in predictions:
                    continue
                measured = thickness if filename == "residuals.png" else gap
                axis.plot(
                    load[rows],
                    (predictions[name] - measured)[rows],
                    color=COLORS.get(name, "#6c6c6c"),
                    marker=marker,
                    markersize=3.5,
                    linewidth=1.1,
                    label=MODEL_LABELS[name],
                )
            axis.grid(alpha=0.2)
        for axis in list(axes.flat)[len(widths) :]:
            axis.set_visible(False)
        handles, labels = axes.flat[0].get_legend_handles_labels()
        fig.get_layout_engine().set(rect=(0, 0.12, 1, 0.88))
        fig.legend(
            handles,
            labels,
            loc="lower center",
            bbox_to_anchor=(0.5, 0.01),
            ncols=min(3, len(labels)),
            frameon=False,
        )
        fig.suptitle(f"{heading}  |  OP zero load {p0:g} tf")
        fig.supxlabel("OP load (tf)", y=0.083)
        fig.supylabel(ylabel)
        fig.savefig(folder / filename, dpi=220)
        plt.close(fig)

    evaluations = ("fit", "point", "width", "load_band", "outside_common")
    fig, axis = plt.subplots(figsize=(10, 4.8), layout="constrained")
    lookup = {
        (case, model): (total, n, mae)
        for case, subset, model, total, n, _, mae, *_ in scores
        if subset == "all"
    }
    indexes = np.arange(len(evaluations), dtype=float)
    for i, name in enumerate(PLOT_MODELS):
        heights, counts = [], []
        for case in evaluations:
            total, n, mae = lookup.get((case, name), (0, 0, ""))
            heights.append(mae if n and n == total else np.nan)
            counts.append(f"{n}/{total}" if total and n != total else "")
        positions = indexes + (i - 1.5) * 0.18
        axis.bar(
            positions, heights, width=0.16, color=COLORS[name], label=MODEL_LABELS[name]
        )
        for position, count in zip(positions, counts, strict=True):
            if count:
                axis.text(
                    position,
                    0,
                    count,
                    color=COLORS[name],
                    rotation=90,
                    va="bottom",
                    ha="center",
                    fontsize=8,
                )
    axis.set_xticks(
        indexes,
        (
            "All rows",
            "Hold out\none row",
            "Hold out\none width",
            "Hold out\none load band",
            "Train only in\ncommon load range",
        ),
    )
    axis.set_ylabel("Mean absolute thickness error (mm)")
    axis.set_title("Prediction error after refitting")
    axis.set_xlabel("Fractions show prediction coverage when a bar is unavailable.")
    fig.get_layout_engine().set(rect=(0, 0.16, 1, 0.84))
    fig.legend(loc="lower center", bbox_to_anchor=(0.5, 0.01), ncols=2, frameon=False)
    axis.grid(axis="y", alpha=0.2)
    fig.savefig(folder / "validation.png", dpi=220)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(
        description="Compare mill models on historical-format OP measurements."
    )
    parser.add_argument("--input", type=Path, default=HISTORICAL)
    parser.add_argument("--output", type=Path, default=HERE / "results")
    parser.add_argument(
        "--p0", type=float, default=5, help="OP zero adjustment load in tf"
    )
    parser.add_argument(
        "--load-breaks", type=float, nargs=2, default=(25, 68), metavar=("LOW", "HIGH")
    )
    args = parser.parse_args()
    low, high = args.load_breaks
    if not all(map(math.isfinite, (args.p0, low, high))) or not (
        0 <= args.p0 and 0 < low < high
    ):
        parser.error("requires finite P0 >= 0 and 0 < LOW < HIGH")
    try:
        data, excluded = read_points(args.input)
    except (ValueError, OSError, csv.Error) as error:
        parser.error(str(error))
    historical = args.input.resolve() == HISTORICAL.resolve()
    lines, width, load, gap, thickness, recorded = data.T
    widths = np.unique(width)
    whole = np.ones(len(data), dtype=bool)
    bands = [
        (f"P<={low:g}", load <= low),
        (f"{low:g}<P<={high:g}", (load > low) & (load <= high)),
        (f"P>{high:g}", load > high),
    ]
    common_low = max(load[width == w].min() for w in widths)
    common_high = min(load[width == w].max() for w in widths)
    common = (load >= common_low) & (load <= common_high)
    by_width = [(f"{w:g} mm", width == w) for w in widths]
    subsets = [
        ("all", whole),
        *by_width,
        *bands,
        ("common_load", common),
        *((label + " common_load", mask & common) for label, mask in by_width),
    ]
    predictions, parameters = fit_predictions(data, whole, args.p0, historical)
    validation_models = [name for name in MODEL_LABELS if name not in HISTORICAL_MODELS]
    for name in validation_models:
        predictions.setdefault(name, np.full(len(data), np.nan))
    if parameters["staged"]["model"]:
        measurements = [(["op"], tuple(row)) for row in data[:, 1:5]]
        reference_rows, _ = legacy.compare_thickness(
            measurements, {"op": parameters["staged"]}
        )
        expected = [row[-2] if row[-2] != "" else np.nan for row in reference_rows]
        np.testing.assert_allclose(
            predictions["staged"], expected, equal_nan=True, atol=1e-12
        )
    scores = list(metric_rows("fit", predictions, thickness, subsets))
    evaluations = {
        "point": [(f"line {line:g}", lines == line, lines != line) for line in lines],
        "width": [(label, mask, ~mask) for label, mask in by_width],
        "load_band": [(label, mask, ~mask) for label, mask in bands if mask.any()],
    }
    if common.any() and not common.all():
        evaluations["outside_common"] = [("outside common load range", ~common, common)]
    all_predictions = {"fit": predictions}
    folds = {}
    for name, cases in evaluations.items():
        pred, folds[name] = validate(
            data,
            cases,
            args.p0,
            historical,
            validation_models,
        )
        all_predictions[name] = pred
        evaluated = np.logical_or.reduce([test for _, test, _ in cases])
        scores.extend(
            metric_rows(
                name,
                pred,
                thickness,
                [(label, mask & evaluated) for label, mask in subsets],
            )
        )

    sensitivity, sensitivity_parameters = [], {}
    for p0 in sorted({0, 3, 5, 7, 10, args.p0}):
        pred, sensitivity_parameters[f"P0={p0:g}"] = fit_predictions(
            data, whole, p0, historical
        )
        sensitivity.extend(metric_rows(f"P0={p0:g}", pred, thickness, [("all", whole)]))
    if historical:
        flagged = (width == 557) & np.isclose(load, 31.8)
        if flagged.any() and (~flagged).any():
            pred, sensitivity_parameters["without flagged point"] = fit_predictions(
                data, ~flagged, args.p0, historical
            )
            for label, values, mask in (
                ("full fit on remaining points", predictions, ~flagged),
                ("refit on remaining points", pred, ~flagged),
                ("refit tested on flagged point", pred, flagged),
            ):
                sensitivity.extend(
                    metric_rows(label, values, thickness, [("all", mask)])
                )

    result_dir = args.output.resolve() / f"study-{datetime.now():%Y%m%d-%H%M%S-%f}"
    args.output.mkdir(parents=True, exist_ok=True)
    metric_header = [
        "evaluation",
        "subset",
        "model",
        "rows",
        "predicted_rows",
        "bias_mm",
        "mae_mm",
        "rmse_mm",
        "max_abs_mm",
        "within_0.10_mm",
    ]
    with TemporaryDirectory(prefix=".study-", dir=args.output) as staging:
        folder = Path(staging) / result_dir.name
        folder.mkdir()
        write_csv(
            folder / "measurements.csv",
            legacy.INPUT_COLUMNS,
            (("op", *row) for row in data[:, 1:5]),
        )
        write_csv(folder / "excluded.csv", ["source_line", *INPUT, "missing"], excluded)
        columns = [
            (evaluation, model, pred[model])
            for evaluation, pred in all_predictions.items()
            for model in MODEL_LABELS
            if model in pred
        ]
        write_csv(
            folder / "points.csv",
            [
                "source_line",
                *legacy.INPUT_COLUMNS,
                "extension_mm",
                "reported_extension_mm",
                *(
                    f"fit_{model}_thickness_mm"
                    for model in MODEL_LABELS
                    if model in predictions
                ),
                *(f"{case}_{model}_error_mm" for case, model, _ in columns),
            ],
            (
                [
                    int(lines[i]),
                    "op",
                    *data[i, 1:5],
                    thickness[i] - gap[i],
                    recorded[i] if np.isfinite(recorded[i]) else "",
                    *(
                        predictions[model][i]
                        if np.isfinite(predictions[model][i])
                        else ""
                        for model in MODEL_LABELS
                        if model in predictions
                    ),
                    *(
                        values[i] - thickness[i] if np.isfinite(values[i]) else ""
                        for _, _, values in columns
                    ),
                ]
                for i in range(len(data))
            ),
        )
        write_csv(folder / "metrics.csv", metric_header, scores)
        write_csv(folder / "sensitivity.csv", metric_header, sensitivity)
        (folder / "models.json").write_text(
            json.dumps(
                {
                    "input": str(args.input),
                    "p0_tf": args.p0,
                    "side": "op",
                    "reference_width_mm": max(widths),
                    "common_load_tf": [common_low, common_high]
                    if common_low <= common_high
                    else None,
                    "load_breaks_tf": [low, high],
                    "historical_comparators": historical,
                    "model_labels": MODEL_LABELS,
                    "versions": {
                        name: version(name) for name in ("numpy", "scipy", "matplotlib")
                    },
                    "parameters": parameters,
                    "sensitivity_parameters": sensitivity_parameters,
                    "folds": folds,
                },
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
        save_plots(folder, data, predictions, scores, args.p0)
        folder.rename(result_dir)

    print(f"OP: {len(data)} included, {len(excluded)} excluded")
    if reason := parameters["staged"]["fit"]["reason"]:
        print(f"Current staged fit: {reason}")
    for case, subset, model, total, n, _, mae, *_ in scores:
        if subset == "all" and model in PLOT_MODELS:
            print(
                f"{case:15s} {model:13s}  {n:2}/{total:<2}  {f'{mae:.3f} mm' if n else 'unavailable'}"
            )
    print(result_dir)


if __name__ == "__main__":
    main()
