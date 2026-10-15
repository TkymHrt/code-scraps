"""長さCSVから、左右側辺長のグラフをGUIなしでPNGに保存する。"""

import csv
import math
from pathlib import Path

from matplotlib import rcParams
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

# ファイル名は例。計測GUIの長さCSVを撮影順に並べる。
# 相対パスはこのスクリプトがあるフォルダを基準にする。
INPUT_CSVS = [
    "output/shot1_lengths.csv",
    "output/shot2_lengths.csv",
]
OUTPUT_PATH = "output/length_comparison_no_thickness.png"


def positive_value(value: str | None, name: str) -> float:
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
    raise ValueError("INPUT_CSVSへ長さCSVを1枚以上指定してください")

positions = []
left_values = []
right_values = []
input_paths = []
for index, csv_path in enumerate(INPUT_CSVS):
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
    positions.append(index + 1)
    left_values.append(left)
    right_values.append(right)
    print(f"{index + 1}: {input_path.name} / 左{left:.3f}mm / 右{right:.3f}mm")

rcParams["font.sans-serif"] = ["Meiryo", "DejaVu Sans"]
figure = Figure(figsize=(8, 5), layout="constrained")
FigureCanvasAgg(figure)
axis = figure.subplots()
axis.plot(positions, left_values, marker="o", label="左側辺", color="#d96c17")
axis.plot(positions, right_values, marker="o", label="右側辺", color="#15927e")
axis.set_xticks(positions)
axis.set_xlim(0.5, len(positions) + 0.5)
axis.set_xlabel("撮影順（コードの指定順）")
axis.set_ylabel("側辺長 (mm)")
axis.set_title("左右側辺長の推移")
axis.grid(alpha=0.3)
axis.legend()
output_path.parent.mkdir(parents=True, exist_ok=True)
figure.savefig(output_path, dpi=160)
print(f"保存: {output_path}")
