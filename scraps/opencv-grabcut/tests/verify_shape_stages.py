"""生成画像と既知形状で03〜09を実行し、仮算出の入力・実行コピー・成果を残す."""

import argparse
import ast
import csv
import hashlib
import io
import json
import runpy
from contextlib import redirect_stdout
from pathlib import Path

import cv2 as cv
import numpy as np


def configured_source(project, filename, settings):
    source = (project / "submissions" / filename).read_text(encoding="utf-8")
    lines = source.splitlines(keepends=True)
    for node in reversed(ast.parse(source).body):
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in settings:
                lines[node.lineno - 1 : node.end_lineno] = [
                    f"{name} = {settings[name]!r}\n"
                ]
    return "".join(lines)


def execute(project, folder, filename, settings):
    script = folder / filename
    script.write_text(configured_source(project, filename, settings), encoding="utf-8")
    log = io.StringIO()
    with redirect_stdout(log):
        values = runpy.run_path(str(script))
    (folder / f"{script.stem}.log").write_text(log.getvalue(), encoding="utf-8")
    return values


def save_image(path, image):
    success, encoded = cv.imencode(".png", image)
    if not success:
        raise OSError(f"検証入力を保存できません: {path}")
    path.write_bytes(encoded.tobytes())


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def verify(project, output):
    if output.exists():
        raise ValueError("過去の成果を保つため、まだ存在しない検証先を指定してください")
    if not output.is_relative_to((project / "tests/results").resolve()):
        raise ValueError("検証先は題材のtests/results内にしてください")
    output.mkdir(parents=True)
    originals = {}
    for folder in (project / "submissions/input", project / "submissions/results"):
        for path in folder.rglob("*"):
            if path.is_file():
                originals[str(path.relative_to(project))] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()

    input_path = project / "submissions/input/赤茶色の床と剥離した金属帯.png"
    image = cv.imdecode(
        np.frombuffer(input_path.read_bytes(), np.uint8), cv.IMREAD_COLOR
    )
    if image is None:
        raise OSError(f"生成画像を読み込めません: {input_path}")
    stages = (
        "03_side_lengths.py",
        "05_widths.py",
        "06_reference_edges.py",
        "07_notch_candidates.py",
        "08_candidate_sizes.py",
    )
    report = {"input_kind": "generated_test_image_not_production", "cases": {}}
    original_folder = output / "original"
    original_folder.mkdir()
    save_image(original_folder / "input.png", image)
    settings = {"INPUT_PATH": "input.png", "START_Y": 80, "END_Y": 1000}
    measured = execute(project, original_folder, stages[0], settings)

    # 比較計算の確認用に、同じ生成画像の左端を80px内側へ削る。
    # 圧延パスや撮り直しではなく、人工的に追加した凹みの例。
    modified = image.copy()
    for y, left_x, _ in measured["edge_rows"]:
        if 600 <= y <= 620:
            modified[y, left_x : left_x + 80] = image[y, left_x - 15]
    added_folder = output / "added_notch"
    added_folder.mkdir()
    save_image(added_folder / "input.png", modified)
    cases = (
        ("original", original_folder, settings),
        ("added_notch", added_folder, settings),
    )

    for case, folder, case_settings in cases:
        first = (
            measured
            if case == "original"
            else execute(project, folder, stages[0], case_settings)
        )
        for filename in stages[1:]:
            values = execute(project, folder, filename, case_settings)
            np.testing.assert_array_equal(values["mask"], first["mask"])
            if filename != "05_widths.py":
                self_rows = values["edge_rows"]
                assert self_rows == first["edge_rows"]
        widths = read_csv(folder / "results/05_widths.csv")
        width_values = [float(row["width_px"]) for row in widths if row["width_px"]]
        summary = read_csv(folder / "results/08_candidate_summary.csv")
        report["cases"][case] = {
            "width_min_px": min(width_values),
            "width_mean_px": float(np.mean(width_values)),
            "width_max_px": max(width_values),
            "summary": summary,
        }
        print(f"{case}: 03・05〜08の独立実行とマスク・端の一致を確認")

    comparison_inputs = tuple(
        (case, f"{case}/results/03_side_lengths.csv") for case, _, _ in cases
    )
    execute(
        project,
        output,
        "04_compare_lengths.py",
        {"INPUT_CSVS": comparison_inputs, "BASELINE_ID": "original"},
    )
    comparison_inputs = tuple(
        (case, f"{case}/results/08_candidate_summary.csv") for case, _, _ in cases
    )
    execute(
        project,
        output,
        "09_compare_candidates.py",
        {"INPUT_CSVS": comparison_inputs, "BASELINE_ID": "original"},
    )
    comparisons = read_csv(output / "results/09_compare_candidates.csv")
    assert comparisons[-1]["delta_candidate_count"] == "1"
    report["candidate_comparison"] = comparisons

    # 正解の分かる形状でも、候補なし・左1個・左右各1個を確認する。
    synthetic = output / "synthetic"
    synthetic.mkdir()
    synthetic_settings = {
        "INPUT_PATH": "input.png",
        "START_Y": 20,
        "END_Y": 140,
        "CANDIDATE_RECT": (0.34, 0.0, 0.705, 1.0),
        "BACKGROUND_RECTS": ((0.0, 0.0, 0.33, 1.0), (0.72, 0.0, 1.0, 1.0)),
        "FOREGROUND_RECTS": ((0.48, 0.4, 0.56, 0.6),),
        "LEFT_REFERENCE_RANGES": ((20, 40), (120, 140)),
        "RIGHT_REFERENCE_RANGES": ((20, 40), (120, 140)),
    }
    synthetic_counts = {
        "rectangle": (0, 0),
        "left_notch": (1, 0),
        "both_notches": (1, 1),
    }
    for case, expected_counts in synthetic_counts.items():
        folder = synthetic / case
        folder.mkdir()
        mask = np.zeros((160, 140), np.uint8)
        mask[20:141, 50:91] = 255
        if case != "rectangle":
            mask[75:90, 50:60] = 0
        if case == "both_notches":
            mask[75:80, 84:91] = 0
        synthetic_image = np.full((160, 140, 3), 35, np.uint8)
        synthetic_image[mask > 0] = 200
        save_image(folder / "input.png", synthetic_image)
        for filename in stages:
            execute(project, folder, filename, synthetic_settings)
        rows = read_csv(folder / "results/08_candidate_sizes.csv")
        summary = read_csv(folder / "results/08_candidate_summary.csv")
        assert (
            int(summary[0]["candidate_count"]),
            int(summary[1]["candidate_count"]),
        ) == expected_counts
        if case != "rectangle":
            assert rows[0]["max_inward_px"] == "10.00"
            assert rows[0]["span_along_reference_px"] == "14.00"
        if case == "both_notches":
            assert rows[1]["max_inward_px"] == "7.00"
            assert rows[1]["span_along_reference_px"] == "4.00"
        report["cases"][case] = {"summary": summary}
    for filename, csv_name in (
        ("04_compare_lengths.py", "03_side_lengths.csv"),
        ("09_compare_candidates.py", "08_candidate_summary.csv"),
    ):
        comparison_inputs = tuple(
            (case, f"{case}/results/{csv_name}") for case in synthetic_counts
        )
        execute(
            project,
            synthetic,
            filename,
            {"INPUT_CSVS": comparison_inputs, "BASELINE_ID": "rectangle"},
        )

    for name, expected_hash in originals.items():
        assert (
            hashlib.sha256((project / name).read_bytes()).hexdigest() == expected_hash
        ), name
    report["original_files_unchanged"] = list(originals)
    report["artificial_change"] = (
        "left edge removed by 80px at original y=600..620; not a rolling pass"
    )
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"既知形状・候補比較・入力保護の検証完了: {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, default=Path("tests/results/shape_pipeline_20261013")
    )
    arguments = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    verify(project, (project / arguments.out).resolve())
