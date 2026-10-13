"""提出版を1本ずつコピーし、初期指定と実際の抽出結果を確認する."""

import ast
import csv
import math
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2 as cv
import numpy as np


class SubmissionTests(unittest.TestCase):
    def submission_source(self, filename: str, **overrides: object) -> str:
        """コピーの設定だけを合成画像用に替え、手元の実画像設定を使わない."""
        path = Path(__file__).resolve().parents[1] / "submissions" / filename
        source = path.read_text(encoding="utf-8")
        stem = path.stem
        settings = {
            "INPUT_PATH": "input.png",
            "OUTPUT_PATH": f"results/{stem}.png",
            "OUTPUT_IMAGE_PATH": f"results/{stem}.png",
            "OUTPUT_CSV_PATH": f"results/{stem}.csv",
            "CANDIDATE_RECT": (0.34, 0.0, 0.705, 1.0),
            "BACKGROUND_RECTS": ((0.0, 0.0, 0.33, 1.0), (0.72, 0.0, 1.0, 1.0)),
            "FOREGROUND_RECTS": ((0.48, 0.4, 0.56, 0.6),),
            "ITERATIONS": 5,
            "RANDOM_SEED": 0,
            "START_Y": 0,
            "END_Y": None,
        }
        settings.update(overrides)
        lines = source.splitlines(keepends=True)
        for node in reversed(ast.parse(source).body):
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                if name in settings:
                    lines[node.lineno - 1 : node.end_lineno] = [
                        f"{name} = {settings[name]!r}\n"
                    ]
        return "".join(lines)

    def temporary_directory(self) -> tempfile.TemporaryDirectory[str]:
        """既存入力を触らず、試験結果フォルダ内だけで実行する."""
        results = Path(__file__).resolve().parents[1] / "tests" / "results"
        results.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=results)
        if not Path(temporary.name).resolve().is_relative_to(results.resolve()):
            raise ValueError("検証用の一時領域が試験結果フォルダ外にあります")
        return temporary

    def test_initial_overlay_matches_mask_given_to_grabcut(self) -> None:
        """重なった指定を含め、01の表示と02に渡す指定が一致する."""
        with self.temporary_directory() as temporary:
            directory = Path(temporary)
            image = np.full((100, 100, 3), 100, np.uint8)
            self.assertTrue(cv.imwrite(str(directory / "input.png"), image))
            for filename in ("01_initial_regions.py", "02_grabcut_mask.py"):
                source = self.submission_source(filename)
                source = source.replace(
                    "FOREGROUND_RECTS = ((0.48, 0.4, 0.56, 0.6),)",
                    "FOREGROUND_RECTS = ((0.30, 0.4, 0.56, 0.6),)",
                )
                (directory / filename).write_text(source, encoding="utf-8")

            def inspect_initial_mask(
                image: np.ndarray, labels: np.ndarray, *unused: object
            ) -> None:
                overlay = cv.imread(str(directory / "results/01_initial_regions.png"))
                if overlay is None:
                    self.fail("初期指定の重ね画像を読み込めません")
                # x=31は背景と前景の指定が重なり、後の前景が優先される。
                for x, y, label, color in (
                    (10, 10, cv.GC_BGD, (255, 80, 0)),
                    (80, 10, cv.GC_BGD, (255, 80, 0)),
                    (33, 10, cv.GC_PR_BGD, (64, 64, 64)),
                    (40, 10, cv.GC_PR_FGD, (0, 165, 255)),
                    (31, 50, cv.GC_FGD, (0, 255, 0)),
                ):
                    self.assertEqual(labels[y, x], label)
                    tint = np.full((1, 1, 3), color, np.uint8)
                    expected = cv.addWeighted(
                        image[y : y + 1, x : x + 1], 0.65, tint, 0.35, 0
                    )
                    np.testing.assert_array_equal(overlay[y, x], expected[0, 0])
                # 抽出失敗の黒いマスクも、輪郭処理を要求せず保存できる。
                labels[:] = cv.GC_BGD

            with patch.object(
                cv, "grabCut", side_effect=AssertionError("Unexpected GrabCut")
            ):
                runpy.run_path(str(directory / "01_initial_regions.py"))
            with (
                patch.object(cv, "grabCut", side_effect=inspect_initial_mask),
                patch.object(
                    cv, "findContours", side_effect=AssertionError("Unexpected contour")
                ),
            ):
                runpy.run_path(str(directory / "02_grabcut_mask.py"))
            mask = cv.imread(
                str(directory / "results/02_grabcut_mask.png"), cv.IMREAD_GRAYSCALE
            )
            self.assertIsNotNone(mask)
            np.testing.assert_array_equal(mask, np.zeros((100, 100), np.uint8))

    def test_real_grabcut_preserves_hole_and_separate_foreground(self) -> None:
        """既知の合成画像を実際のGrabCutで抽出し、画素単位で照合する."""
        with self.temporary_directory() as temporary:
            directory = Path(temporary)
            expected = np.zeros((160, 140), np.uint8)
            expected[20:141, 50:91] = 255
            expected[50:65, 55:61] = 0
            expected[8:14, 50:57] = 255
            image = np.full((160, 140, 3), 35, np.uint8)
            image[expected > 0] = 200
            self.assertTrue(cv.imwrite(str(directory / "input.png"), image))
            filename = "02_grabcut_mask.py"
            source = self.submission_source(filename)
            script = directory / filename
            script.write_text(source, encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(script)],
                cwd=directory,
                capture_output=True,
                check=False,
            )
            self.assertEqual(
                completed.returncode, 0, completed.stderr.decode(errors="replace")
            )
            mask = cv.imread(
                str(directory / "results/02_grabcut_mask.png"), cv.IMREAD_GRAYSCALE
            )
            self.assertIsNotNone(mask)
            np.testing.assert_array_equal(mask, expected)

    def test_real_side_edges_match_known_shapes_and_overlay(self) -> None:
        """実際のGrabCutで5形状を抽出し、全行の座標と赤線を照合する."""
        project = Path(__file__).resolve().parents[1]
        filename = "03_side_edges.py"
        source = self.submission_source(filename)
        with self.temporary_directory() as temporary:
            for shape in (
                "rectangle",
                "notch",
                "zigzag",
                "diagonal",
                "hole_and_island",
            ):
                with self.subTest(shape=shape):
                    directory = Path(temporary) / shape
                    directory.mkdir()
                    mask = np.zeros((160, 140), np.uint8)
                    expected = []
                    for y in range(20, 141):
                        left_x, right_x = 50, 90
                        if shape == "notch" and 75 <= y < 90:
                            left_x = 60
                        elif shape == "zigzag" and y % 2 == 1:
                            left_x = 54
                        elif shape == "diagonal":
                            left_x = 50 + (y - 20) // 8
                            right_x = 79 + (y - 20) // 8
                        mask[y, left_x : right_x + 1] = 255
                        expected.append((y, left_x, right_x))
                    if shape == "hole_and_island":
                        mask[50:65, 55:61] = 0
                        mask[8:14, 50:57] = 255
                    image = np.full((160, 140, 3), 35, np.uint8)
                    image[mask > 0] = 200
                    self.assertTrue(cv.imwrite(str(directory / "input.png"), image))
                    script = directory / filename
                    script.write_text(source, encoding="utf-8")
                    completed = subprocess.run(
                        [sys.executable, str(script)],
                        cwd=project,
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(
                        completed.returncode,
                        0,
                        completed.stderr.decode(errors="replace"),
                    )
                    with (directory / "results/03_side_edges.csv").open(
                        encoding="utf-8", newline=""
                    ) as output:
                        reader = csv.reader(output)
                        self.assertEqual(next(reader), ["y", "left_x", "right_x"])
                        actual = [tuple(map(int, row)) for row in reader]
                    self.assertEqual(actual, expected)
                    overlay = cv.imread(str(directory / "results/03_side_edges.png"))
                    if overlay is None:
                        self.fail("左右端の重ね画像を読み込めません")
                    self.assertEqual(overlay.shape, image.shape)
                    for y, left_x, right_x in expected:
                        self.assertEqual(overlay[y, left_x].tolist(), [0, 0, 255])
                        self.assertEqual(overlay[y, right_x].tolist(), [0, 0, 255])
                    # 上下辺の中央と、試料のない行には赤線を描かない。
                    for y, x in ((20, 70), (140, 70), (10, 53)):
                        np.testing.assert_array_equal(overlay[y, x], image[y, x])

    def test_real_side_lengths_match_known_lengths_and_coordinate_csv(self) -> None:
        """7形状で既知の長さと、独立実行した03の点列からの長さを照合する."""
        project = Path(__file__).resolve().parents[1]
        with self.temporary_directory() as temporary:
            for shape in (
                "rectangle",
                "wide_rectangle",
                "notch",
                "double_notch",
                "zigzag",
                "diagonal",
                "hole_and_island",
            ):
                with self.subTest(shape=shape):
                    directory = Path(temporary) / shape
                    directory.mkdir()
                    mask = np.zeros((160, 140), np.uint8)
                    for y in range(20, 141):
                        left_x, right_x = 50, 90
                        if shape == "wide_rectangle":
                            left_x, right_x = 47, 95
                        elif shape == "notch" and 75 <= y < 90:
                            left_x = 60
                        elif shape == "double_notch" and 75 <= y < 90:
                            left_x, right_x = 53, 87
                        elif shape == "zigzag" and y % 2 == 1:
                            left_x = 54
                        elif shape == "diagonal":
                            left_x = 50 + (y - 20) // 8
                            right_x = 79 + (y - 20) // 8
                        mask[y, left_x : right_x + 1] = 255
                    if shape == "hole_and_island":
                        mask[50:65, 55:61] = 0
                        mask[8:14, 50:57] = 255
                    image = np.full((160, 140, 3), 35, np.uint8)
                    image[mask > 0] = 200
                    self.assertTrue(cv.imwrite(str(directory / "input.png"), image))

                    # 04は03がない状態で実行し、前段階への依存がないことを確認。
                    for filename in ("04_side_lengths.py", "03_side_edges.py"):
                        script = directory / filename
                        script.write_text(
                            self.submission_source(filename),
                            encoding="utf-8",
                        )
                        completed = subprocess.run(
                            [sys.executable, str(script)],
                            cwd=project,
                            capture_output=True,
                            check=False,
                        )
                        self.assertEqual(
                            completed.returncode,
                            0,
                            completed.stderr.decode(errors="replace"),
                        )

                    # 120区間のうち、xが変わる区間の数と既知のx差から求める。
                    left_length = right_length = 120.0
                    if shape == "notch":
                        left_length = 118 + 2 * math.sqrt(101)
                    elif shape == "double_notch":
                        left_length = right_length = 118 + 2 * math.sqrt(10)
                    elif shape == "zigzag":
                        left_length = 120 * math.sqrt(17)
                    elif shape == "diagonal":
                        left_length = right_length = 105 + 15 * math.sqrt(2)
                    expected = {
                        "left": f"{left_length:.2f}",
                        "right": f"{right_length:.2f}",
                        "total": f"{left_length + right_length:.2f}",
                    }
                    with (directory / "results/04_side_lengths.csv").open(
                        encoding="utf-8", newline=""
                    ) as output:
                        reader = csv.DictReader(output)
                        self.assertEqual(
                            reader.fieldnames, ["edge", "length_px", "start_y", "end_y"]
                        )
                        rows = list(reader)
                    self.assertEqual(
                        [row["edge"] for row in rows], ["left", "right", "total"]
                    )
                    lengths = {row["edge"]: row["length_px"] for row in rows}
                    self.assertEqual(lengths, expected)
                    for row in rows:
                        self.assertEqual((row["start_y"], row["end_y"]), ("0", "159"))

                    with (directory / "results/03_side_edges.csv").open(
                        encoding="utf-8", newline=""
                    ) as output:
                        points = list(csv.DictReader(output))
                    for edge in ("left", "right"):
                        length_from_csv = sum(
                            math.hypot(
                                int(after[f"{edge}_x"]) - int(before[f"{edge}_x"]),
                                int(after["y"]) - int(before["y"]),
                            )
                            for before, after in zip(points, points[1:])
                        )
                        self.assertEqual(lengths[edge], f"{length_from_csv:.2f}")

    def test_side_lengths_reject_empty_and_single_row_without_saving(self) -> None:
        """側辺長が成立しない抽出結果で、ゼロ長のCSVを保存しない."""
        with self.temporary_directory() as temporary:
            for shape, message in (
                ("empty", "試料の領域が見つかりません"),
                ("single_row", "試料が2行以上必要です"),
            ):
                with self.subTest(shape=shape):
                    directory = Path(temporary) / shape
                    directory.mkdir()
                    image = np.full((100, 100, 3), 100, np.uint8)
                    self.assertTrue(cv.imwrite(str(directory / "input.png"), image))
                    filename = "04_side_lengths.py"
                    script = directory / filename
                    script.write_text(
                        self.submission_source(filename),
                        encoding="utf-8",
                    )

                    def fixed_mask(
                        image: np.ndarray, labels: np.ndarray, *unused: object
                    ) -> None:
                        labels[:] = cv.GC_BGD
                        if shape == "single_row":
                            labels[50, 40:61] = cv.GC_PR_FGD

                    with (
                        patch.object(cv, "grabCut", side_effect=fixed_mask),
                        self.assertRaisesRegex(ValueError, message),
                    ):
                        runpy.run_path(str(script))
                    self.assertFalse(
                        (directory / "results/04_side_lengths.csv").exists()
                    )
                    self.assertFalse(
                        (directory / "results/04_side_lengths.png").exists()
                    )

    def test_side_edges_save_single_row_points(self) -> None:
        """1行だけの抽出結果でも、CSVと同じ端の画素を表示する."""
        with self.temporary_directory() as temporary:
            directory = Path(temporary)
            image = np.full((100, 100, 3), 100, np.uint8)
            self.assertTrue(cv.imwrite(str(directory / "input.png"), image))
            filename = "03_side_edges.py"
            script = directory / filename
            script.write_text(self.submission_source(filename), encoding="utf-8")

            def single_row(
                image: np.ndarray, labels: np.ndarray, *unused: object
            ) -> None:
                labels[:] = cv.GC_BGD
                labels[50, 40:61] = cv.GC_PR_FGD

            with patch.object(cv, "grabCut", side_effect=single_row):
                runpy.run_path(str(script))
            with (directory / "results/03_side_edges.csv").open(
                encoding="utf-8", newline=""
            ) as output:
                self.assertEqual(
                    list(csv.reader(output)),
                    [["y", "left_x", "right_x"], ["50", "40", "60"]],
                )
            overlay = cv.imread(str(directory / "results/03_side_edges.png"))
            if overlay is None:
                self.fail("左右端の重ね画像を読み込めません")
            self.assertEqual(overlay[50, 40].tolist(), [0, 0, 255])
            self.assertEqual(overlay[50, 60].tolist(), [0, 0, 255])
            np.testing.assert_array_equal(overlay[50, 50], image[50, 50])

    def test_real_measurement_range_excludes_irregular_end_faces(self) -> None:
        """斜めで不規則な端面を除外し、元座標・長さ・確認画像を照合する."""
        project = Path(__file__).resolve().parents[1]
        with self.temporary_directory() as temporary:
            directory = Path(temporary)
            mask = np.zeros((160, 140), np.uint8)
            for x in range(50, 91):
                top = 20 + (x - 50) // 4 + int(x % 3 == 0)
                bottom = 130 + (x - 50) // 4 - int(x % 4 == 0)
                mask[top : bottom + 1, x] = 255
            mask[75:90, 50:60] = 0
            image = np.full((160, 140, 3), 35, np.uint8)
            image[mask > 0] = 200
            self.assertTrue(cv.imwrite(str(directory / "input.png"), image))
            for filename in ("04_side_lengths.py", "03_side_edges.py"):
                source = self.submission_source(filename)
                source = source.replace("START_Y = 0", "START_Y = 40")
                source = source.replace("END_Y = None", "END_Y = 120")
                script = directory / filename
                script.write_text(source, encoding="utf-8")
                completed = subprocess.run(
                    [sys.executable, str(script)],
                    cwd=project,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(
                    completed.returncode, 0, completed.stderr.decode(errors="replace")
                )

            expected = [(y, 60 if 75 <= y < 90 else 50, 90) for y in range(40, 121)]
            with (directory / "results/03_side_edges.csv").open(
                encoding="utf-8", newline=""
            ) as output:
                actual = [
                    tuple(map(int, row.values())) for row in csv.DictReader(output)
                ]
            self.assertEqual(actual, expected)
            with (directory / "results/04_side_lengths.csv").open(
                encoding="utf-8", newline=""
            ) as output:
                rows = list(csv.DictReader(output))
            lengths = {row["edge"]: row["length_px"] for row in rows}
            self.assertEqual(
                lengths,
                {
                    "left": f"{78 + 2 * math.sqrt(101):.2f}",
                    "right": "80.00",
                    "total": f"{158 + 2 * math.sqrt(101):.2f}",
                },
            )
            for row in rows:
                self.assertEqual((row["start_y"], row["end_y"]), ("40", "120"))
            overlay = cv.imread(str(directory / "results/03_side_edges.png"))
            length_image = cv.imread(str(directory / "results/04_side_lengths.png"))
            if overlay is None or length_image is None:
                self.fail("計測範囲の確認画像を読み込めません")
            self.assertEqual(overlay.shape, image.shape)
            np.testing.assert_array_equal(overlay, length_image)
            for y, left_x, right_x in expected:
                self.assertEqual(overlay[y, left_x].tolist(), [0, 0, 255])
                self.assertEqual(overlay[y, right_x].tolist(), [0, 0, 255])
            for y in (40, 120):
                self.assertEqual(overlay[y, 10].tolist(), [0, 255, 255])
            for y in (30, 130):
                expected_gray = cv.addWeighted(
                    image[y : y + 1], 0.4, np.full_like(image[y : y + 1], 220), 0.6, 0
                )
                np.testing.assert_array_equal(overlay[y], expected_gray[0])
            np.testing.assert_array_equal(overlay[60, 70], image[60, 70])

    def test_measurement_range_rejects_invalid_and_empty_selections(self) -> None:
        """範囲の誤り・試料なし・長さを測れない1行を保存前に検出する."""
        with self.temporary_directory() as temporary:
            for filename in ("03_side_edges.py", "04_side_lengths.py"):
                for name, start, end in (
                    ("negative", -1, 80),
                    ("reversed", 80, 40),
                    ("outside", 0, 100),
                    ("empty", 0, 10),
                    ("single_row", 50, 50),
                ):
                    if filename == "03_side_edges.py" and name == "single_row":
                        continue
                    with self.subTest(filename=filename, selection=name):
                        directory = Path(temporary) / f"{Path(filename).stem}_{name}"
                        directory.mkdir()
                        image = np.full((100, 100, 3), 100, np.uint8)
                        self.assertTrue(cv.imwrite(str(directory / "input.png"), image))
                        source = self.submission_source(filename)
                        source = source.replace("START_Y = 0", f"START_Y = {start}")
                        source = source.replace("END_Y = None", f"END_Y = {end}")
                        script = directory / filename
                        script.write_text(source, encoding="utf-8")

                        def fixed_mask(
                            image: np.ndarray, labels: np.ndarray, *unused: object
                        ) -> None:
                            labels[:] = cv.GC_BGD
                            labels[20:81, 40:61] = cv.GC_PR_FGD

                        with (
                            patch.object(cv, "grabCut", side_effect=fixed_mask),
                            self.assertRaisesRegex(ValueError, "計測範囲"),
                        ):
                            runpy.run_path(str(script))
                        prefix = Path(filename).stem
                        self.assertFalse(
                            (directory / "results" / f"{prefix}.png").exists()
                        )
                        self.assertFalse(
                            (directory / "results" / f"{prefix}.csv").exists()
                        )

    def test_side_edges_reject_empty_extraction_without_saving(self) -> None:
        """抽出領域がない場合に、空の座標CSVや結果画像を保存しない."""
        with self.temporary_directory() as temporary:
            directory = Path(temporary)
            image = np.full((100, 100, 3), 100, np.uint8)
            self.assertTrue(cv.imwrite(str(directory / "input.png"), image))
            filename = "03_side_edges.py"
            script = directory / filename
            script.write_text(self.submission_source(filename), encoding="utf-8")

            def empty_mask(
                image: np.ndarray, labels: np.ndarray, *unused: object
            ) -> None:
                labels[:] = cv.GC_BGD

            with (
                patch.object(cv, "grabCut", side_effect=empty_mask),
                self.assertRaisesRegex(ValueError, "試料の領域が見つかりません"),
            ):
                runpy.run_path(str(script))
            self.assertFalse((directory / "results/03_side_edges.png").exists())
            self.assertFalse((directory / "results/03_side_edges.csv").exists())

    def test_unicode_paths_with_spaces_relative_and_absolute(self) -> None:
        """日本語・空白・絶対/相対パスで、独立実行とPNG・CSV保存を確認する."""
        project = Path(__file__).resolve().parents[1]
        filenames = (
            "01_initial_regions.py",
            "02_grabcut_mask.py",
            "03_side_edges.py",
            "04_side_lengths.py",
        )
        with self.temporary_directory() as temporary:
            workspace = Path(temporary) / "日本語 フォルダ"
            inputs = workspace / "入力 資料"
            inputs.mkdir(parents=True)
            expected_mask = np.zeros((160, 140), np.uint8)
            expected_mask[20:141, 50:91] = 255
            image = np.full((160, 140, 3), 35, np.uint8)
            image[expected_mask > 0] = 200
            input_path = inputs / "試料 画像.png"
            success, encoded = cv.imencode(".png", image)
            self.assertTrue(success)
            input_path.write_bytes(encoded.tobytes())
            original_bytes = input_path.read_bytes()
            for mode in ("relative", "absolute"):
                directory = workspace / mode
                directory.mkdir()
                for filename in filenames:
                    with self.subTest(mode=mode, filename=filename):
                        stem = Path(filename).stem
                        output_image = directory / "出力 結果" / f"{stem}_確認.png"
                        output_csv = directory / "出力 結果" / f"{stem}_座標.csv"
                        source = self.submission_source(
                            filename,
                            INPUT_PATH=(
                                "../入力 資料/試料 画像.png"
                                if mode == "relative"
                                else str(input_path)
                            ),
                            OUTPUT_PATH=(
                                f"出力 結果/{output_image.name}"
                                if mode == "relative"
                                else str(output_image)
                            ),
                            OUTPUT_IMAGE_PATH=(
                                f"出力 結果/{output_image.name}"
                                if mode == "relative"
                                else str(output_image)
                            ),
                            OUTPUT_CSV_PATH=(
                                f"出力 結果/{output_csv.name}"
                                if mode == "relative"
                                else str(output_csv)
                            ),
                        )
                        script = directory / filename
                        script.write_text(source, encoding="utf-8")
                        completed = subprocess.run(
                            [sys.executable, str(script)],
                            cwd=project,
                            capture_output=True,
                            check=False,
                        )
                        self.assertEqual(
                            completed.returncode,
                            0,
                            completed.stderr.decode(errors="replace"),
                        )
                        output = cv.imdecode(
                            np.frombuffer(output_image.read_bytes(), np.uint8),
                            cv.IMREAD_UNCHANGED,
                        )
                        if output is None:
                            self.fail("日本語パスへ保存した確認画像を読み込めません")
                        if filename == "02_grabcut_mask.py":
                            np.testing.assert_array_equal(output, expected_mask)
                        else:
                            self.assertEqual(output.shape, image.shape)
                        if filename == "03_side_edges.py":
                            with output_csv.open(encoding="utf-8", newline="") as saved:
                                self.assertEqual(
                                    list(csv.reader(saved)),
                                    [["y", "left_x", "right_x"]]
                                    + [[str(y), "50", "90"] for y in range(20, 141)],
                                )
                        elif filename == "04_side_lengths.py":
                            with output_csv.open(encoding="utf-8", newline="") as saved:
                                self.assertEqual(
                                    list(csv.reader(saved)),
                                    [
                                        ["edge", "length_px", "start_y", "end_y"],
                                        ["left", "120.00", "0", "159"],
                                        ["right", "120.00", "0", "159"],
                                        ["total", "240.00", "0", "159"],
                                    ],
                                )
            self.assertEqual(input_path.read_bytes(), original_bytes)


if __name__ == "__main__":
    unittest.main()
