"""長さCSVと撮影時の厚さから、左右側辺長と理想長のグラフをPNGに保存する。"""

import csv
import math
from pathlib import Path

from matplotlib import rcParams
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

# 数値とファイル名は例。本番の初期区間長・初期厚さへ置き換える。
INITIAL_LENGTH_MM = 100.0
INITIAL_THICKNESS_MM = 10.0
# 撮影順に、計測GUIの長さCSVと撮影時の厚さ(mm)を並べる。
# 相対パスはこのスクリプトがあるフォルダを基準にする。
INPUT_CSVS = [
    ("output/shot1_lengths.csv", 10.0),
    ("output/shot2_lengths.csv", 5.0),
]
OUTPUT_PATH = "output/length_comparison_simple.png"


def positive_value(value: float | str | None, name: str) -> float:
    try:
        number = float(value) if value is not None else math.nan
    except ValueError as error:
        raise ValueError(f"{name}は0より大きい数値にしてください") from error
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name}は0より大きい有限値が必要です")
    return number


directory = Path(__file__).resolve().parent
output_path = (directory / OUTPUT_PATH).resolve()
if output_path.suffix.lower() != ".png":
    raise ValueError("保存先の拡張子は .png にしてください")
if not INPUT_CSVS:
    raise ValueError("INPUT_CSVSへ長さCSVと撮影時の厚さを1組以上指定してください")
initial_length = positive_value(INITIAL_LENGTH_MM, "初期区間長(mm)")
initial_thickness = positive_value(INITIAL_THICKNESS_MM, "初期厚さ(mm)")

positions = []
left_values = []
right_values = []
ideal_values = []
input_paths = []
for index, (csv_path, thickness_mm) in enumerate(INPUT_CSVS):
    input_path = (directory / csv_path).resolve()
    if input_path in input_paths:
        raise ValueError(f"同じCSVを重複して指定しないでください: {input_path.name}")
    input_paths.append(input_path)
    with input_path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        required = {"image_path", "left_mm", "right_mm"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"計測GUIの長さCSVを指定してください: {input_path.name}")
        saved_rows = list(reader)
    if len(saved_rows) != 1:
        raise ValueError(f"長さCSVは1画像につき1行が必要です: {input_path.name}")
    saved = saved_rows[0]
    if not saved["image_path"] or not saved["image_path"].strip():
        raise ValueError(f"画像パスが空欄です: {input_path.name}")
    image_path = (input_path.parent / saved["image_path"]).resolve()
    if output_path in (input_path, image_path):
        raise ValueError("入力CSV・元画像と別の保存先を指定してください")
    left = positive_value(saved["left_mm"], f"左側辺長: {input_path.name}")
    right = positive_value(saved["right_mm"], f"右側辺長: {input_path.name}")
    thickness = positive_value(thickness_mm, f"撮影時の厚さ: {input_path.name}")
    ideal = initial_length * (initial_thickness / thickness)
    ideal = positive_value(ideal, f"理想片側長: {input_path.name}")
    positions.append(index + 1)
    left_values.append(left)
    right_values.append(right)
    ideal_values.append(ideal)
    print(
        f"{index + 1}: {input_path.name} / 厚さ{thickness:g}mm / "
        f"左{left:.3f}mm / 右{right:.3f}mm / 理想{ideal:.3f}mm"
    )

# 幅一定・体積一定の理想片側長 = 初期区間長 × 初期厚さ ÷ 撮影時の厚さ。
rcParams["font.sans-serif"] = ["Meiryo", "DejaVu Sans"]
figure = Figure(figsize=(8, 5), layout="constrained")
FigureCanvasAgg(figure)
axis = figure.subplots()
axis.plot(positions, left_values, marker="o", label="左側辺", color="#d96c17")
axis.plot(positions, right_values, marker="o", label="右側辺", color="#15927e")
axis.plot(
    positions,
    ideal_values,
    marker="s",
    linestyle="--",
    color="black",
    label="理想片側長",
)
axis.set_xticks(positions)
axis.set_xlim(0.5, len(positions) + 0.5)
axis.set_xlabel("撮影順（コードの指定順）")
axis.set_ylabel("側辺長 (mm)")
axis.set_title("左右側辺長と厚さから求めた理想片側長")
axis.grid(alpha=0.3)
axis.legend()
output_path.parent.mkdir(parents=True, exist_ok=True)
figure.savefig(output_path, dpi=160)
print(f"保存: {output_path}")
