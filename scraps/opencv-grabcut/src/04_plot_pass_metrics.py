"""計測CSVから、各区間の超過率・初回差・DR−OP差と平均・SDを保存する。"""

import math
from pathlib import Path
from statistics import mean, stdev

from matplotlib import rcParams
from matplotlib.figure import Figure

from utils.file_io import check_output_path
from utils.measurement_csv import read_lengths
from workflow_settings import BASE_DIRECTORY, OUTPUT_DIRECTORY

# 実験回、パス番号、区間ID、計測CSV。相対パスはこのスクリプトのフォルダが基準。
MEASUREMENTS = [
    ("run01", 0, "a", "output/run01_pass00_a.csv"),
    ("run01", 2, "a", "output/run01_pass02_a.csv"),
    ("run01", 4, "a", "output/run01_pass04_a.csv"),
]
GRAPH_DIRECTORY = OUTPUT_DIRECTORY / "pass_graphs"

# 比較する図で共通に使う見た目。Noneの軸範囲は自動で決まる。
FIGURE_SIZE = (10, 6)
FONT_FAMILY = "Meiryo"
FONT_SIZE = 11
SAVE_DPI = 180
DR_COLOR = "#d96c17"
OP_COLOR = "#15927e"
DIFFERENCE_COLOR = "#5964a6"
LINE_STYLES = ("-", "--", "-.", ":")
MARKERS = ("o", "s", "^", "D", "v", "P", "X")
PASS_X_LIMITS = None
EXCESS_Y_LIMITS = None
CHANGE_Y_LIMITS = None
DIFFERENCE_Y_LIMITS = None


def read_pass_measurements(measurements: list[tuple[str, int, str, str]]) -> list[dict]:
    records = {}
    used_paths = set()
    reference_measurement = None
    for experiment_id, pass_number, section_id, csv_name in measurements:
        experiment_id = experiment_id.strip()
        section_id = section_id.strip()
        if not experiment_id or not section_id or not csv_name.strip():
            raise ValueError("実験回・区間ID・計測CSVを空欄にしないでください")
        if type(pass_number) is not int or pass_number < 0 or pass_number % 2 != 0:
            raise ValueError("パス番号は0以上の偶数整数にしてください")
        key = (experiment_id, section_id, pass_number)
        if key in records:
            raise ValueError(f"同じ実験回・区間ID・パス番号が重複しています: {key}")
        measurement_path = (BASE_DIRECTORY / csv_name.strip()).resolve()
        if measurement_path in used_paths:
            raise ValueError(
                f"同じ計測CSVを重複して指定しないでください: {measurement_path.name}"
            )
        measurement = read_lengths(measurement_path)
        if reference_measurement is None:
            reference_measurement = measurement
        for column in (
            "interval_length_mm",
            "mm_per_px",
            "evaluation_interval_mm",
            "smoothing_width_mm",
        ):
            if not math.isclose(
                measurement[column],
                reference_measurement[column],
                rel_tol=1e-8,
                abs_tol=1e-8,
            ):
                raise ValueError(
                    f"計測条件が一致しません: {column}: {measurement_path.name}"
                )
        measurement["experiment_id"] = experiment_id
        measurement["section_id"] = section_id
        measurement["pass_number"] = pass_number
        measurement["measurement_csv"] = str(measurement_path)
        records[key] = measurement
        used_paths.add(measurement_path)
    if not records:
        raise ValueError("MEASUREMENTSへ計測CSVを1件以上指定してください")
    rows = []
    # 実験回・区間ID・パス番号の順に揃える。欠測の行は作らない。
    for key in sorted(records):
        initial_key = (key[0], key[1], 0)
        if initial_key not in records:
            raise ValueError(
                f"初回差の基準となるパス0がありません: {key[0]} / {key[1]}"
            )
        rows.append(records[key])
    return rows


def summarize_measurements(rows: list[dict]) -> list[dict]:
    if not rows:
        raise ValueError("計測結果を1件以上指定してください")
    initials = {}
    for row in rows:
        if row["pass_number"] == 0:
            key = (row["experiment_id"], row["section_id"])
            initials[key] = row
    groups = {}
    for row in rows:
        section_key = (row["experiment_id"], row["section_id"])
        if section_key not in initials:
            raise ValueError(
                f"初回差の基準となるパス0がありません: {section_key[0]} / {section_key[1]}"
            )
        initial = initials[section_key]
        key = (row["experiment_id"], row["pass_number"])
        if key not in groups:
            groups[key] = {
                "left_excess_percent": [],
                "right_excess_percent": [],
                "left_change_points": [],
                "right_change_points": [],
                "difference_points": [],
            }
        values = groups[key]
        dr = row["left_excess_percent"]
        op = row["right_excess_percent"]
        values["left_excess_percent"].append(dr)
        values["right_excess_percent"].append(op)
        # 差のばらつきは、対応する区間同士で差を求めてから計算する。
        values["left_change_points"].append(dr - initial["left_excess_percent"])
        values["right_change_points"].append(op - initial["right_excess_percent"])
        values["difference_points"].append(dr - op)
    summaries = []
    for key in sorted(groups):
        count = len(groups[key]["left_excess_percent"])
        summary = {
            "experiment_id": key[0],
            "pass_number": key[1],
            "count": count,
        }
        for metric, values in groups[key].items():
            summary[f"{metric}_values"] = values
            summary[f"{metric}_mean"] = mean(values)
            summary[f"{metric}_sd"] = None
            if count >= 2:
                summary[f"{metric}_sd"] = stdev(values)
        summaries.append(summary)
    return summaries


def create_graphs(rows: list[dict]) -> list[Figure]:
    summaries = summarize_measurements(rows)
    rcParams["font.sans-serif"] = [FONT_FAMILY, "DejaVu Sans"]
    rcParams["font.size"] = FONT_SIZE
    figures = []
    axes = []
    first = rows[0]
    conditions = (
        f"基準区間長 {first['interval_length_mm']:g} mm / "
        f"倍率 {first['mm_per_px']:g} mm/px / "
        f"評価間隔 {first['evaluation_interval_mm']:g} mm / "
        f"平滑化幅 {first['smoothing_width_mm']:g} mm"
    )
    passes = set()
    groups = {}
    for summary in summaries:
        experiment = summary["experiment_id"]
        if experiment not in groups:
            groups[experiment] = []
        groups[experiment].append(summary)
        passes.add(summary["pass_number"])
    count_notes = []
    for experiment, group in groups.items():
        counts = []
        for summary in group:
            counts.append(f"パス{summary['pass_number']}={summary['count']}")
        count_notes.append(f"区間数 n / {experiment}: " + ", ".join(counts))
    for title, ylabel, limits in (
        ("DR・OP側辺長の超過率", "超過率 [%]", EXCESS_Y_LIMITS),
        ("パス0からの超過率の変化", "初回からの変化 [ポイント]", CHANGE_Y_LIMITS),
        ("DR・OPの超過率の差", "DR − OP [ポイント]", DIFFERENCE_Y_LIMITS),
    ):
        figure = Figure(figsize=FIGURE_SIZE, layout="constrained")
        axis = figure.subplots()
        figure.suptitle(title)
        axis.set_title(
            conditions + "\n小点：各区間 / 線：平均 / 誤差棒：±SD（n≧2）",
            fontsize=FONT_SIZE - 2,
        )
        axis.set_xlabel("圧延パス数\n" + "\n".join(count_notes))
        axis.set_ylabel(ylabel)
        axis.set_xticks(sorted(passes))
        axis.axhline(0, linestyle="--", color="gray", linewidth=1)
        axis.grid(alpha=0.3)
        axis.margins(x=0.06)
        if PASS_X_LIMITS is not None:
            axis.set_xlim(PASS_X_LIMITS)
        if limits is not None:
            axis.set_ylim(limits)
        figures.append(figure)
        axes.append(axis)
    for index, experiment in enumerate(sorted(groups)):
        group = groups[experiment]
        line_style = LINE_STYLES[index % len(LINE_STYLES)]
        marker = MARKERS[index % len(MARKERS)]
        for axis_index, metric, side, color in (
            (0, "left_excess_percent", "DR", DR_COLOR),
            (0, "right_excess_percent", "OP", OP_COLOR),
            (1, "left_change_points", "DR", DR_COLOR),
            (1, "right_change_points", "OP", OP_COLOR),
            (2, "difference_points", "DR−OP", DIFFERENCE_COLOR),
        ):
            pass_numbers = []
            averages = []
            point_passes = []
            point_values = []
            sd_passes = []
            sd_averages = []
            deviations = []
            for summary in group:
                pass_number = summary["pass_number"]
                average = summary[f"{metric}_mean"]
                pass_numbers.append(pass_number)
                averages.append(average)
                for value in summary[f"{metric}_values"]:
                    point_passes.append(pass_number)
                    point_values.append(value)
                deviation = summary[f"{metric}_sd"]
                if deviation is not None:
                    sd_passes.append(pass_number)
                    sd_averages.append(average)
                    deviations.append(deviation)
            axis = axes[axis_index]
            axis.scatter(
                point_passes, point_values, color=color, marker=marker, s=24, alpha=0.55
            )
            axis.plot(
                pass_numbers,
                averages,
                label=f"{experiment} {side}",
                color=color,
                linestyle=line_style,
                marker=marker,
                markerfacecolor="white",
                zorder=3,
            )
            if sd_passes:
                axis.errorbar(
                    sd_passes,
                    sd_averages,
                    yerr=deviations,
                    fmt="none",
                    ecolor=color,
                    capsize=4,
                )
    for axis in axes:
        axis.legend(fontsize=FONT_SIZE - 1)
    return figures


def write_graphs(directory: Path, rows: list[dict]) -> list[Path]:
    inputs = [Path(__file__)]
    for row in rows:
        inputs.append(Path(row["measurement_csv"]))
        inputs.append(Path(row["image_path"]))
    paths = []
    for name in ("excess.png", "change_from_initial.png", "dr_op_difference.png"):
        paths.append(check_output_path(directory / name, ".png", inputs))
    figures = create_graphs(rows)
    directory.mkdir(parents=True, exist_ok=True)
    for path, figure in zip(paths, figures):
        figure.savefig(path, dpi=SAVE_DPI)
    return paths


def main() -> None:
    try:
        rows = read_pass_measurements(MEASUREMENTS)
        paths = write_graphs(GRAPH_DIRECTORY, rows)
    except (ValueError, OSError) as error:
        raise SystemExit(f"作図できません: {error}") from error
    for path in paths:
        print(f"保存: {path}")


if __name__ == "__main__":
    main()
