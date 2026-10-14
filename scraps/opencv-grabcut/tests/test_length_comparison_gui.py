"""画像別校正・幅一定のスラブ基準・実寸差と保存を既知値で確認する."""

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
            str(self.project / "submissions/length_comparison_gui.py")
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
        calibration = self.gui["calibration_from_points"](
            50, ((30, 40), (30 + reference_px, 40)), (700, 800)
        )
        calibration["image_path"] = str(image_path.resolve())
        return {
            "sample_id": name,
            "csv_path": path,
            "thickness_mm": thickness,
            "calibration": calibration,
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

    def test_diagonal_calibration_and_single_image_against_model(self):
        calibration = self.gui["calibration_from_points"](
            50, ((10, 10), (40, 50)), (100, 100)
        )
        self.assertEqual(calibration["reference_px"], 50)
        self.assertEqual(calibration["mm_per_px"], 1)
        with self.comparison.temporary_directory() as temporary:
            sample = self.write_case(Path(temporary), "1枚", (200, 200, 400))
            rows = self.gui["compare_lengths"]([sample], 100, 10)
            self.assertEqual(rows[0]["left_mm"], 100)
            self.assertEqual(rows[0]["delta_left_mm"], 0)
            self.assertIsNone(rows[0]["previous_delta_left_mm"])
            figure = self.gui["create_graph"](rows)
            self.assertEqual(figure.axes[0].lines[2].get_marker(), "s")

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

    def test_multiple_scales_slab_length_csv_graph_and_independent_script(self):
        with self.comparison.temporary_directory() as temporary:
            directory = Path(temporary)
            samples = self.known_samples(directory)
            before = [
                (
                    sample["csv_path"].read_bytes(),
                    Path(sample["calibration"]["image_path"]).read_bytes(),
                )
                for sample in samples
            ]
            copy = directory / "length_comparison_gui.py"
            copy.write_bytes(
                (self.project / "submissions/length_comparison_gui.py").read_bytes()
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
                saved[0]["image_path"], samples[0]["calibration"]["image_path"]
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
                        Path(sample["calibration"]["image_path"]).read_bytes(),
                    )
                    for sample in samples
                ],
                before,
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
                [dict(samples[0], calibration=None)],
            ]
            for items in invalid_samples:
                with self.subTest(items=items):
                    with self.assertRaises(ValueError):
                        self.gui["compare_lengths"](items, 100, 10)
            path = samples[2]["csv_path"]
            path.write_text(
                path.read_text(encoding="utf-8-sig").replace(",30,430", ",30,900"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "校正画像"):
                self.gui["compare_lengths"](samples, 100, 10)
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
                    Path(sample["calibration"]["image_path"]).read_bytes(),
                )
                for sample in samples
            ]
            for sample in samples:
                with self.assertRaisesRegex(ValueError, "入力CSV"):
                    self.gui["write_csv"](sample["csv_path"], rows)
                with self.assertRaisesRegex(ValueError, "校正画像"):
                    self.gui["write_graph"](
                        Path(sample["calibration"]["image_path"]), rows
                    )
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
                        Path(sample["calibration"]["image_path"]).read_bytes(),
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


if __name__ == "__main__":
    unittest.main()
