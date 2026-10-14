"""相対的な高さをそろえて幅を比較し、基準試料からの変化を保存する."""

import csv
from pathlib import Path

import numpy as np

# パスはこのスクリプトのフォルダが基準。基準試料を明示して比較する。
INPUT_CSV = "results/measurements.csv"
OUTPUT_CSV = "results/width_comparison.csv"
BASELINE_ID = "sample_A_pass00"
UNIT = "px"  # "px" または "mm"。mmの場合は全ての試料で換算値が必要。
POSITION_COUNT = 21

unit = UNIT.lower()
if unit not in ("px", "mm"):
    raise ValueError('UNIT は "px" または "mm" にしてください')
if POSITION_COUNT <= 1:
    raise ValueError("POSITION_COUNT は2以上にしてください")

directory = Path(__file__).resolve().parent
input_path = directory / INPUT_CSV
output_path = directory / OUTPUT_CSV

# 幅の比較に必要な側辺CSVを、計測表に書かれた順で読み込む。
with input_path.open(encoding="utf-8-sig", newline="") as source:
    measurements = list(csv.DictReader(source))
if not measurements:
    raise ValueError("入力CSVに計測データがありません")

positions = np.linspace(0.0, 1.0, POSITION_COUNT)
profiles = []
baseline = None
for row in measurements:
    sample_id = row["sample_id"]
    edges_path = input_path.parent / row["edges_path"]
    with edges_path.open(encoding="utf-8-sig", newline="") as source:
        edges = list(csv.DictReader(source))
    if len(edges) <= 1:
        raise ValueError(f"{sample_id}: 幅比較には側辺の点が2点以上必要です")

    # 幅は右端と左端の画素中心間の距離。画素数ではないので1を足さない。
    y_values = np.array([float(edge["y_px"]) for edge in edges])
    widths = np.array(
        [float(edge["right_x_px"]) - float(edge["left_x_px"]) for edge in edges]
    )
    if not np.all(np.diff(y_values) > 0):
        raise ValueError(f"{sample_id}: y_px は上から下へ増える順にしてください")
    if not np.all(np.isfinite(y_values)) or not np.all(np.isfinite(widths)):
        raise ValueError(f"{sample_id}: 側辺の座標は有限の数値にしてください")
    if np.any(widths < 0):
        raise ValueError(f"{sample_id}: 右端が左端より左にある行があります")

    # mmで比較するときは、試料ごとの換算値を幅に掛ける。
    if unit == "mm":
        if not row["mm_per_px"]:
            raise ValueError(f"{sample_id}: mm_per_px が空欄です")
        mm_per_px = float(row["mm_per_px"])
        if not np.isfinite(mm_per_px) or mm_per_px <= 0:
            raise ValueError(f"{sample_id}: mm_per_px は正の有限な数値にしてください")
        widths = widths * mm_per_px

    # 上端を0、下端を1にそろえ、等間隔の位置の幅を線形補間する。
    # 対応するのは相対高さ。画像間で同じ亀裂や材料の点を追跡するものではない。
    relative_y = (y_values - y_values[0]) / (y_values[-1] - y_values[0])
    profile = np.interp(positions, relative_y, widths)
    profiles.append((sample_id, profile))
    if sample_id == BASELINE_ID:
        baseline = profile

if baseline is None:
    raise ValueError(f"基準試料がありません: {BASELINE_ID}")
if np.any(baseline == 0):
    raise ValueError("基準試料の幅に0があるため変化率を計算できません")

# 全ての試料について差分と変化率を計算してから、出力CSVを保存する。
comparisons = []
for sample_id, profile in profiles:
    differences = profile - baseline
    changes = 100 * differences / baseline
    for position, width, baseline_width, difference, change in zip(
        positions, profile, baseline, differences, changes, strict=True
    ):
        comparisons.append(
            (sample_id, position, width, baseline_width, difference, change)
        )

output_path.parent.mkdir(parents=True, exist_ok=True)
with output_path.open("w", encoding="utf-8", newline="") as output:
    writer = csv.writer(output)
    writer.writerow(
        (
            "sample_id",
            "position_fraction",
            f"width_{unit}",
            f"baseline_width_{unit}",
            f"width_diff_{unit}",
            "width_change_pct",
        )
    )
    writer.writerows(comparisons)
