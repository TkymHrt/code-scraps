"""08の候補集計CSVを読み、候補数と大きさの基準との差を比較する."""

import csv
import math
from pathlib import Path

from matplotlib import pyplot as plt

# パスはこのスクリプトのフォルダが基準。撮影倍率・向き・評価条件を揃える。
INPUT_CSVS = (
    ("sample_A", "results/sample_A/08_candidate_summary.csv"),
    ("sample_B", "results/sample_B/08_candidate_summary.csv"),
)
BASELINE_ID = "sample_A"
OUTPUT_CSV_PATH = "results/09_compare_candidates.csv"
OUTPUT_IMAGE_PATH = "results/09_compare_candidates.png"

directory = Path(__file__).resolve().parent
output_csv_path = (directory / OUTPUT_CSV_PATH).resolve()
output_image_path = (directory / OUTPUT_IMAGE_PATH).resolve()
if len(INPUT_CSVS) < 2:
    raise ValueError("08の候補集計CSVを2枚以上指定してください")
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

# 候補なしの0も有効な集計。左・右・合計と評価条件を、保存前に確認する。
measurements = []
comparison_settings = None
for input_path in input_paths:
    summary = {}
    with input_path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        required_columns = {
            "edge",
            "candidate_count",
            "max_inward_px",
            "total_span_px",
            "boundary_candidate_count",
            "start_y",
            "end_y",
            "threshold_px",
            "min_rows",
            "left_reference_ranges",
            "right_reference_ranges",
        }
        if not required_columns.issubset(reader.fieldnames or []):
            raise ValueError(f"08の集計CSVに必要な列がありません: {input_path}")
        for row in reader:
            edge = row["edge"]
            if edge not in ("left", "right", "total") or edge in summary:
                raise ValueError(f"左・右・合計を1行ずつ指定してください: {input_path}")
            count = int(row["candidate_count"])
            boundary_count = int(row["boundary_candidate_count"])
            max_inward = float(row["max_inward_px"])
            total_span = float(row["total_span_px"])
            if count < 0 or not (0 <= boundary_count <= count):
                raise ValueError(f"候補数と境界候補数が不正です: {input_path}")
            for value in (max_inward, total_span):
                if not math.isfinite(value) or value < 0:
                    raise ValueError(
                        f"候補の大きさは0以上の有限値が必要です: {input_path}"
                    )
            if count == 0 and (max_inward != 0 or total_span != 0):
                raise ValueError(f"候補なしの大きさは0にしてください: {input_path}")
            start_y = int(row["start_y"])
            end_y = int(row["end_y"])
            threshold = float(row["threshold_px"])
            min_rows = int(row["min_rows"])
            if not (0 <= start_y < end_y) or min_rows < 2:
                raise ValueError(f"計測範囲または連続行数が不正です: {input_path}")
            if not math.isfinite(threshold) or threshold <= 0:
                raise ValueError(f"候補のしきい値が不正です: {input_path}")
            if count > 0 and (max_inward + 0.005 < threshold or total_span <= 0):
                raise ValueError(f"候補数と大きさが矛盾しています: {input_path}")
            left_ranges = row["left_reference_ranges"].strip()
            right_ranges = row["right_reference_ranges"].strip()
            if not left_ranges or not right_ranges:
                raise ValueError(f"正常部分の指定がありません: {input_path}")
            settings = (start_y, end_y, threshold, min_rows, left_ranges, right_ranges)
            if comparison_settings is not None and settings != comparison_settings:
                raise ValueError(
                    "比較するCSVの計測範囲・候補条件・正常部分を揃えてください"
                )
            comparison_settings = settings
            summary[edge] = (count, max_inward, total_span, boundary_count)
    if len(summary) != 3:
        raise ValueError(f"左・右・合計の集計が揃っていません: {input_path}")
    left = summary["left"]
    right = summary["right"]
    total = summary["total"]
    if total[0] != left[0] + right[0] or total[3] != left[3] + right[3]:
        raise ValueError(f"左右の個数と合計が一致しません: {input_path}")
    if abs(total[1] - max(left[1], right[1])) > 0.011:
        raise ValueError(f"左右の最大偏差と合計行が一致しません: {input_path}")
    if abs(total[2] - left[2] - right[2]) > 0.011:
        raise ValueError(f"左右の影響範囲と合計が一致しません: {input_path}")
    measurements.append(summary)

if comparison_settings is None:
    raise ValueError("評価条件を読み込めませんでした")
baseline_index = sample_ids.index(BASELINE_ID)
baseline = measurements[baseline_index]
start_y, end_y, threshold, min_rows, left_ranges, right_ranges = comparison_settings
comparison_rows = []
for sample_id, summary in zip(sample_ids, measurements):
    for edge in ("left", "right", "total"):
        count, max_inward, total_span, boundary_count = summary[edge]
        base_count, base_max, base_span, _ = baseline[edge]
        comparison_rows.append(
            (
                sample_id,
                BASELINE_ID,
                edge,
                count,
                f"{max_inward:.2f}",
                f"{total_span:.2f}",
                boundary_count,
                count - base_count,
                f"{max_inward - base_max:.2f}",
                f"{total_span - base_span:.2f}",
                start_y,
                end_y,
                threshold,
                min_rows,
                left_ranges,
                right_ranges,
            )
        )

# 候補数・最大内向き偏差・影響範囲合計を、左右別の棒グラフで比較する。
plt.switch_backend("Agg")
plt.rcParams["font.sans-serif"] = ["Meiryo", "DejaVu Sans"]
figure, axes = plt.subplots(
    3, 1, figsize=(max(8, len(sample_ids) * 1.6), 11), layout="constrained"
)
positions = list(range(len(sample_ids)))
left_positions = []
right_positions = []
for position in positions:
    left_positions.append(position - 0.2)
    right_positions.append(position + 0.2)
for axis, column, label in zip(
    axes,
    (0, 1, 2),
    ("Candidate count", "Maximum inward offset (px)", "Total affected span (px)"),
):
    left_values = []
    right_values = []
    for summary in measurements:
        left_values.append(summary["left"][column])
        right_values.append(summary["right"][column])
    left_bars = axis.bar(left_positions, left_values, width=0.4, label="Left")
    right_bars = axis.bar(right_positions, right_values, width=0.4, label="Right")
    number_format = "%.0f" if column == 0 else "%.2f"
    axis.bar_label(left_bars, fmt=number_format, padding=3, fontsize=9)
    axis.bar_label(right_bars, fmt=number_format, padding=3, fontsize=9)
    axis.set_xticks(positions, sample_ids)
    axis.set_ylim(0, max(1, max(left_values + right_values)) * 1.25)
    axis.set_ylabel(label)
    axis.set_axisbelow(True)
    axis.grid(axis="y", alpha=0.3)
    axis.legend()
figure.suptitle(
    f"Provisional candidates | Baseline: {BASELINE_ID}\n"
    f"y={start_y}..{end_y} | inward >= {threshold:g}px, >= {min_rows} rows"
)
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
            "edge",
            "candidate_count",
            "max_inward_px",
            "total_span_px",
            "boundary_candidate_count",
            "delta_candidate_count",
            "delta_max_inward_px",
            "delta_total_span_px",
            "start_y",
            "end_y",
            "threshold_px",
            "min_rows",
            "left_reference_ranges",
            "right_reference_ranges",
        )
    )
    writer.writerows(comparison_rows)

print(f"基準: {BASELINE_ID} / 計測範囲: y={start_y}〜{end_y}")
print(f"候補数と大きさの比較CSV: {output_csv_path}")
print(f"候補数・偏差・影響範囲の比較グラフ: {output_image_path}")
