"""形状が分かっている4枚の画像を作り、4本のスクリプトを実行する."""

import csv
import runpy
import sys
from pathlib import Path

import cv2 as cv
import numpy as np

directory = Path(__file__).resolve().parent
output_directory = directory / "results" / "quantitative_demo"
output_directory.mkdir(parents=True, exist_ok=True)
script_directory = directory.parent

# 基準、左端の切欠き、毎行の凹凸、倍率2倍の同じ長方形を用意する。
samples = []
for sample_id in (
    "sample_A_pass00",
    "sample_A_pass01",
    "sample_A_zigzag",
    "sample_A_scaled",
):
    scaled = sample_id == "sample_A_scaled"
    height, width = (241, 400) if scaled else (121, 200)
    image = np.full((height, width, 3), 30, np.uint8)
    for y in range(height):
        left, right = (140, 260) if scaled else (70, 130)
        if sample_id == "sample_A_pass01" and 40 <= y < 80:
            left += 10
        if sample_id == "sample_A_zigzag":
            left += 4 * (y % 2)
        image[y, left : right + 1] = 180
    image_name = f"{sample_id}.png"
    cv.imwrite(str(output_directory / image_name), image)
    samples.append(
        {
            "sample_id": sample_id,
            "image_path": image_name,
            "mm_per_px": 0.05 if scaled else 0.1,
        }
    )

with (output_directory / "samples.csv").open(
    "w", encoding="utf-8", newline=""
) as output:
    writer = csv.DictWriter(output, fieldnames=list(samples[0]))
    writer.writeheader()
    writer.writerows(samples)

# コピーしたスクリプトの入出力と単位だけを変える。実践用の設定は変えない。
for filename in (
    "measure_batch.py",
    "compare_lengths.py",
    "compare_sampling.py",
    "compare_widths.py",
):
    settings = (
        {"OUTPUT_DIRECTORY": "batch"}
        if filename == "measure_batch.py"
        else {"INPUT_CSV": "batch/measurements.csv"}
    )
    if filename in ("compare_lengths.py", "compare_widths.py"):
        settings["UNIT"] = "mm"
    lines = (script_directory / filename).read_text(encoding="utf-8").splitlines()
    for name, value in settings.items():
        for index, line in enumerate(lines):
            if line.startswith((f"{name} = ", f"{name}:")):
                lines[index] = f"{name} = {value!r}"
                break
    script_path = output_directory / filename
    script_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    runpy.run_path(str(script_path), run_name="__main__")

sys.stdout.write(f"合成画像と比較CSVの保存先: {output_directory}\n")
