"""既存の実行コードを単独で動かし、段階別の成果と制約を確認する。"""

import argparse
import ast
import csv
import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import cv2 as cv
import numpy as np

PROJECT = Path(__file__).resolve().parents[1]
SCRIPTS = ("outline.py", "side_edges.py", "side_lengths.py")
EXTRA_SCRIPTS = (
    "measure_batch.py",
    "compare_lengths.py",
    "compare_sampling.py",
    "compare_widths.py",
)
SYNTHETIC_SETTINGS = {
    "CANDIDATE_RECT": (0.25, 0.0, 0.75, 1.0),
    "BACKGROUND_RECTS": ((0.0, 0.0, 0.2, 1.0), (0.8, 0.0, 1.0, 1.0)),
    "FOREGROUND_RECTS": ((0.48, 0.4, 0.52, 0.6),),
}


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def read_mask(path):
    mask = cv.imread(str(path), cv.IMREAD_GRAYSCALE)
    assert mask is not None, path
    assert set(np.unique(mask)).issubset({0, 255}), path
    return mask


def run_script(filename, folder, settings):
    """設定だけ変えた1本を専用フォルダへコピーし、別プロセスで実行する。"""
    source = (PROJECT / filename).read_text(encoding="utf-8")
    lines = source.splitlines()
    replacements = []
    found = set()
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in settings:
                assert node.end_lineno is not None
                replacements.append(
                    (node.lineno - 1, node.end_lineno, f"{name} = {settings[name]!r}")
                )
                found.add(name)
    assert found == set(settings), (filename, set(settings) - found)
    for start, end, replacement in reversed(replacements):
        lines[start:end] = [replacement]
    isolated = folder / "scripts" / Path(filename).stem
    isolated.mkdir(parents=True)
    script = isolated / filename
    script.write_text("\n".join(lines) + "\n", encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "-X", "utf8", str(script)],
        cwd=isolated,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    (isolated / "stdout.txt").write_text(completed.stdout, encoding="utf-8")
    (isolated / "stderr.txt").write_text(completed.stderr, encoding="utf-8")
    assert completed.returncode == 0, (filename, completed.stderr)


def verify_image(image_path, folder, settings, expected_raw=None, expected_mask=None):
    folder.mkdir(parents=True)
    output = folder / "outputs"
    for filename in SCRIPTS:
        run_script(
            filename,
            folder,
            {
                **settings,
                "INPUT_PATH": str(image_path),
                "OUTPUT_DIRECTORY": str(output),
            },
        )
    masks = [read_mask(output / f"result_{number:02}_mask.png") for number in (3, 4, 5)]
    raw_masks = [
        read_mask(output / f"result_{number:02}_raw_mask.png") for number in (3, 4, 5)
    ]
    assert all(np.array_equal(mask, masks[0]) for mask in masks)
    assert all(np.array_equal(mask, raw_masks[0]) for mask in raw_masks)
    conditions = [
        json.loads((output / f"result_{number:02}_conditions.json").read_text("utf-8"))
        for number in (3, 4, 5)
    ]
    assert conditions[0] == conditions[1] == conditions[2]
    if expected_raw is not None:
        assert expected_mask is not None
        assert np.array_equal(raw_masks[0], expected_raw), image_path.name
        assert np.array_equal(masks[0], expected_mask), image_path.name
        result = cv.imread(str(output / "result_04.png"))
        assert result is not None
        # 既知の形状の左右端が、実際の成果画像で赤く描かれているか確認する。
        for y in np.flatnonzero(np.any(expected_mask > 0, axis=1)):
            xs = np.flatnonzero(expected_mask[y])
            assert np.all(result[y, xs[[0, -1]]] == (0, 0, 255))
    lengths = {
        row["edge"]: float(row["length_px"])
        for row in read_csv(output / "result_05.csv")
    }
    return {
        "left_px": lengths["left"],
        "right_px": lengths["right"],
        "total_px": lengths["total"],
        "three_masks_and_conditions_match": True,
        "raw_foreground_pixels": int(np.count_nonzero(raw_masks[0])),
        "filled_foreground_pixels": int(np.count_nonzero(masks[0])),
    }


def verify_batch(folder, samples, settings, unit="mm"):
    folder.mkdir()
    input_csv = folder / "samples.csv"
    write_csv(input_csv, samples)
    batch = folder / "batch"
    run_script(
        "measure_batch.py",
        folder,
        {**settings, "INPUT_CSV": str(input_csv), "OUTPUT_DIRECTORY": str(batch)},
    )
    for filename in EXTRA_SCRIPTS[1:]:
        options = {
            "INPUT_CSV": str(batch / "measurements.csv"),
            "OUTPUT_CSV": str(folder / f"{Path(filename).stem}.csv"),
        }
        if filename != "compare_sampling.py":
            options.update(BASELINE_ID=samples[0]["sample_id"], UNIT=unit)
        run_script(filename, folder, options)
    return read_csv(batch / "measurements.csv")


def make_overview(folder):
    rows = []
    for name in ("rectangle", "left_notch", "zigzag", "internal_hole"):
        images = [
            folder / f"{name}.png",
            folder / name / "outputs/result_03_raw_mask.png",
            folder / name / "outputs/result_03_mask.png",
            folder / name / "outputs/result_04.png",
        ]
        panels = []
        for path, label in zip(
            images, ("Input", "Raw GrabCut", "Filled mask", "Side edges"), strict=True
        ):
            image = cv.imread(str(path))
            assert image is not None
            image = cv.resize(image, (400, 320), interpolation=cv.INTER_NEAREST)
            panel = np.full((360, 400, 3), 245, np.uint8)
            panel[40:] = image
            cv.putText(
                panel, f"{name}: {label}", (8, 27), cv.FONT_HERSHEY_SIMPLEX, 0.55, 0, 1
            )
            panels.append(panel)
        rows.append(np.hstack(panels))
    assert cv.imwrite(str(folder / "overview.png"), np.vstack(rows))


def verify(output, with_local_inputs):
    # 新しい保存先だけを使い、前回の結果と実行コードの設定を保全する。
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    synthetic = output / "synthetic"
    synthetic.mkdir()
    report = {
        "python": sys.version.split()[0],
        "opencv": cv.__version__,
        "numpy": np.__version__,
        "source_sha256": {
            name: hashlib.sha256((PROJECT / name).read_bytes()).hexdigest()
            for name in (*SCRIPTS, *EXTRA_SCRIPTS)
        },
        "synthetic": {},
        "local_inputs": {},
    }
    samples = []
    expected_edges = {}
    for name in ("rectangle", "left_notch", "zigzag", "internal_hole", "scaled"):
        scale = 2 if name == "scaled" else 1
        raw = np.zeros((160 * scale, 200 * scale), np.uint8)
        for y in range(20 * scale, 140 * scale + 1):
            left = 70 * scale
            if name == "left_notch" and 60 <= y < 100:
                left += 10
            if name == "zigzag":
                left += 4 * (y % 2)
            raw[y, left : 130 * scale + 1] = 255
        filled = raw.copy()
        if name == "internal_hole":
            raw[70:90, 110:120] = 0
        image = np.full((*raw.shape, 3), 30, np.uint8)
        image[raw > 0] = 180
        image_path = synthetic / f"{name}.png"
        assert cv.imwrite(str(image_path), image)
        expected_left = 120.0 * scale
        if name == "left_notch":
            expected_left = 118 + 2 * math.sqrt(101)
        if name == "zigzag":
            expected_left = 120 * math.sqrt(17)
        result = verify_image(
            image_path, synthetic / name, SYNTHETIC_SETTINGS, raw, filled
        )
        assert result["left_px"] == round(expected_left, 2), name
        assert result["right_px"] == 120.0 * scale, name
        report["synthetic"][name] = result
        expected_edges[name] = filled
        samples.append(
            {"sample_id": name, "image_path": str(image_path), "mm_per_px": 0.1 / scale}
        )
    measurements = verify_batch(synthetic / "comparison", samples, SYNTHETIC_SETTINGS)
    for row in measurements:
        name = row["sample_id"]
        mask = expected_edges[name]
        edges = read_csv(synthetic / "comparison/batch" / row["edges_path"])
        expected_y = np.flatnonzero(np.any(mask > 0, axis=1))
        assert len(edges) == len(expected_y)
        for edge, y in zip(edges, expected_y, strict=True):
            xs = np.flatnonzero(mask[y])
            assert (
                int(edge["y_px"]),
                int(edge["left_x_px"]),
                int(edge["right_x_px"]),
            ) == (
                y,
                xs[0],
                xs[-1],
            )
        assert abs(float(row["left_px"]) - report["synthetic"][name]["left_px"]) < 0.005
        batch_mask = read_mask(synthetic / "comparison/batch" / name / "mask.png")
        assert np.array_equal(batch_mask, mask)
    widths = read_csv(synthetic / "comparison/compare_widths.csv")
    for row in widths:
        expected = (
            5.0
            if row["sample_id"] == "left_notch"
            and 1 / 3 <= float(row["position_fraction"]) <= 0.65
            else 6.0
        )
        assert abs(float(row["width_mm"]) - expected) < 1e-6, row
    lengths = read_csv(synthetic / "comparison/compare_lengths.csv")
    scaled = next(row for row in lengths if row["sample_id"] == "scaled")
    assert float(scaled["total_change_pct"]) == 0
    make_overview(synthetic)
    if with_local_inputs:
        local_samples = []
        for name in ("input_ai", "input"):
            image_path = PROJECT / "sandbox" / f"{name}.png"
            if not image_path.exists():
                report["local_inputs"][name] = {"status": "input_missing"}
                continue
            report["local_inputs"][name] = verify_image(image_path, output / name, {})
            local_samples.append(
                {"sample_id": name, "image_path": str(image_path), "mm_per_px": ""}
            )
        if local_samples:
            # 実寸不明の画像は換算値を入れず、pxだけを検証する。
            rows = verify_batch(output / "local_comparison", local_samples, {}, "px")
            for row in rows:
                result = report["local_inputs"][row["sample_id"]]
                assert abs(float(row["left_px"]) - result["left_px"]) < 0.005
                assert abs(float(row["right_px"]) - result["right_px"]) < 0.005
                batch_mask = read_mask(
                    output / "local_comparison/batch" / row["sample_id"] / "mask.png"
                )
                single_mask = read_mask(
                    output / row["sample_id"] / "outputs/result_05_mask.png"
                )
                assert np.array_equal(batch_mask, single_mask)
    report["all_checks_passed"] = True
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"保存先: {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=PROJECT / "tests/results/stages")
    parser.add_argument("--with-local-inputs", action="store_true")
    arguments = parser.parse_args()
    verify(arguments.out, arguments.with_local_inputs)
