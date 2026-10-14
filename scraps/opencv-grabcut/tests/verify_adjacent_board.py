"""元の生成画像の試料隣にChArUco板を仮合成し、補正・03・CSV換算を確認する."""

import argparse
import csv
import hashlib
import io
import json
import runpy
from contextlib import redirect_stdout
from pathlib import Path

import cv2 as cv
import numpy as np
from test_camera_conversion import copy_script

PIXELS_PER_MM = 4
START_Y = 80
END_Y = 1000


def save_image(path, image):
    success, encoded = cv.imencode(".png", image)
    if not success:
        raise OSError(f"検証画像を保存できません: {path}")
    path.write_bytes(encoded.tobytes())


def execute(filename, directory, **settings):
    path = copy_script(filename, directory, **settings)
    log = io.StringIO()
    with redirect_stdout(log):
        values = runpy.run_path(str(path), run_name="__main__")
    (directory / f"{path.stem}.log").write_text(log.getvalue(), encoding="utf-8")
    return values


def read_row(path):
    with path.open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))[0]


def distort(image, matrix, coefficients, background):
    height, width = image.shape[:2]
    ys, xs = np.indices((height, width), dtype=np.float32)
    pixels = np.column_stack((xs.ravel(), ys.ravel())).reshape(-1, 1, 2)
    # 歪んだ画像の各画素に対応する、歪みなし画像の座標を求めて描く。
    source = cv.undistortPoints(pixels, matrix, coefficients, P=matrix).reshape(-1, 2)
    map_x = source[:, 0].reshape(height, width)
    map_y = source[:, 1].reshape(height, width)
    return cv.remap(
        image,
        map_x,
        map_y,
        cv.INTER_LINEAR,
        borderMode=cv.BORDER_CONSTANT,
        borderValue=background,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, default=Path("tests/results/adjacent_board_20261014")
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
    input_path = project / "submissions/input/赤茶色の床と剥離した金属帯.png"
    original_bytes = input_path.read_bytes()
    original_hash = hashlib.sha256(original_bytes).hexdigest()
    image = cv.imdecode(np.frombuffer(original_bytes, np.uint8), cv.IMREAD_COLOR)
    if image is None:
        raise OSError("元の生成画像を読み込めません")
    height, width = image.shape[:2]

    baseline_folder = output / "original"
    baseline_folder.mkdir()
    baseline = execute(
        "03_side_lengths.py",
        baseline_folder,
        INPUT_PATH=str(input_path),
        OUTPUT_IMAGE_PATH=str(baseline_folder / "03_side_lengths.png"),
        OUTPUT_CSV_PATH=str(baseline_folder / "03_side_lengths.csv"),
        START_Y=START_Y,
        END_Y=END_Y,
    )
    baseline_lengths = {
        "left": baseline["left_length"] / PIXELS_PER_MM,
        "right": baseline["right_length"] / PIXELS_PER_MM,
        "total": baseline["total_length"] / PIXELS_PER_MM,
    }
    slab_right = int(np.max(np.nonzero(baseline["mask"])[1]))
    board_left = slab_right + 40
    board_folder = output / "board"
    board_folder.mkdir()
    execute("generate_charuco_board.py", board_folder, PIXELS_PER_MM=PIXELS_PER_MM)
    board_path = board_folder / "results/charuco_board.png"
    board_image = cv.imdecode(
        np.frombuffer(board_path.read_bytes(), np.uint8), cv.IMREAD_COLOR
    )
    assert board_image is not None
    board_height, board_width = board_image.shape[:2]
    board_top = (height - board_height) // 2
    extended_width = max(width, board_left + board_width + 40)
    background = tuple(
        int(value) for value in np.median(image[:, width - 150 :], axis=(0, 1))
    )
    composite = np.full((height, extended_width, 3), background, np.uint8)
    composite[:height, :width] = image
    composite[
        board_top : board_top + board_height, board_left : board_left + board_width
    ] = board_image
    # 隣への仮合成だけで、元の試料画素を変更していないことを確認する。
    specimen = baseline["mask"] > 0
    assert np.array_equal(composite[:, :width][specimen], image[specimen])
    save_image(output / "input_with_board.png", composite)

    matrix = np.array([[1800.0, 0, width / 2], [0, 1800.0, height / 2], [0, 0, 1]])
    frame = np.array(
        [
            [0, 0],
            [extended_width - 1, 0],
            [extended_width - 1, height - 1],
            [0, height - 1],
        ],
        np.float32,
    )
    tilted_frame = np.array(
        [
            [80, 65],
            [extended_width - 110, 20],
            [extended_width - 35, height - 55],
            [25, height - 15],
        ],
        np.float32,
    )
    perspective = cv.getPerspectiveTransform(frame, tilted_frame)
    tilted = cv.warpPerspective(
        composite,
        perspective,
        (extended_width, height),
        flags=cv.INTER_LINEAR,
        borderValue=background,
    )
    coefficients = np.array([-0.12, 0.025, 0.0005, -0.0008, 0.0])
    distorted = distort(tilted, matrix, coefficients, background)
    cases = (
        ("front", "正対・歪みなし", composite, np.zeros(5)),
        ("perspective", "傾きあり・歪みなし", tilted, np.zeros(5)),
        ("lens", "傾き＋仮のレンズ歪み", distorted, coefficients),
    )
    report = {
        "input_kind": "generated_test_image_not_production",
        "original_sha256": original_hash,
        "original_size": [width, height],
        "extended_size": [extended_width, height],
        "board_body_mm": [210, 150],
        "board_pixels_per_mm": PIXELS_PER_MM,
        "board_panel_rect": [
            board_left,
            board_top,
            board_left + board_width,
            board_top + board_height,
        ],
        "sample_to_panel_gap_px": 40,
        "background_bgr": list(background),
        "camera_matrix_is_hypothetical": True,
        "camera_matrix": matrix.tolist(),
        "perspective_transform": perspective.tolist(),
        "baseline_assumed_mm": baseline_lengths,
        "cases": [],
    }
    comparison = runpy.run_path(str(project / "submissions/length_comparison_gui.py"))
    samples = []
    dictionary = cv.aruco.getPredefinedDictionary(cv.aruco.DICT_4X4_50)
    board = cv.aruco.CharucoBoard((7, 5), 30.0, 18.0, dictionary)
    detector = cv.aruco.CharucoDetector(board)
    for name, label, source_image, distortion_coefficients in cases:
        folder = output / name
        folder.mkdir()
        source_path = folder / "input.png"
        corrected_path = folder / "rectified.png"
        calibration_path = folder / "image_calibration.csv"
        save_image(source_path, source_image)
        undistorted = cv.undistort(
            source_image, matrix, distortion_coefficients, None, matrix
        )
        corners, ids, _, _ = detector.detectBoard(undistorted)
        assert corners is not None and ids is not None and len(ids) == 24
        detection = undistorted.copy()
        cv.aruco.drawDetectedCornersCharuco(detection, corners.reshape(-1, 1, 2), ids)
        save_image(folder / "board_detection.png", detection)
        execute(
            "rectify_image.py",
            folder,
            INPUT_PATH=str(source_path),
            OUTPUT_IMAGE_PATH=str(corrected_path),
            OUTPUT_CSV_PATH=str(calibration_path),
            CALIBRATION_SIZE=(extended_width, height),
            CAMERA_MATRIX=matrix.tolist(),
            DIST_COEFFS=distortion_coefficients.tolist(),
        )
        calibration = read_row(calibration_path)
        output_width, output_height = (
            int(calibration["image_width"]),
            int(calibration["image_height"]),
        )
        # 全24点の最初は板の(30,30)mm。仮合成した元画像との対応を計算する。
        margin_px = 10 * PIXELS_PER_MM
        offset_x = (
            float(calibration["reference_x1"])
            - 30 * PIXELS_PER_MM
            - (board_left + margin_px)
        )
        offset_y = (
            float(calibration["reference_y1"])
            - 30 * PIXELS_PER_MM
            - (board_top + margin_px)
        )
        start_y, end_y = round(START_Y + offset_y), round(END_Y + offset_y)
        candidate = baseline["CANDIDATE_RECT"]
        foreground = baseline["FOREGROUND_RECTS"][0]
        lengths_csv = folder / "03_side_lengths.csv"
        measured = execute(
            "03_side_lengths.py",
            folder,
            INPUT_PATH=str(corrected_path),
            OUTPUT_IMAGE_PATH=str(folder / "03_side_lengths.png"),
            OUTPUT_CSV_PATH=str(lengths_csv),
            START_Y=start_y,
            END_Y=end_y,
            CANDIDATE_RECT=(
                (candidate[0] * width + offset_x) / output_width,
                0.0,
                (candidate[2] * width + offset_x) / output_width,
                1.0,
            ),
            BACKGROUND_RECTS=(
                (
                    0.0,
                    0.0,
                    (0.30120481927710846 * width + offset_x) / output_width,
                    1.0,
                ),
                ((0.7028112449799196 * width + offset_x) / output_width, 0.0, 1.0, 1.0),
            ),
            FOREGROUND_RECTS=(
                (
                    (foreground[0] * width + offset_x) / output_width,
                    (START_Y + offset_y) / output_height,
                    (foreground[2] * width + offset_x) / output_width,
                    (END_Y + offset_y) / output_height,
                ),
            ),
        )
        destination = folder / "calibrated_lengths.csv"
        execute(
            "calibrate_lengths.py",
            folder,
            INPUT_CSV_PATH=str(lengths_csv),
            CALIBRATION_CSV_PATH=str(calibration_path),
            OUTPUT_CSV_PATH=str(destination),
        )
        measurement = comparison["read_calibrated_lengths"](destination)
        samples.append(
            {"sample_id": label, "csv_path": destination, "thickness_mm": 10}
        )
        transform = np.array([[1.0, 0, offset_x], [0, 1.0, offset_y]])
        expected_mask = cv.warpAffine(
            baseline["mask"],
            transform,
            (output_width, output_height),
            flags=cv.INTER_NEAREST,
        )
        expected = expected_mask[start_y : end_y + 1] > 0
        actual = measured["mask"][start_y : end_y + 1] > 0
        iou = float(
            np.count_nonzero(expected & actual) / np.count_nonzero(expected | actual)
        )
        assert iou > 0.95, (name, iou)
        panel_left = round(board_left + offset_x)
        panel_top = round(board_top + offset_y)
        board_overlap = int(
            np.count_nonzero(
                measured["mask"][
                    panel_top : panel_top + board_height,
                    panel_left : panel_left + board_width,
                ]
            )
        )
        assert board_overlap == 0
        differences = {}
        for edge in ("left", "right", "total"):
            differences[edge] = (
                measurement[f"{edge}_mm"] / baseline_lengths[edge] - 1
            ) * 100
        item = {
            "name": name,
            "label": label,
            "charuco_corners": len(ids),
            "distortion_coefficients": distortion_coefficients.tolist(),
            "output_size": [output_width, output_height],
            "start_y": start_y,
            "end_y": end_y,
            "reference_mm": float(calibration["reference_mm"]),
            "reference_px": float(calibration["reference_px"]),
            "mm_per_px": measurement["mm_per_px"],
            "left_mm": measurement["left_mm"],
            "right_mm": measurement["right_mm"],
            "total_mm": measurement["total_mm"],
            "difference_from_original_pct": differences,
            "specimen_mask_iou": iou,
            "board_foreground_pixels": board_overlap,
        }
        report["cases"].append(item)
        print(
            f"{label}: 角{len(ids)}点 / 左{item['left_mm']:.3f}mm・右{item['right_mm']:.3f}mm / IoU={iou:.4f}"
        )

    compared = comparison["compare_lengths"](
        samples, (END_Y - START_Y) / PIXELS_PER_MM, 10
    )
    comparison["write_csv"](output / "comparison.csv", compared)
    comparison["write_graph"](output / "comparison.png", compared)
    assert hashlib.sha256(input_path.read_bytes()).hexdigest() == original_hash
    report["original_unchanged"] = True
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# 生成画像の試料隣にChArUco板を置いた仮検証",
        "",
        "実試料・実カメラの測定ではありません。元の生成画像に4px/mmを仮定しています。",
        f"元画像 {width}×{height}px → 右側を背景色で拡張 {extended_width}×{height}px。",
        "板は210×150mm、試料右端から白い外枠まで40px。試料の元画素は変更していません。",
        "画像全体を同じ平面として変形し、カメラ行列・歪み係数は既知の仮値を使っています。",
        "",
        "| 条件 | 検出点 | 左mm | 右mm | 元画像からの左差% | 右差% | mask IoU |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in report["cases"]:
        differences = item["difference_from_original_pct"]
        lines.append(
            f"| {item['label']} | {item['charuco_corners']} | {item['left_mm']:.3f} | {item['right_mm']:.3f} | {differences['left']:.3f} | {differences['right']:.3f} | {item['specimen_mask_iou']:.4f} |"
        )
    lines.extend(
        [
            "",
            "全ケースで板の前景混入は0画素。元画像のSHA256は不変。",
            "03の折れ線長には補間・画素の段差が入ります。配置・寸法・係数・同一平面は仮定です。",
            "input_with_board.png が配置、各ケースのboard_detection.pngが板検出、03_side_lengths.pngが試料の抽出・計測です。",
        ]
    )
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"元画像を保護して、3配置の補正・03・CSV換算・複数比較を確認: {output}")


if __name__ == "__main__":
    main()
