"""コード内の入力設定を確認し、3図の数値と別フォルダからの実行を検証する。"""

import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2 as cv
import numpy as np
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

    def test_three_graphs_keep_numeric_passes_and_separate_initial_values(self):
        rows = self.read_measurements(self.example_measurements())
        self.assertEqual(len(rows), 7)
        for row in rows:
            self.assertIsInstance(row["pass_number"], int)
            self.assertTrue(Path(row["measurement_csv"]).is_absolute())
            self.assertIn("image_name", row)
        figures = self.module["create_graphs"](rows)
        self.assertEqual(len(figures), 3)
        for figure in figures:
            self.addCleanup(figure.clear)
        excess, change, difference = figures
        self.assert_graph_contains(excess, [0, 2, 6], [1, 3, 5])
        self.assert_graph_contains(excess, [0, 2, 6], [2, 2, 8])
        self.assert_graph_contains(excess, [0, 4], [10, 7])
        self.assert_graph_contains(excess, [0, 4], [8, 12])
        self.assert_graph_contains(change, [0, 2, 6], [0, 2, 4])
        self.assert_graph_contains(change, [0, 2, 6], [0, 0, 6])
        self.assert_graph_contains(change, [0, 4], [0, -3])
        self.assert_graph_contains(change, [0, 4], [0, 4])
        self.assert_graph_contains(change, [0, 2], [0, 2])
        self.assert_graph_contains(change, [0, 2], [0, -1])
        self.assert_graph_contains(difference, [0, 2, 6], [-1, 1, -3])
        self.assert_graph_contains(difference, [0, 4], [2, -5])
        self.assert_graph_contains(difference, [0, 2], [-5, -2])

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
        ):
            with self.subTest(protected_kind=protected_kind):
                directory = self.directory / protected_kind
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
                ):
                    path = directory / name
                    if path != protected_path:
                        self.assertFalse(path.exists(), "入力衝突時は保存前に止める")

    def test_cli_runs_from_another_directory_and_writes_three_readable_pngs(self):
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
            {path.name for path in output.glob("*.png")},
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
