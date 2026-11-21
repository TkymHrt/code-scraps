"""実機を使わず、8CHの換算とOCRから独立した状態表示を確認する。"""

import csv
import importlib.util
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from queue import Queue
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "src" / "main.py"
SPEC = importlib.util.spec_from_file_location("calculate_readings_under_test", SCRIPT)
readings = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(readings)


class CalculateReadingsTests(unittest.TestCase):
    def setUp(self):
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
        voltages = [4.0, 2.0, 2.5, 4.0, 2.0, 4.0, 2.0, 0.0]
        self.voltages = dict(zip(self.channels, voltages, strict=True))
        self.timestamp = "2026-11-06T00:00:00.150+00:00"

    def read_rows(self, messages):
        received_lines = Queue()
        for source, message in messages:
            message = message.copy()
            message.setdefault("acquired_mono_ns", 1_000_000_000)
            received_lines.put((source, json.dumps(message), 1.0))
        received_lines.put(("logger", "", 1.0))
        output = io.StringIO()
        with patch.object(readings.time, "monotonic", return_value=1.0):
            with redirect_stdout(output):
                self.assertEqual(
                    readings.write_readings_csv(received_lines, Queue(), {}), "logger"
                )
        return list(csv.DictReader(io.StringIO(output.getvalue())))

    def test_converts_eight_independent_ranges_and_units_to_csv(self):
        rows = self.read_rows(
            [
                ("ocr", {"received_at": self.timestamp, "value": 0.0}),
                ("logger", {"received_at": self.timestamp, "voltages": self.voltages}),
            ]
        )

        self.assertEqual(len(rows), 1)
        row = rows[0]
        expected_values = [40.0, 50.0, 50.0, 500.0, 100.0, 400.0, 100.0, 5.0]
        for (channel, settings), expected in zip(
            self.channels.items(),
            expected_values,
            strict=True,
        ):
            self.assertEqual(float(row[f"{channel}_V"]), self.voltages[channel])
            self.assertEqual(
                float(row[f"{settings['name']}_{settings['unit']}"]), expected
            )
        self.assertEqual(row["ocr_value"], "0.0")
        self.assertEqual(row["voltage_status"], "valid")
        self.assertEqual(row["ocr_status"], "ready")

    def test_endpoints_are_included_and_outside_values_are_missing(self):
        for channel, settings in self.channels.items():
            low_voltage, low_value = settings["low_point"]
            high_voltage, high_value = settings["high_point"]
            cases = [
                (low_voltage, low_value),
                (high_voltage, high_value),
                (low_voltage - 0.001, None),
                (high_voltage + 0.001, None),
                (None, None),
                (float("nan"), None),
                (float("inf"), None),
            ]
            for voltage, expected in cases:
                with self.subTest(channel=channel, voltage=voltage):
                    voltages = self.voltages.copy()
                    voltages[channel] = voltage
                    message = {"received_at": self.timestamp, "voltages": voltages}
                    row = self.read_rows([("logger", message)])[0]
                    column = f"{settings['name']}_{settings['unit']}"
                    if expected is None:
                        self.assertEqual(row[column], "")
                    else:
                        self.assertEqual(float(row[column]), expected)

    def test_invalid_voltage_remains_visible_while_waiting_for_ocr(self):
        self.voltages["U1_CH2"] = 0.5
        self.voltages["U1_CH3"] = None
        row = self.read_rows(
            [
                ("logger", {"received_at": self.timestamp, "voltages": self.voltages}),
            ]
        )[0]

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
                row = self.read_rows(
                    [
                        ("ocr", {"received_at": timestamp, "value": value}),
                        (
                            "logger",
                            {"received_at": self.timestamp, "voltages": self.voltages},
                        ),
                    ]
                )[0]
                self.assertEqual(row["voltage_status"], "invalid")
                self.assertEqual(row["ocr_status"], expected)

    def test_late_ocr_leaves_previous_logger_row_waiting(self):
        first_logger = {
            "received_at": "2026-11-06T00:00:00.900+00:00",
            "acquired_mono_ns": 900_000_000,
            "voltages": self.voltages,
        }
        late_ocr = {
            "received_at": "2026-11-06T00:00:00.880+00:00",
            "acquired_mono_ns": 880_000_000,
            "value": 1.234,
        }
        next_logger = {
            "received_at": "2026-11-06T00:00:00.950+00:00",
            "acquired_mono_ns": 950_000_000,
            "voltages": self.voltages,
        }
        rows = self.read_rows(
            [("logger", first_logger), ("ocr", late_ocr), ("logger", next_logger)]
        )
        ocr_results = [(row["ocr_status"], row["ocr_value"]) for row in rows]
        self.assertEqual(ocr_results, [("waiting", ""), ("ready", "1.234")])

    def test_ocr_timeout_discards_stale_lines_and_recovers(self):
        ocr_message = {"received_at": self.timestamp, "value": 0.0}
        logger_message = {"received_at": self.timestamp, "voltages": self.voltages}
        resumed_at = "2026-11-06T00:00:01.550+00:00"
        resumed_ocr = {"received_at": resumed_at, "value": 1.234}
        resumed_logger = {"received_at": resumed_at, "voltages": self.voltages}
        events = [
            (10.0, 10.0, "ocr", ocr_message),
            (11.0, 11.0, "logger", logger_message),
            (11.1, 11.1, "logger", logger_message),
            (11.2, 10.1, "ocr", ocr_message),
            (11.3, 11.3, "logger", logger_message),
            (11.4, 11.4, "ocr", resumed_ocr),
            (11.5, 11.5, "logger", resumed_logger),
        ]
        received_lines = Queue()
        clock_times = [10.0]
        for processed_at, line_read_at, source, message in events:
            message = dict(message, acquired_mono_ns=int(line_read_at * 1_000_000_000))
            received_lines.put((source, json.dumps(message), line_read_at))
            clock_times.append(processed_at)
        received_lines.put(("ocr", "", 11.6))
        clock_times.append(11.6)

        output = io.StringIO()
        notices = io.StringIO()
        with (
            patch.object(readings, "INPUT_TIMEOUT", 1.0),
            patch.object(readings.time, "monotonic", side_effect=clock_times),
            redirect_stdout(output),
            redirect_stderr(notices),
        ):
            self.assertEqual(
                readings.write_readings_csv(received_lines, Queue(), {}), "ocr"
            )

        rows = csv.DictReader(io.StringIO(output.getvalue()))
        ocr_results = [(row["ocr_status"], row["ocr_value"]) for row in rows]
        self.assertEqual(
            ocr_results,
            [("ready", "0.0"), ("waiting", ""), ("waiting", ""), ("ready", "1.234")],
        )
        self.assertEqual(notices.getvalue(), "ocr 受信タイムアウト\n")

    def test_unconfigured_points_prevent_starting_child_processes(self):
        self.channels["U1_CH1"]["low_point"] = (None, None)
        with patch.object(readings.subprocess, "Popen", side_effect=AssertionError):
            with self.assertRaisesRegex(ValueError, "U1_CH1.*有限"):
                readings.main()

    def test_empty_unit_is_rejected(self):
        self.channels["U1_CH1"]["unit"] = ""
        with patch.object(readings.subprocess, "Popen", side_effect=AssertionError):
            with self.assertRaisesRegex(ValueError, "U1_CH1.*unit"):
                readings.main()

    def test_invalid_calibration_is_rejected(self):
        cases = [
            ((-10.1, 0.0), (8.0, 80.0)),
            ((0.0, 0.0), (10.1, 80.0)),
            ((3.0, 0.0), (1.0, 80.0)),
            ((1.0, 0.0), (1.0, 80.0)),
            ((float("nan"), 0.0), (8.0, 80.0)),
            ((0.0, 0.0), (8.0, float("inf"))),
        ]
        with patch.object(readings.subprocess, "Popen", side_effect=AssertionError):
            for low_point, high_point in cases:
                with self.subTest(low_point=low_point, high_point=high_point):
                    self.channels["U1_CH1"].update(
                        low_point=low_point, high_point=high_point
                    )
                    with self.assertRaises(ValueError):
                        readings.main()

    def test_full_logger_range_is_allowed(self):
        settings = self.channels["U1_CH1"]
        settings.update(low_point=(-10.0, -100.0), high_point=(10.0, 100.0))
        with patch.object(
            readings.subprocess, "Popen", side_effect=OSError("模擬起動")
        ):
            with self.assertRaisesRegex(OSError, "模擬起動"):
                readings.main()

        messages = []
        for voltage in (-10.0, 10.0):
            voltages = self.voltages.copy()
            voltages["U1_CH1"] = voltage
            messages.append(
                ("logger", {"received_at": self.timestamp, "voltages": voltages})
            )
        rows = self.read_rows(messages)
        self.assertEqual(float(rows[0]["rolling_speed_mpm"]), -100.0)
        self.assertEqual(float(rows[1]["rolling_speed_mpm"]), 100.0)


if __name__ == "__main__":
    unittest.main()
