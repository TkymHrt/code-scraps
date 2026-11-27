import csv
from math import ceil

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from organize_errors import TABLES_DIR


def main():
    with (TABLES_DIR / "errors.csv").open(encoding="utf-8-sig", newline="") as stream:
        points = list(csv.DictReader(stream))
    with (TABLES_DIR / "summary.csv").open(encoding="utf-8-sig", newline="") as stream:
        summary = list(csv.DictReader(stream))
    if not points or not summary:
        raise ValueError("errors.csv and summary.csv must contain rows")

    residual_path = TABLES_DIR / "error_by_load.png"
    mae_path = TABLES_DIR / "mae_by_width.png"
    for path in (residual_path, mae_path):
        if path.exists():
            raise FileExistsError(f"{path} already exists")

    models = list(dict.fromkeys(row["model"] for row in points))
    styles = dict(
        zip(models, (("#626770", "x"), ("#2866a4", "D"), ("#bb382d", "o")), strict=True)
    )
    widths = sorted({float(row["width_mm"]) for row in points})
    row_count = ceil(len(widths) / 2)
    fig, axes = plt.subplots(
        row_count,
        2,
        figsize=(9, 3 * row_count + 0.8),
        sharex=True,
        sharey=True,
        layout="constrained",
    )
    for i, width in enumerate(widths):
        axis = axes.flat[i]
        axis.axhline(0, linestyle="--", linewidth=0.8, color="#999999")
        for model in models:
            rows = [
                row
                for row in points
                if float(row["width_mm"]) == width
                and row["model"] == model
                and row["error_mm"]
            ]
            color, marker = styles[model]
            axis.scatter(
                [float(row["load_tf"]) for row in rows],
                [float(row["error_mm"]) for row in rows],
                label=model,
                color=color,
                marker=marker,
                s=25,
            )
        axis.set_title(f"{width:g} mm")
        axis.grid(alpha=0.2)
    for axis in list(axes.flat)[len(widths) :]:
        axis.set_visible(False)
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.get_layout_engine().set(rect=(0, 0.11, 1, 0.89))
    fig.legend(
        handles,
        labels,
        loc="lower center",
        bbox_to_anchor=(0.5, 0.01),
        ncols=3,
        frameon=False,
    )
    fig.suptitle("Thickness prediction errors by load")
    fig.supxlabel("OP load (tf)", y=0.073)
    fig.supylabel("Predicted − measured thickness (mm)")
    with residual_path.open("xb") as stream:
        fig.savefig(stream, format="png", dpi=220)
    plt.close(fig)

    width_rows = [row for row in summary if row["group"] in ("overall", "width")]
    labels = list(dict.fromkeys(row["label"] for row in width_rows))
    fig, axis = plt.subplots(
        figsize=(max(8.5, 1.1 * len(labels)), 4.2), layout="constrained"
    )
    bar_width = 0.24
    for index, model in enumerate(models):
        rows = [row for row in width_rows if row["model"] == model]
        x = [labels.index(row["label"]) + (index - 1) * bar_width for row in rows]
        values = [
            float(row["mae_mm"])
            if row["mae_mm"] and row["predicted_rows"] == row["rows"]
            else float("nan")
            for row in rows
        ]
        axis.bar(x, values, width=bar_width, color=styles[model][0], label=model)
        for position, row in zip(x, rows, strict=True):
            if row["predicted_rows"] != row["rows"]:
                axis.text(
                    position,
                    0,
                    f"{row['predicted_rows']}/{row['rows']}",
                    rotation=90,
                    va="bottom",
                    ha="center",
                    fontsize=8,
                )
    axis.set_xticks(range(len(labels)), labels)
    axis.set_title("Mean absolute thickness error by width")
    axis.set_ylabel("MAE (mm)")
    axis.set_xlabel("Fractions show prediction coverage when a bar is unavailable.")
    axis.grid(axis="y", alpha=0.2)
    fig.get_layout_engine().set(rect=(0, 0.13, 1, 0.87))
    fig.legend(loc="lower center", bbox_to_anchor=(0.5, 0.01), ncols=3, frameon=False)
    with mae_path.open("xb") as stream:
        fig.savefig(stream, format="png", dpi=220)
    plt.close(fig)
    print(residual_path.resolve())
    print(mae_path.resolve())


if __name__ == "__main__":
    main()
