"""比較GUI 2本で使う長さCSVの読込・検証とグラフ。"""

from pathlib import Path

from file_io import check_output_path
from matplotlib import rcParams
from matplotlib.figure import Figure
from measurement_csv import read_lengths


def read_measurements(csv_paths: list[Path]) -> list[dict]:
    if not csv_paths:
        raise ValueError("長さCSVを1つ以上追加してください")
    used_paths = []
    rows = []
    for index, path in enumerate(csv_paths):
        path = path.resolve()
        if path in used_paths:
            raise ValueError(f"同じCSVを重複して指定しないでください: {path.name}")
        used_paths.append(path)
        row = {
            "order": index + 1,
            "csv_name": path.name,
            "measurement_csv": str(path),
        }
        row.update(read_lengths(path))
        rows.append(row)
    return rows


def create_graph(
    rows: list[dict],
    normalized: bool = False,
    reduction_axis: bool = False,
    *,
    initial_thickness_mm: float | None = None,
) -> Figure:
    rcParams["font.sans-serif"] = ["Meiryo", "DejaVu Sans"]
    figure = Figure(figsize=(9, 5), layout="constrained")
    axis = figure.subplots()
    positions = []
    labels = []
    left_values = []
    right_values = []
    interval_values = []
    for row in rows:
        if reduction_axis:
            positions.append(row["reduction_pct"])
        else:
            positions.append(row["order"])
        labels.append(Path(row["csv_name"]).stem)
        interval_values.append(row["interval_length_mm"])
        if normalized:
            left_values.append(row["left_per_100mm"])
            right_values.append(row["right_per_100mm"])
        else:
            left_values.append(row["left_mm"])
            right_values.append(row["right_mm"])
    axis.plot(positions, left_values, marker="o", label="左側辺", color="#d96c17")
    axis.plot(positions, right_values, marker="o", label="右側辺", color="#15927e")
    if normalized:
        axis.axhline(100, linestyle="--", color="gray", label="基準（直線の目安）")
    else:
        axis.plot(
            positions,
            interval_values,
            marker="s",
            linestyle="--",
            color="gray",
            label="基準（直線の目安）",
        )
    if reduction_axis:
        axis.set_xlabel("累積圧下率 (%)")
        axis.margins(x=0.1)
    else:
        axis.set_xticks(positions, labels, rotation=25, ha="right", fontsize=9)
        axis.set_xlim(0.5, len(rows) + 0.5)
        axis.set_xlabel("撮影 / CSV（追加順）")
    if normalized:
        axis.set_ylabel("100mmあたりの側辺長 (mm)")
        axis.set_title("左右側辺長の比較（100mm換算）")
    else:
        axis.set_ylabel("側辺長 (mm)")
        axis.set_title("左右側辺長の比較（実測長）")
    axis.grid(alpha=0.3)
    axis.legend()
    if initial_thickness_mm is not None:
        figure.suptitle(f"初期厚さ：{initial_thickness_mm:g} mm")
    return figure


def write_graph(
    path: Path,
    rows: list[dict],
    normalized: bool = False,
    reduction_axis: bool = False,
    *,
    initial_thickness_mm: float | None = None,
) -> None:
    if not rows:
        raise ValueError("比較してから保存してください")
    inputs = []
    for row in rows:
        inputs.extend([Path(row["measurement_csv"]), Path(row["image_path"])])
    path = check_output_path(path, ".png", inputs)
    figure = create_graph(
        rows, normalized, reduction_axis, initial_thickness_mm=initial_thickness_mm
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=160)
