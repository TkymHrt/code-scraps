"""実機を使わず、8CHの換算とOCRから独立した状態表示を確認する。"""

from contextlib import redirect_stderr, redirect_stdout
import csv
import importlib.util
import io
import json
from pathlib import Path
from queue import Queue
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "calculate_readings.py"
SPEC = importlib.util.spec_from_file_location("calculate_readings_under_test", SCRIPT)
readings = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(readings)


class CalculateReadingsTests(unittest.TestCase):
    def setUp(self):
        # 現場の値ではなく、異なる範囲・単位を試すための換算値。
        signals = [
            ("rolling_speed", "mpm", (0.0, 0.0), (8.0, 80.0)),
            ("load_OP", "ton", (1.0, 0.0), (3.0, 100.0)),
            ("load_DR", "ton", (0.0, 0.0), (5.0, 100.0)),
            ("tension_in", "kg", (0.0, 100.0), (8.0, 900.0)),
            ("tension_out", "kg", (1.0, 0.0), (3.0, 200.0)),
            ("bender_Inc", "kg", (0.0, 0.0), (8.0, 800.0)),
            ("bender_Dec", "kg", (1.0, 200.0), (3.0, 0.0)),
            ("exit_thickness", "mm", (-5.0, 0.0), (5.0, 10.0)),
        ]
        self.channels = {}
        for channel, (name, unit, low_point, high_point) in enumerate(signals, start=1):
            self.channels[f"U1_CH{channel}"] = {
                "name": name,
                "unit": unit,
                "low_point": low_point,
                "high_point": high_point,
            }
        settings_patch = patch.object(readings, "CHANNELS", self.channels)
        settings_patch.start()
        self.addCleanup(settings_patch.stop)
        self.voltages = dict(zip(self.channels, [4.0, 2.0, 2.5, 4.0, 2.0, 4.0, 2.0, 0.0]))
        self.timestamp = "2026-11-06T00:00:00.150+00:00"

    def read_rows(self, messages):
        events = Queue()
        for source, message in messages:
            events.put((source, json.dumps(message), 1.0))
        events.put(("logger", None, 1.0))
        output = io.StringIO()
        diagnostics = io.StringIO()
        with patch.object(readings.time, "monotonic", return_value=1.0):
            with redirect_stdout(output), redirect_stderr(diagnostics):
                self.assertEqual(readings.show_readings(events), "logger")
        self.diagnostics = diagnostics.getvalue()
        return list(csv.DictReader(io.StringIO(output.getvalue())))

    def test_gauge_trial_prints_zero_corrected_thickness_without_changing_csv(self):
        self.channels["U1_CH2"]["high_point"] = (3.0, 1000.0)
        self.channels["U1_CH3"]["high_point"] = (5.0, 1000.0)
        rows = self.read_rows([
            ("ocr", {"received_at": self.timestamp, "value": 0.8}),
            ("logger", {"received_at": self.timestamp, "voltages": self.voltages}),
        ])
        self.assertIn(f"[gauge test] {self.timestamp} h_test_mm=0.880000", self.diagnostics)
        self.assertEqual(len(rows[0]), 22)
        self.assertNotIn("h_test_mm", rows[0])

    def test_gauge_trial_uses_reference_gap_display_direction_and_both_stiffnesses(self):
        self.channels["U1_CH2"]["high_point"] = (3.0, 1000.0)
        self.channels["U1_CH3"]["high_point"] = (5.0, 1000.0)
        with patch.multiple(
            readings, GAUGE_BASE_THICKNESS_MM=1.0, GAUGE_ZERO_READING=2.0,
            GAUGE_DISPLAY_TO_MM=-1.0, GAUGE_MILL_STIFFNESS=5000.0,
        ):
            self.read_rows([
                ("ocr", {"received_at": self.timestamp, "value": 2.2}),
                ("logger", {"received_at": self.timestamp, "voltages": self.voltages}),
            ])
        self.assertIn("h_test_mm=0.980000", self.diagnostics)

    def test_gauge_trial_accepts_zero_loads_and_zero_ocr(self):
        self.voltages["U1_CH2"] = 1.0
        self.voltages["U1_CH3"] = 0.0
        with patch.object(readings, "GAUGE_ZERO_LOAD", 0.0):
            self.read_rows([
                ("ocr", {"received_at": self.timestamp, "value": 0.0}),
                ("logger", {"received_at": self.timestamp, "voltages": self.voltages}),
            ])
        self.assertIn("h_test_mm=0.000000", self.diagnostics)

    def test_gauge_trial_is_missing_when_either_load_is_invalid(self):
        for channel, voltage in (
            ("U1_CH2", None), ("U1_CH3", None),
            ("U1_CH2", 0.5), ("U1_CH3", 5.1),
        ):
            with self.subTest(channel=channel, voltage=voltage):
                voltages = self.voltages.copy()
                voltages[channel] = voltage
                self.read_rows([
                    ("ocr", {"received_at": self.timestamp, "value": 0.8}),
                    ("logger", {"received_at": self.timestamp, "voltages": voltages}),
                ])
                self.assertIn("h_test_mm=missing", self.diagnostics)

    def test_gauge_trial_uses_only_required_load_channels(self):
        self.voltages["U1_CH1"] = None
        row = self.read_rows([
            ("ocr", {"received_at": self.timestamp, "value": 0.8}),
            ("logger", {"received_at": self.timestamp, "voltages": self.voltages}),
        ])[0]
        self.assertEqual(row["voltage_status"], "invalid")
        self.assertIn("h_test_mm=0.790000", self.diagnostics)

    def test_gauge_trial_requires_ready_ocr_and_accepts_150ms_boundary(self):
        cases = [
            (None, "missing"),
            ({"received_at": self.timestamp, "value": None}, "missing"),
            ({"received_at": "2026-11-05T23:59:59.999+00:00", "value": 0.9}, "missing"),
            ({"received_at": "2026-11-06T00:00:00.000+00:00", "value": 0.9}, "0.890000"),
        ]
        for ocr, expected in cases:
            with self.subTest(ocr=ocr):
                messages = []
                if ocr is not None:
                    messages.append(("ocr", ocr))
                messages.append(("logger", {
                    "received_at": self.timestamp, "voltages": self.voltages,
                }))
                self.read_rows(messages)
                self.assertIn(f"h_test_mm={expected}", self.diagnostics)

    def test_gauge_trial_does_not_reuse_last_thickness_after_ocr_becomes_invalid(self):
        self.read_rows([
            ("ocr", {"received_at": self.timestamp, "value": 0.8}),
            ("logger", {"received_at": self.timestamp, "voltages": self.voltages}),
            ("ocr", {"received_at": self.timestamp, "value": None}),
            ("logger", {"received_at": self.timestamp, "voltages": self.voltages}),
        ])
        lines = self.diagnostics.splitlines()
        self.assertIn("h_test_mm=0.790000", lines[0])
        self.assertIn("h_test_mm=missing", lines[-1])

    def test_invalid_gauge_coefficients_prevent_starting_child_processes(self):
        cases = [
            {"GAUGE_BASE_THICKNESS_MM": None},
            {"GAUGE_ZERO_READING": float("nan")},
            {"GAUGE_DISPLAY_TO_MM": float("inf")},
            {"GAUGE_ZERO_LOAD": None},
            {"GAUGE_MILL_STIFFNESS": 0.0},
            {"GAUGE_ZERO_STIFFNESS": -1.0},
        ]
        for settings in cases:
            with self.subTest(settings=settings):
                with patch.multiple(readings, **settings):
                    with patch.object(readings.subprocess, "Popen") as start_process:
                        with self.assertRaises(ValueError):
                            readings.main()
                        start_process.assert_not_called()

    def test_gauge_trial_requires_matching_load_units(self):
        self.channels["U1_CH3"]["unit"] = "kN"
        with self.assertRaisesRegex(ValueError, "荷重単位"):
            readings.validate_settings()

    def test_converts_eight_independent_ranges_and_units_to_csv(self):
        readings.validate_settings()
        rows = self.read_rows([
            ("ocr", {"received_at": self.timestamp, "value": 0.0}),
            ("logger", {"received_at": self.timestamp, "voltages": self.voltages}),
        ])

        self.assertEqual(len(rows), 1)
        row = rows[0]
        expected_values = [40.0, 50.0, 50.0, 500.0, 100.0, 400.0, 100.0, 5.0]
        for (channel, settings), expected in zip(self.channels.items(), expected_values):
            self.assertEqual(float(row[f"{channel}_V"]), self.voltages[channel])
            self.assertEqual(float(row[f"{settings['name']}_{settings['unit']}"]), expected)
        self.assertEqual(row["ocr_value"], "0.0")
        self.assertEqual(row["voltage_status"], "valid")
        self.assertEqual(row["ocr_status"], "ready")

    def test_endpoints_are_included_and_outside_values_are_missing(self):
        for channel, settings in self.channels.items():
            low_voltage, low_value = settings["low_point"]
            high_voltage, high_value = settings["high_point"]
            cases = [
                (low_voltage, low_value), (high_voltage, high_value),
                (low_voltage - 0.001, None), (high_voltage + 0.001, None),
                (None, None), (float("nan"), None), (float("inf"), None),
            ]
            for voltage, expected in cases:
                with self.subTest(channel=channel, voltage=voltage):
                    self.assertEqual(readings.convert_voltage(voltage, settings), expected)

    def test_invalid_voltage_remains_visible_while_waiting_for_ocr(self):
        self.voltages["U1_CH2"] = 0.5
        self.voltages["U1_CH3"] = None
        row = self.read_rows([
            ("logger", {"received_at": self.timestamp, "voltages": self.voltages}),
        ])[0]

        self.assertEqual(row["U1_CH2_V"], "0.5")
        self.assertEqual(row["load_OP_ton"], "")
        self.assertEqual(row["U1_CH3_V"], "")
        self.assertEqual(row["load_DR_ton"], "")
        self.assertEqual(row["rolling_speed_mpm"], "40.0")
        self.assertEqual(row["voltage_status"], "invalid")
        self.assertEqual(row["ocr_status"], "waiting")

    def test_ocr_status_does_not_hide_invalid_voltage(self):
        self.voltages["U1_CH1"] = 9.0
        cases = [
            (None, self.timestamp, "unreadable"),
            (1.234, "2026-11-05T23:59:59.999+00:00", "time_gap"),
            (1.234, "2026-11-06T00:00:00.000+00:00", "ready"),
        ]
        for value, timestamp, expected in cases:
            with self.subTest(ocr_status=expected):
                row = self.read_rows([
                    ("ocr", {"received_at": timestamp, "value": value}),
                    ("logger", {"received_at": self.timestamp, "voltages": self.voltages}),
                ])[0]
                self.assertEqual(row["voltage_status"], "invalid")
                self.assertEqual(row["ocr_status"], expected)

    def test_unconfigured_points_prevent_starting_child_processes(self):
        self.channels["U1_CH1"]["low_point"] = (None, None)
        with patch.object(readings.subprocess, "Popen") as start_process:
            with self.assertRaisesRegex(ValueError, "U1_CH1.*有限"):
                readings.main()
        start_process.assert_not_called()

    def test_empty_unit_is_rejected(self):
        self.channels["U1_CH1"]["unit"] = ""
        with self.assertRaisesRegex(ValueError, "U1_CH1.*unit"):
            readings.validate_settings()

    def test_invalid_calibration_is_rejected(self):
        cases = [
            ((-10.1, 0.0), (8.0, 80.0)),
            ((0.0, 0.0), (10.1, 80.0)),
            ((3.0, 0.0), (1.0, 80.0)),
            ((1.0, 0.0), (1.0, 80.0)),
            ((float("nan"), 0.0), (8.0, 80.0)),
            ((0.0, 0.0), (8.0, float("inf"))),
        ]
        for low_point, high_point in cases:
            with self.subTest(low_point=low_point, high_point=high_point):
                self.channels["U1_CH1"].update(low_point=low_point, high_point=high_point)
                with self.assertRaises(ValueError):
                    readings.validate_settings()

    def test_full_logger_range_is_allowed(self):
        settings = self.channels["U1_CH1"]
        settings.update(low_point=(-10.0, -100.0), high_point=(10.0, 100.0))
        readings.validate_settings()
        self.assertEqual(readings.convert_voltage(-10.0, settings), -100.0)
        self.assertEqual(readings.convert_voltage(10.0, settings), 100.0)


if __name__ == "__main__":
    unittest.main()
