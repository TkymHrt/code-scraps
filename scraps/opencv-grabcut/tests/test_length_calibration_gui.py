"""画像別の校正・pxからmmへの変換・CSV保存と入力保護を確認する."""

import csv
import runpy
import unittest
from pathlib import Path

import test_submission_comparison


class LengthCalibrationGuiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = Path(__file__).resolve().parents[1]
        self.gui = runpy.run_path(
            str(self.project / "submissions/length_calibration_gui.py")
        )
        self.comparison = test_submission_comparison.SubmissionComparisonTests()

    def source(self, directory, lengths=(200, 200, 400), y_range=(20, 220)):
        path = directory / "元 長さ.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(("edge", "length_px", "start_y", "end_y"))
            for edge, length in zip(("left", "right", "total"), lengths):
                writer.writerow((edge, f"{length:.2f}", *y_range))
        image_path = directory / "元画像.png"
        image_path.write_bytes(b"protected original")
        calibration = self.gui["calibration_from_points"](
            50, ((30, 40), (130, 40)), (700, 800)
        )
        calibration["image_path"] = str(image_path.resolve())
        return path, image_path, calibration

    def test_diagonal_reference_and_calibrated_csv_are_independent(self):
        diagonal = self.gui["calibration_from_points"](
            50, ((10, 10), (40, 50)), (100, 100)
        )
        self.assertEqual(diagonal["reference_px"], 50)
        self.assertEqual(diagonal["mm_per_px"], 1)
        with self.comparison.temporary_directory() as temporary:
            directory = Path(temporary)
            source_path, image_path, calibration = self.source(directory)
            copy = directory / "length_calibration_gui.py"
            copy.write_bytes(
                (self.project / "submissions/length_calibration_gui.py").read_bytes()
            )
            gui = runpy.run_path(str(copy))
            row = gui["calibrate_lengths"](source_path, calibration)
            self.assertEqual(
                (row["left_mm"], row["right_mm"], row["total_mm"]), (100, 100, 200)
            )
            path = directory / "出力/校正済み 長さ.csv"
            gui["write_csv"](path, row)
            self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))
            with path.open(encoding="utf-8-sig", newline="") as source:
                saved = list(csv.DictReader(source))
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]["input_csv"], str(source_path.resolve()))
            self.assertEqual(saved[0]["image_path"], str(image_path.resolve()))
            self.assertEqual(saved[0]["mm_per_px"], "0.5")
            self.assertEqual(saved[0]["reference_x1"], "30")
            self.assertEqual(saved[0]["reference_x2"], "130")
            self.assertEqual(saved[0]["start_y"], "20")
            self.assertEqual(saved[0]["left_px"], "200")
            self.assertEqual(saved[0]["total_mm"], "200")

    def test_source_range_and_overwrite_are_checked_before_saving(self):
        with self.comparison.temporary_directory() as temporary:
            directory = Path(temporary)
            path, image_path, calibration = self.source(directory)
            before = (path.read_bytes(), image_path.read_bytes())
            row = self.gui["calibrate_lengths"](path, calibration)
            for target in (path, image_path):
                with self.assertRaises(ValueError):
                    self.gui["write_csv"](target, row)
            with self.assertRaisesRegex(ValueError, "拡張子"):
                self.gui["write_csv"](directory / "wrong.txt", row)
            with self.assertRaisesRegex(ValueError, "校正"):
                self.gui["write_csv"](directory / "empty.csv", {})
            self.assertFalse((directory / "wrong.txt").exists())
            self.assertFalse((directory / "empty.csv").exists())
            self.assertEqual((path.read_bytes(), image_path.read_bytes()), before)
            path.write_text(
                path.read_text(encoding="utf-8-sig").replace(",20,220", ",20,800"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "校正画像"):
                self.gui["calibrate_lengths"](path, calibration)
            path.unlink()
            with self.assertRaises(OSError):
                self.gui["calibrate_lengths"](path, calibration)

    def test_calibration_rejects_invalid_reference_and_points(self):
        for reference, points, size in (
            (0, ((1, 1), (5, 5)), (100, 100)),
            (-1, ((1, 1), (5, 5)), (100, 100)),
            ("bad", ((1, 1), (5, 5)), (100, 100)),
            (float("inf"), ((1, 1), (5, 5)), (100, 100)),
            (float("nan"), ((1, 1), (5, 5)), (100, 100)),
            (50, (), (100, 100)),
            (50, ((1, 1),), (100, 100)),
            (50, ((1, 1), (1, 1)), (100, 100)),
            (50, ((1, 1), (100, 5)), (100, 100)),
            (50, ((1, 1), (-1, 5)), (100, 100)),
            (50, ((1, 1), (float("nan"), 5)), (100, 100)),
            (50, ((0, 0), (0, 5)), (1, 100)),
        ):
            with self.subTest(reference=reference, points=points, size=size):
                with self.assertRaises(ValueError):
                    self.gui["calibration_from_points"](reference, points, size)

    def test_display_coordinates_map_to_original_image(self):
        convert = self.gui["point_on_image"]
        bounds = (12, 24, 101, 51)
        self.assertEqual(convert(12, 24, bounds, (1001, 501)), (0, 0))
        self.assertEqual(convert(62, 49, bounds, (1001, 501)), (500, 250))
        self.assertEqual(convert(112, 74, bounds, (1001, 501)), (1000, 500))
        self.assertIsNone(convert(11, 24, bounds, (1001, 501)))
        self.assertIsNone(convert(113, 24, bounds, (1001, 501)))
        self.assertEqual(
            convert(112, 124, (12, 24, 1001, 501), (1001, 501)), (100, 100)
        )

    def test_invalid_csv_rows_are_rejected(self) -> None:
        with self.comparison.temporary_directory() as temporary:
            path = Path(temporary) / "不正 長さ.csv"
            header = "edge,length_px,start_y,end_y\n"
            good_rows = "left,120,20,140\nright,120,20,140\ntotal,240,20,140\n"
            cases = {
                "candidate_format": "edge,candidate_count\nleft,2\nright,3\ntotal,5\n",
                "missing_row": header + "left,120,20,140\nright,120,20,140\n",
                "duplicate_edge": header + good_rows.replace("right,", "left,"),
                "unknown_edge": header + good_rows.replace("right,", "top,"),
                "missing_field": header
                + good_rows.replace("left,120,20,140", "left,120,20"),
                "empty_field": header + good_rows.replace("left,120", "left,"),
                "not_number": header + good_rows.replace("left,120", "left,abc"),
                "nan": header + good_rows.replace("left,120", "left,nan"),
                "infinity": header + good_rows.replace("left,120", "left,inf"),
                "zero": header + good_rows.replace("left,120", "left,0"),
                "negative": header + good_rows.replace("left,120", "left,-1"),
                "invalid_range": header + good_rows.replace(",20,140", ",140,20"),
                "mixed_ranges": header
                + good_rows.replace("left,120,20", "left,120,21"),
                "wrong_total": header + good_rows.replace("total,240", "total,250"),
            }
            for name, text in cases.items():
                with self.subTest(name=name):
                    path.write_text(text, encoding="utf-8")
                    with self.assertRaises(ValueError):
                        self.gui["read_lengths"](path)

    def test_zoom_keeps_the_cursor_on_the_same_original_coordinate(self):
        image_size = (1920, 1080)
        view = (-125.5, 48.25, 0.73)
        anchor = (312, 187)
        before_bounds = (
            view[0],
            view[1],
            1 + (image_size[0] - 1) * view[2],
            1 + (image_size[1] - 1) * view[2],
        )
        before = self.gui["point_on_image"](*anchor, before_bounds, image_size)
        changed = self.gui["zoomed_view"](view, anchor, 1.1**0.5)
        after_bounds = (
            changed[0],
            changed[1],
            1 + (image_size[0] - 1) * changed[2],
            1 + (image_size[1] - 1) * changed[2],
        )
        after = self.gui["point_on_image"](*anchor, after_bounds, image_size)
        assert before is not None and after is not None
        self.assertAlmostEqual(before[0], after[0], places=10)
        self.assertAlmostEqual(before[1], after[1], places=10)
        restored = self.gui["zoomed_view"](changed, anchor, 1.1**-0.5)
        for original, value in zip(view, restored):
            self.assertAlmostEqual(original, value, places=10)

    def test_large_and_small_zoom_keep_the_anchor_and_bound_render_scale(self):
        anchor = (120, 80)
        view = (-20, -15, 1)
        for factor, expected_scale in ((100, 16), (0.0001, 0.01)):
            with self.subTest(factor=factor):
                changed = self.gui["zoomed_view"](view, anchor, factor)
                self.assertEqual(changed[2], expected_scale)
                self.assertAlmostEqual(
                    (anchor[0] - changed[0]) / changed[2],
                    (anchor[0] - view[0]) / view[2],
                )
                self.assertAlmostEqual(
                    (anchor[1] - changed[1]) / changed[2],
                    (anchor[1] - view[1]) / view[2],
                )


if __name__ == "__main__":
    unittest.main()
