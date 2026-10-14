"""03の長さCSVを読み、基準との差分CSVと左右の棒グラフを保存する."""

import csv
import math
from pathlib import Path

from matplotlib import pyplot as plt

# パスはこのスクリプトのフォルダが基準。識別名と03のCSVを2枚以上指定する。
# 撮影倍率・向き・計測範囲を揃え、各画像の端線を確認してから比較する。
INPUT_CSVS = (
    ("sample_A", "results/sample_A/03_side_lengths.csv"),
    ("sample_B", "results/sample_B/03_side_lengths.csv"),
)
BASELINE_ID = "sample_A"
OUTPUT_CSV_PATH = "results/04_compare_lengths.csv"
OUTPUT_IMAGE_PATH = "results/04_compare_lengths.png"

directory = Path(__file__).resolve().parent
output_csv_path = (directory / OUTPUT_CSV_PATH).resolve()
output_image_path = (directory / OUTPUT_IMAGE_PATH).resolve()
if len(INPUT_CSVS) < 2:
    raise ValueError("03の長さCSVを2枚以上指定してください")

sample_ids = []
input_paths = []
for sample_id, csv_path in INPUT_CSVS:
    if not sample_id.strip() or sample_id in sample_ids:
        raise ValueError("画像の識別名は空欄にせず、重複しない名前にしてください")
    sample_ids.append(sample_id)
    input_paths.append((directory / csv_path).resolve())
if BASELINE_ID not in sample_ids:
    raise ValueError(f"基準の識別名がありません: {BASELINE_ID}")
if output_csv_path == output_image_path:
    raise ValueError("比較CSVとグラフは別々のパスにしてください")
for input_path in input_paths:
    if input_path in (output_csv_path, output_image_path):
        raise ValueError("入力CSV・比較CSV・グラフは別々のパスにしてください")

# 全入力を確認してから保存する。03のCSVは左・右・合計の3行。
measurements = []
baseline = None
comparison_range = None
for sample_id, input_path in zip(sample_ids, input_paths):
    lengths = {}
    measurement_range = None
    with input_path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        required_columns = {"edge", "length_px", "start_y", "end_y"}
        if not required_columns.issubset(reader.fieldnames or []):
            raise ValueError(f"03の長さCSVに必要な列がありません: {input_path}")
        for row in reader:
            edge = row["edge"]
            if edge not in ("left", "right", "total") or edge in lengths:
                raise ValueError(f"左・右・合計を1行ずつ指定してください: {input_path}")
            length = float(row["length_px"])
            if not math.isfinite(length) or length <= 0:
                raise ValueError(f"長さは0より大きい有限値が必要です: {input_path}")
            start_y = int(row["start_y"])
            end_y = int(row["end_y"])
            if not (0 <= start_y < end_y):
                raise ValueError(f"長さを測れる計測範囲が必要です: {input_path}")
            row_range = (start_y, end_y)
            if measurement_range is not None and row_range != measurement_range:
                raise ValueError(f"CSV内の計測範囲が一致しません: {input_path}")
            measurement_range = row_range
            lengths[edge] = length
    if len(lengths) != 3:
        raise ValueError(f"左・右・合計の長さが揃っていません: {input_path}")
    # 03は丸める前に合計を求めるため、左右の和と最大0.01pxずれる。
    if abs(lengths["left"] + lengths["right"] - lengths["total"]) > 0.011:
        raise ValueError(f"左右の長さと合計が一致しません: {input_path}")
    if comparison_range is not None and measurement_range != comparison_range:
        raise ValueError("比較するCSVの計測範囲を揃えてください")
    comparison_range = measurement_range
    measurements.append(lengths)
    if sample_id == BASELINE_ID:
        baseline = lengths

if baseline is None or comparison_range is None:
    raise ValueError("基準と計測範囲を読み込めませんでした")
start_y, end_y = comparison_range

# 差分は各画像の値から基準の値を引く。単位はすべてpx。
comparison_rows = []
left_lengths = []
right_lengths = []
for sample_id, lengths in zip(sample_ids, measurements):
    left = lengths["left"]
    right = lengths["right"]
    total = lengths["total"]
    left_diff = left - baseline["left"]
    right_diff = right - baseline["right"]
    total_diff = total - baseline["total"]
    comparison_rows.append(
        (
            sample_id,
            BASELINE_ID,
            f"{left:.2f}",
            f"{right:.2f}",
            f"{total:.2f}",
            f"{left_diff:.2f}",
            f"{right_diff:.2f}",
            f"{total_diff:.2f}",
            start_y,
            end_y,
        )
    )
    left_lengths.append(left)
    right_lengths.append(right)

# 画面を開かずPNGに保存する。WindowsではMeiryoで日本語の識別名も表示する。
plt.switch_backend("Agg")
plt.rcParams["font.sans-serif"] = ["Meiryo", "DejaVu Sans"]
figure, axes = plt.subplots(
    figsize=(max(7, len(sample_ids) * 1.6), 5), layout="constrained"
)
positions = list(range(len(sample_ids)))
left_positions = []
right_positions = []
for position in positions:
    left_positions.append(position - 0.2)
    right_positions.append(position + 0.2)
left_bars = axes.bar(left_positions, left_lengths, width=0.4, label="Left")
right_bars = axes.bar(right_positions, right_lengths, width=0.4, label="Right")
axes.bar_label(left_bars, fmt="%.2f", padding=3, fontsize=9)
axes.bar_label(right_bars, fmt="%.2f", padding=3, fontsize=9)
axes.set_xticks(positions, sample_ids)
axes.set_ylim(0, max(left_lengths + right_lengths) * 1.2)
axes.set_ylabel("Side length (px)")
axes.set_title(f"Baseline: {BASELINE_ID} | y={start_y}..{end_y}")
axes.set_axisbelow(True)
axes.grid(axis="y", alpha=0.3)
axes.legend()
output_image_path.parent.mkdir(parents=True, exist_ok=True)
figure.savefig(output_image_path, dpi=160)
plt.close(figure)

output_csv_path.parent.mkdir(parents=True, exist_ok=True)
with output_csv_path.open("w", encoding="utf-8", newline="") as output:
    writer = csv.writer(output)
    writer.writerow(
        (
            "sample_id",
            "baseline_id",
            "left_px",
            "right_px",
            "total_px",
            "delta_left_px",
            "delta_right_px",
            "delta_total_px",
            "start_y",
            "end_y",
        )
    )
    writer.writerows(comparison_rows)

print(f"基準: {BASELINE_ID} / 計測範囲: y={start_y}〜{end_y}（両端を含む）")
print(f"長さと基準との差分CSV: {output_csv_path}")
print(f"左右側辺の長さの棒グラフ: {output_image_path}")
