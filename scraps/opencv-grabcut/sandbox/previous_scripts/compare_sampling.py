"""点を拾う行間隔を変え、左右の長さの画素段差への感度を比較する."""

import csv
from pathlib import Path

import numpy as np

# 変更する設定。パスはこのスクリプトのフォルダが基準。
INPUT_CSV = "results/measurements.csv"
OUTPUT_CSV = "results/sampling_comparison.csv"
ROW_STEPS = (1, 2, 5, 10)

directory = Path(__file__).resolve().parent
input_path = directory / INPUT_CSV
output_path = directory / OUTPUT_CSV

# measure_batch.py が保存した計測一覧を読む。
with input_path.open(encoding="utf-8", newline="") as source:
    measurements = list(csv.DictReader(source))
if not measurements:
    raise ValueError("計測一覧が空です。measure_batch.py を先に実行してください")

comparison_rows = []
for measurement in measurements:
    # 点列のパスは計測一覧CSVのフォルダからの相対パス。
    edges_path = input_path.parent / measurement["edges_path"]
    with edges_path.open(encoding="utf-8", newline="") as source:
        edges = list(csv.DictReader(source))
    if len(edges) < 2:
        raise ValueError(f"長さを測るには2点以上が必要です: {edges_path}")

    y_values, left_x_values, right_x_values = np.array(
        [
            (float(row["y_px"]), float(row["left_x_px"]), float(row["right_x_px"]))
            for row in edges
        ],
        dtype=np.float64,
    ).T

    for side, x_values in (("left", left_x_values), ("right", right_x_values)):
        # 比較の基準は毎行の点を結んだ長さ。ROW_STEPSの並び順に依存しない。
        baseline_length = float(np.hypot(np.diff(x_values), np.diff(y_values)).sum())
        chord_length = float(
            np.hypot(x_values[-1] - x_values[0], y_values[-1] - y_values[0])
        )

        for row_step in ROW_STEPS:
            # 連続した行の点を一定間隔で選ぶ。末尾も含めて測る範囲をそろえる。
            indices = np.arange(0, len(y_values), row_step)
            last_index = len(y_values) - 1
            if indices[-1] != last_index:
                indices = np.append(indices, last_index)

            delta_x = np.diff(x_values[indices])
            delta_y = np.diff(y_values[indices])
            length = float(np.hypot(delta_x, delta_y).sum())
            change_pct = (length / baseline_length - 1.0) * 100.0
            comparison_rows.append(
                (
                    measurement["sample_id"],
                    row_step,
                    side,
                    f"{length:.6f}",
                    f"{chord_length:.6f}",
                    f"{length / chord_length:.6f}",
                    f"{change_pct:.6f}",
                )
            )

# 間隔を広げたときの変化をCSVに保存する。亀裂の有無を判定する指標ではない。
output_path.parent.mkdir(parents=True, exist_ok=True)
with output_path.open("w", encoding="utf-8", newline="") as output:
    writer = csv.writer(output)
    writer.writerow(
        (
            "sample_id",
            "row_step_px",
            "side",
            "length_px",
            "chord_px",
            "length_over_chord",
            "change_from_step1_pct",
        )
    )
    writer.writerows(comparison_rows)

print(f"行間隔による比較を保存しました: {output_path}")
