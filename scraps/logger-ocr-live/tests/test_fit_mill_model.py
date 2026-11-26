import csv
import json
import math
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

SCRIPT = Path(__file__).resolve().parents[1] / "src" / "fit_mill_model.py"
HEADER = ["side", "width_mm", "load", "gap_mm", "measured_thickness_mm"]


def synthetic_rows(side, p0, coefficients, widths):
    c1, c2, c3, c4, c5 = coefficients
    for width in widths:
        x = width / 1000
        kb = c3 + c4 * x + c5 * x**2
        for gap, load in zip((1.5, 2.0, 2.5, 3.0), (12, 25, 40, 55), strict=True):
            if c2 == 0:
                extension = (load - p0) / (kb * c1)
            else:
                loaded = math.sqrt(c1**2 + 2 * c2 * load / kb)
                zero = math.sqrt(c1**2 + 2 * c2 * p0 / kb)
                extension = (loaded - zero) / c2
            yield [side, width, load, gap, gap + extension]


class FitMillModelTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.trial = Path(temporary.name)
        self.measurements = self.trial / "measurements.csv"
        self.conditions = self.trial / "conditions.toml"
        self.conditions.write_text(
            'roll = "試験ロール"\nzero_reference = "試験ゼロ"\nload_unit = "ton"\n'
            "[op]\np0 = 7\nreference_width_mm = 1000\n"
            "[dr]\np0 = 8\nreference_width_mm = 1000\n",
            encoding="utf-8",
        )

    def write_measurements(self, rows):
        with self.measurements.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(HEADER)
            writer.writerows(rows)

    def run_fit(self):
        return subprocess.run(
            [sys.executable, str(SCRIPT)],
            cwd=self.trial,
            capture_output=True,
            encoding="utf-8",
            check=False,
        )

    def read_outputs(self):
        (folder,) = self.trial.glob("fit-*")
        result = json.loads((folder / "coefficients.json").read_text(encoding="utf-8"))
        with (folder / "comparison.csv").open(encoding="utf-8", newline="") as stream:
            comparison = list(csv.DictReader(stream))
        return result, comparison

    def test_recovers_normalized_coefficients_and_preserves_input_order(self):
        widths = [1000, 600, 800, 950]
        op = (100, 20, 0.64, 0.24, 0.12)
        dr = (85, -20, 0.7, 0.35, -0.05)
        rows = [
            row
            for pair in zip(
                synthetic_rows("op", 7, op, widths),
                synthetic_rows("dr", 8, dr, widths),
                strict=True,
            )
            for row in pair
        ]
        self.write_measurements(rows)

        process = self.run_fit()

        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("OP 評価 16 件", process.stdout)
        self.assertIn("DR 評価 16 件", process.stdout)
        result, comparison = self.read_outputs()
        self.assertEqual(result["roll"], "試験ロール")
        for side, expected, p0 in (("op", op, 7), ("dr", dr, 8)):
            model = result[side]["model"]
            self.assertEqual(result[side]["p0"], p0)
            self.assertEqual(model["width_range_mm"], [600, 1000])
            self.assertEqual(model["load_range"], [12, 55])
            for index, coefficient in enumerate(expected, 1):
                self.assertAlmostEqual(model[f"c{index}"], coefficient, places=9)
            self.assertAlmostEqual(sum(model[key] for key in ("c3", "c4", "c5")), 1)
            curve = result[side]["fit"]["by_width"]["600.0"]
            self.assertAlmostEqual(curve["b"], curve["kb"] * expected[1] / 2)
            self.assertAlmostEqual(curve["max_abs_load_error"], 0, places=10)
        for given, returned in zip(rows, comparison, strict=True):
            self.assertEqual(
                [returned[column] for column in HEADER], list(map(str, given))
            )
            self.assertAlmostEqual(float(returned["error_mm"]), 0, places=10)

    def test_fits_widths_with_separate_measured_load_ranges(self):
        rows = []
        loads_by_width = {600: (10, 15, 20), 800: (25, 30, 35), 1000: (45, 50, 55)}
        for width, loads in loads_by_width.items():
            kb = width / 1000
            zero = math.sqrt(100**2 - 120 * 7 / kb)
            for gap, load in zip((-0.01, 0, 2), loads, strict=True):
                loaded = math.sqrt(100**2 - 120 * load / kb)
                rows.append(["op", width, load, gap, gap + (zero - loaded) / 60])
        self.write_measurements(rows)

        process = self.run_fit()

        self.assertEqual(process.returncode, 0, process.stderr)
        result, comparison = self.read_outputs()
        model = result["op"]["model"]
        self.assertEqual(model["width_range_mm"], [600, 1000])
        self.assertEqual(model["load_range"], [10, 55])
        self.assertAlmostEqual(model["c4"], 1)
        self.assertEqual(len(comparison), 9)
        for row in comparison:
            self.assertAlmostEqual(float(row["error_mm"]), 0, places=10)

    def test_keeps_reference_fit_when_widths_are_insufficient_and_repeats_safely(self):
        rows = list(synthetic_rows("op", 7, (100, 0, 1, 0, 0), [900, 1000]))
        rows += [["dr", 1000, 25, 2, 2.2], ["dr", 1000, 25, 3, 3.2]]
        self.write_measurements(rows)
        original_input = self.measurements.read_bytes()
        original_conditions = self.conditions.read_bytes()

        process = self.run_fit()

        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("OP 評価 4 件", process.stdout)
        self.assertIn("DR 評価 0 件", process.stdout)
        result, comparison = self.read_outputs()
        model = result["op"]["model"]
        self.assertAlmostEqual(model["c1"], 100)
        self.assertAlmostEqual(model["c2"], 0)
        self.assertEqual(model["width_range_mm"], [1000, 1000])
        for key in ("c3", "c4", "c5"):
            self.assertIsNone(model[key])
        self.assertIsNone(result["dr"]["model"])
        for row in comparison:
            if row["side"] == "op" and row["width_mm"] == "1000":
                self.assertAlmostEqual(float(row["error_mm"]), 0)
            else:
                self.assertEqual(row["predicted_thickness_mm"], "")
                self.assertEqual(row["error_mm"], "")

        retry = self.run_fit()

        self.assertEqual(retry.returncode, 0, retry.stderr)
        self.assertEqual(len(list(self.trial.glob("fit-*"))), 2)
        self.assertEqual(self.measurements.read_bytes(), original_input)
        self.assertEqual(self.conditions.read_bytes(), original_conditions)

    def test_rejects_width_correction_that_turns_negative_between_measurements(self):
        # kb = 16(x - 0.7)^2 - 0.44 is positive at the sampled widths.
        self.write_measurements(
            synthetic_rows("op", 7, (100, 20, 7.4, -22.4, 16), [400, 900, 1000])
        )

        process = self.run_fit()

        self.assertEqual(process.returncode, 0, process.stderr)
        result, _ = self.read_outputs()
        self.assertIsNone(result["op"]["model"]["c3"])
        self.assertEqual(
            result["op"]["fit"]["reason"], "板幅補正: 測定幅範囲内でkbが不正"
        )

    def test_keeps_completed_fits_when_a_width_fails(self):
        rows = list(synthetic_rows("op", 7, (100, 20, 0.64, 0.24, 0.12), [1000, 600]))
        rows.append(["op", 800, 25, 2, 2.2])
        self.write_measurements(rows)

        process = self.run_fit()

        self.assertEqual(process.returncode, 0, process.stderr)
        result, comparison = self.read_outputs()
        self.assertIsNone(result["op"]["model"]["c3"])
        fit = result["op"]["fit"]
        self.assertEqual(fit["reason"], "板幅 800 mm: 荷重差不足")
        self.assertEqual(list(fit["by_width"]), ["1000.0", "600.0"])
        self.assertEqual(fit["by_width"]["1000.0"]["kb"], 1)
        self.assertNotIn("kb", fit["by_width"]["600.0"])
        self.assertEqual(comparison[-1]["predicted_thickness_mm"], "")

    def test_reports_bad_csv_row_and_does_not_create_results(self):
        for thickness in ("", 0, -0.01):
            with self.subTest(thickness=thickness):
                self.write_measurements([["op", 1000, 12, 1.5, thickness]])
                process = self.run_fit()
                self.assertEqual(process.returncode, 2)
                self.assertEqual(process.stderr, "measurements.csv: 2行目が不正\n")
                self.assertEqual(list(self.trial.glob("fit-*")), [])


if __name__ == "__main__":
    unittest.main()
