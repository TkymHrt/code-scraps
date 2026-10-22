"""長手軸を使う計測CSVの読込と、不正なCSVの拒否を確認する。"""

import csv
import tempfile
import unittest
from pathlib import Path

from test_refactored_workflow import load_refactored


class AxisMeasurementCsvTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.path = self.directory / "measurement.csv"
        self.module = load_refactored("measurement_csv.py")
        self.measurement = {
            "interval_length_mm": 125.0,
            "left_mm": 127.5,
            "right_mm": 130.0,
            "left_excess_percent": 2.0,
            "right_excess_percent": 4.0,
            "mm_per_px": 0.25,
            "evaluation_interval_mm": 1.0,
            "smoothing_width_mm": 2.0,
        }

    def write_row(self, row):
        with self.path.open("w", encoding="utf-8-sig", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=list(row))
            writer.writeheader()
            writer.writerow(row)

    def new_row(self):
        row = {"image_path": "sample.png", "image_name": "sample.png"}
        row.update(self.measurement)
        return row

    def test_new_csv_round_trip_and_comparison_use_axis_interval(self):
        image_path = self.directory / "試料 00.png"
        self.module["write_csv"](self.path, image_path, self.measurement)
        saved = self.module["read_lengths"](self.path)
        self.assertEqual(saved["image_name"], image_path.name)
        self.assertEqual(saved["image_path"], str(image_path.resolve()))
        for column, value in self.measurement.items():
            self.assertAlmostEqual(saved[column], value)
        self.assertNotIn("start_y", saved)
        comparison = load_refactored("length_comparison.py")
        rows = comparison["read_measurements"]([self.path])
        self.assertEqual(rows[0]["interval_length_mm"], 125)
        self.assertEqual(rows[0]["left_per_100mm"], 102)
        self.assertEqual(rows[0]["right_per_100mm"], 104)

    def test_zero_smoothing_width_is_allowed(self):
        row = self.new_row()
        row["smoothing_width_mm"] = 0
        self.write_row(row)
        saved = self.module["read_lengths"](self.path)
        self.assertEqual(saved["smoothing_width_mm"], 0)

    def test_image_name_is_derived_when_column_is_missing(self):
        row = self.new_row()
        image_path = self.directory / "元画像 試料.png"
        row["image_path"] = str(image_path)
        del row["image_name"]
        self.write_row(row)
        saved = self.module["read_lengths"](self.path)
        self.assertEqual(saved["image_name"], image_path.name)
        self.assertEqual(saved["image_path"], str(image_path.resolve()))

    def test_image_name_always_comes_from_image_path(self):
        image_path = self.directory / "元画像 試料.png"
        for image_name in ("別の名前.png", ""):
            row = self.new_row()
            row["image_path"] = str(image_path)
            row["image_name"] = image_name
            self.write_row(row)
            with self.subTest(image_name=image_name):
                saved = self.module["read_lengths"](self.path)
                self.assertEqual(saved["image_name"], image_path.name)

    def test_legacy_horizontal_interval_csv_is_rejected(self):
        self.write_row(
            {
                "image_path": "old.png",
                "mm_per_px": 0.25,
                "start_y": 20,
                "end_y": 420,
                "left_mm": 105,
                "right_mm": 110,
            }
        )
        with self.assertRaises(ValueError):
            self.module["read_lengths"](self.path)

    def test_each_required_column_is_checked(self):
        row = self.new_row()
        del row["image_name"]
        for column in row:
            broken = dict(row)
            del broken[column]
            self.write_row(broken)
            with self.subTest(column=column), self.assertRaises(ValueError):
                self.module["read_lengths"](self.path)

    def test_missing_column_error_identifies_csv_path_and_column(self):
        row = self.new_row()
        del row["smoothing_width_mm"]
        self.write_row(row)
        with self.assertRaises(ValueError) as caught:
            self.module["read_lengths"](self.path)
        message = str(caught.exception)
        self.assertIn(str(self.path.resolve()), message)
        self.assertIn("smoothing_width_mm", message)

    def test_invalid_new_measurement_values_are_rejected(self):
        invalid_values = (
            ("interval_length_mm", 0),
            ("interval_length_mm", "nan"),
            ("left_mm", 124),
            ("right_mm", "inf"),
            ("mm_per_px", -1),
            ("evaluation_interval_mm", 0),
            ("evaluation_interval_mm", "nan"),
            ("smoothing_width_mm", -1),
            ("smoothing_width_mm", "inf"),
            ("smoothing_width_mm", "abc"),
            ("left_excess_percent", "nan"),
            ("right_excess_percent", 3),
        )
        for column, value in invalid_values:
            row = self.new_row()
            row[column] = value
            self.write_row(row)
            with (
                self.subTest(column=column, value=value),
                self.assertRaises(ValueError),
            ):
                self.module["read_lengths"](self.path)


if __name__ == "__main__":
    unittest.main()
