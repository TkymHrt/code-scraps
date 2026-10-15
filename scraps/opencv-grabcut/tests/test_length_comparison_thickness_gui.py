"""実測厚さによる累積圧下率、4通りのグラフとPNG保存を確認する。"""

import runpy
import tempfile
import unittest
from pathlib import Path

import numpy as np
from test_length_comparison_local_gui import sample_csv

PROJECT = Path(__file__).resolve().parents[1]


class ThicknessComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.script = (
            PROJECT / "submissions/03_compare_edge_lengths_with_thickness_gui.py"
        )
        self.gui = runpy.run_path(str(self.script))
        self.samples: list[dict] = [
            {"csv_path": sample_csv(self.directory, "p00_a"), "thickness_mm": 10},
            {
                "csv_path": sample_csv(self.directory, "p01_a", 200, 208, 204),
                "thickness_mm": "8",
            },
            {
                "csv_path": sample_csv(self.directory, "p01_b", 100, 108, 106),
                "thickness_mm": 8,
            },
            {
                "csv_path": sample_csv(self.directory, "p02_a", 100, 110, 108),
                "thickness_mm": 6,
            },
        ]

    def test_initial_thickness_and_observations_define_cumulative_reduction(self):
        rows = self.gui["compare_lengths"](self.samples, "10")
        self.assertEqual([row["reduction_pct"] for row in rows], [0, 20, 20, 40])
        self.assertEqual([row["thickness_mm"] for row in rows], [10, 8, 8, 6])
        self.assertEqual([row["initial_thickness_mm"] for row in rows], [10] * 4)
        np.testing.assert_allclose(
            [row["left_per_100mm"] for row in rows], [104, 104, 108, 110]
        )
        self.assertEqual(rows[1]["interval_length_mm"], 200)
        # 厚さだけを変更した再比較は、画像の再抽出を必要としない。
        changed = self.gui["compare_lengths"](self.samples, 20)
        self.assertEqual([row["reduction_pct"] for row in changed], [50, 60, 60, 70])
        self.assertEqual(changed[1]["left_mm"], rows[1]["left_mm"])

    def test_four_graph_modes_keep_repeated_reduction_points_and_reference(self):
        rows = self.gui["compare_lengths"](self.samples, 10)
        for normalized in (False, True):
            for reduction_axis in (False, True):
                with self.subTest(normalized=normalized, reduction_axis=reduction_axis):
                    figure = self.gui["create_graph"](rows, normalized, reduction_axis)
                    axis = figure.axes[0]
                    expected_x = [0, 20, 20, 40] if reduction_axis else [1, 2, 3, 4]
                    expected_y = (
                        [104, 104, 108, 110] if normalized else [104, 208, 108, 110]
                    )
                    np.testing.assert_allclose(axis.lines[0].get_xdata(), expected_x)
                    np.testing.assert_allclose(axis.lines[0].get_ydata(), expected_y)
                    self.assertEqual(axis.lines[0].get_linestyle(), "-")
                    self.assertEqual(axis.lines[1].get_linestyle(), "-")
                    self.assertEqual(axis.lines[2].get_linestyle(), "--")
                    expected_reference = (
                        [100, 100] if normalized else [100, 200, 100, 100]
                    )
                    np.testing.assert_allclose(
                        axis.lines[2].get_ydata(), expected_reference
                    )
                    self.assertEqual(len(axis.lines), 3)
                    if reduction_axis:
                        self.assertEqual(axis.get_xlabel(), "累積圧下率 (%)")
                    else:
                        self.assertEqual(
                            [text.get_text() for text in axis.get_xticklabels()],
                            ["p00_a", "p01_a", "p01_b", "p02_a"],
                        )

    def test_standalone_png_save_and_input_protection(self):
        copied = self.directory / self.script.name
        copied.write_bytes(self.script.read_bytes())
        gui = runpy.run_path(str(copied))
        before = [sample["csv_path"].read_bytes() for sample in self.samples]
        rows = gui["compare_lengths"](self.samples, 10)
        for normalized in (False, True):
            for reduction_axis in (False, True):
                graph = self.directory / f"出力/graph_{normalized}_{reduction_axis}.png"
                gui["write_graph"](graph, rows, normalized, reduction_axis)
                self.assertEqual(graph.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        with self.assertRaises(ValueError):
            gui["write_graph"](self.samples[0]["csv_path"], rows)
        with self.assertRaises(ValueError):
            gui["write_graph"](Path(rows[0]["image_path"]), rows)
        self.assertEqual(
            [sample["csv_path"].read_bytes() for sample in self.samples], before
        )

    def test_empty_duplicate_and_invalid_thickness_inputs_are_rejected(self):
        for value in (None, "", "abc", 0, -1, "nan", "inf"):
            with self.subTest(initial=value), self.assertRaises(ValueError):
                self.gui["compare_lengths"](self.samples, value)
            samples = [dict(self.samples[0], thickness_mm=value)]
            with self.subTest(thickness=value), self.assertRaises(ValueError):
                self.gui["compare_lengths"](samples, 10)
        for samples in ([], self.samples + [self.samples[0]]):
            with self.assertRaises(ValueError):
                self.gui["compare_lengths"](samples, 10)
        with self.assertRaises(ValueError):
            self.gui["compare_lengths"](
                [dict(self.samples[0], thickness_mm=1e308)], 1e-308
            )

    def test_single_twenty_and_nonmonotonic_observations_preserve_input_order(self):
        samples = []
        for index in range(20):
            samples.append(
                {
                    "csv_path": sample_csv(self.directory, f"撮影{index:02}"),
                    "thickness_mm": 8,
                }
            )
        rows = self.gui["compare_lengths"](list(reversed(samples)), 10)
        self.assertEqual(rows[0]["csv_name"], "撮影19.csv")
        figure = self.gui["create_graph"](rows, True, True)
        np.testing.assert_allclose(figure.axes[0].lines[0].get_xdata(), [20] * 20)
        single = self.gui["create_graph"](rows[:1], True, True)
        self.assertEqual(len(single.axes[0].lines[0].get_xdata()), 1)
        nonmonotonic = self.gui["compare_lengths"](list(reversed(self.samples)), 10)
        self.assertEqual(
            [row["reduction_pct"] for row in nonmonotonic], [40, 20, 20, 0]
        )
        thicker = self.gui["compare_lengths"](
            [dict(self.samples[0], thickness_mm=11)], 10
        )
        self.assertEqual(thicker[0]["reduction_pct"], -10)


if __name__ == "__main__":
    unittest.main()
