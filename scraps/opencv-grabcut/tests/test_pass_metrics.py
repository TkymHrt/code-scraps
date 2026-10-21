"""対応表の誤入力を止め、3図の数値と別フォルダからの実行を確認する。"""

import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2 as cv
import numpy as np
from test_refactored_workflow import load_refactored

PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT / "src" / "04_plot_pass_metrics.py"
TABLE_COLUMNS = (
    "experiment_id",
    "pass_number",
    "section_id",
    "measurement_csv",
)


class PassMetricsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name) / "試験 データ"
        self.directory.mkdir()
        self.table_path = self.directory / "対応表.csv"
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

    def write_table(self, rows, columns=TABLE_COLUMNS):
        with self.table_path.open("w", encoding="utf-8-sig", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(columns)
            writer.writerows(rows)

    def read_table(self):
        return self.module["read_pass_measurements"](self.table_path)

    def example_table(self):
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
        table = []
        for experiment, number, section, dr, op in data:
            name = f"{experiment}_{section}_{number}.csv"
            path = self.measurement(name, dr, op)
            table.append((experiment, number, section, path.name))
        # 絶対パスの入力も、相対パスと同じように扱う。
        table[1] = (*table[1][:3], str(self.directory / table[1][3]))
        self.write_table(table)
        return self.read_table()

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
        rows = self.example_table()
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
            self.write_table(
                [("runA", 0, "A", first.name), (experiment, 2, section, later.name)]
            )
            with self.subTest(experiment=experiment, section=section):
                with self.assertRaises(ValueError):
                    self.read_table()

    def test_graph_settings_control_limits_size_and_side_colors(self):
        rows = self.example_table()
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
        for number in (-2, 1, "2.5", "nan", ""):
            self.write_table(
                [("runA", 0, "A", first.name), ("runA", number, "A", later.name)]
            )
            with self.subTest(pass_number=number), self.assertRaises(ValueError):
                self.read_table()
        for column in (0, 2, 3):
            row = ["runA", 0, "A", first.name]
            row[column] = " "
            self.write_table([row])
            with self.subTest(column=column), self.assertRaises(ValueError):
                self.read_table()

    def test_duplicate_pass_or_same_csv_path_alias_is_rejected(self):
        first = self.measurement("first.csv")
        later = self.measurement("later.csv", 3, 4)
        cases = (
            [("runA", 0, "A", first.name), ("runA", 0, "A", later.name)],
            [("runA", 0, "A", first.name), ("runB", 0, "B", str(first))],
        )
        for table in cases:
            self.write_table(table)
            with self.subTest(table=table), self.assertRaises(ValueError):
                self.read_table()

    def test_empty_table_and_missing_columns_are_rejected(self):
        self.write_table([])
        with self.assertRaises(ValueError):
            self.read_table()
        self.write_table([], columns=TABLE_COLUMNS[:-1])
        with self.assertRaises(ValueError):
            self.read_table()

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
            self.write_table(
                [("runA", 0, "A", first.name), ("runA", 2, "A", later.name)]
            )
            with self.subTest(column=column), self.assertRaises(ValueError):
                self.read_table()

    def test_rounded_conditions_are_accepted_within_tolerance(self):
        first = self.measurement("first.csv")
        later = self.measurement("later.csv", evaluation_interval_mm=1.000000001)
        self.write_table([("runA", 0, "A", first.name), ("runA", 2, "A", later.name)])
        self.assertEqual(len(self.read_table()), 2)

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
        self.write_table([("runA", 0, "A", legacy.name)])
        with self.assertRaises(ValueError):
            self.read_table()
        broken = self.measurement("broken.csv", evaluation_interval_mm="")
        self.write_table([("runA", 0, "A", broken.name)])
        with self.assertRaises(ValueError):
            self.read_table()

    def test_output_protects_table_measurement_and_source_image(self):
        for protected_kind, output_name in (
            ("table", "excess.png"),
            ("measurement", "change_from_initial.png"),
            ("image", "dr_op_difference.png"),
        ):
            with self.subTest(protected_kind=protected_kind):
                directory = self.directory / protected_kind
                directory.mkdir()
                protected_path = directory / output_name
                self.table_path = directory / "対応表.csv"
                measurement_name = "measurement.csv"
                image_path = directory / "source.png"
                if protected_kind == "table":
                    self.table_path = protected_path
                elif protected_kind == "measurement":
                    measurement_name = str(protected_path)
                else:
                    image_path = protected_path
                    image_path.write_bytes(b"original source image")
                measurement = self.measurement(
                    measurement_name, image_path=str(image_path)
                )
                self.write_table([("runA", 0, "A", str(measurement))])
                rows = self.read_table()
                before = protected_path.read_bytes()
                with self.assertRaises(ValueError):
                    self.module["write_graphs"](directory, rows, self.table_path)
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
        self.example_table()
        output = self.directory / "保存 画像"
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(self.table_path), "--out", str(output)],
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
