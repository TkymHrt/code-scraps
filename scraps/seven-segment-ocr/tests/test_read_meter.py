"""合成した計器画像と動画で、認識結果と出力の扱いを確認する。"""

import ast
import csv
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import cv2

TOPIC = Path(__file__).resolve().parents[1]
reader_spec = importlib.util.spec_from_file_location(
    "read_meter", TOPIC / "read_meter.py"
)
read_meter = importlib.util.module_from_spec(reader_spec)
reader_spec.loader.exec_module(read_meter)

spec = importlib.util.spec_from_file_location(
    "simulate_meter", TOPIC / "sandbox" / "simulate_meter.py"
)
simulate_meter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(simulate_meter)

calibration_spec = importlib.util.spec_from_file_location(
    "calibrate_meter", TOPIC / "calibrate_meter.py"
)
calibrate_meter = importlib.util.module_from_spec(calibration_spec)
calibration_spec.loader.exec_module(calibrate_meter)


class CalibrationTests(unittest.TestCase):
    def test_printed_calibration_can_be_copied_into_reader(self):
        frame = simulate_meter.make_frame("  1234", reflection="vertical")
        capture = Mock()
        capture.isOpened.return_value = True
        capture.read.return_value = (True, frame)

        def choose_corners(window_name, callback):
            for x, y in simulate_meter.DISPLAY_CORNERS:
                callback(cv2.EVENT_LBUTTONDOWN, x, y, 0, None)

        rois = []
        for position in range(6):
            rois.append((position * 120 + 14, 13, 92, 174))
        output = io.StringIO()
        with patch.multiple(calibrate_meter, SOURCE=0, REFLECTION="vertical"):
            with patch.multiple(
                calibrate_meter.cv2,
                VideoCapture=Mock(return_value=capture),
                namedWindow=Mock(),
                resizeWindow=Mock(),
                imshow=Mock(),
                waitKey=Mock(side_effect=[ord(" "), 13]),
                setMouseCallback=Mock(side_effect=choose_corners),
                selectROI=Mock(side_effect=rois),
                destroyWindow=Mock(),
                destroyAllWindows=Mock(),
            ):
                with redirect_stdout(output), redirect_stderr(io.StringIO()):
                    calibrate_meter.main()
        capture.release.assert_called_once()

        # 表示された代入文は実行せず、右辺のリテラルだけを読む。
        settings = {}
        for line in output.getvalue().splitlines():
            name, literal = line.split("=", 1)
            settings[name.strip()] = ast.literal_eval(literal.strip())
        self.assertEqual(
            set(settings),
            {"FRAME_SIZE", "REFLECTION", "DISPLAY_CORNERS", "DIGIT_BOXES"},
        )
        with patch.multiple(read_meter, **settings):
            image = read_meter.rectify_display(frame)
            reading, _ = read_meter.recognize_display(image)
        self.assertEqual(reading["raw_value"], "1.234")


class RecognitionTests(unittest.TestCase):
    def setUp(self):
        reflection = patch.object(read_meter, "REFLECTION", "none")
        reflection.start()
        self.addCleanup(reflection.stop)

    def recognize(self, display):
        image = simulate_meter.draw_display(display)
        reading, mask = read_meter.recognize_display(image)
        self.assertEqual(mask.shape, (200, 720))
        return reading

    def test_all_digits_in_all_six_positions(self):
        for position in range(6):
            for digit in "0123456789":
                symbols = list("123456")
                symbols[position] = digit
                display = "".join(symbols)
                expected = str(int(display[:3])) + "." + display[3:]
                with self.subTest(position=position, digit=digit):
                    reading = self.recognize(display)
                    self.assertEqual(reading["display"], display)
                    self.assertEqual(reading["raw_value"], expected)
                    self.assertEqual(reading["reason"], "")

    def test_fixed_decimal_and_leading_blank_positions(self):
        examples = {
            "  0000": "0.000",
            "  0001": "0.001",
            "  1234": "1.234",
            " 12345": "12.345",
            "123456": "123.456",
            "999999": "999.999",
        }
        for display, expected in examples.items():
            with self.subTest(display=display):
                reading = self.recognize(display)
                self.assertEqual(reading["display"], display)
                self.assertEqual(reading["raw_value"], expected)

    def test_invalid_patterns_and_missing_required_digits(self):
        for display in ["      ", "12 456", "1 3456", "123 56", "12345 ", "123?56"]:
            with self.subTest(display=display):
                reading = self.recognize(display)
                self.assertIsNone(reading["raw_value"])
                self.assertTrue(reading["reason"])

    def test_ambiguous_segment_is_not_rounded_to_a_digit(self):
        image = simulate_meter.draw_display("888888")
        # 最初の桁の上辺を半分隠す。消灯とも点灯とも確定させない。
        cv2.rectangle(image, (30, 10), (60, 29), (8, 8, 8), -1)
        reading, _ = read_meter.recognize_display(image)
        self.assertIsNone(reading["raw_value"])
        self.assertTrue(reading["reason"])
        fraction = reading["fractions"][0][0]
        self.assertGreater(fraction, read_meter.OFF_FRACTION)
        self.assertLess(fraction, read_meter.ON_FRACTION)

    def test_non_red_light_is_not_a_lit_segment(self):
        for color in [(230, 230, 230), (230, 15, 15), (15, 230, 15)]:
            with self.subTest(color=color):
                image = simulate_meter.draw_display("      ")
                image[:, :] = color
                reading, _ = read_meter.recognize_display(image)
                self.assertIsNone(reading["raw_value"])

    def test_perspective_and_all_reflection_directions(self):
        for reflection in ["none", "horizontal", "vertical", "both"]:
            with self.subTest(reflection=reflection):
                frame = simulate_meter.make_frame(" 12345", reflection=reflection)
                with patch.object(read_meter, "REFLECTION", reflection):
                    image = read_meter.rectify_display(frame)
                reading, _ = read_meter.recognize_display(image)
                self.assertEqual(reading["raw_value"], "12.345")

    def test_all_normal_simulation_conditions(self):
        for (
            display,
            expected,
            scenario,
            brightness,
            blur,
            noise,
        ) in simulate_meter.make_scenarios():
            if not expected:
                continue
            with self.subTest(display=display, scenario=scenario):
                frame = simulate_meter.make_frame(
                    display, "horizontal", brightness, blur, noise, seed=23
                )
                with patch.object(read_meter, "REFLECTION", "horizontal"):
                    image = read_meter.rectify_display(frame)
                reading, _ = read_meter.recognize_display(image)
                self.assertEqual(reading["raw_value"], expected)

    def test_frame_size_must_match_calibration(self):
        frame = simulate_meter.make_frame("123456", reflection="none")
        smaller_frame = cv2.resize(frame, (480, 180))
        with self.assertRaises(ValueError):
            read_meter.rectify_display(smaller_frame)


class VideoOutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.output = Path(cls.temporary.name)
        with patch.multiple(
            simulate_meter,
            OUTPUT_DIR=cls.output,
            FRAMES_PER_VALUE=5,
            FPS=30.0,
            REFLECTION="horizontal",
        ):
            with redirect_stdout(io.StringIO()):
                simulate_meter.main()

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def run_reader(self, csv_path, video_path=None):
        if video_path is None:
            video_path = self.output / "meter.avi"
        output = io.StringIO()
        with patch.multiple(
            read_meter,
            SOURCE=video_path,
            CSV_FILE=csv_path,
            SHOW_PREVIEW=False,
            REFLECTION="horizontal",
        ):
            with redirect_stdout(output):
                read_meter.main()
        return output.getvalue()

    def test_video_to_jsonl_and_csv_with_stability_reset(self):
        csv_path = self.output / "readings.csv"
        output = self.run_reader(csv_path)
        records = []
        for line in output.splitlines():
            records.append(json.loads(line))
        with (self.output / "truth.csv").open(encoding="utf-8", newline="") as file:
            truth = list(csv.DictReader(file))
        with csv_path.open(encoding="utf-8-sig", newline="") as file:
            csv_records = list(csv.DictReader(file))
        self.assertEqual(len(records), len(truth))
        self.assertEqual(len(csv_records), len(truth))

        previous_value = None
        consecutive_count = 0
        for expected, record, csv_record in zip(truth, records, csv_records):
            value = expected["value"] or None
            with self.subTest(
                frame_index=expected["frame_index"], scenario=expected["scenario"]
            ):
                self.assertEqual(record["frame_index"], int(expected["frame_index"]))
                self.assertEqual(record["raw_value"], value)
                self.assertAlmostEqual(
                    record["source_time_seconds"],
                    float(expected["time_seconds"]),
                    places=5,
                )
                self.assertTrue(record["captured_at"])
                if value is None:
                    expected_status = "invalid"
                    previous_value = None
                    consecutive_count = 0
                else:
                    if value == previous_value:
                        consecutive_count += 1
                    else:
                        previous_value = value
                        consecutive_count = 1
                    expected_status = "warming_up"
                    if consecutive_count >= 3:
                        expected_status = "ok"
                self.assertEqual(record["status"], expected_status)
                accepted_value = None
                if expected_status == "ok":
                    accepted_value = value
                self.assertEqual(record["value"], accepted_value)
                self.assertEqual(csv_record["status"], expected_status)
                self.assertEqual(csv_record["value"], accepted_value or "")
                self.assertEqual(csv_record["raw_value"], value or "")

    def test_existing_csv_is_not_overwritten(self):
        csv_path = self.output / "existing.csv"
        original = "以前の測定値\n123.456\n"
        csv_path.write_text(original, encoding="utf-8")
        with self.assertRaises(FileExistsError):
            self.run_reader(csv_path)
        self.assertEqual(csv_path.read_text(encoding="utf-8"), original)

    def test_same_value_after_invalid_requires_new_stability(self):
        video_path = self.output / "interrupted.avi"
        writer = cv2.VideoWriter(
            str(video_path), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, (960, 360)
        )
        self.assertTrue(writer.isOpened())
        displays = [
            "  1234",
            "  1234",
            "  1234",
            "      ",
            "  1234",
            "  1234",
            "  1234",
        ]
        try:
            for display in displays:
                writer.write(simulate_meter.make_frame(display, "horizontal"))
        finally:
            writer.release()
        output = self.run_reader(self.output / "interrupted.csv", video_path=video_path)
        statuses = []
        values = []
        for line in output.splitlines():
            record = json.loads(line)
            statuses.append(record["status"])
            values.append(record["value"])
        self.assertEqual(
            statuses,
            [
                "warming_up",
                "warming_up",
                "ok",
                "invalid",
                "warming_up",
                "warming_up",
                "ok",
            ],
        )
        self.assertEqual(values, [None, None, "1.234", None, None, None, "1.234"])

    def test_camera_disconnect_is_an_error_and_releases_camera(self):
        capture = Mock()
        capture.isOpened.return_value = True
        capture.get.return_value = 30.0
        frame = simulate_meter.make_frame("  1234", "horizontal")
        capture.read.side_effect = [(True, frame), (False, None)]
        csv_path = self.output / "camera_disconnect.csv"
        output = io.StringIO()
        with patch.multiple(
            read_meter,
            SOURCE=0,
            CSV_FILE=csv_path,
            SHOW_PREVIEW=False,
            REFLECTION="horizontal",
        ):
            with patch.object(read_meter.cv2, "VideoCapture", return_value=capture):
                with redirect_stdout(output):
                    with self.assertRaises(RuntimeError):
                        read_meter.main()
        capture.release.assert_called_once()
        with csv_path.open(encoding="utf-8", newline="") as file:
            records = list(csv.DictReader(file))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["value"], "")

    def test_mismatched_video_size_fails_without_a_value(self):
        output = io.StringIO()
        with patch.multiple(
            read_meter,
            SOURCE=self.output / "meter.avi",
            CSV_FILE=self.output / "wrong_size.csv",
            SHOW_PREVIEW=False,
            FRAME_SIZE=[1280, 720],
        ):
            with redirect_stdout(output):
                with self.assertRaises(ValueError):
                    read_meter.main()
        self.assertEqual(output.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
