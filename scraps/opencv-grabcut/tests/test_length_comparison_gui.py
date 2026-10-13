"""長さ専用GUIの差分、03形式の入力、保存結果と入力保護を確認する."""

import csv
import runpy
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2 as cv
import numpy as np
import test_submission_comparison
from matplotlib import pyplot as plt


class LengthComparisonGuiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = Path(__file__).resolve().parents[1]
        self.gui = runpy.run_path(
            str(self.project / "submissions/length_comparison_gui.py")
        )
        self.comparison = test_submission_comparison.SubmissionComparisonTests()

    def test_known_differences_csv_graph_and_independent_script(self) -> None:
        """負・正の差と03の丸めを確認し、04の結果と数値を照合する."""
        with self.comparison.temporary_directory() as temporary:
            directory = Path(temporary)
            baseline = directory / "基準 長さ.csv"
            comparison = directory / "比較 長さ.csv"
            self.comparison.write_lengths(baseline, (124.32, 124.32, 248.65))
            self.comparison.write_lengths(comparison, (110.25, 125.5, 235.75))
            original_bytes = (baseline.read_bytes(), comparison.read_bytes())
            copy = directory / "length_comparison_gui.py"
            copy.write_bytes(
                (self.project / "submissions/length_comparison_gui.py").read_bytes()
            )
            gui = runpy.run_path(str(copy))
            rows = gui["compare_lengths"](baseline, comparison)
            self.assertEqual([row["edge"] for row in rows], ["left", "right", "total"])
            for row, expected in zip(rows, (-14.07, 1.18, -12.9)):
                self.assertAlmostEqual(row["delta_px"], expected)
                self.assertEqual((row["start_y"], row["end_y"]), (20, 140))

            csv_path = directory / "出力/長さ 比較.csv"
            gui["write_csv"](csv_path, rows)
            with csv_path.open(encoding="utf-8-sig", newline="") as source:
                saved = list(csv.DictReader(source))
            self.assertEqual(
                [row["delta_px"] for row in saved], ["-14.07", "1.18", "-12.90"]
            )
            self.assertEqual(saved[0]["baseline_csv"], str(baseline.resolve()))
            self.assertEqual(saved[0]["comparison_csv"], str(comparison.resolve()))

            script = directory / "04_compare_lengths.py"
            script.write_text(
                self.comparison.script_source(
                    INPUT_CSVS=(("基準", str(baseline)), ("比較対象", str(comparison))),
                    BASELINE_ID="基準",
                ),
                encoding="utf-8",
            )
            runpy.run_path(str(script))
            with (directory / "comparison.csv").open(
                encoding="utf-8", newline=""
            ) as source:
                reference = list(csv.DictReader(source))
            for edge, row in zip(("left", "right", "total"), saved):
                self.assertEqual(row["baseline_px"], reference[0][f"{edge}_px"])
                self.assertEqual(row["comparison_px"], reference[1][f"{edge}_px"])
                self.assertEqual(row["delta_px"], reference[1][f"delta_{edge}_px"])

            graph_path = directory / "出力/左右の長さ.png"
            original_subplots = plt.subplots
            figures = []

            def capture_figure(*args, **kwargs):
                figure, axes = original_subplots(*args, **kwargs)
                figures.append((figure, axes))
                return figure, axes

            with patch.object(plt, "subplots", side_effect=capture_figure):
                gui["write_graph"](graph_path, rows)
            figure, axes = figures[0]
            self.assertEqual(
                [bar.get_height() for bar in axes.patches],
                [124.32, 124.32, 110.25, 125.5],
            )
            self.assertEqual(axes.get_ylim()[0], 0)
            self.assertFalse(plt.fignum_exists(figure.number))
            image = cv.imdecode(
                np.frombuffer(graph_path.read_bytes(), np.uint8), cv.IMREAD_COLOR
            )
            if image is None:
                self.fail("保存したグラフを読み込めません")
            self.assertGreater(float(np.std(image)), 10)
            self.assertEqual(
                (baseline.read_bytes(), comparison.read_bytes()), original_bytes
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

    def test_same_input_and_different_ranges_are_rejected(self) -> None:
        with self.comparison.temporary_directory() as temporary:
            directory = Path(temporary)
            baseline = directory / "A.csv"
            comparison = directory / "B.csv"
            self.comparison.write_lengths(baseline)
            self.comparison.write_lengths(comparison)
            with self.assertRaisesRegex(ValueError, "別々"):
                self.gui["compare_lengths"](baseline, baseline)
            comparison.write_text(
                comparison.read_text(encoding="utf-8-sig").replace(
                    ",20,140", ",21,140"
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "計測範囲"):
                self.gui["compare_lengths"](baseline, comparison)

    def test_input_and_extension_protection(self) -> None:
        with self.comparison.temporary_directory() as temporary:
            directory = Path(temporary)
            baseline = directory / "A.csv"
            comparison = directory / "B.csv"
            self.comparison.write_lengths(baseline)
            self.comparison.write_lengths(comparison)
            rows = self.gui["compare_lengths"](baseline, comparison)
            original_bytes = (baseline.read_bytes(), comparison.read_bytes())
            for path in (baseline, comparison):
                with self.assertRaisesRegex(ValueError, "入力CSV"):
                    self.gui["write_csv"](path, rows)
            wrong_csv = directory / "wrong.txt"
            wrong_graph = directory / "wrong.csv"
            with self.assertRaisesRegex(ValueError, "拡張子"):
                self.gui["write_csv"](wrong_csv, rows)
            with self.assertRaisesRegex(ValueError, "拡張子"):
                self.gui["write_graph"](wrong_graph, rows)
            self.assertFalse(wrong_csv.exists())
            self.assertFalse(wrong_graph.exists())
            self.assertEqual(
                (baseline.read_bytes(), comparison.read_bytes()), original_bytes
            )


if __name__ == "__main__":
    unittest.main()
