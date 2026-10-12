"""複数試料の左右側辺の長さを、指定した基準試料と比較する."""

import csv
from pathlib import Path

# パスはこのスクリプトのフォルダが基準。基準試料を明示して比較する。
INPUT_CSV = "results/measurements.csv"
OUTPUT_CSV = "results/length_comparison.csv"
BASELINE_ID = "sample_A_pass00"
UNIT = "px"  # "px" または "mm"。mmの場合は全ての試料で換算値が必要。

unit = UNIT.lower()
if unit not in ("px", "mm"):
    raise ValueError('UNIT は "px" または "mm" にしてください')

directory = Path(__file__).resolve().parent
input_path = directory / INPUT_CSV
output_path = directory / OUTPUT_CSV

# 必要な値を全行読み込む。途中で問題があれば、出力CSVはまだ保存しない。
measurements = []
baseline = None
with input_path.open(encoding="utf-8-sig", newline="") as source:
    for row in csv.DictReader(source):
        sample_id = row["sample_id"]
        columns = [f"{side}_{unit}" for side in ("left", "right", "total")]
        if unit == "mm" and any(not row[column] for column in columns):
            raise ValueError(
                f"{sample_id}: mm の値が空欄です。換算値を設定して再計測してください"
            )
        left, right, total = (float(row[column]) for column in columns)
        if total == 0:
            raise ValueError(
                f"{sample_id}: 合計長さが0のため左右差の割合を計算できません"
            )
        measurements.append((sample_id, left, right, total))
        if sample_id == BASELINE_ID:
            baseline = (left, right, total)

if not measurements:
    raise ValueError("入力CSVに計測データがありません")
if baseline is None:
    raise ValueError(f"基準試料がありません: {BASELINE_ID}")
if any(length == 0 for length in baseline):
    raise ValueError("基準試料の長さに0があるため変化率を計算できません")

# 差分は今回の値から基準値を引き、変化率は差分を基準値で割って100倍する。
baseline_left, baseline_right, baseline_total = baseline
comparisons = []
for sample_id, left, right, total in measurements:
    left_diff = left - baseline_left
    right_diff = right - baseline_right
    total_diff = total - baseline_total
    comparisons.append(
        (
            sample_id,
            BASELINE_ID,
            unit,
            left,
            right,
            total,
            left_diff,
            right_diff,
            total_diff,
            100 * left_diff / baseline_left,
            100 * right_diff / baseline_right,
            100 * total_diff / baseline_total,
            100 * (left - right) / total,
        )
    )

# 左右差の割合は正なら左が長く、負なら右が長い。
output_path.parent.mkdir(parents=True, exist_ok=True)
with output_path.open("w", encoding="utf-8", newline="") as output:
    writer = csv.writer(output)
    writer.writerow(
        (
            "sample_id",
            "baseline_id",
            "unit",
            f"left_{unit}",
            f"right_{unit}",
            f"total_{unit}",
            f"left_diff_{unit}",
            f"right_diff_{unit}",
            f"total_diff_{unit}",
            "left_change_pct",
            "right_change_pct",
            "total_change_pct",
            "signed_left_minus_right_pct",
        )
    )
    writer.writerows(comparisons)
