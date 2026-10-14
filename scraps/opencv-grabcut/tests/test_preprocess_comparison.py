"""前処理の比較用スクリプトを単独実行し、03との一致と組み合わせを確認する."""

import ast
import csv
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2 as cv
import numpy as np


class PreprocessComparisonTests(unittest.TestCase):
    def script_source(self, filename: str, **overrides: object) -> str:
        """コピーの設定だけを合成画像用に替え、手元の生成画像設定を使わない."""
        project = Path(__file__).resolve().parents[1]
        if filename == "03_side_lengths.py":
            path = project / "sandbox/previous_submissions" / filename
        else:
            path = project / "sandbox" / filename
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

    def test_preprocessing_original_matches_03_at_original_resolution(self) -> None:
        """比較用スクリプト単独で全ケースを実行し、無処理の長さと端線を03と照合する."""
        project = Path(__file__).resolve().parents[1]
        cases = [
            "original",
            "blur",
            "clahe",
            "gamma",
            "sharp",
            "blur_clahe",
            "clahe_blur",
        ]
        with self.temporary_directory() as temporary:
            directory = Path(temporary) / "日本語の比較 フォルダ"
            directory.mkdir()
            mask = np.zeros((160, 140), np.uint8)
            mask[20:141, 50:91] = 255
            mask[75:90, 50:60] = 0
            image = np.full((160, 140, 3), 35, np.uint8)
            image[mask > 0] = 200
            input_path = directory / "入力 試料.png"
            success, encoded = cv.imencode(".png", image)
            self.assertTrue(success)
            input_path.write_bytes(encoded.tobytes())
            original_bytes = input_path.read_bytes()
            for filename in ("preprocess_comparison.py", "03_side_lengths.py"):
                script = directory / filename
                script.write_text(
                    self.script_source(
                        filename,
                        INPUT_PATH=str(input_path),
                        OUTPUT_DIRECTORY="比較 結果",
                        START_Y=40,
                        END_Y=120,
                    ),
                    encoding="utf-8",
                )
                completed = subprocess.run(
                    [sys.executable, str(script)],
                    cwd=project,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(
                    completed.returncode, 0, completed.stderr.decode(errors="replace")
                )
            results = directory / "比較 結果"
            with (results / "comparison.csv").open(
                encoding="utf-8", newline=""
            ) as saved:
                rows = list(csv.DictReader(saved))
            self.assertEqual([row["case"] for row in rows], cases)
            with (directory / "results/03_side_lengths.csv").open(
                encoding="utf-8", newline=""
            ) as saved:
                expected = {
                    row["edge"]: row["length_px"] for row in csv.DictReader(saved)
                }
            for edge in ("left", "right", "total"):
                self.assertEqual(rows[0][f"{edge}_px"], expected[edge])
                self.assertEqual(rows[0][f"delta_{edge}_px"], "0.00")
            self.assertEqual(
                expected, {"left": "98.10", "right": "80.00", "total": "178.10"}
            )
            for row in rows:
                self.assertEqual((row["start_y"], row["end_y"]), ("40", "120"))
                for edge in ("left", "right", "total"):
                    self.assertAlmostEqual(
                        float(row[f"delta_{edge}_px"]),
                        float(row[f"{edge}_px"]) - float(rows[0][f"{edge}_px"]),
                        delta=0.011,
                    )
                for name in ("processed.png", "mask.png", "overlay.png"):
                    output = cv.imdecode(
                        np.frombuffer(
                            (results / row["case"] / name).read_bytes(), np.uint8
                        ),
                        cv.IMREAD_UNCHANGED,
                    )
                    if output is None:
                        self.fail(f"比較画像を読み込めません: {row['case']}/{name}")
                    self.assertEqual(
                        output.shape, mask.shape if name == "mask.png" else image.shape
                    )
            original_processed = cv.imdecode(
                np.frombuffer(
                    (results / "original/processed.png").read_bytes(), np.uint8
                ),
                cv.IMREAD_COLOR,
            )
            np.testing.assert_array_equal(original_processed, image)
            overlay = cv.imdecode(
                np.frombuffer(
                    (results / "original/overlay.png").read_bytes(), np.uint8
                ),
                cv.IMREAD_COLOR,
            )
            expected_overlay = cv.imdecode(
                np.frombuffer(
                    (directory / "results/03_side_lengths.png").read_bytes(), np.uint8
                ),
                cv.IMREAD_COLOR,
            )
            np.testing.assert_array_equal(overlay, expected_overlay)
            self.assertEqual(input_path.read_bytes(), original_bytes)

    def test_preprocessing_order_and_case_isolation(self) -> None:
        """順序違いを画像へ反映し、初期マスク・モデル・シードを毎回戻す."""
        cases = {
            "original": (),
            "gamma_blur": ("gamma", "blur"),
            "blur_gamma": ("blur", "gamma"),
            "clahe": ("clahe",),
            "sharp": ("sharp",),
        }
        with self.temporary_directory() as temporary:
            directory = Path(temporary)
            image = np.random.default_rng(3).integers(0, 256, (160, 140, 3), np.uint8)
            _, encoded = cv.imencode(".png", image)
            (directory / "input.png").write_bytes(encoded.tobytes())
            script = directory / "preprocess_comparison.py"
            script.write_text(
                self.script_source(script.name, CASES=cases), encoding="utf-8"
            )
            initial_masks = []
            processed_images = []

            def inspect_case(
                processed: np.ndarray,
                labels: np.ndarray,
                rectangle: object,
                background: np.ndarray,
                foreground: np.ndarray,
                *unused: object,
            ) -> None:
                initial_masks.append(labels.copy())
                processed_images.append(processed.copy())
                np.testing.assert_array_equal(background, np.zeros((1, 65)))
                np.testing.assert_array_equal(foreground, np.zeros((1, 65)))
                background[:] = 1
                foreground[:] = 1
                labels[:] = cv.GC_BGD
                labels[20:141, 50:91] = cv.GC_PR_FGD
                labels[50:65, 55:61] = cv.GC_BGD
                if len(processed_images) == 2:
                    labels[75:90, 50:60] = cv.GC_BGD

            with (
                patch.object(cv, "grabCut", side_effect=inspect_case),
                patch.object(cv, "setRNGSeed") as seeds,
            ):
                runpy.run_path(str(script))
            self.assertEqual(
                [args[0][0] for args in seeds.call_args_list], [0] * len(cases)
            )
            for labels in initial_masks[1:]:
                np.testing.assert_array_equal(labels, initial_masks[0])
            np.testing.assert_array_equal(processed_images[0], image)
            self.assertFalse(np.array_equal(processed_images[1], processed_images[2]))
            results = directory / "results/preprocess_comparison"
            for index, case in enumerate(cases):
                processed = cv.imdecode(
                    np.frombuffer(
                        (results / case / "processed.png").read_bytes(), np.uint8
                    ),
                    cv.IMREAD_COLOR,
                )
                np.testing.assert_array_equal(processed, processed_images[index])
                overlay = cv.imdecode(
                    np.frombuffer(
                        (results / case / "overlay.png").read_bytes(), np.uint8
                    ),
                    cv.IMREAD_COLOR,
                )
                if overlay is None:
                    self.fail("端線の確認画像を読み込めません")
                np.testing.assert_array_equal(overlay[60, 70], image[60, 70])
            raw_mask = cv.imdecode(
                np.frombuffer((results / "original/mask.png").read_bytes(), np.uint8),
                cv.IMREAD_GRAYSCALE,
            )
            if raw_mask is None:
                self.fail("抽出マスクを読み込めません")
            self.assertEqual(raw_mask[55, 58], 0)
            with (results / "comparison.csv").open(
                encoding="utf-8", newline=""
            ) as saved:
                rows = list(csv.DictReader(saved))
            self.assertEqual(rows[1]["steps"], "gamma -> blur")
            self.assertEqual(rows[2]["steps"], "blur -> gamma")
            self.assertEqual(rows[1]["delta_left_px"], "18.10")
            self.assertEqual(rows[1]["delta_right_px"], "0.00")
            self.assertEqual(rows[1]["delta_total_px"], "18.10")

    def test_preprocessing_neutral_parameters_and_baseline_last(self) -> None:
        """gamma=1・sharp=0は無補正になり、基準を最後に置いても差はゼロ."""
        cases = {"sharp": ("sharp",), "gamma": ("gamma",), "original": ()}
        with self.temporary_directory() as temporary:
            directory = Path(temporary)
            image = np.random.default_rng(4).integers(0, 256, (160, 140, 3), np.uint8)
            _, encoded = cv.imencode(".png", image)
            (directory / "input.png").write_bytes(encoded.tobytes())
            script = directory / "preprocess_comparison.py"
            script.write_text(
                self.script_source(script.name, CASES=cases, GAMMA=1, SHARP_AMOUNT=0),
                encoding="utf-8",
            )

            def fixed_mask(
                processed: np.ndarray, labels: np.ndarray, *unused: object
            ) -> None:
                np.testing.assert_array_equal(processed, image)
                labels[:] = cv.GC_BGD
                labels[20:141, 50:91] = cv.GC_PR_FGD

            with patch.object(cv, "grabCut", side_effect=fixed_mask):
                runpy.run_path(str(script))
            with (directory / "results/preprocess_comparison/comparison.csv").open(
                encoding="utf-8", newline=""
            ) as saved:
                rows = list(csv.DictReader(saved))
            self.assertEqual([row["case"] for row in rows], list(cases))
            for row in rows:
                for edge in ("left", "right", "total"):
                    self.assertEqual(row[f"delta_{edge}_px"], "0.00")

    def test_preprocessing_invalid_settings_protect_input(self) -> None:
        """誤った基準・処理名・保存先で元画像を上書きしない."""
        scenarios = (
            ({"CASES": {"blur": ("blur",)}}, "original"),
            ({"CASES": {"original": ("gamma",)}}, "original"),
            ({"CASES": {"original": (), "../outside": ()}}, "フォルダ名"),
            ({"CASES": {"original": (), "original/../original": ()}}, "フォルダ名"),
            ({"CASES": {"typo": ("blurr",), "original": ()}}, "未知の前処理"),
            ({"CASES": {"gamma": ("gamma",), "original": ()}, "GAMMA": 0}, "GAMMA"),
            (
                {"CASES": {"sharp": ("sharp",), "original": ()}, "SHARP_AMOUNT": -1},
                "SHARP_AMOUNT",
            ),
            (
                {"INPUT_PATH": "results/preprocess_comparison/original/processed.png"},
                "別々",
            ),
            ({"START_Y": -1}, "計測範囲"),
        )
        with self.temporary_directory() as temporary:
            for index, (settings, message) in enumerate(scenarios):
                with self.subTest(message=message):
                    directory = Path(temporary) / str(index)
                    directory.mkdir()
                    input_path = directory / str(
                        settings.get("INPUT_PATH", "input.png")
                    )
                    input_path.parent.mkdir(parents=True, exist_ok=True)
                    image = np.full((160, 140, 3), 100, np.uint8)
                    _, encoded = cv.imencode(".png", image)
                    original_bytes = encoded.tobytes()
                    input_path.write_bytes(original_bytes)
                    script = directory / "preprocess_comparison.py"
                    script.write_text(
                        self.script_source(script.name, **settings),
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(ValueError, message):
                        runpy.run_path(str(script))
                    self.assertEqual(input_path.read_bytes(), original_bytes)
                    self.assertFalse(
                        (
                            directory / "results/preprocess_comparison/comparison.csv"
                        ).exists()
                    )

    def test_preprocessing_rejects_empty_and_single_row_without_saving(self) -> None:
        """計測できない結果をゼロ長として比較CSVへ載せない."""
        with self.temporary_directory() as temporary:
            for single_row in (False, True):
                with self.subTest(single_row=single_row):
                    directory = Path(temporary) / str(single_row)
                    directory.mkdir()
                    image = np.full((100, 100, 3), 100, np.uint8)
                    _, encoded = cv.imencode(".png", image)
                    (directory / "input.png").write_bytes(encoded.tobytes())
                    script = directory / "preprocess_comparison.py"
                    script.write_text(
                        self.script_source(script.name, CASES={"original": ()}),
                        encoding="utf-8",
                    )

                    def fixed_mask(
                        processed: np.ndarray, labels: np.ndarray, *unused: object
                    ) -> None:
                        labels[:] = cv.GC_BGD
                        if single_row:
                            labels[50, 40:61] = cv.GC_PR_FGD

                    with (
                        patch.object(cv, "grabCut", side_effect=fixed_mask),
                        self.assertRaisesRegex(ValueError, "original"),
                    ):
                        runpy.run_path(str(script))
                    self.assertFalse(
                        (directory / "results/preprocess_comparison").exists()
                    )


if __name__ == "__main__":
    unittest.main()
