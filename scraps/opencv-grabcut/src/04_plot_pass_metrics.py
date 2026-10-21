"""対応表から計測CSVを読み、パス別の超過率・初回差・DR−OP差を保存する。"""

import argparse
import csv
import math
from pathlib import Path

from matplotlib import rcParams
from matplotlib.figure import Figure

from utils.file_io import check_output_path
from utils.measurement_csv import read_lengths

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


def read_pass_measurements(path: Path) -> list[dict]:
    path = path.resolve()
    required = ("experiment_id", "pass_number", "section_id", "measurement_csv")
    records = {}
    used_paths = set()
    reference_measurement = None
    try:
        with path.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            if not set(required).issubset(reader.fieldnames or []):
                raise ValueError(
                    "対応表には experiment_id, pass_number, section_id, measurement_csv が必要です"
                )
            for line_number, saved in enumerate(reader, start=2):
                for column in required:
                    value = saved[column]
                    if value is None or not value.strip():
                        raise ValueError(
                            f"対応表{line_number}行目の空欄を確認してください: {column}"
                        )
                experiment_id = saved["experiment_id"].strip()
                section_id = saved["section_id"].strip()
                try:
                    pass_number = int(saved["pass_number"].strip())
                except ValueError as error:
                    raise ValueError(
                        f"対応表{line_number}行目のパス番号は0以上の偶数整数にしてください"
                    ) from error
                if pass_number < 0 or pass_number % 2 != 0:
                    raise ValueError(
                        f"対応表{line_number}行目のパス番号は0以上の偶数整数にしてください"
                    )
                key = (experiment_id, section_id, pass_number)
                if key in records:
                    raise ValueError(
                        f"同じ実験回・区間ID・パス番号が重複しています: {key}"
                    )
                measurement_path = (
                    path.parent / saved["measurement_csv"].strip()
                ).resolve()
                if measurement_path in used_paths:
                    raise ValueError(
                        f"同じ計測CSVを重複して指定しないでください: {measurement_path.name}"
                    )
                measurement = read_lengths(measurement_path)
                if "left_excess_percent" not in measurement:
                    raise ValueError(
                        f"長手軸と平滑化を使った新形式の計測CSVを指定してください: {measurement_path.name}"
                    )
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
    except (OSError, UnicodeError, csv.Error) as error:
        raise ValueError(f"対応表を読み込めません: {path}") from error
    if not records:
        raise ValueError("対応表へ計測CSVを1件以上指定してください")
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


def create_graphs(rows: list[dict]) -> list[Figure]:
    if not rows:
        raise ValueError("計測結果を1件以上指定してください")
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
    for row in rows:
        key = (row["experiment_id"], row["section_id"])
        if key not in groups:
            groups[key] = {}
        groups[key][row["pass_number"]] = row
        passes.add(row["pass_number"])
    for title, ylabel, limits in (
        ("DR・OP側辺長の超過率", "超過率 [%]", EXCESS_Y_LIMITS),
        ("パス0からの超過率の変化", "初回からの変化 [ポイント]", CHANGE_Y_LIMITS),
        ("DR・OPの超過率の差", "DR − OP [ポイント]", DIFFERENCE_Y_LIMITS),
    ):
        figure = Figure(figsize=FIGURE_SIZE, layout="constrained")
        axis = figure.subplots()
        figure.suptitle(title)
        axis.set_title(conditions, fontsize=FONT_SIZE - 2)
        axis.set_xlabel("圧延パス数")
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
    for index, key in enumerate(sorted(groups)):
        group = groups[key]
        if 0 not in group:
            raise ValueError(
                f"初回差の基準となるパス0がありません: {key[0]} / {key[1]}"
            )
        pass_numbers = sorted(group)
        label = f"{key[0]} / {key[1]}"
        line_style = LINE_STYLES[index % len(LINE_STYLES)]
        marker = MARKERS[index % len(MARKERS)]
        for edge, side, color in (
            ("left", "DR", DR_COLOR),
            ("right", "OP", OP_COLOR),
        ):
            values = []
            changes = []
            initial = group[0][f"{edge}_excess_percent"]
            for pass_number in pass_numbers:
                excess = group[pass_number][f"{edge}_excess_percent"]
                values.append(excess)
                changes.append(excess - initial)
            axes[0].plot(
                pass_numbers,
                values,
                label=f"{label} {side}",
                color=color,
                linestyle=line_style,
                marker=marker,
            )
            axes[1].plot(
                pass_numbers,
                changes,
                label=f"{label} {side}",
                color=color,
                linestyle=line_style,
                marker=marker,
            )
        differences = []
        for pass_number in pass_numbers:
            row = group[pass_number]
            differences.append(row["left_excess_percent"] - row["right_excess_percent"])
        axes[2].plot(
            pass_numbers,
            differences,
            label=label,
            color=DIFFERENCE_COLOR,
            linestyle=line_style,
            marker=marker,
        )
    for axis in axes:
        axis.legend(fontsize=FONT_SIZE - 1)
    return figures


def write_graphs(directory: Path, rows: list[dict], input_path: Path) -> list[Path]:
    inputs = [input_path]
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mapping", type=Path, help="実験回・パス番号・計測CSVの対応表")
    parser.add_argument(
        "--out", type=Path, required=True, help="3枚のPNGの保存先フォルダ"
    )
    arguments = parser.parse_args()
    try:
        rows = read_pass_measurements(arguments.mapping)
        paths = write_graphs(arguments.out, rows, arguments.mapping)
    except (ValueError, OSError) as error:
        parser.exit(1, f"作図できません: {error}\n")
    for path in paths:
        print(f"保存: {path}")


if __name__ == "__main__":
    main()
