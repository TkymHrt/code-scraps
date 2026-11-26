import csv
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ORGANIZER = (
    Path(__file__).resolve().parents[1]
    / "sandbox"
    / "mill-model-study"
    / "organize_errors.py"
)


class MillErrorTablesTest(unittest.TestCase):
    def test_keeps_missing_prediction_without_counting_it_as_zero(self):
        with TemporaryDirectory() as folder:
            source = Path(folder) / "points.csv"
            tables = Path(folder) / "tables"
            source.write_text(
                "source_line,side,width_mm,load,measured_thickness_mm,"
                "fit_old_thickness_mm,fit_kb1_thickness_mm,fit_staged_thickness_mm\n"
                "2,op,178,20,24,24,24.25,\n"
                "3,op,178,40,20,20,20.50,19.75\n",
                encoding="utf-8",
            )
            subprocess.run(
                [sys.executable, ORGANIZER, source, tables],
                check=True,
                capture_output=True,
            )
            with (tables / "errors.csv").open(
                encoding="utf-8-sig", newline=""
            ) as stream:
                points = list(csv.DictReader(stream))
            self.assertEqual(len(points), 6)
            self.assertEqual(points[2]["error_mm"], "")
            with (tables / "summary.csv").open(
                encoding="utf-8-sig", newline=""
            ) as stream:
                summary = list(csv.DictReader(stream))
            staged = next(
                row
                for row in summary
                if row["group"] == "overall"
                and row["model"] == "Current width correction"
            )
            self.assertEqual((staged["rows"], staged["predicted_rows"]), ("2", "1"))
            self.assertEqual(float(staged["bias_mm"]), -0.25)
            self.assertEqual(float(staged["mae_mm"]), 0.25)
