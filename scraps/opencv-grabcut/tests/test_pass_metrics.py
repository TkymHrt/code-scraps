"""コード内の入力設定を確認し、3図の数値と別フォルダからの実行を検証する。"""

import csv
import math
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import cv2 as cv
import numpy as np
from matplotlib.collections import LineCollection, PathCollection
from test_refactored_workflow import (
    copy_refactored,
    load_refactored,
    run_refactored,
)


class PassMetricsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name) / "試験 データ"
        self.directory.mkdir()
        self.module = load_refactored("04_plot_pass_metrics.py")

    def measurement(self, name, dr=1.0, op=2.0, **changes):
        path = self.directory / name
        row = {
            "image_path": str(path.with_suffix(".png")),
            "image_name": path.with_suffix(".png").name,
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
        self.write_csv(path, row)
        return path

    def write_csv(self, path, row):
        with path.open("w", encoding="utf-8-sig", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=list(row))
            writer.writeheader()
            writer.writerow(row)

    def read_measurements(self, measurements):
        reader = self.module["read_pass_measurements"]
        with patch.dict(reader.__globals__, {"BASE_DIRECTORY": self.directory}):
            return reader(measurements)

    def example_measurements(self):
        # 入力順に依存せず、実験回と区間ごとに初回からの差を計算する。
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
            name = f"{experiment}_{section}_{number}.csv"
            path = self.measurement(name, dr, op)
            measurements.append((experiment, number, section, path.name))
        # 絶対パスの入力も、相対パスと同じように扱う。
        measurements[1] = (
            *measurements[1][:3],
            str(self.directory / measurements[1][3]),
        )
        return measurements

    def assert_graph_contains(self, figure, x_values, y_values):
        for line in figure.axes[0].lines:
            actual_x = np.asarray(line.get_xdata(), dtype=float)
            actual_y = np.asarray(line.get_ydata(), dtype=float)
            if actual_x.shape != np.asarray(x_values).shape:
                continue
            if np.allclose(actual_x, x_values) and np.allclose(actual_y, y_values):
                return
        self.fail(f"グラフに期待する系列がありません: x={x_values}, y={y_values}")

    def test_summary_keeps_section_baselines_and_experiments_separate(self):
        rows = self.read_measurements(self.example_measurements())
        self.assertEqual(len(rows), 7)
        for row in rows:
            self.assertIsInstance(row["pass_number"], int)
            self.assertTrue(Path(row["measurement_csv"]).is_absolute())
            self.assertIn("image_name", row)
        summaries = self.module["summarize_measurements"](rows)
        grouped = {}
        for summary in summaries:
            grouped[(summary["experiment_id"], summary["pass_number"])] = summary
        self.assertEqual(
            set(grouped),
            {("runA", 0), ("runA", 2), ("runA", 6), ("runB", 0), ("runB", 4)},
        )

        initial = grouped[("runA", 0)]
        self.assertEqual(initial["count"], 2)
        np.testing.assert_allclose(initial["left_excess_percent_values"], [1, 4])
        np.testing.assert_allclose(initial["right_excess_percent_values"], [2, 9])
        self.assertAlmostEqual(initial["left_excess_percent_mean"], 2.5)
        self.assertAlmostEqual(initial["left_excess_percent_sd"], math.sqrt(4.5))
        self.assertAlmostEqual(initial["right_excess_percent_mean"], 5.5)
        self.assertAlmostEqual(initial["right_excess_percent_sd"], math.sqrt(24.5))
        self.assertEqual(initial["left_change_points_values"], [0, 0])
        self.assertEqual(initial["right_change_points_values"], [0, 0])
        self.assertEqual(initial["left_change_points_sd"], 0)

        later = grouped[("runA", 2)]
        self.assertEqual(later["count"], 2)
        # 区間Aの初回は1/2%、区間Bは4/9%。各区間の差を求めてから集計する。
        np.testing.assert_allclose(later["left_change_points_values"], [2, 2])
        np.testing.assert_allclose(later["right_change_points_values"], [0, -1])
        self.assertAlmostEqual(later["left_change_points_mean"], 2)
        self.assertAlmostEqual(later["left_change_points_sd"], 0)
        self.assertAlmostEqual(later["right_change_points_mean"], -0.5)
        self.assertAlmostEqual(later["right_change_points_sd"], math.sqrt(0.5))
        # DRとOPのばらつきを別々に合成せず、対応する区間の差を集計する。
        np.testing.assert_allclose(later["difference_points_values"], [1, -2])
        self.assertAlmostEqual(later["difference_points_mean"], -0.5)
        self.assertAlmostEqual(later["difference_points_sd"], math.sqrt(4.5))

        missing_section = grouped[("runA", 6)]
        self.assertEqual(missing_section["count"], 1)
        np.testing.assert_allclose(missing_section["left_change_points_values"], [4])
        np.testing.assert_allclose(missing_section["right_change_points_values"], [6])
        np.testing.assert_allclose(missing_section["difference_points_values"], [-3])
        for metric in (
            "left_excess_percent",
            "right_excess_percent",
            "left_change_points",
            "right_change_points",
            "difference_points",
        ):
            self.assertIsNone(missing_section[f"{metric}_sd"])
        self.assertAlmostEqual(grouped[("runB", 0)]["left_excess_percent_mean"], 10)
        self.assertAlmostEqual(grouped[("runB", 4)]["left_change_points_mean"], -3)
        self.assertAlmostEqual(grouped[("runB", 4)]["right_change_points_mean"], 4)

    def test_three_graphs_show_experiment_means_at_numeric_passes(self):
        rows = self.read_measurements(self.example_measurements())
        figures = self.module["create_graphs"](rows)
        self.assertEqual(len(figures), 3)
        for figure in figures:
            self.addCleanup(figure.clear)
            self.assertEqual(figure.axes[0].get_xlabel(), "圧延パス数")
        excess, change, difference = figures
        self.assert_graph_contains(excess, [0, 2, 6], [2.5, 4.5, 5])
        self.assert_graph_contains(excess, [0, 2, 6], [5.5, 5, 8])
        self.assert_graph_contains(excess, [0, 4], [10, 7])
        self.assert_graph_contains(excess, [0, 4], [8, 12])
        self.assert_graph_contains(change, [0, 2, 6], [0, 2, 4])
        self.assert_graph_contains(change, [0, 2, 6], [0, -0.5, 6])
        self.assert_graph_contains(change, [0, 4], [0, -3])
        self.assert_graph_contains(change, [0, 4], [0, 4])
        self.assert_graph_contains(difference, [0, 2, 6], [-3, -0.5, -3])
        self.assert_graph_contains(difference, [0, 4], [2, -5])

    def test_paper_style_keeps_plot_clear_and_sides_distinct_in_grayscale(self):
        rows = self.read_measurements(self.example_measurements())
        figures = self.module["create_graphs"](rows)
        for figure in figures:
            self.addCleanup(figure.clear)
            axis = figure.axes[0]
            self.assertFalse(figure.get_suptitle())
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
                self.assertTrue(tick.label1.get_visible())
                self.assertFalse(tick.label2.get_visible())
            self.assertFalse(axis.get_legend().get_frame_on())
            lower, upper = axis.get_ylim()
            self.assertLessEqual(lower, 0)
            self.assertGreaterEqual(upper, 0)
            # ゼロ基準線など、区間値とは無関係な線を追加しない。
            for line in axis.lines:
                self.assertNotEqual(list(line.get_xdata()), [0, 1])
        for figure in figures[:2]:
            series = {}
            for line in figure.axes[0].lines:
                if line.get_label() in ("runA DR", "runA OP", "runB DR"):
                    series[line.get_label()] = line
            self.assertNotEqual(
                series["runA DR"].get_marker(), series["runA OP"].get_marker()
            )
            self.assertNotEqual(
                series["runA DR"].get_linestyle(), series["runB DR"].get_linestyle()
            )

    def test_captions_preserve_measurement_conditions_and_section_counts(self):
        rows = self.read_measurements(self.example_measurements())
        captions = self.module["create_captions"](rows)
        for title in (
            "DR・OP側辺長の超過率",
            "パス0からの超過率の変化",
            "DR・OPの超過率の差",
        ):
            self.assertIn(title, captions)
        for condition in (
            "基準区間長 100 mm",
            "倍率 0.25 mm/px",
            "評価間隔 1 mm",
            "平滑化幅 2 mm",
        ):
            self.assertIn(condition, captions)
        self.assertIn("runA: パス0=2, パス2=2, パス6=1", captions)
        self.assertIn("runB: パス0=1, パス4=1", captions)
        self.assertIn("標本SD", captions)
        self.assertIn("1区間", captions)
        self.assertIn("独立", captions)

    def test_graphs_keep_raw_points_and_sample_sd_without_horizontal_jitter(self):
        rows = self.read_measurements(self.example_measurements())
        figures = self.module["create_graphs"](rows)
        expected_points = [
            [
                (0, 1),
                (0, 2),
                (0, 4),
                (0, 9),
                (0, 10),
                (0, 8),
                (2, 3),
                (2, 2),
                (2, 6),
                (2, 8),
                (4, 7),
                (4, 12),
                (6, 5),
                (6, 8),
            ],
            [(0, 0)] * 6
            + [(2, 2), (2, 0), (2, 2), (2, -1), (4, -3), (4, 4), (6, 4), (6, 6)],
            [(0, -1), (0, -5), (0, 2), (2, 1), (2, -2), (4, -5), (6, -3)],
        ]
        for figure, expected in zip(figures, expected_points):
            self.addCleanup(figure.clear)
            raw_points = []
            error_segments = []
            for collection in figure.axes[0].collections:
                if isinstance(collection, PathCollection):
                    raw_points.extend(collection.get_offsets().tolist())
                elif isinstance(collection, LineCollection):
                    for segment in collection.get_segments():
                        if len(segment) == 2:
                            error_segments.append(segment)
            raw_tuples = []
            for point in raw_points:
                raw_tuples.append(tuple(point))
            actual = np.asarray(sorted(raw_tuples))
            expected = np.asarray(sorted(expected))
            np.testing.assert_array_equal(actual[:, 0], expected[:, 0])
            np.testing.assert_allclose(actual[:, 1], expected[:, 1])
            self.assertTrue(error_segments, "2区間あるパスのSDを表示する")
            for segment in error_segments:
                self.assertEqual(segment[0][0], segment[1][0])
                self.assertIn(segment[0][0], (0, 2), "1区間のパスにはSDを描かない")
        # 初回DRの標本SDはsqrt(4.5)。母標準偏差との取り違えも確認する。
        target = np.array([[0, 2.5 - math.sqrt(4.5)], [0, 2.5 + math.sqrt(4.5)]])
        matching_segments = []
        for collection in figures[0].axes[0].collections:
            if isinstance(collection, LineCollection):
                matching_segments.extend(collection.get_segments())
        sample_sd_found = False
        for segment in matching_segments:
            if np.asarray(segment).shape == (2, 2) and np.allclose(segment, target):
                sample_sd_found = True
        self.assertTrue(sample_sd_found)

    def test_single_section_has_no_sample_sd_or_errorbar(self):
        first = self.measurement("first.csv", 1, 2)
        later = self.measurement("later.csv", 3, 5)
        rows = self.read_measurements(
            [("runA", 0, "A", first.name), ("runA", 2, "A", later.name)]
        )
        summaries = self.module["summarize_measurements"](rows)
        for summary in summaries:
            self.assertEqual(summary["count"], 1)
            self.assertIsNone(summary["difference_points_sd"])
        figures = self.module["create_graphs"](rows)
        for figure in figures:
            self.addCleanup(figure.clear)
            for collection in figure.axes[0].collections:
                if isinstance(collection, LineCollection):
                    self.assertEqual(len(collection.get_segments()), 0)

    def test_each_series_requires_pass_zero(self):
        first = self.measurement("first.csv")
        later = self.measurement("later.csv", 3, 4)
        for experiment, section in (("別の実験", "A"), ("runA", "別区間")):
            with self.subTest(experiment=experiment, section=section):
                with self.assertRaises(ValueError):
                    self.read_measurements(
                        [
                            ("runA", 0, "A", first.name),
                            (experiment, 2, section, later.name),
                        ]
                    )

    def test_graph_settings_control_limits_size_and_side_colors(self):
        rows = self.read_measurements(self.example_measurements())
        settings = {
            "PASS_X_LIMITS": (-1, 8),
            "EXCESS_Y_LIMITS": (0, 15),
            "CHANGE_Y_LIMITS": (-6, 10),
            "DIFFERENCE_Y_LIMITS": (-8, 4),
            "FIGURE_SIZE": (8, 5),
            "DR_COLOR": "#123456",
            "OP_COLOR": "#abcdef",
        }
        create_graphs = self.module["create_graphs"]
        with patch.dict(create_graphs.__globals__, settings):
            figures = create_graphs(rows)
        expected_y_limits = ((0, 15), (-6, 10), (-8, 4))
        for figure, y_limits in zip(figures, expected_y_limits):
            self.addCleanup(figure.clear)
            axis = figure.axes[0]
            self.assertEqual(axis.get_xlim(), (-1, 8))
            self.assertEqual(axis.get_ylim(), y_limits)
            np.testing.assert_allclose(figure.get_size_inches(), [8, 5])
        for figure in figures[:2]:
            colors = set()
            for line in figure.axes[0].lines:
                colors.add(line.get_color())
            self.assertIn("#123456", colors)
            self.assertIn("#abcdef", colors)

    def test_invalid_passes_and_empty_identifiers_are_rejected(self):
        first = self.measurement("first.csv")
        later = self.measurement("later.csv", 3, 4)
        for number in (-2, 1, "2", "2.5", "nan", "", 2.0, True, False):
            with self.subTest(pass_number=number), self.assertRaises(ValueError):
                self.read_measurements(
                    [("runA", 0, "A", first.name), ("runA", number, "A", later.name)]
                )
        for column in (0, 2, 3):
            row = ["runA", 0, "A", first.name]
            row[column] = " "
            with self.subTest(column=column), self.assertRaises(ValueError):
                self.read_measurements([tuple(row)])

    def test_duplicate_pass_or_same_csv_path_alias_is_rejected(self):
        first = self.measurement("first.csv")
        later = self.measurement("later.csv", 3, 4)
        cases = (
            [("runA", 0, "A", first.name), ("runA", 0, "A", later.name)],
            [("runA", 0, "A", first.name), ("runB", 0, "B", str(first))],
        )
        for measurements in cases:
            with self.subTest(measurements=measurements), self.assertRaises(ValueError):
                self.read_measurements(measurements)

    def test_distinct_sections_can_share_one_source_image(self):
        first = self.measurement("section_a.csv", 1, 2, image_path="same_image.png")
        second = self.measurement("section_b.csv", 3, 4, image_path="same_image.png")
        rows = self.read_measurements(
            [("runA", 0, "A", first.name), ("runA", 0, "B", second.name)]
        )
        self.assertEqual(rows[0]["image_path"], rows[1]["image_path"])
        summary = self.module["summarize_measurements"](rows)[0]
        self.assertEqual(summary["count"], 2)
        self.assertAlmostEqual(summary["left_excess_percent_mean"], 2)

    def test_empty_measurements_are_rejected(self):
        with self.assertRaises(ValueError):
            self.read_measurements([])

    def test_mixed_measurement_conditions_are_rejected(self):
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
                    [("runA", 0, "A", first.name), ("runA", 2, "A", later.name)]
                )

    def test_rounded_conditions_are_accepted_within_tolerance(self):
        first = self.measurement("first.csv")
        later = self.measurement("later.csv", evaluation_interval_mm=1.000000001)
        rows = self.read_measurements(
            [("runA", 0, "A", first.name), ("runA", 2, "A", later.name)]
        )
        self.assertEqual(len(rows), 2)

    def test_legacy_or_incomplete_csv_is_rejected(self):
        legacy = self.directory / "legacy.csv"
        self.write_csv(
            legacy,
            {
                "image_path": "old.png",
                "mm_per_px": 0.25,
                "start_y": 0,
                "end_y": 400,
                "left_mm": 101,
                "right_mm": 102,
            },
        )
        with self.assertRaises(ValueError):
            self.read_measurements([("runA", 0, "A", legacy.name)])
        broken = self.measurement("broken.csv", evaluation_interval_mm="")
        with self.assertRaises(ValueError):
            self.read_measurements([("runA", 0, "A", broken.name)])

    def test_output_protects_script_measurement_and_source_image(self):
        for protected_kind, output_name in (
            ("script", "excess.png"),
            ("measurement", "change_from_initial.png"),
            ("image", "dr_op_difference.png"),
            ("measurement", "change_from_initial.svg"),
            ("image", "dr_op_difference.svg"),
            ("measurement", "figure_captions.txt"),
        ):
            with self.subTest(protected_kind=protected_kind):
                directory = self.directory / (protected_kind + "_" + output_name)
                directory.mkdir()
                protected_path = directory / output_name
                measurement_name = "measurement.csv"
                image_path = directory / "source.png"
                module = self.module
                if protected_kind == "script":
                    script = copy_refactored("04_plot_pass_metrics.py", directory)
                    script.rename(protected_path)
                    module = run_refactored(protected_path)
                elif protected_kind == "measurement":
                    measurement_name = str(protected_path)
                else:
                    image_path = protected_path
                    image_path.write_bytes(b"original source image")
                measurement = self.measurement(
                    measurement_name, image_path=str(image_path)
                )
                rows = self.read_measurements([("runA", 0, "A", str(measurement))])
                before = protected_path.read_bytes()
                with self.assertRaises(ValueError):
                    module["write_graphs"](directory, rows)
                self.assertEqual(protected_path.read_bytes(), before)
                for name in (
                    "excess.png",
                    "change_from_initial.png",
                    "dr_op_difference.png",
                    "excess.svg",
                    "change_from_initial.svg",
                    "dr_op_difference.svg",
                    "figure_captions.txt",
                ):
                    path = directory / name
                    if path != protected_path:
                        self.assertFalse(path.exists(), "入力衝突時は保存前に止める")

    def test_write_graphs_exports_seven_paths_and_captions_outside_figure(self):
        rows = self.read_measurements(self.example_measurements())
        output = self.directory / "export"
        paths = self.module["write_graphs"](output, rows)
        self.assertEqual(len(paths), 7)
        self.assertEqual(set(paths), set(output.iterdir()))
        for name in ("excess", "change_from_initial", "dr_op_difference"):
            svg_root = ET.parse(output / f"{name}.svg").getroot()
            self.assertEqual(svg_root.tag, "{http://www.w3.org/2000/svg}svg")
        captions = (output / "figure_captions.txt").read_text(encoding="utf-8-sig")
        self.assertEqual(captions, self.module["create_captions"](rows))
        self.assertIn("runA: パス0=2, パス2=2, パス6=1", captions)
        self.assertIn("倍率 0.25 mm/px", captions)

    def test_cli_runs_from_another_directory_and_writes_png_svg_and_captions(self):
        measurements = self.example_measurements()
        script = copy_refactored(
            "04_plot_pass_metrics.py", self.directory, MEASUREMENTS=measurements
        )
        # 保存先もコピー内のコードで設定する。実行時引数は使わない。
        source = script.read_text(encoding="utf-8")
        source = source.replace(
            'GRAPH_DIRECTORY = OUTPUT_DIRECTORY / "pass_graphs"',
            'GRAPH_DIRECTORY = BASE_DIRECTORY / "保存 画像"',
        )
        script.write_text(source, encoding="utf-8")
        output = self.directory / "保存 画像"
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
        self.assertEqual(
            {path.name for path in output.iterdir()},
            {
                "excess.png",
                "change_from_initial.png",
                "dr_op_difference.png",
                "excess.svg",
                "change_from_initial.svg",
                "dr_op_difference.svg",
                "figure_captions.txt",
            },
        )
        for path in output.glob("*.png"):
            image = cv.imdecode(
                np.frombuffer(path.read_bytes(), np.uint8), cv.IMREAD_COLOR
            )
            assert image is not None, path.name
            self.assertGreater(image.shape[0], 100)
            self.assertGreater(image.shape[1], 100)
            self.assertGreater(float(image.std()), 1.0)
        for path in output.glob("*.svg"):
            self.assertEqual(
                ET.parse(path).getroot().tag, "{http://www.w3.org/2000/svg}svg"
            )
        captions = (output / "figure_captions.txt").read_text(encoding="utf-8-sig")
        self.assertIn("runA: パス0=2, パス2=2, パス6=1", captions)
        self.assertIn("評価間隔 1 mm", captions)


if __name__ == "__main__":
    unittest.main()
