"""設定GUIの数値・設定コピーを、単独スクリプトと照合する."""

import ast
import csv
import math
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2 as cv
import numpy as np
import test_shape_stages
import test_submission_comparison


class ParameterGuiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = Path(__file__).resolve().parents[1]
        self.image_gui = runpy.run_path(
            str(
                self.project
                / "sandbox/previous_submissions/measurement_settings_gui.py"
            )
        )
        self.comparison_gui = runpy.run_path(
            str(
                self.project / "sandbox/previous_submissions/comparison_settings_gui.py"
            )
        )
        self.settings: dict = {
            "INPUT_PATH": "input.png",
            "CANDIDATE_RECT": (0.34, 0, 0.705, 1),
            "BACKGROUND_RECTS": ((0, 0, 0.33, 1), (0.72, 0, 1, 1)),
            "FOREGROUND_RECTS": ((0.48, 0.4, 0.56, 0.6),),
            "START_Y": 20,
            "END_Y": 140,
            "ITERATIONS": 5,
            "RANDOM_SEED": 0,
            "LEFT_REFERENCE_RANGES": ((20, 40), (120, 140)),
            "RIGHT_REFERENCE_RANGES": ((20, 40), (120, 140)),
            "MIN_INWARD_PX": 5.0,
            "MIN_ROWS": 3,
        }

    def temporary_directory(self) -> tempfile.TemporaryDirectory[str]:
        results = self.project / "tests/results"
        results.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=results)
        if not Path(temporary.name).resolve().is_relative_to(results.resolve()):
            raise ValueError("検証用の一時領域が試験結果フォルダ外にあります")
        return temporary

    def known_image(self) -> tuple[np.ndarray, np.ndarray]:
        mask = np.zeros((160, 140), np.uint8)
        mask[20:141, 50:91] = 255
        mask[75:90, 50:60] = 0
        image = np.full((160, 140, 3), 35, np.uint8)
        image[mask > 0] = 200
        return image, mask

    def copied_values(self, text: str) -> dict:
        values = {}
        for node in ast.parse(text).body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                values[node.targets[0].id] = ast.literal_eval(node.value)
        return values

    def copy_script(self, directory: Path, filename: str, values: dict) -> Path:
        source = (self.project / "sandbox/previous_submissions" / filename).read_text(
            encoding="utf-8"
        )
        lines = source.splitlines(keepends=True)
        for node in reversed(ast.parse(source).body):
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                if name in values:
                    lines[node.lineno - 1 : node.end_lineno] = [
                        f"{name} = {values[name]!r}\n"
                    ]
        script = directory / filename
        script.write_text("".join(lines), encoding="utf-8")
        return script

    def test_script_settings_are_read_as_literals_without_execution(self) -> None:
        text = "CANDIDATE_RECT = (0.1234567890123456, 0, 0.9, 1)\n"
        text += "START_Y = 80\nEND_Y = None\nraise RuntimeError('must not run')\n"
        values = self.image_gui["read_settings"](text)
        self.assertEqual(values["CANDIDATE_RECT"][0], 0.1234567890123456)
        self.assertIsNone(values["END_Y"])
        with self.assertRaises(ValueError):
            self.image_gui["read_settings"]("START_Y = __import__('os').getpid()")

    def test_initial_labels_and_copy_scopes(self) -> None:
        image, _ = self.known_image()
        labels = self.image_gui["initial_labels"](image, self.settings)
        expected = np.full(image.shape[:2], cv.GC_PR_BGD, np.uint8)
        for label, rectangles in (
            (cv.GC_PR_FGD, (self.settings["CANDIDATE_RECT"],)),
            (cv.GC_BGD, self.settings["BACKGROUND_RECTS"]),
            (cv.GC_FGD, self.settings["FOREGROUND_RECTS"]),
        ):
            for left, top, right, bottom in rectangles:
                expected[
                    int(160 * top) : int(160 * bottom),
                    int(140 * left) : int(140 * right),
                ] = label
        np.testing.assert_array_equal(labels, expected)
        for level, count in ((0, 8), (1, 10), (2, 12)):
            values = self.copied_values(
                self.image_gui["settings_text"](image, self.settings, level)
            )
            self.assertEqual(len(values), count)
            for key, value in values.items():
                self.assertEqual(value, self.settings[key])

    def test_preview_and_pasted_settings_match_standalone_measurements(self) -> None:
        image, expected_mask = self.known_image()
        mask = self.image_gui["extract_mask"](image, self.settings)
        np.testing.assert_array_equal(mask, expected_mask)
        with self.temporary_directory() as temporary:
            directory = Path(temporary)
            input_path = directory / "入力 試料.png"
            success, encoded = cv.imencode(".png", image)
            self.assertTrue(success)
            input_path.write_bytes(encoded.tobytes())
            original = input_path.read_bytes()
            settings = {**self.settings, "INPUT_PATH": str(input_path)}
            for filename, level in (
                ("03_side_lengths.py", 0),
                ("06_reference_edges.py", 1),
                ("08_candidate_sizes.py", 2),
            ):
                with self.subTest(filename=filename):
                    data = self.image_gui["analyze"](image, mask, settings, level)
                    values = self.copied_values(
                        self.image_gui["settings_text"](image, settings, level)
                    )
                    script = self.copy_script(directory, filename, values)
                    actual = runpy.run_path(str(script))
                    self.assertEqual(data["edge_rows"], actual["edge_rows"])
                    if level == 0:
                        self.assertAlmostEqual(
                            data["left_length"], actual["left_length"]
                        )
                        self.assertAlmostEqual(
                            data["right_length"], actual["right_length"]
                        )
                        self.assertAlmostEqual(
                            data["left_length"], 118 + 2 * math.sqrt(101)
                        )
                    elif level == 1:
                        self.assertEqual(
                            data["deviation_rows"], actual["deviation_rows"]
                        )
                    else:
                        self.assertEqual(data["candidates"], actual["candidates"])
                        self.assertEqual(data["candidates"][0]["max_inward_px"], 10)
                        self.assertEqual(
                            data["candidates"][0]["span_along_reference_px"], 14
                        )
            self.assertEqual(input_path.read_bytes(), original)

    def test_invalid_image_settings_and_unobserved_rows_are_rejected(self) -> None:
        image, mask = self.known_image()
        for overrides in (
            {"START_Y": -1},
            {"END_Y": 160},
            {"ITERATIONS": 0},
            {"RANDOM_SEED": 2147483648},
            {"CANDIDATE_RECT": None},
            {"LEFT_REFERENCE_RANGES": ()},
            {"RIGHT_REFERENCE_RANGES": ((20, 30), (30, 40))},
            {"MIN_INWARD_PX": 0},
            {"MIN_INWARD_PX": float("nan")},
            {"MIN_ROWS": 1},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    self.image_gui["settings_text"](
                        image, {**self.settings, **overrides}, 2
                    )
        with patch.object(
            cv,
            "grabCut",
            side_effect=AssertionError("Invalid settings reached GrabCut"),
        ):
            with self.assertRaises(ValueError):
                self.image_gui["extract_mask"](image, {**self.settings, "START_Y": -1})
        missing_row = mask.copy()
        missing_row[60] = 0
        with self.assertRaisesRegex(ValueError, "端を取得できない行"):
            self.image_gui["analyze"](image, missing_row, self.settings, 2)
        no_normals = {
            **self.settings,
            "LEFT_REFERENCE_RANGES": (),
            "RIGHT_REFERENCE_RANGES": (),
        }
        self.assertAlmostEqual(
            self.image_gui["analyze"](image, mask, no_normals, 0)["right_length"], 120
        )

    def test_comparison_copy_runs_in_both_standalone_scripts(self) -> None:
        with self.temporary_directory() as temporary:
            directory = Path(temporary)
            for kind, filename in (
                ("長さ（04）", "04_compare_lengths.py"),
                ("候補（09）", "09_compare_candidates.py"),
            ):
                with self.subTest(kind=kind):
                    inputs = [directory / "基準 長さ.csv", directory / "比較 長さ.csv"]
                    if kind == "長さ（04）":
                        helper = test_submission_comparison.SubmissionComparisonTests()
                        helper.write_lengths(inputs[0])
                        helper.write_lengths(inputs[1], (138.1, 120, 258.1))
                    else:
                        helper = test_shape_stages.ShapeStageTests()
                        helper.write_summary(inputs[0], (0, 0, 0, 0), (0, 0, 0, 0))
                        helper.write_summary(inputs[1], (1, 10, 14, 0), (0, 0, 0, 0))
                    originals = [path.read_bytes() for path in inputs]
                    output_csv = directory / f"{Path(filename).stem}.csv"
                    output_image = directory / f"{Path(filename).stem}.png"
                    text = self.comparison_gui["settings_text"](
                        [("基準", inputs[0]), ("比較", inputs[1])],
                        "基準",
                        output_csv,
                        output_image,
                        kind,
                    )
                    values = self.copied_values(text)
                    script = self.copy_script(directory, filename, values)
                    runpy.run_path(str(script))
                    with output_csv.open(encoding="utf-8", newline="") as source:
                        rows = list(csv.DictReader(source))
                    if kind == "長さ（04）":
                        self.assertEqual(rows[-1]["delta_total_px"], "18.10")
                    else:
                        self.assertEqual(rows[-1]["delta_candidate_count"], "1")
                    self.assertTrue(output_image.is_file())
                    self.assertEqual([path.read_bytes() for path in inputs], originals)

    def test_comparison_copy_rejects_bad_settings_and_input_overwrite(self) -> None:
        with self.temporary_directory() as temporary:
            directory = Path(temporary)
            a, b = directory / "A.csv", directory / "B.csv"
            helper = test_submission_comparison.SubmissionComparisonTests()
            helper.write_lengths(a)
            helper.write_lengths(b)
            originals = (a.read_bytes(), b.read_bytes())
            good = [("A", a), ("B", b)]
            for samples, baseline, out_csv, out_image, kind in (
                (
                    good[:1],
                    "A",
                    directory / "out.csv",
                    directory / "out.png",
                    "長さ（04）",
                ),
                (
                    [("A", a), ("A", b)],
                    "A",
                    directory / "out.csv",
                    directory / "out.png",
                    "長さ（04）",
                ),
                (
                    good,
                    "missing",
                    directory / "out.csv",
                    directory / "out.png",
                    "長さ（04）",
                ),
                (good, "A", a, directory / "out.png", "長さ（04）"),
                (good, "A", directory / "out.csv", directory / "out.jpg", "長さ（04）"),
                (good, "A", directory / "out.csv", directory / "out.png", "候補（09）"),
            ):
                with self.subTest(samples=samples, baseline=baseline, kind=kind):
                    with self.assertRaises(ValueError):
                        self.comparison_gui["settings_text"](
                            samples, baseline, out_csv, out_image, kind
                        )
                    self.assertEqual((a.read_bytes(), b.read_bytes()), originals)
                    self.assertFalse((directory / "out.csv").exists())


if __name__ == "__main__":
    unittest.main()
