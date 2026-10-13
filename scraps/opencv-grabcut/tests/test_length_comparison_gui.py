"""撮影ごとの長さGUIの複数入力・撮影順・基準差・前回差と保存を確認する."""

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

    def known_samples(self, directory: Path) -> list[tuple[str, Path]]:
        samples = []
        for name, lengths in (
            ("撮影C", (120.0, 120.0, 240.0)),
            ("撮影B", (110.25, 125.5, 235.75)),
            ("基準", (124.32, 124.32, 248.65)),
        ):
            path = directory / name / "03_side_lengths.csv"
            self.comparison.write_lengths(path, lengths)
            samples.append((name, path))
        return samples

    def graph_axes(self, gui: dict, path: Path, rows: list[dict]):
        figure = gui["create_graph"](rows)
        gui["write_graph"](path, rows)
        return figure.axes

    def test_multiple_differences_csv_graph_and_independent_script(self) -> None:
        """基準を最後に置いた3枚の値を、既知の差と提出版04に照合する."""
        with self.comparison.temporary_directory() as temporary:
            directory = Path(temporary)
            samples = self.known_samples(directory)
            original_bytes = [path.read_bytes() for _, path in samples]
            copy = directory / "length_comparison_gui.py"
            copy.write_bytes(
                (self.project / "submissions/length_comparison_gui.py").read_bytes()
            )
            gui = runpy.run_path(str(copy))
            rows = gui["compare_lengths"](samples, "基準")
            self.assertEqual(
                [row["sample_id"] for row in rows], ["撮影C", "撮影B", "基準"]
            )
            self.assertEqual(
                [row["previous_id"] for row in rows], ["", "撮影C", "撮影B"]
            )
            for row, differences in zip(
                rows, ((-4.32, -4.32, -8.65), (-14.07, 1.18, -12.9), (0, 0, 0))
            ):
                for edge, expected in zip(("left", "right", "total"), differences):
                    self.assertAlmostEqual(row[f"delta_{edge}_px"], expected)
                self.assertEqual((row["start_y"], row["end_y"]), (20, 140))
            for edge in ("left", "right", "total"):
                self.assertIsNone(rows[0][f"previous_delta_{edge}_px"])
            self.assertAlmostEqual(rows[1]["previous_delta_left_px"], -9.75)
            self.assertAlmostEqual(rows[1]["previous_delta_right_px"], 5.5)
            self.assertAlmostEqual(rows[1]["previous_delta_total_px"], -4.25)
            self.assertAlmostEqual(rows[2]["previous_delta_total_px"], 12.9)

            csv_path = directory / "出力/長さ 比較.csv"
            gui["write_csv"](csv_path, rows)
            with csv_path.open(encoding="utf-8-sig", newline="") as source:
                saved = list(csv.DictReader(source))
            self.assertEqual(saved[0]["previous_delta_total_px"], "")
            self.assertEqual(saved[1]["previous_delta_total_px"], "-4.25")
            self.assertEqual(saved[0]["baseline_csv"], str(samples[2][1].resolve()))
            self.assertEqual(saved[0]["input_csv"], str(samples[0][1].resolve()))

            script = directory / "04_compare_lengths.py"
            script.write_text(
                self.comparison.script_source(
                    INPUT_CSVS=tuple((name, str(path)) for name, path in samples),
                    BASELINE_ID="基準",
                ),
                encoding="utf-8",
            )
            runpy.run_path(str(script))
            with (directory / "comparison.csv").open(
                encoding="utf-8", newline=""
            ) as source:
                reference = list(csv.DictReader(source))
            for actual, expected in zip(saved, reference):
                for column in expected:
                    self.assertEqual(actual[column], expected[column])

            graph_path = directory / "出力/撮影 推移.png"
            axes = self.graph_axes(gui, graph_path, rows)
            self.assertEqual(len(axes), 3)
            self.assertEqual(
                list(axes[0].lines[0].get_ydata()), [120.0, 110.25, 124.32]
            )
            np.testing.assert_allclose(axes[1].lines[2].get_ydata(), [-8.65, -12.9, 0])
            np.testing.assert_allclose(
                axes[2].lines[2].get_ydata(), [np.nan, -4.25, 12.9], equal_nan=True
            )
            self.assertEqual(axes[0].get_ylim()[0], 0)
            self.assertEqual(
                [label.get_text() for label in axes[2].get_xticklabels()],
                ["撮影C", "撮影B", "基準（基準）"],
            )
            image = cv.imdecode(
                np.frombuffer(graph_path.read_bytes(), np.uint8), cv.IMREAD_COLOR
            )
            if image is None:
                self.fail("保存したグラフを読み込めません")
            self.assertGreater(float(np.std(image)), 10)
            self.assertEqual([path.read_bytes() for _, path in samples], original_bytes)

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

    def test_invalid_sample_lists_and_different_ranges_are_rejected(self) -> None:
        with self.comparison.temporary_directory() as temporary:
            samples = self.known_samples(Path(temporary))
            for items, baseline in (
                ([], "基準"),
                (samples[:1], "撮影C"),
                (samples + [samples[0]], "基準"),
                ([("撮影C", samples[0][1]), ("別名", samples[0][1])], "撮影C"),
                ([("撮影C", samples[0][1]), ("撮影C", samples[1][1])], "撮影C"),
                ([(" ", samples[0][1]), samples[1]], "撮影B"),
                (samples, "存在しない"),
            ):
                with self.subTest(items=items, baseline=baseline):
                    with self.assertRaises(ValueError):
                        self.gui["compare_lengths"](items, baseline)
            last = samples[2][1]
            last.write_text(
                last.read_text(encoding="utf-8-sig").replace(",20,140", ",21,140"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "計測範囲"):
                self.gui["compare_lengths"](samples, "撮影C")
            last.unlink()
            with self.assertRaises(OSError):
                self.gui["compare_lengths"](samples, "撮影C")

    def test_all_inputs_and_extensions_are_protected(self) -> None:
        with self.comparison.temporary_directory() as temporary:
            directory = Path(temporary)
            samples = self.known_samples(directory)
            rows = self.gui["compare_lengths"](samples, "基準")
            original_bytes = [path.read_bytes() for _, path in samples]
            for _, path in samples:
                with self.assertRaisesRegex(ValueError, "入力CSV"):
                    self.gui["write_csv"](path, rows)
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
            self.assertEqual([path.read_bytes() for _, path in samples], original_bytes)

    def test_reordering_changes_previous_difference_and_preserves_baseline_difference(
        self,
    ) -> None:
        with self.comparison.temporary_directory() as temporary:
            samples = self.known_samples(Path(temporary))
            original = self.gui["compare_lengths"](samples, "基準")
            reordered = self.gui["compare_lengths"](
                [samples[2], samples[0], samples[1]], "基準"
            )
            by_name = {row["sample_id"]: row for row in original}
            for row in reordered:
                self.assertEqual(
                    row["delta_total_px"], by_name[row["sample_id"]]["delta_total_px"]
                )
            self.assertEqual(
                [row["previous_id"] for row in reordered], ["", "基準", "撮影C"]
            )
            self.assertIsNone(reordered[0]["previous_delta_total_px"])
            self.assertAlmostEqual(reordered[1]["previous_delta_total_px"], -8.65)
            self.assertAlmostEqual(reordered[2]["previous_delta_total_px"], -4.25)
            changed_baseline = self.gui["compare_lengths"](samples, "撮影B")
            self.assertAlmostEqual(changed_baseline[0]["delta_total_px"], 4.25)
            self.assertEqual(
                changed_baseline[0]["previous_delta_total_px"],
                original[0]["previous_delta_total_px"],
            )

    def test_twenty_shootings_keep_every_csv_row_and_graph_point(self) -> None:
        with self.comparison.temporary_directory() as temporary:
            directory = Path(temporary)
            samples = []
            for index in range(20):
                name = f"撮影{index + 1:02d}"
                path = directory / name / "03_side_lengths.csv"
                self.comparison.write_lengths(
                    path, (120 + index, 120 + index * 0.5, 240 + index * 1.5)
                )
                samples.append((name, path))
            rows = self.gui["compare_lengths"](samples, "撮影08")
            self.assertEqual(len(rows), 20)
            self.assertEqual(rows[-1]["delta_total_px"], 18.0)
            self.assertEqual(rows[-1]["previous_delta_total_px"], 1.5)
            self.gui["write_csv"](directory / "many.csv", rows)
            with (directory / "many.csv").open(
                encoding="utf-8-sig", newline=""
            ) as source:
                saved = list(csv.DictReader(source))
            self.assertEqual(
                [row["sample_id"] for row in saved], [name for name, _ in samples]
            )
            axes = self.graph_axes(self.gui, directory / "many.png", rows)
            self.assertEqual(len(axes[0].lines[0].get_ydata()), 20)
            self.assertEqual(len(axes[2].get_xticklabels()), 20)
            self.assertIn("基準", axes[2].get_xticklabels()[7].get_text())
            self.assertEqual(axes[2].get_xticklabels()[-1].get_rotation(), 45)


if __name__ == "__main__":
    unittest.main()
