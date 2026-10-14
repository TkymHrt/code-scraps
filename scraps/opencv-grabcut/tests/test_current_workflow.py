"""現行5本の単発スクリプトの画像・CSV受け渡しと既知の長さを確認する."""

import ast
import contextlib
import csv
import io
import runpy
import tempfile
import unittest
from pathlib import Path

import cv2 as cv
import numpy as np
from test_camera_conversion import (
    DISTORTION,
    IMAGE_SIZE,
    MATRIX,
    calibration_photos,
    configure,
    rendered_scene,
)

PROJECT = Path(__file__).resolve().parents[1]


def copy_current(filename, directory, **settings):
    source = (PROJECT / "submissions" / filename).read_text(encoding="utf-8")
    lines = source.splitlines(keepends=True)
    for node in reversed(ast.parse(source).body):
        if isinstance(node, ast.Assign):
            target = node.targets[0]
        elif isinstance(node, ast.AnnAssign):
            target = node.target
        else:
            continue
        if isinstance(target, ast.Name) and target.id in settings:
            lines[node.lineno - 1 : node.end_lineno] = [
                f"{target.id} = {settings[target.id]!r}\n"
            ]
    path = directory / filename
    path.write_text("".join(lines), encoding="utf-8")
    return path


class CurrentWorkflowTests(unittest.TestCase):
    def setUp(self):
        results = PROJECT / "tests/results"
        results.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=results)
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.gui = runpy.run_path(
            str(copy_current("01_initial_regions_gui.py", self.directory))
        )
        self.comparison = runpy.run_path(
            str(copy_current("length_comparison_gui.py", self.directory))
        )
        self.regions = {
            cv.GC_PR_FGD: [(0.3, 0, 0.7, 1)],
            cv.GC_BGD: [(0, 0, 0.3, 1), (0.7, 0, 1, 1)],
            cv.GC_FGD: [(0.48, 0.4, 0.56, 0.6)],
        }
        self.image = np.full((160, 140, 3), 35, np.uint8)
        self.image[20:141, 50:91] = 200

    def sample(self, name, length_px=120, thickness=10):
        image_path = self.directory / f"{name}.png"
        image_path.write_bytes(b"protected image")
        measurement = {
            "image_width": 140,
            "image_height": 400,
            "mm_per_px": 0.25,
            "start_y": 20,
            "end_y": 20 + length_px,
            "left_px": length_px,
            "left_mm": length_px * 0.25,
            "right_px": length_px,
            "right_mm": length_px * 0.25,
            "total_px": length_px * 2,
            "total_mm": length_px * 0.5,
        }
        path = self.directory / f"{name}.csv"
        self.gui["write_csv"](path, image_path, measurement)
        return {"sample_id": name, "csv_path": path, "thickness_mm": thickness}

    def test_real_grabcut_excludes_ends_and_keeps_notch_length(self):
        before = self.image.copy()
        row, overlay = self.gui["measure_lengths"](self.image, self.regions, 20, 140)
        self.assertEqual(
            (row["left_px"], row["right_px"], row["total_mm"]), (120, 120, 60)
        )
        self.assertEqual(overlay.shape, self.image.shape)
        np.testing.assert_array_equal(self.image, before)
        self.image[60:71, 50:61] = 35
        row, _ = self.gui["measure_lengths"](self.image, self.regions, 20, 140)
        self.assertAlmostEqual(row["left_px"], 118 + 2 * np.hypot(11, 1))
        self.assertEqual(row["right_px"], 120)
        cropped, _ = self.gui["measure_lengths"](self.image, self.regions, 80, 120)
        self.assertEqual(cropped["total_mm"], 20)

    def test_empty_rows_bad_ranges_and_missing_seeds_stop_measurement(self):
        for start, end in ((-1, 140), (140, 20), (20, 160), (20, 20)):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                self.gui["measure_lengths"](self.image, self.regions, start, end)
        with self.assertRaisesRegex(ValueError, "試料がありません"):
            self.gui["measure_lengths"](self.image, self.regions, 0, 140)
        empty_regions = {label: [] for label in self.regions}
        with self.assertRaisesRegex(ValueError, "前景候補"):
            self.gui["measure_lengths"](self.image, empty_regions, 20, 140)

    def test_csv_round_trip_and_multiple_shots_against_volume_model(self):
        samples = [
            self.sample("初期"),
            self.sample("撮り直し"),
            self.sample("圧延後", 240, 5),
        ]
        rows = self.comparison["compare_lengths"](samples, 30, 10)
        self.assertEqual([row["ideal_length_mm"] for row in rows], [30, 30, 60])
        self.assertEqual([row["delta_total_mm"] for row in rows], [0, 0, 0])
        self.assertIsNone(rows[0]["previous_delta_total_mm"])
        self.assertEqual(rows[1]["previous_delta_total_mm"], 0)
        self.assertEqual(rows[2]["previous_delta_total_mm"], 60)
        self.comparison["write_csv"](self.directory / "比較.csv", rows)
        self.comparison["write_graph"](self.directory / "比較.png", rows)
        with (self.directory / "比較.csv").open(
            encoding="utf-8-sig", newline=""
        ) as source:
            saved = list(csv.DictReader(source))
        self.assertEqual(saved[2]["ideal_length_mm"], "60")
        figure = self.comparison["create_graph"](rows)
        np.testing.assert_array_equal(figure.axes[0].lines[2].get_ydata(), [30, 30, 60])
        self.assertTrue(samples[0]["csv_path"].read_bytes().startswith(b"\xef\xbb\xbf"))
        # 比較には画像を読み直す処理もカメラ設定も必要ない。
        for path in self.directory.glob("初期.png"):
            path.unlink()
        self.assertEqual(self.comparison["compare_lengths"](samples, 30, 10), rows)

    def test_inconsistent_csv_is_rejected_and_inputs_are_protected(self):
        sample = self.sample("入力")
        path = sample["csv_path"]
        rows = self.comparison["compare_lengths"]([sample], 30, 10)
        for protected, suffix in (
            (path, ".csv"),
            (self.directory / "入力.png", ".png"),
        ):
            before = protected.read_bytes()
            with self.assertRaises(ValueError):
                self.comparison["check_output"](protected, rows, suffix)
            with self.assertRaises(ValueError):
                self.gui["write_csv"](protected, protected, rows[0])
            self.assertEqual(protected.read_bytes(), before)
        with path.open(encoding="utf-8-sig", newline="") as source:
            saved = list(csv.DictReader(source))[0]
        for column, value in (
            ("left_mm", "31"),
            ("mm_per_px", "nan"),
            ("total_px", "241"),
            ("end_y", "400"),
        ):
            bad = dict(saved, **{column: value})
            with path.open("w", encoding="utf-8-sig", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=list(bad))
                writer.writeheader()
                writer.writerow(bad)
            with self.subTest(column=column), self.assertRaises(ValueError):
                self.comparison["read_lengths"](path)

    def test_twenty_shots_reordering_and_invalid_conditions(self):
        samples = [self.sample(f"撮影{i:02}", 120 + i * 4) for i in range(20)]
        rows = self.comparison["compare_lengths"](samples, 30, 10)
        self.assertEqual(rows[-1]["left_mm"], 49)
        self.assertEqual(rows[-1]["previous_delta_total_mm"], 2)
        rows = self.comparison["compare_lengths"](list(reversed(samples)), 30, 10)
        self.assertEqual(rows[1]["previous_delta_total_mm"], -2)
        for invalid in (
            [],
            samples + [samples[0]],
            [dict(samples[0], thickness_mm=None)],
        ):
            with self.assertRaises(ValueError):
                self.comparison["compare_lengths"](invalid, 30, 10)
        for initial_length, initial_thickness in ((0, 10), (30, float("inf"))):
            with self.assertRaises(ValueError):
                self.comparison["compare_lengths"](
                    samples, initial_length, initial_thickness
                )

    def test_corrected_image_has_known_scale_without_metadata_csv(self):
        script = copy_current(
            "rectify_image.py",
            self.directory,
            INPUT_PATH="撮影.png",
            OUTPUT_IMAGE_PATH="補正.png",
            CALIBRATION_SIZE=IMAGE_SIZE,
            CAMERA_MATRIX=MATRIX.tolist(),
            DIST_COEFFS=DISTORTION.tolist(),
        )
        image = rendered_scene((0.12, -0.22, 0.03), (-170, -65, 600))
        _, encoded = cv.imencode(".png", image)
        source_path = self.directory / "撮影.png"
        source_path.write_bytes(encoded.tobytes())
        before = source_path.read_bytes()
        with contextlib.redirect_stdout(io.StringIO()):
            rectifier = runpy.run_path(str(script), run_name="__main__")
        self.assertEqual(source_path.read_bytes(), before)
        self.assertFalse(list(self.directory.glob("*.csv")))
        self.assertEqual(rectifier["MM_PER_PX"], self.gui["MM_PER_PX"])
        configure(rectifier)
        for rotation, translation in [
            ((0.12, -0.22, 0.03), (-170, -65, 600)),
            ((-0.20, 0.18, -0.10), (-150, -100, 650)),
            ((0.20, 0.15, 0.12), (-160, -90, 560)),
        ]:
            corrected = rectifier["rectify_image"](
                rendered_scene(rotation, translation)
            )["image"]
            ys, xs = np.nonzero(cv.inRange(corrected, (20, 75, 145), (90, 145, 220)))
            self.assertAlmostEqual((ys.max() - ys.min()) * 0.25, 150, delta=1)
            self.assertAlmostEqual((xs.max() - xs.min()) * 0.25, 40, delta=1)

    def test_board_generation_and_camera_settings_copy_remain_independent(self):
        generator = copy_current("generate_charuco_board.py", self.directory)
        with contextlib.redirect_stdout(io.StringIO()):
            runpy.run_path(str(generator), run_name="__main__")
        board_path = self.directory / "results/charuco_board.png"
        before = board_path.read_bytes()
        camera = runpy.run_path(
            str(copy_current("camera_calibration.py", self.directory))
        )
        size, matrix, distortion, rms, _ = camera["calibrate"](
            calibration_photos(self.directory)
        )
        self.assertLess(rms, 0.5)
        rectifier = runpy.run_path(
            str(copy_current("rectify_image.py", self.directory))
        )
        settings = rectifier["rectify_image"].__globals__
        exec(camera["parameter_text"](size, matrix, distortion), settings)
        corrected = rectifier["rectify_image"](
            rendered_scene((0.12, -0.22, 0.03), (-170, -65, 600))
        )
        self.assertLess(corrected["error_px"], 1)
        self.assertEqual(board_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
