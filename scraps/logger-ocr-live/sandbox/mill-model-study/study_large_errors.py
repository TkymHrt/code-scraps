from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from compare_mill_models import (
    COLORS,
    METRIC_HEADER,
    MODEL_LABELS,
    fit_predictions,
    metric_rows,
    read_points,
    write_csv,
)
from matplotlib.lines import Line2D

HERE = Path(__file__).resolve().parent
INPUT_CSV = HERE / "historical.csv"
OUTPUT_ROOT = HERE / "results"
P0_TF = 5
REMOVE_COUNTS = (1, 2, 3)
# CSVのヘッダーを1行目とする。別の入力に替えた場合は対象行も見直す。
MANUAL_LINES = (30,)
PLOT_CASE = None

MODELS = ("staged", "kb1", "joint_linear", "joint_robust")
RANK_MODELS = ("staged", "joint_robust")


def largest_errors(predicted, measured, eligible, count):
    indexes = np.flatnonzero(eligible)
    errors = np.abs(predicted[indexes] - measured[indexes])
    if len(errors) <= count or not np.isfinite(errors).all():
        return None
    return indexes[np.argsort(-errors, kind="stable")[:count]]


def save_refit_plots(folder, case, widths, loads, measured, kept, before, after):
    unique_widths = np.unique(widths)
    rows = (len(unique_widths) + 1) // 2
    fig, axes = plt.subplots(
        rows,
        2,
        figsize=(10, 3 * rows + 0.6),
        sharex=True,
        sharey=True,
        layout="constrained",
    )
    for width, axis in zip(
        unique_widths, list(axes.flat)[: len(unique_widths)], strict=True
    ):
        kept_at_width = (widths == width) & kept
        removed_at_width = (widths == width) & ~kept
        for name in MODELS:
            errors = after[name] - measured
            axis.scatter(
                loads[kept_at_width],
                errors[kept_at_width],
                color=COLORS[name],
                s=22,
                label=MODEL_LABELS[name],
            )
            axis.scatter(
                loads[removed_at_width],
                errors[removed_at_width],
                facecolors="none",
                edgecolors=COLORS[name],
                s=65,
            )
        axis.axhline(0, color="#888888", linestyle="--", linewidth=0.8)
        axis.set_title(f"{width:g} mm")
        axis.grid(alpha=0.2)
    for axis in list(axes.flat)[len(unique_widths) :]:
        axis.set_visible(False)
    handles, labels = axes.flat[0].get_legend_handles_labels()
    handles.append(
        Line2D(
            [],
            [],
            marker="o",
            color="#333333",
            markerfacecolor="none",
            linestyle="none",
        )
    )
    labels.append("Excluded from fit")
    fig.get_layout_engine().set(rect=(0, 0.14, 1, 0.86))
    fig.legend(
        handles,
        labels,
        loc="lower center",
        bbox_to_anchor=(0.5, 0.01),
        ncols=3,
        frameon=False,
    )
    fig.suptitle(f"Thickness errors after refit · {case}")
    fig.supxlabel("OP load (tf)", y=0.10)
    fig.supylabel("Predicted − measured thickness (mm)")
    fig.savefig(folder / "error_by_load.png", dpi=220)
    plt.close(fig)

    subsets = [
        ("All points", np.ones(len(kept), dtype=bool)),
        ("Kept", kept),
        ("Excluded", ~kept),
        *((f"{width:g} mm", kept & (widths == width)) for width in unique_widths),
    ]
    subsets = [(label, mask) for label, mask in subsets if mask.any()]
    scores = {
        (phase, label, name): (total, n, mae)
        for phase, predictions in (("Before", before), ("After", after))
        for _, label, name, total, n, _, mae, *_ in metric_rows(
            phase, predictions, measured, subsets
        )
    }
    fig, axes = plt.subplots(2, 2, figsize=(10, 6.5), sharey=True, layout="constrained")
    positions = np.arange(len(subsets))
    for axis, name in zip(axes.flat, MODELS, strict=True):
        for phase, offset, color in (
            ("Before", -0.18, "#a5aab3"),
            ("After", 0.18, COLORS[name]),
        ):
            rows = [scores[phase, label, name] for label, _ in subsets]
            axis.bar(
                positions + offset,
                [mae if n == total else np.nan for total, n, mae in rows],
                width=0.34,
                color=color,
                label=phase,
            )
            for position, (total, n, _) in zip(positions + offset, rows, strict=True):
                if n != total:
                    axis.text(
                        position,
                        0,
                        f"{n}/{total}",
                        rotation=90,
                        ha="center",
                        va="bottom",
                        fontsize=8,
                    )
        axis.set_xticks(
            positions, [label for label, _ in subsets], rotation=25, ha="right"
        )
        axis.set_title(MODEL_LABELS[name])
        axis.grid(axis="y", alpha=0.2)
        axis.legend(frameon=False)
    fig.suptitle(f"Thickness MAE before and after refit · {case}")
    fig.supylabel("Mean absolute error (mm)")
    fig.supxlabel(
        "Width groups use kept points only. Fractions show incomplete prediction coverage.",
        fontsize=9,
    )
    fig.savefig(folder / "mae_by_width.png", dpi=220)
    plt.close(fig)


def main():
    data, _ = read_points(INPUT_CSV)
    lines = data[:, 0].astype(int)
    widths, loads, measured = data[:, 1], data[:, 2], data[:, 4]
    if not np.isfinite(P0_TF) or P0_TF < 0:
        raise ValueError("P0_TF must be finite and nonnegative")
    if (
        not REMOVE_COUNTS
        or any(type(count) is not int for count in REMOVE_COUNTS)
        or tuple(sorted(set(REMOVE_COUNTS))) != REMOVE_COUNTS
        or not (0 < min(REMOVE_COUNTS) <= max(REMOVE_COUNTS) < len(data) - 1)
    ):
        raise ValueError(
            "REMOVE_COUNTS must contain distinct ascending positive counts"
        )
    missing = set(MANUAL_LINES) - set(lines)
    if missing:
        raise ValueError(
            f"MANUAL_LINES contains unusable source lines: {sorted(missing)}"
        )

    all_points = np.ones(len(data), dtype=bool)
    unavailable = np.full(len(data), np.nan)
    scenarios = [
        (f"{rank_model}_top{count}", rank_model, count)
        for rank_model in RANK_MODELS
        for count in REMOVE_COUNTS
    ]
    original, _ = fit_predictions(data, all_points, P0_TF, historical=False)
    models_before = {name: original.get(name, unavailable) for name in MODELS}
    full_cases = [
        (
            case,
            largest_errors(
                original.get(rank_model, unavailable), measured, all_points, count
            ),
        )
        for case, rank_model, count in scenarios
    ]
    if MANUAL_LINES:
        full_cases.insert(0, ("manual", np.flatnonzero(np.isin(lines, MANUAL_LINES))))
    plot_count = 2 if 2 in REMOVE_COUNTS else REMOVE_COUNTS[0]
    plot_case = PLOT_CASE if PLOT_CASE is not None else f"joint_robust_top{plot_count}"
    case_names = [case for case, _ in full_cases]
    if plot_case not in case_names:
        raise ValueError(f"PLOT_CASE must be one of {', '.join(case_names)}")

    sensitivity = list(
        metric_rows("baseline", models_before, measured, [("all", all_points)])
    )
    removed_points, coefficients = [], []
    skipped = []
    plot_data = None
    for case, removed in full_cases:
        if removed is None:
            skipped.append([case, "", "ranking model cannot predict every candidate"])
            continue
        kept = all_points.copy()
        kept[removed] = False
        if not kept.any():
            raise ValueError(f"{case}: no points left to fit")
        predictions, parameters = fit_predictions(data, kept, P0_TF, historical=False)
        if reason := parameters["staged"]["fit"]["reason"]:
            skipped.append([case, "", reason])
        models_after = {name: predictions.get(name, unavailable) for name in MODELS}
        if case == plot_case:
            plot_data = kept, models_after
        subsets = [("all", all_points), ("kept", kept), ("removed", ~kept)]
        sensitivity.extend(
            metric_rows(f"{case}_before", models_before, measured, subsets)
        )
        sensitivity.extend(
            metric_rows(f"{case}_after", models_after, measured, subsets)
        )
        for index in removed:
            removed_points.append(
                [
                    case,
                    lines[index],
                    widths[index],
                    loads[index],
                    measured[index],
                    *(models_before[name][index] - measured[index] for name in MODELS),
                ]
            )
        for name in ("staged", "joint_linear", "joint_robust"):
            model = parameters.get(name, {})
            if name == "staged":
                model = model["model"] or {}
            coefficients.append(
                [
                    case,
                    name,
                    *(model.get(key, "") for key in ("c1", "c2", "c3", "c4", "c5")),
                ]
            )

    held_out = {
        case: {name: np.full(len(data), np.nan) for name in MODELS}
        for case in ("baseline", *(case for case, _, _ in scenarios))
    }
    splits = []
    for test in range(len(data)):
        training = all_points.copy()
        training[test] = False
        initial, _ = fit_predictions(data, training, P0_TF, historical=False)
        for name in MODELS:
            held_out["baseline"][name][test] = initial.get(name, unavailable)[test]
        for case, rank_model, count in scenarios:
            removed = largest_errors(
                initial.get(rank_model, unavailable), measured, training, count
            )
            if removed is None:
                skipped.append(
                    [
                        case,
                        lines[test],
                        "ranking model cannot predict every training point",
                    ]
                )
                continue
            kept = training.copy()
            kept[removed] = False
            assert (
                test not in removed
                and not kept[test]
                and kept.sum() == len(data) - 1 - count
            )
            predictions, parameters = fit_predictions(
                data, kept, P0_TF, historical=False
            )
            if reason := parameters["staged"]["fit"]["reason"]:
                skipped.append([case, lines[test], reason])
            splits.append([case, lines[test], " ".join(map(str, lines[removed]))])
            for name in MODELS:
                held_out[case][name][test] = predictions.get(name, unavailable)[test]

    subsets = [
        ("all", all_points),
        *((f"{w:g} mm", widths == w) for w in np.unique(widths)),
    ]
    validation = [
        row
        for case, predictions in held_out.items()
        for row in metric_rows(case, predictions, measured, subsets)
    ]

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    result_name = f"large-errors-{datetime.now():%Y%m%d-%H%M%S-%f}"
    result_dir = OUTPUT_ROOT.resolve() / result_name
    with TemporaryDirectory(prefix=".large-errors-", dir=OUTPUT_ROOT) as staging:
        folder = Path(staging) / result_name
        folder.mkdir()
        write_csv(folder / "refit_metrics.csv", METRIC_HEADER, sensitivity)
        write_csv(
            folder / "removed_points.csv",
            (
                "case",
                "source_line",
                "width_mm",
                "load_tf",
                "measured_mm",
                *(f"{name}_error_before_mm" for name in MODELS),
            ),
            removed_points,
        )
        write_csv(
            folder / "refit_coefficients.csv",
            ("case", "model", "c1", "c2", "c3", "c4", "c5"),
            coefficients,
        )
        write_csv(folder / "loo_metrics.csv", METRIC_HEADER, validation)
        write_csv(
            folder / "loo_splits.csv", ("case", "test_line", "removed_lines"), splits
        )
        write_csv(folder / "fit_notes.csv", ("case", "test_line", "reason"), skipped)

        score = {(row[0], row[2]): row for row in validation if row[1] == "all"}
        fig, axes = plt.subplots(
            1, len(RANK_MODELS), figsize=(10, 4.2), sharey=True, layout="constrained"
        )
        counts = (0, *REMOVE_COUNTS)
        for axis, rank_model in zip(axes, RANK_MODELS, strict=True):
            cases = ("baseline", *(f"{rank_model}_top{n}" for n in REMOVE_COUNTS))
            for name in MODELS:
                rows = [score[case, name] for case in cases]
                maes = [row[6] if row[3] == row[4] else np.nan for row in rows]
                axis.plot(
                    counts,
                    maes,
                    color=COLORS[name],
                    marker="o",
                    label=MODEL_LABELS[name],
                )
            axis.set_title(
                "Ranked by current staged fit errors"
                if rank_model == "staged"
                else "Ranked by robust fit errors"
            )
            axis.set_xticks(counts)
            axis.set_xlabel("Training points removed")
            axis.grid(alpha=0.2)
        axes[0].set_ylabel("Held-out thickness MAE (mm)")
        handles, labels = axes[0].get_legend_handles_labels()
        fig.get_layout_engine().set(rect=(0, 0.17, 1, 0.83))
        fig.legend(handles, labels, loc="lower center", ncols=2, frameon=False)
        fig.suptitle("Leave-one-out validation after trimming training data")
        fig.savefig(folder / "loo_mae.png", dpi=220)
        plt.close(fig)
        if plot_data is not None:
            kept, models_after = plot_data
            save_refit_plots(
                folder,
                plot_case,
                widths,
                loads,
                measured,
                kept,
                models_before,
                models_after,
            )
        else:
            print(f"{plot_case}: refit plots unavailable; see fit_notes.csv")
        folder.rename(result_dir)

    for case, subset, name, total, n, _, mae, *_ in validation:
        if subset == "all":
            print(
                f"{case:20s} {name:13s} {n:2}/{total:<2} {f'{mae:.3f} mm' if n else 'unavailable'}"
            )
    print(result_dir)


if __name__ == "__main__":
    main()
