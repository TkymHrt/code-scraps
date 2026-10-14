"""保存済みのmm長さ・幅一定のスラブ基準・実寸差と保存を確認する."""

import csv
import runpy
import unittest
from pathlib import Path

import cv2 as cv
import numpy as np
import test_submission_comparison


class LengthComparisonGuiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = Path(__file__).resolve().parents[1]
        self.gui = runpy.run_path(
            str(self.project / "sandbox/previous_submissions/length_comparison_gui.py")
        )
        self.calibrator = runpy.run_path(
            str(self.project / "sandbox/previous_submissions/length_calibration_gui.py")
        )
        self.comparison = test_submission_comparison.SubmissionComparisonTests()

    def write_case(
        self,
        directory,
        name,
        lengths,
        thickness=10,
        reference_px=100,
        y_range=(20, 220),
    ):
        path = directory / name / "03_side_lengths.csv"
        path.parent.mkdir(parents=True)
        with path.open("w", encoding="utf-8-sig", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(("edge", "length_px", "start_y", "end_y"))
            for edge, length in zip(("left", "right", "total"), lengths):
                writer.writerow((edge, f"{length:.2f}", *y_range))
        image_path = path.parent / "元画像.png"
        image = np.full((800, 700, 3), 245, np.uint8)
        cv.line(image, (30, 40), (30 + reference_px, 40), (0, 0, 0), 2)
        success, encoded = cv.imencode(".png", image)
        self.assertTrue(success)
        image_path.write_bytes(encoded.tobytes())
        calibration = self.calibrator["calibration_from_points"](
            50, ((30, 40), (30 + reference_px, 40)), (700, 800)
        )
        calibration["image_path"] = str(image_path.resolve())
        calibrated_path = path.parent / "calibrated_lengths.csv"
        row = self.calibrator["calibrate_lengths"](path, calibration)
        self.calibrator["write_csv"](calibrated_path, row)
        return {
            "sample_id": name,
            "csv_path": calibrated_path,
            "source_csv": path,
            "image_path": image_path,
            "thickness_mm": thickness,
        }

    def known_samples(self, directory):
        return [
            self.write_case(directory, "初期", (200, 200, 400)),
            self.write_case(
                directory,
                "倍率2倍の撮り直し",
                (400, 400, 800),
                reference_px=200,
                y_range=(60, 460),
            ),
            self.write_case(
                directory, "厚さ半分", (430, 410, 840), thickness=5, y_range=(30, 430)
            ),
        ]

    def test_single_image_against_model(self):
        with self.comparison.temporary_directory() as temporary:
            sample = self.write_case(Path(temporary), "1枚", (200, 200, 400))
            rows = self.gui["compare_lengths"]([sample], 100, 10)
            self.assertEqual(rows[0]["left_mm"], 100)
            self.assertEqual(rows[0]["delta_left_mm"], 0)
            self.assertIsNone(rows[0]["previous_delta_left_mm"])
            figure = self.gui["create_graph"](rows)
            self.assertEqual(figure.axes[0].lines[2].get_marker(), "s")

    def test_multiple_scales_slab_length_csv_graph_and_independent_script(self):
        with self.comparison.temporary_directory() as temporary:
            directory = Path(temporary)
            samples = self.known_samples(directory)
            before = [
                (
                    sample["csv_path"].read_bytes(),
                    sample["image_path"].read_bytes(),
                )
                for sample in samples
            ]
            copy = directory / "length_comparison_gui.py"
            copy.write_bytes(
                (
                    self.project
                    / "sandbox/previous_submissions/length_comparison_gui.py"
                ).read_bytes()
            )
            gui = runpy.run_path(str(copy))
            rows = gui["compare_lengths"](samples, 100, 10)
            self.assertEqual([row["ideal_length_mm"] for row in rows], [100, 100, 200])
            self.assertEqual([row["elongation"] for row in rows], [1, 1, 2])
            self.assertEqual([row["left_mm"] for row in rows], [100, 100, 215])
            self.assertEqual([row["right_mm"] for row in rows], [100, 100, 205])
            self.assertEqual([row["delta_total_mm"] for row in rows], [0, 0, 20])
            self.assertEqual([row["delta_total_pct"] for row in rows], [0, 0, 5])
            self.assertEqual(rows[2]["delta_left_pct"], 7.5)
            self.assertEqual(rows[2]["delta_right_pct"], 2.5)
            self.assertEqual(rows[1]["previous_delta_total_mm"], 0)
            self.assertEqual(rows[2]["previous_delta_total_mm"], 220)
            self.assertEqual([row["start_y"] for row in rows], [20, 60, 30])
            csv_path = directory / "出力/実寸 比較.csv"
            gui["write_csv"](csv_path, rows)
            with csv_path.open(encoding="utf-8-sig", newline="") as source:
                saved = list(csv.DictReader(source))
            self.assertEqual(len(saved), 3)
            self.assertEqual(saved[0]["previous_delta_total_mm"], "")
            self.assertEqual(saved[1]["mm_per_px"], "0.25")
            self.assertEqual(saved[2]["ideal_length_mm"], "200")
            self.assertEqual(saved[2]["delta_total_pct"], "5")
            self.assertEqual(saved[0]["reference_x1"], "30")
            self.assertEqual(
                saved[0]["image_path"], str(samples[0]["image_path"].resolve())
            )
            graph_path = directory / "出力/スラブ 比較.png"
            gui["write_graph"](graph_path, rows)
            figure = gui["create_graph"](rows)
            axes = figure.axes
            self.assertEqual(len(axes), 3)
            np.testing.assert_allclose(axes[0].lines[0].get_ydata(), [100, 100, 215])
            np.testing.assert_allclose(axes[0].lines[2].get_ydata(), [100, 100, 200])
            np.testing.assert_allclose(axes[1].lines[2].get_ydata(), [0, 0, 5])
            np.testing.assert_allclose(
                axes[2].lines[2].get_ydata(), [np.nan, 0, 220], equal_nan=True
            )
            image = cv.imdecode(
                np.frombuffer(graph_path.read_bytes(), np.uint8), cv.IMREAD_COLOR
            )
            if image is None:
                self.fail("保存したグラフを読み込めません")
            self.assertGreater(float(np.std(image)), 10)
            self.assertEqual(
                [
                    (
                        sample["csv_path"].read_bytes(),
                        sample["image_path"].read_bytes(),
                    )
                    for sample in samples
                ],
                before,
            )

    def test_invalid_models_and_incomplete_sample_conditions_are_rejected(self):
        with self.comparison.temporary_directory() as temporary:
            samples = self.known_samples(Path(temporary))
            for length, thickness in (
                (None, 10),
                (0, 10),
                (-1, 10),
                (100, 0),
                (100, float("nan")),
                (float("inf"), 10),
            ):
                with self.subTest(length=length, thickness=thickness):
                    with self.assertRaises(ValueError):
                        self.gui["compare_lengths"](samples, length, thickness)
            invalid_samples = [
                [],
                samples + [samples[0]],
                [samples[0], dict(samples[1], csv_path=samples[0]["csv_path"])],
                [samples[0], dict(samples[1], sample_id=samples[0]["sample_id"])],
                [dict(samples[0], sample_id=" ")],
                [dict(samples[0], thickness_mm=None)],
                [dict(samples[0], thickness_mm=-1)],
                [dict(samples[0], thickness_mm=float("inf"))],
            ]
            for items in invalid_samples:
                with self.subTest(items=items):
                    with self.assertRaises(ValueError):
                        self.gui["compare_lengths"](items, 100, 10)
            path = samples[2]["csv_path"]
            path.unlink()
            with self.assertRaises(OSError):
                self.gui["compare_lengths"](samples, 100, 10)

    def test_all_csv_and_calibration_images_are_protected(self):
        with self.comparison.temporary_directory() as temporary:
            directory = Path(temporary)
            samples = self.known_samples(directory)
            rows = self.gui["compare_lengths"](samples, 100, 10)
            before = [
                (
                    sample["csv_path"].read_bytes(),
                    sample["image_path"].read_bytes(),
                )
                for sample in samples
            ]
            for sample in samples:
                with self.assertRaisesRegex(ValueError, "入力CSV"):
                    self.gui["write_csv"](sample["csv_path"], rows)
                with self.assertRaisesRegex(ValueError, "入力CSV"):
                    self.gui["write_csv"](sample["source_csv"], rows)
                with self.assertRaisesRegex(ValueError, "校正画像"):
                    self.gui["write_graph"](sample["image_path"], rows)
            for function, path in (
                ("write_csv", directory / "wrong.txt"),
                ("write_graph", directory / "wrong.csv"),
            ):
                with self.assertRaisesRegex(ValueError, "拡張子"):
                    self.gui[function](path, rows)
                self.assertFalse(path.exists())
            with self.assertRaisesRegex(ValueError, "比較"):
                self.gui["write_csv"](directory / "empty.csv", [])
            self.assertFalse((directory / "empty.csv").exists())
            self.assertEqual(
                [
                    (
                        sample["csv_path"].read_bytes(),
                        sample["image_path"].read_bytes(),
                    )
                    for sample in samples
                ],
                before,
            )

    def test_reordering_preserves_slab_deviation_and_changes_previous_difference(self):
        with self.comparison.temporary_directory() as temporary:
            samples = self.known_samples(Path(temporary))
            original = self.gui["compare_lengths"](samples, 100, 10)
            reordered = self.gui["compare_lengths"](
                [samples[2], samples[0], samples[1]], 100, 10
            )
            by_name = {row["sample_id"]: row for row in original}
            for row in reordered:
                self.assertEqual(
                    row["delta_total_mm"], by_name[row["sample_id"]]["delta_total_mm"]
                )
                self.assertEqual(
                    row["delta_total_pct"], by_name[row["sample_id"]]["delta_total_pct"]
                )
            self.assertEqual(
                [row["previous_id"] for row in reordered], ["", "厚さ半分", "初期"]
            )
            self.assertIsNone(reordered[0]["previous_delta_total_mm"])
            self.assertEqual(reordered[1]["previous_delta_total_mm"], -220)
            self.assertEqual(reordered[2]["previous_delta_total_mm"], 0)

    def test_twenty_images_keep_scales_model_and_every_graph_point(self):
        with self.comparison.temporary_directory() as temporary:
            directory = Path(temporary)
            samples = []
            for index in range(20):
                magnification = index % 3 + 1
                sample = self.write_case(
                    directory,
                    f"撮影{index + 1:02d}",
                    (
                        (200 + index * 2) * magnification,
                        (200 + index) * magnification,
                        (400 + index * 3) * magnification,
                    ),
                    reference_px=100 * magnification,
                    y_range=(20, 220 * magnification),
                )
                samples.append(sample)
            rows = self.gui["compare_lengths"](samples, 100, 10)
            self.assertEqual(len(rows), 20)
            self.assertEqual(rows[-1]["left_mm"], 119)
            self.assertEqual(rows[-1]["delta_total_mm"], 28.5)
            self.assertEqual(rows[-1]["previous_delta_total_mm"], 1.5)
            self.gui["write_csv"](directory / "many.csv", rows)
            with (directory / "many.csv").open(
                encoding="utf-8-sig", newline=""
            ) as source:
                saved = list(csv.DictReader(source))
            self.assertEqual(
                [row["sample_id"] for row in saved],
                [sample["sample_id"] for sample in samples],
            )
            self.gui["write_graph"](directory / "many.png", rows)
            axes = self.gui["create_graph"](rows).axes
            self.assertEqual(len(axes[0].lines[0].get_ydata()), 20)
            self.assertEqual(len(axes[2].get_xticklabels()), 20)
            self.assertEqual(axes[2].get_xticklabels()[-1].get_rotation(), 45)

    def test_invalid_calibrated_csv_and_manual_unit_mismatch_are_rejected(self):
        with self.comparison.temporary_directory() as temporary:
            sample = self.write_case(Path(temporary), "校正済み", (200, 200, 400))
            path = sample["csv_path"]
            with path.open(encoding="utf-8-sig", newline="") as source:
                reader = csv.DictReader(source)
                fields = reader.fieldnames
                assert fields is not None
                original = next(reader)
            with self.assertRaisesRegex(ValueError, "校正済み"):
                self.gui["read_calibrated_lengths"](sample["source_csv"])
            for column, value in (
                ("left_mm", ""),
                ("left_mm", "nan"),
                ("left_mm", "inf"),
                ("left_mm", "0"),
                ("left_mm", "99"),
                ("mm_per_px", "-1"),
                ("mm_per_px", "0.6"),
                ("reference_mm", "bad"),
                ("image_path", ""),
                ("reference_x1", "nan"),
                ("image_width", "1"),
                ("end_y", "800"),
                ("total_px", "410"),
                ("total_mm", "205"),
            ):
                invalid = dict(original, **{column: value})
                if column == "total_px":
                    invalid["total_mm"] = "205"
                with path.open("w", encoding="utf-8-sig", newline="") as output:
                    writer = csv.DictWriter(output, fieldnames=fields)
                    writer.writeheader()
                    writer.writerow(invalid)
                with self.subTest(column=column, value=value):
                    with self.assertRaises(ValueError):
                        self.gui["read_calibrated_lengths"](path)
            for count in (0, 2):
                with path.open("w", encoding="utf-8-sig", newline="") as output:
                    writer = csv.DictWriter(output, fieldnames=fields)
                    writer.writeheader()
                    for _ in range(count):
                        writer.writerow(original)
                with self.assertRaisesRegex(ValueError, "1行"):
                    self.gui["read_calibrated_lengths"](path)

    def test_saved_measurements_work_without_original_images_or_pixel_csvs(self):
        with self.comparison.temporary_directory() as temporary:
            samples = self.known_samples(Path(temporary))
            before = self.gui["compare_lengths"](samples, 100, 10)
            for sample in samples:
                sample["source_csv"].unlink()
                sample["image_path"].unlink()
            # 比較時に画像を開いたり、校正点から倍率を作り直したりしない。
            after = self.gui["compare_lengths"](samples, 100, 10)
            self.assertEqual(after, before)
            changed = self.gui["compare_lengths"](samples, 120, 10)
            self.assertEqual(changed[2]["left_mm"], 215)
            self.assertEqual(changed[2]["ideal_length_mm"], 240)

    def test_pixel_rounding_and_fractional_scale_survive_csv_roundtrip(self):
        with self.comparison.temporary_directory() as temporary:
            sample = self.write_case(
                Path(temporary), "小数", (200.004, 201.004, 401.008), reference_px=150
            )
            rows = self.gui["compare_lengths"]([sample], 100, 10)
            self.assertAlmostEqual(rows[0]["left_mm"], 200 / 3, places=9)
            self.assertAlmostEqual(rows[0]["total_mm"], 401.01 / 3, places=9)


if __name__ == "__main__":
    unittest.main()
