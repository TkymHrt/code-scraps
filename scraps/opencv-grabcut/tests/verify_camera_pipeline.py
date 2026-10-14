"""独立スクリプトで板生成・カメラ校正・画像補正・03・CSV換算まで動かす."""

import argparse
import ast
import csv
import os
import runpy
import subprocess
import sys
from pathlib import Path

import cv2 as cv
import numpy as np
from test_camera_conversion import calibration_photos, copy_script, rendered_scene
from test_submissions import SubmissionTests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, default=Path("tests/results/camera_cli_20261014")
    )
    arguments = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    output = (project / arguments.out).resolve()
    if (
        not output.is_relative_to((project / "tests/results").resolve())
        or output.exists()
    ):
        raise ValueError("tests/results内の、まだ存在しない検証先を指定してください")
    output.mkdir(parents=True)
    logs = []

    def execute(script):
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=output.parent,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        logs.append(result.stdout)
        return result.stdout

    execute(copy_script("generate_charuco_board.py", output))
    photos = output / "input/camera_calibration"
    photos.mkdir(parents=True)
    calibration_photos(photos)
    text = execute(copy_script("camera_calibration.py", output))
    (output / "camera_calibration.txt").write_text(text, encoding="utf-8")
    block = text[text.index("CALIBRATION_SIZE = ") :]
    camera_settings = {}
    for node in ast.parse(block).body:
        assert isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
        camera_settings[node.targets[0].id] = ast.literal_eval(node.value)

    measured_paths = []
    for index, (rotation, translation) in enumerate(
        [
            ((0.12, -0.22, 0.03), (-170, -65, 600)),
            ((-0.20, 0.18, -0.10), (-150, -100, 650)),
        ]
    ):
        directory = output / f"撮影{index + 1}"
        directory.mkdir()
        source = directory / "source.png"
        _, encoded = cv.imencode(".png", rendered_scene(rotation, translation))
        source.write_bytes(encoded.tobytes())
        original = source.read_bytes()
        corrected = directory / "rectified.png"
        calibration = directory / "image_calibration.csv"
        execute(
            copy_script(
                "rectify_image.py",
                directory,
                INPUT_PATH=str(source),
                OUTPUT_IMAGE_PATH=str(corrected),
                OUTPUT_CSV_PATH=str(calibration),
                **camera_settings,
            )
        )
        image = cv.imdecode(
            np.frombuffer(corrected.read_bytes(), np.uint8), cv.IMREAD_COLOR
        )
        assert image is not None
        height, width = image.shape[:2]
        ys, xs = np.nonzero(cv.inRange(image, (20, 75, 145), (90, 145, 220)))
        x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
        assert abs((y1 - y0) * 0.25 - 150) < 1
        source_csv = directory / "03_side_lengths.csv"
        measurement = directory / "03_side_lengths.py"
        measurement.write_text(
            SubmissionTests().submission_source(
                "03_side_lengths.py",
                INPUT_PATH=str(corrected),
                OUTPUT_IMAGE_PATH=str(directory / "03_side_lengths.png"),
                OUTPUT_CSV_PATH=str(source_csv),
                CANDIDATE_RECT=(
                    (x0 - 12) / width,
                    (y0 - 12) / height,
                    (x1 + 12) / width,
                    (y1 + 12) / height,
                ),
                BACKGROUND_RECTS=(
                    (0.0, 0.0, (x0 - 20) / width, 1.0),
                    ((x1 + 20) / width, 0.0, 1.0, 1.0),
                ),
                FOREGROUND_RECTS=(
                    (
                        (x0 + 10) / width,
                        (y0 + 10) / height,
                        (x1 - 10) / width,
                        (y1 - 10) / height,
                    ),
                ),
                START_Y=y0,
                END_Y=y1,
            ),
            encoding="utf-8",
        )
        execute(measurement)
        destination = directory / "calibrated_lengths.csv"
        conversion = copy_script(
            "calibrate_lengths.py",
            directory,
            INPUT_CSV_PATH=str(source_csv),
            CALIBRATION_CSV_PATH=str(calibration),
            OUTPUT_CSV_PATH=str(destination),
        )
        before = (
            source.read_bytes(),
            corrected.read_bytes(),
            source_csv.read_bytes(),
            calibration.read_bytes(),
        )
        execute(conversion)
        assert before == (
            source.read_bytes(),
            corrected.read_bytes(),
            source_csv.read_bytes(),
            calibration.read_bytes(),
        )
        assert source.read_bytes() == original
        # 画像を退避した後も、別プロセスでCSVだけから同じ結果になる。
        source.rename(directory / "archived_source.png")
        corrected.rename(directory / "archived_rectified.png")
        saved = destination.read_bytes()
        execute(conversion)
        assert destination.read_bytes() == saved
        with destination.open(encoding="utf-8-sig", newline="") as source_file:
            row = list(csv.DictReader(source_file))[0]
        for edge in ("left", "right", "total"):
            assert float(row[f"{edge}_mm"]) == float(row[f"{edge}_px"]) * 0.25
        logs.append(
            f"撮影{index + 1}: 上下間隔 {(y1 - y0) * 0.25:.2f}mm / 側辺長 左{row['left_mm']}mm・右{row['right_mm']}mm\n"
        )
        measured_paths.append(destination)

    comparison = runpy.run_path(str(project / "submissions/length_comparison_gui.py"))
    samples = []
    for index, path in enumerate(measured_paths):
        samples.append(
            {"sample_id": f"撮影{index + 1}", "csv_path": path, "thickness_mm": 10}
        )
    compared = comparison["compare_lengths"](samples, 150, 10)
    assert len(compared) == 2
    (output / "verification.txt").write_text("\n".join(logs), encoding="utf-8")
    print("板生成・12枚のカメラ校正・2画像の補正・03計測・CSV換算・複数比較を確認")
    print("元画像・補正PNGがなくても、換算係数CSVと03 CSVだけで同じmm値を保存")
    print(f"結果: {output}")


if __name__ == "__main__":
    main()
