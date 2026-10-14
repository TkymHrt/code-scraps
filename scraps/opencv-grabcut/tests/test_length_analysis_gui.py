"""伸びと側辺形状の分離、割合の前回差、CSV入出力を既知の寸法で確認する."""

import csv
import math
import runpy
import tempfile
import unittest
from pathlib import Path

import numpy as np

PROJECT = Path(__file__).resolve().parents[1]


def write_sample(
    directory, name, interval, left, right, thickness, scale=0.25, start=20
):
    row = {
        "image_path": f"{name}.png",
        "image_width": 400,
        "image_height": start + round(interval / scale) + 10,
        "mm_per_px": scale,
        "start_y": start,
        "end_y": start + round(interval / scale),
        "left_px": left / scale,
        "left_mm": left,
        "right_px": right / scale,
        "right_mm": right,
        "total_px": (left + right) / scale,
        "total_mm": left + right,
    }
    path = directory / f"{name}.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    return {"csv_path": path, "thickness_mm": thickness}


class LengthAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.script = PROJECT / "submissions/length_analysis_gui.py"
        self.gui = runpy.run_path(str(self.script))

    def test_straight_extension_and_side_detour_are_separate_quantities(self):
        samples = [
            write_sample(self.directory, "初期", 100, 100, 100, 10),
            write_sample(self.directory, "伸びだけ", 210, 210, 210, 5),
            write_sample(self.directory, "形状だけ", 200, 210, 200, 5),
        ]
        rows = self.gui["analyze_lengths"](samples, 100, 10)
        self.assertEqual([row["ideal_length_mm"] for row in rows], [100, 200, 200])
        self.assertEqual([row["interval_length_mm"] for row in rows], [100, 210, 200])
        self.assertEqual([row["stretch_pct"] for row in rows], [0, 5, 0])
        self.assertEqual([row["left_shape_pct"] for row in rows], [0, 0, 5])
        self.assertEqual([row["right_shape_pct"] for row in rows], [0, 0, 0])
        self.assertIsNone(rows[0]["previous_delta_stretch_pp"])
        self.assertEqual(rows[2]["previous_delta_stretch_pp"], -5)
        self.assertEqual(rows[2]["previous_delta_left_shape_pp"], 5)
        for row in rows:
            for edge in ("left", "right"):
                total_deviation = row[f"{edge}_mm"] - row["ideal_length_mm"]
                components = row["stretch_delta_mm"] + row[f"{edge}_excess_mm"]
                self.assertAlmostEqual(total_deviation, components)

    def test_same_relative_shape_has_zero_change_even_when_length_doubles(self):
        samples = [
            write_sample(self.directory, "初期", 100, 105, 100, 10),
            write_sample(self.directory, "2倍", 200, 210, 200, 5),
            write_sample(self.directory, "4倍", 400, 420, 400, 2.5),
            write_sample(self.directory, "変化", 420, 462, 441, 2.5),
        ]
        rows = self.gui["analyze_lengths"](samples, 100, 10)
        self.assertEqual([row["left_shape_pct"] for row in rows], [5, 5, 5, 10])
        self.assertEqual([row["stretch_pct"] for row in rows], [0, 0, 0, 5])
        self.assertEqual(rows[1]["previous_delta_left_shape_pp"], 0)
        self.assertEqual(rows[2]["previous_delta_left_shape_pp"], 0)
        self.assertEqual(rows[3]["previous_delta_left_shape_pp"], 5)
        self.assertEqual(rows[3]["previous_delta_right_shape_pp"], 5)
        self.assertEqual(rows[3]["previous_delta_stretch_pp"], 5)
        figure = self.gui["create_graph"](rows)
        axes = figure.axes
        self.assertEqual(len(axes), 4)
        np.testing.assert_allclose(axes[0].lines[0].get_ydata(), [0, 0, 0, 5])
        np.testing.assert_allclose(axes[1].lines[0].get_ydata(), [5, 5, 5, 10])
        self.assertEqual([bar.get_height() for bar in axes[2].patches], [0, 0, 5])
        self.assertEqual(
            [bar.get_height() for bar in axes[3].patches], [0, 0, 5, 0, 0, 5]
        )
        self.assertEqual(
            [bar.get_x() + bar.get_width() / 2 for bar in axes[2].patches], [2, 3, 4]
        )

    def test_endpoint_spacing_scales_and_single_pass_without_previous(self):
        samples = [
            write_sample(
                self.directory, "撮影1", 100, 105, 102, 10, scale=0.25, start=20
            ),
            write_sample(
                self.directory, "撮影2", 100, 105, 102, 10, scale=0.5, start=60
            ),
        ]
        rows = self.gui["analyze_lengths"](samples, 100, 10)
        self.assertEqual(rows[0]["interval_length_mm"], 100)
        self.assertEqual(rows[1]["interval_length_mm"], 100)
        self.assertEqual(rows[1]["previous_delta_left_shape_pp"], 0)
        single = self.gui["create_graph"](rows[:1])
        self.assertFalse(single.axes[2].patches)
        self.assertFalse(single.axes[3].patches)
        shorter = write_sample(self.directory, "短い区間", 90, 90, 90, 10)
        row = self.gui["analyze_lengths"]([shorter], 100, 10)[0]
        self.assertEqual(row["stretch_pct"], -10)
        self.assertEqual(row["left_shape_pct"], 0)

    def test_standalone_copy_csv_graph_and_protected_inputs(self):
        copied = self.directory / "length_analysis_gui.py"
        copied.write_bytes(self.script.read_bytes())
        gui = runpy.run_path(str(copied))
        sample = write_sample(self.directory, "入力 日本語", 100, 105, 100, 10)
        source_before = sample["csv_path"].read_bytes()
        image_path = self.directory / "入力 日本語.png"
        image_path.write_bytes(b"protected image")
        rows = gui["analyze_lengths"]([sample], 100, 10)
        self.assertEqual(rows[0]["image_path"], str(image_path.resolve()))
        output = self.directory / "output/分析.csv"
        graph = self.directory / "output/分析.png"
        gui["write_csv"](output, rows)
        gui["write_graph"](graph, rows)
        self.assertTrue(output.read_bytes().startswith(b"\xef\xbb\xbf"))
        with output.open(encoding="utf-8-sig", newline="") as source:
            saved = list(csv.DictReader(source))
        self.assertEqual(saved[0]["left_shape_pct"], "5")
        self.assertEqual(saved[0]["previous_delta_left_shape_pp"], "")
        self.assertEqual(saved[0]["previous_id"], "")
        self.assertEqual(graph.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        with self.assertRaisesRegex(ValueError, "別の保存先"):
            gui["write_csv"](sample["csv_path"], rows)
        with self.assertRaisesRegex(ValueError, "別の保存先"):
            gui["write_graph"](image_path, rows)
        with self.assertRaises(ValueError):
            gui["write_graph"](self.directory / "wrong.csv", rows)
        with self.assertRaises(ValueError):
            gui["write_csv"](output, [])
        self.assertEqual(sample["csv_path"].read_bytes(), source_before)
        self.assertEqual(image_path.read_bytes(), b"protected image")
        image_path.unlink()
        self.assertEqual(gui["analyze_lengths"]([sample], 100, 10), rows)

    def test_bad_conditions_and_invalid_csv_stop_analysis(self):
        sample = write_sample(self.directory, "正常", 100, 100, 100, 10)
        for length, thickness in ((0, 10), (100, -1), (100, math.nan), (math.inf, 10)):
            with (
                self.subTest(length=length, thickness=thickness),
                self.assertRaises(ValueError),
            ):
                self.gui["analyze_lengths"]([sample], length, thickness)
        for samples in (
            [],
            [sample, sample],
            [dict(sample, thickness_mm="")],
            [dict(sample, thickness_mm=0)],
        ):
            with self.assertRaises(ValueError):
                self.gui["analyze_lengths"](samples, 100, 10)
        path = sample["csv_path"]
        with path.open(encoding="utf-8-sig", newline="") as source:
            original = list(csv.DictReader(source))[0]
        for changes in (
            {"left_mm": "101"},
            {"mm_per_px": "nan"},
            {"start_y": "1.5"},
            {"end_y": original["image_height"]},
            {"image_path": ""},
            {"left_px": "396", "left_mm": "99", "total_px": "796", "total_mm": "199"},
        ):
            bad = dict(original, **changes)
            with path.open("w", encoding="utf-8-sig", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=list(bad))
                writer.writeheader()
                writer.writerow(bad)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.gui["read_lengths"](path)
        for count in (0, 2):
            with path.open("w", encoding="utf-8-sig", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=list(original))
                writer.writeheader()
                for _ in range(count):
                    writer.writerow(original)
            with self.assertRaisesRegex(ValueError, "1行"):
                self.gui["read_lengths"](path)

    def test_order_controls_previous_difference_and_large_batch(self):
        samples = []
        for index in range(20):
            samples.append(
                write_sample(
                    self.directory, f"パス{index + 1}", 100, 100 + index, 100, 10
                )
            )
        rows = self.gui["analyze_lengths"](samples, 100, 10)
        self.assertEqual(len(rows), 20)
        self.assertEqual(rows[-1]["left_shape_pct"], 19)
        self.assertEqual(rows[-1]["previous_delta_left_shape_pp"], 1)
        reverse = self.gui["analyze_lengths"](list(reversed(samples)), 100, 10)
        self.assertEqual(reverse[1]["previous_delta_left_shape_pp"], -1)
        self.assertEqual(reverse[1]["previous_id"], reverse[0]["sample_id"])


if __name__ == "__main__":
    unittest.main()
