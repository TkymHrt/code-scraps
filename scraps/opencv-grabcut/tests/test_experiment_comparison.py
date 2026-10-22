"""実験回の比較図で、対応する区間の集計・表示・保存を確認する。"""

import csv
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2 as cv
import numpy as np
from matplotlib.collections import LineCollection, PathCollection
from matplotlib.colors import to_rgba
from test_refactored_workflow import (
    copy_refactored,
    load_refactored,
    run_refactored,
)


class ExperimentComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name) / "実験 比較"
        self.directory.mkdir()
        self.module = load_refactored("05_plot_experiment_comparison.py")

    def measurement(self, name, dr=1.0, op=2.0, **changes):
        path = self.directory / name
        row = {
            "image_path": str(path.with_suffix(".png")),
            "interval_length_mm": 100.0,
            "left_mm": 100.0 * (1 + dr / 100),
            "right_mm": 100.0 * (1 + op / 100),
            "left_excess_percent": dr,
            "right_excess_percent": op,
            "mm_per_px": 0.25,
            "evaluation_interval_mm": 1.0,
            "smoothing_width_mm": 2.0,
        }
        row.update(changes)
        with path.open("w", encoding="utf-8-sig", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=list(row))
            writer.writeheader()
            writer.writerow(row)
        return path

    def read_measurements(self, measurements):
        reader = self.module["read_pass_measurements"]
        with patch.dict(reader.__globals__, {"BASE_DIRECTORY": self.directory}):
            return reader(measurements)

    def example_measurements(self):
        # A/Bの初回値を違わせ、欠測と実験回の混同も検出する。
        data = (
            ("runA", 6, "A", 5, 8),
            ("runB", 4, "A", 7, 12),
            ("runA", 2, "B", 6, 8),
            ("runA", 0, "A", 1, 2),
            ("runB", 0, "A", 10, 8),
            ("runA", 0, "B", 4, 9),
            ("runA", 2, "A", 3, 2),
        )
        measurements = []
        for experiment, number, section, dr, op in data:
            path = self.measurement(f"{experiment}_{section}_{number}.csv", dr, op)
            measurements.append((experiment, number, section, path.name))
        measurements[1] = (
            *measurements[1][:3],
            str(self.directory / measurements[1][3]),
        )
        return measurements

    def figures(self, rows):
        figures = self.module["create_graphs"](rows)
        for figure in figures:
            self.addCleanup(figure.clear)
        return figures

    def assert_series(self, axis, experiment, x_values, y_values):
        matching = []
        for line in axis.lines:
            if line.get_label() == experiment:
                matching.append(line)
        self.assertEqual(len(matching), 1)
        np.testing.assert_array_equal(matching[0].get_xdata(), x_values)
        np.testing.assert_allclose(matching[0].get_ydata(), y_values)
        return matching[0]

    def test_summary_pairs_sections_and_keeps_experiments_separate(self):
        rows = self.read_measurements(self.example_measurements())
        grouped = {}
        for summary in self.module["summarize_measurements"](rows):
            grouped[(summary["experiment_id"], summary["pass_number"])] = summary
        self.assertEqual(
            set(grouped),
            {("runA", 0), ("runA", 2), ("runA", 6), ("runB", 0), ("runB", 4)},
        )
        initial = grouped[("runA", 0)]
        self.assertEqual(initial["count"], 2)
        self.assertAlmostEqual(initial["left_excess_percent_mean"], 2.5)
        self.assertAlmostEqual(initial["left_excess_percent_sd"], math.sqrt(4.5))
        self.assertAlmostEqual(initial["right_excess_percent_mean"], 5.5)
        self.assertAlmostEqual(initial["right_excess_percent_sd"], math.sqrt(24.5))
        later = grouped[("runA", 2)]
        np.testing.assert_allclose(later["left_change_points_values"], [2, 2])
        np.testing.assert_allclose(later["right_change_points_values"], [0, -1])
        np.testing.assert_allclose(later["difference_points_values"], [1, -2])
        self.assertAlmostEqual(later["left_change_points_mean"], 2)
        self.assertAlmostEqual(later["right_change_points_mean"], -0.5)
        self.assertAlmostEqual(later["right_change_points_sd"], math.sqrt(0.5))
        self.assertAlmostEqual(later["difference_points_mean"], -0.5)
        self.assertAlmostEqual(later["difference_points_sd"], math.sqrt(4.5))
        self.assertEqual(grouped[("runA", 6)]["count"], 1)
        self.assertIsNone(grouped[("runA", 6)]["difference_points_sd"])
        self.assertAlmostEqual(grouped[("runB", 0)]["left_excess_percent_mean"], 10)
        self.assertAlmostEqual(grouped[("runB", 4)]["left_change_points_mean"], -3)
        self.assertAlmostEqual(grouped[("runB", 4)]["right_change_points_mean"], 4)

    def test_panels_compare_sides_on_shared_scales_at_actual_pass_numbers(self):
        rows = self.read_measurements(self.example_measurements())
        excess, change, difference = self.figures(rows)
        self.assertEqual(
            [len(figure.axes) for figure in (excess, change, difference)], [2, 2, 1]
        )
        self.assert_series(excess.axes[0], "runA", [0, 2, 6], [2.5, 4.5, 5])
        self.assert_series(excess.axes[1], "runA", [0, 2, 6], [5.5, 5, 8])
        self.assert_series(excess.axes[0], "runB", [0, 4], [10, 7])
        self.assert_series(excess.axes[1], "runB", [0, 4], [8, 12])
        self.assert_series(change.axes[0], "runA", [0, 2, 6], [0, 2, 4])
        self.assert_series(change.axes[1], "runA", [0, 2, 6], [0, -0.5, 6])
        self.assert_series(change.axes[0], "runB", [0, 4], [0, -3])
        self.assert_series(change.axes[1], "runB", [0, 4], [0, 4])
        self.assert_series(difference.axes[0], "runA", [0, 2, 6], [-3, -0.5, -3])
        self.assert_series(difference.axes[0], "runB", [0, 4], [2, -5])
        for figure in (excess, change):
            left, right = figure.axes
            self.assertTrue(left.get_shared_x_axes().joined(left, right))
            self.assertTrue(left.get_shared_y_axes().joined(left, right))
            self.assertEqual(left.get_xlim(), right.get_xlim())
            self.assertEqual(left.get_ylim(), right.get_ylim())
            for axis, side in zip(figure.axes, ("DR", "OP")):
                labels = [text.get_text() for text in axis.texts]
                self.assertTrue(any(label.endswith(side) for label in labels))
        for figure in (excess, change, difference):
            for axis in figure.axes:
                np.testing.assert_array_equal(axis.get_xticks(), [0, 2, 4, 6])

    def test_experiment_styles_and_paper_style_are_consistent_on_all_panels(self):
        figures = self.figures(self.read_measurements(self.example_measurements()))
        expected_styles = {}
        for figure in figures:
            self.assertFalse(figure.get_suptitle())
            for axis in figure.axes:
                self.assertEqual(axis.get_xlabel(), "Number of rolling passes")
                self.assertFalse(axis.get_title())
                for gridline in axis.get_xgridlines() + axis.get_ygridlines():
                    self.assertFalse(gridline.get_visible())
                for spine in axis.spines.values():
                    self.assertTrue(spine.get_visible())
                for coordinate_axis in (axis.xaxis, axis.yaxis):
                    tick = coordinate_axis.get_major_ticks()[0]
                    self.assertEqual(tick.get_tickdir(), "in")
                    self.assertTrue(tick.tick1line.get_visible())
                    self.assertTrue(tick.tick2line.get_visible())
                legend = axis.get_legend()
                self.assertIsNotNone(legend)
                self.assertFalse(legend.get_frame_on())
                self.assertEqual(
                    [text.get_text() for text in legend.get_texts()], ["runA", "runB"]
                )
                for line in axis.lines:
                    experiment = line.get_label()
                    if experiment not in ("runA", "runB"):
                        continue
                    style = (
                        to_rgba(line.get_color()),
                        line.get_marker(),
                        line.get_linestyle(),
                    )
                    if experiment not in expected_styles:
                        expected_styles[experiment] = style
                    self.assertEqual(style, expected_styles[experiment])
        self.assertNotEqual(expected_styles["runA"][0], expected_styles["runB"][0])
        self.assertNotEqual(expected_styles["runA"][1], expected_styles["runB"][1])

    def test_raw_points_and_paired_sample_sd_remain_on_their_side_panels(self):
        figures = self.figures(self.read_measurements(self.example_measurements()))
        expected_points = (
            [(0, 1), (0, 4), (0, 10), (2, 3), (2, 6), (4, 7), (6, 5)],
            [(0, 2), (0, 9), (0, 8), (2, 2), (2, 8), (4, 12), (6, 8)],
            [(0, 0)] * 3 + [(2, 2), (2, 2), (4, -3), (6, 4)],
            [(0, 0)] * 3 + [(2, 0), (2, -1), (4, 4), (6, 6)],
            [(0, -1), (0, -5), (0, 2), (2, 1), (2, -2), (4, -5), (6, -3)],
        )
        expected_sd = (
            (0, 2.5, math.sqrt(4.5)),
            (0, 5.5, math.sqrt(24.5)),
            (2, 2, 0),
            (2, -0.5, math.sqrt(0.5)),
            (2, -0.5, math.sqrt(4.5)),
        )
        axes = figures[0].axes + figures[1].axes + figures[2].axes
        for axis, expected, (number, average, deviation) in zip(
            axes, expected_points, expected_sd
        ):
            raw_points = []
            segments = []
            for collection in axis.collections:
                if isinstance(collection, PathCollection):
                    for point in collection.get_offsets():
                        raw_points.append(tuple(point))
                elif isinstance(collection, LineCollection):
                    segments.extend(collection.get_segments())
            np.testing.assert_allclose(sorted(raw_points), sorted(expected))
            target = np.array(
                [[number, average - deviation], [number, average + deviation]]
            )
            self.assertTrue(
                any(
                    np.asarray(segment).shape == (2, 2) and np.allclose(segment, target)
                    for segment in segments
                )
            )
            for segment in segments:
                if len(segment) == 2:
                    self.assertEqual(segment[0][0], segment[1][0])
                    self.assertIn(segment[0][0], (0, 2))

    def test_single_section_has_no_sample_sd_or_errorbar(self):
        first = self.measurement("first.csv", 1, 2)
        later = self.measurement("later.csv", 3, 5)
        rows = self.read_measurements(
            [("runA", 0, "A", first.name), ("runA", 2, "A", later.name)]
        )
        for summary in self.module["summarize_measurements"](rows):
            self.assertEqual(summary["count"], 1)
            self.assertIsNone(summary["difference_points_sd"])
        for figure in self.figures(rows):
            for axis in figure.axes:
                for collection in axis.collections:
                    if isinstance(collection, LineCollection):
                        self.assertEqual(len(collection.get_segments()), 0)

    def test_settings_control_both_panel_limits_sizes_and_experiment_colors(self):
        rows = self.read_measurements(self.example_measurements())
        create_graphs = self.module["create_graphs"]
        settings = {
            "PASS_X_LIMITS": (-1, 8),
            "EXCESS_Y_LIMITS": (0, 15),
            "CHANGE_Y_LIMITS": (-6, 10),
            "DIFFERENCE_Y_LIMITS": (-8, 4),
            "FIGURE_SIZE": (8, 4),
            "DIFFERENCE_FIGURE_SIZE": (4, 4),
            "EXPERIMENT_COLORS": ("#123456", "#abcdef"),
            "MARKERS": ("s", "^"),
            "LINE_STYLES": ("-", ":"),
        }
        with patch.dict(create_graphs.__globals__, settings):
            figures = self.figures(rows)
        for figure, limits, size in zip(
            figures, ((0, 15), (-6, 10), (-8, 4)), ((8, 4), (8, 4), (4, 4))
        ):
            np.testing.assert_allclose(figure.get_size_inches(), size)
            for axis in figure.axes:
                self.assertEqual(axis.get_xlim(), (-1, 8))
                self.assertEqual(axis.get_ylim(), limits)
                for experiment, color, marker, line_style in (
                    ("runA", "#123456", "s", "-"),
                    ("runB", "#abcdef", "^", ":"),
                ):
                    for line in axis.lines:
                        if line.get_label() == experiment:
                            self.assertEqual(to_rgba(line.get_color()), to_rgba(color))
                            self.assertEqual(line.get_marker(), marker)
                            self.assertEqual(line.get_linestyle(), line_style)

    def test_same_source_image_is_allowed_but_duplicate_csv_or_missing_baseline_is_not(
        self,
    ):
        first = self.measurement("section_a.csv", 1, 2, image_path="same_image.png")
        second = self.measurement("section_b.csv", 3, 4, image_path="same_image.png")
        rows = self.read_measurements(
            [("runA", 0, "A", first.name), ("runA", 0, "B", second.name)]
        )
        self.assertEqual(rows[0]["image_path"], rows[1]["image_path"])
        self.assertEqual(self.module["summarize_measurements"](rows)[0]["count"], 2)
        for measurements in (
            [("runA", 0, "A", first.name), ("runB", 0, "B", str(first))],
            [("runA", 0, "A", first.name), ("runA", 0, "A", second.name)],
            [("runA", 0, "A", first.name), ("runB", 2, "A", second.name)],
            [("runA", 0, "A", first.name), ("runA", 2, "B", second.name)],
        ):
            with self.subTest(measurements=measurements), self.assertRaises(ValueError):
                self.read_measurements(measurements)

    def test_mixed_measurement_conditions_are_rejected_across_experiments(self):
        first = self.measurement("first.csv")
        for column, value in (
            ("interval_length_mm", 90),
            ("mm_per_px", 0.2),
            ("evaluation_interval_mm", 0.5),
            ("smoothing_width_mm", 0),
        ):
            changes = {column: value}
            if column == "interval_length_mm":
                changes["left_mm"] = value * 1.01
                changes["right_mm"] = value * 1.02
            later = self.measurement("later.csv", **changes)
            with self.subTest(column=column), self.assertRaises(ValueError):
                self.read_measurements(
                    [("runA", 0, "A", first.name), ("runB", 0, "A", later.name)]
                )

    def test_output_protects_script_measurement_and_source_image_before_any_save(self):
        for kind, name in (
            ("script", "excess.png"),
            ("measurement", "change_from_initial.png"),
            ("image", "dr_op_difference.png"),
        ):
            with self.subTest(kind=kind):
                directory = self.directory / kind
                directory.mkdir()
                protected = directory / name
                measurement_name = "measurement.csv"
                image_path = directory / "source.png"
                module = self.module
                if kind == "script":
                    script = copy_refactored(
                        "05_plot_experiment_comparison.py", directory
                    )
                    script.rename(protected)
                    module = run_refactored(protected)
                elif kind == "measurement":
                    measurement_name = str(protected)
                else:
                    image_path = protected
                    image_path.write_bytes(b"original source image")
                measurement = self.measurement(
                    measurement_name, image_path=str(image_path)
                )
                rows = self.read_measurements([("runA", 0, "A", str(measurement))])
                before = protected.read_bytes()
                with self.assertRaises(ValueError):
                    module["write_graphs"](directory, rows)
                self.assertEqual(protected.read_bytes(), before)
                for output_name in (
                    "excess.png",
                    "change_from_initial.png",
                    "dr_op_difference.png",
                ):
                    path = directory / output_name
                    if path != protected:
                        self.assertFalse(path.exists())

    def test_cli_runs_from_another_directory_and_saves_only_three_pngs(self):
        measurements = self.example_measurements()
        script = copy_refactored(
            "05_plot_experiment_comparison.py",
            self.directory,
            MEASUREMENTS=measurements,
        )
        source = script.read_text(encoding="utf-8")
        source = source.replace(
            'GRAPH_DIRECTORY = OUTPUT_DIRECTORY / "experiment_comparison"',
            'GRAPH_DIRECTORY = BASE_DIRECTORY / "保存 画像"',
        )
        script.write_text(source, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=Path(self.temporary.name),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        output = self.directory / "保存 画像"
        self.assertEqual(
            {path.name for path in output.iterdir()},
            {"excess.png", "change_from_initial.png", "dr_op_difference.png"},
        )
        for path in output.glob("*.png"):
            image = cv.imdecode(
                np.frombuffer(path.read_bytes(), np.uint8), cv.IMREAD_COLOR
            )
            assert image is not None, path.name
            self.assertGreater(image.shape[0], 100)
            self.assertGreater(image.shape[1], 100)
            self.assertGreater(float(image.std()), 1.0)


if __name__ == "__main__":
    unittest.main()
