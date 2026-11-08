"""合成した計器画像と動画で、認識結果と出力の扱いを確認する。"""

import ast
import csv
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

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

# 描画用の720×200画像を直接調べるテストだけで使う点。
FLAT_POINTS = []
for digit_index in range(6):
    digit_points = []
    for x, y in [
        [60, 20],
        [99, 58],
        [99, 141],
        [60, 180],
        [21, 141],
        [21, 58],
        [60, 100],
    ]:
        offset = digit_index * 120
        digit_points.append([x + offset, y])
    FLAT_POINTS.append(digit_points)


class CalibrationTests(unittest.TestCase):
    def calibration_points(self):
        points = []
        for digit_points in read_meter.SEGMENT_POINTS:
            for x, y in digit_points:
                points.append((x, y))
        return points

    def run_calibration(self, actions=None, frame=None, visibility=None):
        if actions is None:
            actions = [ord(" ")] + self.calibration_points() + [13]
        if frame is None:
            frame = simulate_meter.make_frame("  1234", reflection="vertical")
        capture = Mock()
        capture.isOpened.return_value = True
        capture.read.return_value = (True, frame)

        output = io.StringIO()
        pending_actions = iter(actions)
        mouse_events = []
        preview_shapes = []
        mouse_callback = Mock()

        def wait_for_action(delay):
            action = next(pending_actions)
            if isinstance(action, tuple):
                event = cv2.EVENT_LBUTTONDOWN
                if len(action) == 3:
                    event, x, y = action
                else:
                    x, y = action
                callback = mouse_callback.call_args.args[1]
                callback(event, x, y, 0, None)
                mouse_events.append((event, x, y))
                return -1
            return action

        def show_image(window, image):
            preview_shapes.append(image.shape)

        named_window = Mock()
        resize_window = Mock()
        visible = Mock(return_value=1, side_effect=visibility)
        wait_key = Mock(side_effect=wait_for_action)
        with patch.multiple(calibrate_meter, SOURCE=0, REFLECTION="vertical"):
            with patch.multiple(
                calibrate_meter.cv2,
                VideoCapture=Mock(return_value=capture),
                namedWindow=named_window,
                resizeWindow=resize_window,
                setWindowTitle=Mock(),
                imshow=show_image,
                waitKey=wait_key,
                setMouseCallback=mouse_callback,
                getWindowProperty=visible,
                destroyAllWindows=Mock(),
            ):
                with redirect_stdout(output), redirect_stderr(io.StringIO()):
                    calibrate_meter.main()
        capture.release.assert_called_once()
        named_window.assert_called_once_with("Calibration", cv2.WINDOW_NORMAL)
        height, width = frame.shape[:2]
        scale = min(1.0, 1280 / width, 720 / height)
        resize_window.assert_called_once_with(
            "Calibration", round(width * scale), round(height * scale)
        )
        for shape in preview_shapes:
            self.assertEqual(shape, frame.shape)
        if mouse_callback.called:
            mouse_callback.assert_called_once()
            self.assertEqual(mouse_callback.call_args.args[0], "Calibration")
        for call in wait_key.call_args_list:
            self.assertEqual(call.args, (30,))

        # 表示された代入文は実行せず、右辺のリテラルだけを読む。
        settings = {}
        for line in output.getvalue().splitlines():
            name, literal = line.split("=", 1)
            settings[name.strip()] = ast.literal_eval(literal.strip())
        return settings, mouse_events

    def test_printed_calibration_can_be_copied_into_reader(self):
        settings, mouse_events = self.run_calibration()
        self.assertEqual(
            set(settings),
            {"FRAME_SIZE", "REFLECTION", "SAMPLE_RADIUS", "SEGMENT_POINTS"},
        )
        self.assertEqual(settings["FRAME_SIZE"], [960, 360])
        self.assertEqual(len(mouse_events), 42)
        self.assertEqual(settings["SAMPLE_RADIUS"], 1)
        self.assertEqual(settings["SEGMENT_POINTS"], read_meter.SEGMENT_POINTS)
        with patch.multiple(read_meter, **settings):
            read_meter.validate_segment_points()
            for display in ["  1234", "000000", "999999"]:
                frame = simulate_meter.make_frame(display, reflection="vertical")
                image = read_meter.prepare_frame(frame)
                reading, _ = read_meter.recognize_display(image)
                expected = str(int(display[:3])) + "." + display[3:]
                self.assertEqual(reading["raw_value"], expected)

    def test_printed_calibration_can_be_copied_into_logger_reader(self):
        settings, _ = self.run_calibration()
        spec = importlib.util.spec_from_file_location(
            "logger_reader", TOPIC.parent / "logger-ocr-live" / "read_meter.py"
        )
        logger_reader = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(logger_reader)
        with patch.multiple(logger_reader, **settings):
            sample_coordinates = logger_reader.prepare_samples("none")
            for digit in "0123456789":
                display = digit * 6
                frame = simulate_meter.make_frame(display, reflection="none")
                value = logger_reader.recognize_display(frame, sample_coordinates)
                expected = float(display) / 1000
                self.assertEqual(value, expected)

    def test_cancel_during_segment_selection_prints_no_partial_settings(self):
        for key in (ord("q"), 27):
            with self.subTest(key=key):
                actions = [ord(" ")] + self.calibration_points()[:2] + [key]
                settings, mouse_events = self.run_calibration(actions)
                self.assertEqual(settings, {})
                self.assertEqual(len(mouse_events), 2)

    def test_outside_segment_selection_is_retried(self):
        expected, _ = self.run_calibration()
        actions = [ord(" "), (0, 0), (959, 359)] + self.calibration_points() + [13]
        settings, mouse_events = self.run_calibration(actions)
        self.assertEqual(settings, expected)
        self.assertEqual(len(mouse_events), 44)

    def test_undo_across_digit_boundary_needs_no_resume_key(self):
        expected, _ = self.run_calibration()
        points = self.calibration_points()
        actions = [ord(" "), ord("b")] + points[:6] + [(30, 30), (50, 50)]
        actions += [ord("b"), ord("b")] + points[6:] + [13]
        settings, _ = self.run_calibration(actions)
        self.assertEqual(settings, expected)

    def test_final_review_undo_allows_redraw_without_resume_key(self):
        actions = [ord(" ")] + self.calibration_points()
        actions += [ord("b"), (790, 174), 13]
        settings, mouse_events = self.run_calibration(actions)
        self.assertEqual(settings["SEGMENT_POINTS"][5][6], [790, 174])
        self.assertEqual(len(mouse_events), 43)

    def test_final_review_can_cancel_without_printing_settings(self):
        actions = [ord(" ")] + self.calibration_points() + [ord("q")]
        settings, mouse_events = self.run_calibration(actions)
        self.assertEqual(settings, {})
        self.assertEqual(len(mouse_events), 42)

    def test_only_left_clicks_add_points_and_final_review_ignores_clicks(self):
        expected, _ = self.run_calibration()
        actions = [ord(" "), 13, (cv2.EVENT_RBUTTONDOWN, 30, 30)]
        actions += [(cv2.EVENT_MOUSEMOVE, 40, 40)] + self.calibration_points()
        actions += [(50, 50), 13]
        settings, _ = self.run_calibration(actions)
        self.assertEqual(settings, expected)

    def test_resized_window_keeps_high_resolution_image_coordinates(self):
        frame = np.zeros((2160, 3840, 3), dtype=np.uint8)
        points = self.calibration_points()
        points[0] = (3050, 1825)
        actions = [ord(" ")] + points + [13]
        settings, _ = self.run_calibration(actions, frame=frame)
        self.assertEqual(settings["FRAME_SIZE"], [3840, 2160])
        self.assertEqual(settings["SEGMENT_POINTS"][0][0], [3050, 1825])

    def test_custom_radius_is_printed_and_controls_edge_selection(self):
        actions = [ord(" "), (1, 1)] + self.calibration_points() + [13]
        with patch.object(calibrate_meter, "SAMPLE_RADIUS", 2):
            settings, mouse_events = self.run_calibration(actions)
        self.assertEqual(settings["SAMPLE_RADIUS"], 2)
        self.assertEqual(settings["SEGMENT_POINTS"], read_meter.SEGMENT_POINTS)
        self.assertEqual(len(mouse_events), 43)

    def test_radius_zero_allows_image_corner(self):
        points = self.calibration_points()
        points[0] = (0, 0)
        with patch.object(calibrate_meter, "SAMPLE_RADIUS", 0):
            settings, _ = self.run_calibration([ord(" ")] + points + [13])
        self.assertEqual(settings["SAMPLE_RADIUS"], 0)
        self.assertEqual(settings["SEGMENT_POINTS"][0][0], [0, 0])

    def test_invalid_radius_is_rejected_before_opening_input(self):
        for radius in (-1, 1.5, float("nan")):
            with self.subTest(radius=radius):
                with patch.object(calibrate_meter, "SAMPLE_RADIUS", radius):
                    with patch.object(calibrate_meter.cv2, "VideoCapture") as capture:
                        with self.assertRaises(ValueError):
                            calibrate_meter.main()
                        capture.assert_not_called()

    def test_closed_window_cancels_at_preview_selection_or_review(self):
        cases = [[0], [cv2.error("window destroyed")], [1, 0], [1] * 43 + [0]]
        for visibility in cases:
            with self.subTest(visibility=visibility):
                settings, _ = self.run_calibration(visibility=visibility)
                self.assertEqual(settings, {})


class ConfigurationTests(unittest.TestCase):
    def test_segment_points_require_six_digits_and_seven_segments(self):
        missing_digit = deepcopy(read_meter.SEGMENT_POINTS)
        missing_digit.pop()
        extra_digit = deepcopy(read_meter.SEGMENT_POINTS)
        extra_digit.append(deepcopy(extra_digit[0]))
        missing_segment = deepcopy(read_meter.SEGMENT_POINTS)
        missing_segment[2].pop()
        extra_segment = deepcopy(read_meter.SEGMENT_POINTS)
        extra_segment[2].append([10, 10])
        for boxes in [[], missing_digit, extra_digit, missing_segment, extra_segment]:
            with self.subTest(boxes=boxes):
                with patch.object(read_meter, "SEGMENT_POINTS", boxes):
                    with self.assertRaises(ValueError):
                        read_meter.validate_segment_points()

    def test_segment_points_require_integers_and_whole_sample_inside_image(self):
        frame_width, frame_height = read_meter.FRAME_SIZE
        bad_points = [
            [10],
            [10, 10, 20],
            [-1, 10],
            [10, -1],
            [0, 10],
            [10, 0],
            [frame_width - 1, 10],
            [10, frame_height - 1],
            [10.5, 10],
            ["10", 10],
            [float("nan"), 10],
        ]
        for point in bad_points:
            with self.subTest(point=point):
                points = deepcopy(read_meter.SEGMENT_POINTS)
                points[0][0] = point
                with patch.object(read_meter, "SEGMENT_POINTS", points):
                    with self.assertRaises(ValueError):
                        read_meter.validate_segment_points()

    def test_thresholds_and_stable_frame_count_are_checked_before_opening_input(self):
        invalid_settings = [
            {"RED_MIN": -1},
            {"RED_MIN": 256},
            {"RED_MARGIN": 0},
            {"RED_MARGIN": 256},
            {"WHITE_MIN": -1},
            {"WHITE_MIN": 256},
            {"SAMPLE_RADIUS": -1},
            {"SAMPLE_RADIUS": 1.5},
            {"OFF_FRACTION": -0.1},
            {"OFF_FRACTION": 0.7, "ON_FRACTION": 0.7},
            {"ON_FRACTION": 1.1},
            {"STABLE_FRAMES": 0},
            {"STABLE_FRAMES": 2.5},
            {"STABLE_FRAMES": float("nan")},
        ]
        for settings in invalid_settings:
            with self.subTest(settings=settings):
                with patch.multiple(read_meter, **settings):
                    with patch.object(read_meter.cv2, "VideoCapture") as capture:
                        with self.assertRaises(ValueError):
                            read_meter.main()
                        capture.assert_not_called()


class RecognitionTests(unittest.TestCase):
    def setUp(self):
        settings = patch.multiple(
            read_meter,
            REFLECTION="none",
            FRAME_SIZE=[720, 200],
            SEGMENT_POINTS=FLAT_POINTS,
        )
        settings.start()
        self.addCleanup(settings.stop)

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
        reading, mask = read_meter.recognize_display(image)
        self.assertIsNone(reading["raw_value"])
        self.assertTrue(reading["reason"])
        x, y = read_meter.SEGMENT_POINTS[0][0]
        left, top, right, bottom = x - 1, y - 1, x + 2, y + 2
        region_mask = mask[top:bottom, left:right]
        fraction = np.count_nonzero(region_mask) / region_mask.size
        self.assertGreater(fraction, read_meter.OFF_FRACTION)
        self.assertLess(fraction, read_meter.ON_FRACTION)

    def test_non_red_light_is_not_a_lit_segment(self):
        for color in [(230, 230, 230), (230, 15, 15), (15, 230, 15)]:
            with self.subTest(color=color):
                image = simulate_meter.draw_display("      ")
                image[:, :] = color
                reading, _ = read_meter.recognize_display(image)
                self.assertIsNone(reading["raw_value"])

    def test_white_cores_are_rejected_even_when_surrounded_by_red(self):
        segment_names = "abcdefg"
        for digit in "0123456789":
            display = digit * 6
            image = simulate_meter.draw_display(display)
            for digit_points in read_meter.SEGMENT_POINTS:
                for segment_index, (x, y) in enumerate(digit_points):
                    name = segment_names[segment_index]
                    if name in simulate_meter.LIT_SEGMENTS[digit]:
                        image[y - 1 : y + 2, x - 1 : x + 2] = 255
            with self.subTest(digit=digit):
                reading, mask = read_meter.recognize_display(image)
                self.assertIsNone(reading["raw_value"])
                self.assertEqual(reading["reason"], "uncertain_segments")

    def test_fully_white_segment_is_uncertain_instead_of_becoming_another_digit(self):
        for digit_index, digit_points in enumerate(read_meter.SEGMENT_POINTS):
            for segment_index, (x, y) in enumerate(digit_points):
                with self.subTest(digit=digit_index, segment=segment_index):
                    image = simulate_meter.draw_display("888888")
                    left, top, right, bottom = x - 1, y - 1, x + 2, y + 2
                    image[top:bottom, left:right] = 255
                    reading, mask = read_meter.recognize_display(image)
                    self.assertIsNone(reading["raw_value"])
                    self.assertEqual(reading["reason"], "uncertain_segments")
                    self.assertEqual(
                        reading["patterns"][digit_index][segment_index], "?"
                    )
                    self.assertEqual(cv2.countNonZero(mask[top:bottom, left:right]), 0)

    def test_red_point_away_from_white_center_remains_readable(self):
        image = simulate_meter.draw_display("888888")
        points = deepcopy(read_meter.SEGMENT_POINTS)
        for digit_points in points:
            for segment_index, point in enumerate(digit_points):
                x, y = point
                image[y - 2 : y + 3, x - 2 : x + 3] = 255
                if segment_index in (0, 3, 6):
                    point[0] += 15
                else:
                    point[1] += 15
        reading, _ = read_meter.recognize_display(image)
        self.assertIsNone(reading["raw_value"])
        with patch.object(read_meter, "SEGMENT_POINTS", points):
            reading, _ = read_meter.recognize_display(image)
        self.assertEqual(reading["raw_value"], "888.888")

    def test_one_red_noise_pixel_does_not_make_white_sample_readable(self):
        image = simulate_meter.draw_display("888888")
        x, y = read_meter.SEGMENT_POINTS[0][0]
        left, top, right, bottom = x - 1, y - 1, x + 2, y + 2
        region = image[top:bottom, left:right]
        region[:] = 255
        region[0, 0] = (12, 17, 230)
        reading, mask = read_meter.recognize_display(image)
        self.assertIsNone(reading["raw_value"])
        self.assertEqual(reading["patterns"][0][0], "?")
        accepted_pixels = cv2.countNonZero(mask[top:bottom, left:right])
        self.assertLessEqual(accepted_pixels, 1)

    def test_excess_white_is_rejected_even_when_red_fraction_is_high(self):
        image = simulate_meter.draw_display("888888")
        x, y = read_meter.SEGMENT_POINTS[0][0]
        image[y - 1, x - 1 : x + 1] = 255
        reading, _ = read_meter.recognize_display(image)
        self.assertIsNone(reading["raw_value"])
        self.assertEqual(reading["patterns"][0][0], "?")

    def test_one_noise_pixel_does_not_change_lit_or_unlit_sample(self):
        image = simulate_meter.draw_display("123456")
        for digit, points in zip("123456", read_meter.SEGMENT_POINTS):
            for name, (x, y) in zip("abcdefg", points):
                if name in simulate_meter.LIT_SEGMENTS[digit]:
                    image[y, x] = 8
                else:
                    image[y, x] = (12, 17, 230)
        reading, _ = read_meter.recognize_display(image)
        self.assertEqual(reading["raw_value"], "123.456")

    def test_larger_radius_reads_the_whole_neighborhood(self):
        image = simulate_meter.draw_display("888888")
        x, y = read_meter.SEGMENT_POINTS[0][0]
        image[y - 2 : y + 3, x - 2 : x + 3] = 8
        image[y - 1 : y + 2, x - 1 : x + 2] = (12, 17, 230)
        reading, _ = read_meter.recognize_display(image)
        self.assertEqual(reading["raw_value"], "888.888")
        with patch.object(read_meter, "SAMPLE_RADIUS", 2):
            reading, _ = read_meter.recognize_display(image)
        self.assertIsNone(reading["raw_value"])

    def test_each_digit_uses_its_individually_selected_absolute_points(self):
        image = np.full((200, 720, 3), 8, dtype=np.uint8)
        display = "123456"
        points = []
        segment_names = "abcdefg"
        for digit_index, digit in enumerate(display):
            digit_points = []
            for segment_index, name in enumerate(segment_names):
                left = digit_index * 120 + 5 + segment_index * 13
                top = 10 + digit_index * 7 + segment_index * 15
                right = left + 3
                bottom = top + 3
                digit_points.append([left + 1, top + 1])
                if name in simulate_meter.LIT_SEGMENTS[digit]:
                    image[top:bottom, left:right] = (12, 17, 230)
            points.append(digit_points)
        with patch.object(read_meter, "SEGMENT_POINTS", points):
            read_meter.validate_segment_points()
            reading, _ = read_meter.recognize_display(image)
        self.assertEqual(reading["display"], display)
        self.assertEqual(reading["raw_value"], "123.456")


class FrameRecognitionTests(unittest.TestCase):
    def test_frame_pixels_and_all_reflection_directions(self):
        unreflected_frame = simulate_meter.make_frame(" 12345", reflection="none")
        for reflection in ["none", "horizontal", "vertical", "both"]:
            with self.subTest(reflection=reflection):
                frame = simulate_meter.make_frame(" 12345", reflection=reflection)
                with patch.object(read_meter, "REFLECTION", reflection):
                    image = read_meter.prepare_frame(frame)
                self.assertTrue(np.array_equal(image, unreflected_frame))
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
                    image = read_meter.prepare_frame(frame)
                reading, _ = read_meter.recognize_display(image)
                self.assertEqual(reading["raw_value"], expected)

    def test_frame_size_must_match_calibration(self):
        frame = simulate_meter.make_frame("123456", reflection="none")
        smaller_frame = cv2.resize(frame, (480, 180))
        with self.assertRaises(ValueError):
            read_meter.prepare_frame(smaller_frame)


def only_readings_csv(directory):
    paths = list(directory.glob("readings_*.csv"))
    if len(paths) != 1:
        raise AssertionError(f"測定CSVは1個必要です。現在は{len(paths)}個です。")
    return paths[0]


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

    def run_reader(self, csv_dir, video_path=None):
        if video_path is None:
            video_path = self.output / "meter.avi"
        output = io.StringIO()
        messages = io.StringIO()
        with patch.multiple(
            read_meter,
            SOURCE=video_path,
            CSV_DIR=csv_dir,
            SHOW_PREVIEW=False,
            REFLECTION="horizontal",
        ):
            with redirect_stdout(output), redirect_stderr(messages):
                read_meter.main()
        self.assertIn(str(csv_dir), messages.getvalue())
        return output.getvalue()

    def test_video_to_minimal_jsonl_and_diagnostic_csv_with_stability_reset(self):
        csv_dir = self.output / "readings"
        output = self.run_reader(csv_dir)
        records = []
        for line in output.splitlines():
            records.append(json.loads(line))
        with (self.output / "truth.csv").open(encoding="utf-8", newline="") as file:
            truth = list(csv.DictReader(file))
        with only_readings_csv(csv_dir).open(
            encoding="utf-8-sig", newline=""
        ) as file:
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
                self.assertEqual(csv_record["frame_index"], expected["frame_index"])
                self.assertEqual(csv_record["display"], expected["display"])
                self.assertAlmostEqual(
                    record["source_time_seconds"],
                    float(expected["time_seconds"]),
                    places=5,
                )
                received_at = datetime.fromisoformat(record["received_at"])
                self.assertEqual(received_at.utcoffset(), timedelta(0))
                self.assertEqual(
                    set(record),
                    {"received_at", "source_time_seconds", "value"},
                )
                self.assertEqual(
                    set(csv_record),
                    {
                        "frame_index", "received_at", "source_time_seconds", "status",
                        "display", "raw_value", "value", "reason",
                    },
                )
                self.assertEqual(csv_record["received_at"], record["received_at"])
                self.assertEqual(
                    csv_record["source_time_seconds"], str(record["source_time_seconds"])
                )
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
                accepted_value = None
                if expected_status == "ok":
                    accepted_value = value
                    self.assertIn(type(record["value"]), (int, float))
                    self.assertEqual(record["value"], float(accepted_value))
                else:
                    self.assertIsNone(record["value"])
                self.assertEqual(csv_record["status"], expected_status)
                self.assertEqual(csv_record["value"], accepted_value or "")
                self.assertEqual(csv_record["raw_value"], value or "")
                if value is None:
                    self.assertIn(
                        csv_record["reason"],
                        ["all_blank", "misplaced_blank", "uncertain_segments"],
                    )
                else:
                    self.assertEqual(csv_record["reason"], "")

    def test_repeated_runs_use_local_datetime_names_and_preserve_existing_files(self):
        csv_dir = self.output / "timestamped"
        csv_dir.mkdir()
        original = "以前の測定値\n123.456\n"
        original_path = csv_dir / "readings_20261103_123456_123455.csv"
        original_path.write_text(original, encoding="utf-8")
        local_times = iter([
            datetime(2026, 11, 3, 12, 34, 56, 123456),
            datetime(2026, 11, 3, 12, 34, 56, 123457),
        ])

        def current_datetime(zone=None):
            if zone is None:
                return next(local_times)
            return datetime.now(zone)

        fake_datetime = Mock()
        fake_datetime.now.side_effect = current_datetime
        first_path = csv_dir / "readings_20261103_123456_123456.csv"
        second_path = csv_dir / "readings_20261103_123456_123457.csv"
        with patch.object(read_meter, "datetime", fake_datetime):
            self.run_reader(csv_dir)
            first_contents = first_path.read_bytes()
            self.run_reader(csv_dir)
        self.assertEqual(first_path.read_bytes(), first_contents)
        self.assertTrue(second_path.is_file())
        self.assertEqual(original_path.read_text(encoding="utf-8"), original)
        self.assertEqual(
            set(csv_dir.glob("readings_*.csv")),
            {original_path, first_path, second_path},
        )

    def test_datetime_name_collision_fails_without_overwriting_or_outputting_values(self):
        csv_dir = self.output / "collision"
        csv_dir.mkdir()
        original = "別の処理が保存した測定値\n".encode("utf-8")
        existing_path = csv_dir / "readings_20261103_123456_123456.csv"
        existing_path.write_bytes(original)
        fixed_time = datetime(2026, 11, 3, 12, 34, 56, 123456)
        fake_datetime = Mock()
        fake_datetime.now.side_effect = lambda zone=None: fixed_time.replace(tzinfo=zone)
        capture = Mock()
        capture.isOpened.return_value = True
        capture.get.return_value = 30.0
        frame = simulate_meter.make_frame("  1234", "horizontal")
        capture.read.return_value = (True, frame)
        output = io.StringIO()
        with patch.multiple(
            read_meter, SOURCE=0, CSV_DIR=csv_dir, SHOW_PREVIEW=False,
            REFLECTION="horizontal", datetime=fake_datetime,
        ):
            with patch.object(read_meter.cv2, "VideoCapture", return_value=capture):
                with redirect_stdout(output), redirect_stderr(io.StringIO()):
                    with self.assertRaises(FileExistsError):
                        read_meter.main()
        self.assertEqual(existing_path.read_bytes(), original)
        self.assertEqual(list(csv_dir.glob("readings_*.csv")), [existing_path])
        self.assertEqual(output.getvalue(), "")
        capture.read.assert_called_once()
        capture.release.assert_called_once()

    def test_white_sample_in_compressed_video_invalidates_and_resets_stability(self):
        video_path = self.output / "white_sample.avi"
        writer = cv2.VideoWriter(
            str(video_path), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, (960, 360)
        )
        self.assertTrue(writer.isOpened())
        try:
            for frame_index in range(9):
                frame = simulate_meter.make_frame("888888", "none", seed=frame_index)
                if 3 <= frame_index < 6:
                    x, y = read_meter.SEGMENT_POINTS[0][6]
                    frame[y - 5 : y + 6, x - 5 : x + 6] = 255
                writer.write(cv2.flip(frame, 1))
        finally:
            writer.release()
        csv_dir = self.output / "white_sample"
        output = self.run_reader(csv_dir, video_path)
        records = []
        for line in output.splitlines():
            records.append(json.loads(line))
        self.assertEqual(len(records), 9)
        with only_readings_csv(csv_dir).open(encoding="utf-8", newline="") as file:
            csv_records = list(csv.DictReader(file))
        expected_values = ["888.888"] * 3 + [""] * 3 + ["888.888"] * 3
        for record, expected in zip(csv_records, expected_values):
            self.assertEqual(record["raw_value"], expected)
        values = []
        for record in records:
            values.append(record["value"])
        self.assertEqual(values, [None, None, 888.888, None, None, None, None, None, 888.888])
        for record in csv_records[3:6]:
            self.assertEqual(record["reason"], "uncertain_segments")

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
        csv_dir = self.output / "interrupted"
        output = self.run_reader(csv_dir, video_path=video_path)
        statuses = []
        values = []
        for line in output.splitlines():
            record = json.loads(line)
            values.append(record["value"])
        with only_readings_csv(csv_dir).open(encoding="utf-8", newline="") as file:
            for record in csv.DictReader(file):
                statuses.append(record["status"])
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
        self.assertEqual(values, [None, None, 1.234, None, None, None, 1.234])

    def test_camera_disconnect_is_an_error_and_releases_camera(self):
        capture = Mock()
        capture.isOpened.return_value = True
        capture.get.return_value = 30.0
        frame = simulate_meter.make_frame("  1234", "horizontal")
        capture.read.side_effect = [(True, frame), (False, None)]
        csv_dir = self.output / "camera_disconnect"
        output = io.StringIO()
        with patch.multiple(
            read_meter,
            SOURCE=0,
            CSV_DIR=csv_dir,
            SHOW_PREVIEW=False,
            REFLECTION="horizontal",
        ):
            with patch.object(read_meter.cv2, "VideoCapture", return_value=capture):
                with redirect_stdout(output), redirect_stderr(io.StringIO()):
                    with self.assertRaises(RuntimeError):
                        read_meter.main()
        capture.release.assert_called_once()
        with only_readings_csv(csv_dir).open(encoding="utf-8", newline="") as file:
            records = list(csv.DictReader(file))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["value"], "")

    def test_mismatched_video_size_fails_without_a_value(self):
        output = io.StringIO()
        csv_dir = self.output / "wrong_size"
        with patch.multiple(
            read_meter,
            SOURCE=self.output / "meter.avi",
            CSV_DIR=csv_dir,
            SHOW_PREVIEW=False,
            FRAME_SIZE=[1280, 720],
        ):
            with redirect_stdout(output):
                with self.assertRaises(ValueError):
                    read_meter.main()
        self.assertEqual(output.getvalue(), "")
        self.assertFalse(csv_dir.exists())


class MeasurementOperationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.csv_dir = Path(temporary.name)
        self.frame = simulate_meter.make_frame("  1234", "horizontal")
        self.capture = Mock()
        self.capture.isOpened.return_value = True
        self.capture.get.return_value = 30.0
        self.capture.read.return_value = (True, self.frame)
        settings = patch.multiple(
            read_meter,
            SOURCE=0,
            CSV_DIR=self.csv_dir,
            SHOW_PREVIEW=True,
            REFLECTION="horizontal",
        )
        settings.start()
        self.addCleanup(settings.stop)
        self.gui = {
            "VideoCapture": Mock(return_value=self.capture),
            "namedWindow": Mock(),
            "resizeWindow": Mock(),
            "setWindowTitle": Mock(),
            "imshow": Mock(),
            "waitKey": Mock(return_value=ord("q")),
            "getWindowProperty": Mock(return_value=1),
            "destroyAllWindows": Mock(),
        }
        gui_patches = patch.multiple(read_meter.cv2, **self.gui)
        gui_patches.start()
        self.addCleanup(gui_patches.stop)

    def run_reader(self):
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(io.StringIO()):
            read_meter.main()
        records = []
        for line in output.getvalue().splitlines():
            records.append(json.loads(line))
        return records

    def test_large_preview_fits_screen_and_keeps_full_image_for_recognition(self):
        self.capture.read.return_value = (
            True, np.zeros((1080, 1920, 3), dtype=np.uint8)
        )
        with patch.object(read_meter, "FRAME_SIZE", [1920, 1080]):
            original_recognize = read_meter.recognize_display
            with patch.object(
                read_meter, "recognize_display", wraps=original_recognize
            ) as recognize:
                self.run_reader()
        self.gui["namedWindow"].assert_called_once_with(
            "Seven segment OCR", cv2.WINDOW_NORMAL
        )
        self.gui["resizeWindow"].assert_called_once_with("Seven segment OCR", 640, 720)
        self.assertEqual(recognize.call_args.args[0].shape, (1080, 1920, 3))
        self.assertEqual(self.gui["imshow"].call_args.args[1].shape, (2160, 1920, 3))
        title = self.gui["setWindowTitle"].call_args.args[1]
        self.assertIn("invalid", title)
        self.assertIn("all_blank", title)

    def test_quit_keys_and_window_close_stop_before_next_camera_read(self):
        for key, visibility in [(ord("q"), 1), (27, 1), (-1, 0), (-1, -1)]:
            with self.subTest(key=key, visibility=visibility):
                self.capture.reset_mock()
                self.gui["destroyAllWindows"].reset_mock()
                self.gui["waitKey"].return_value = key
                self.gui["getWindowProperty"].return_value = visibility
                records = self.run_reader()
                self.assertEqual(len(records), 1)
                self.capture.read.assert_called_once()
                self.capture.release.assert_called_once()
                self.gui["destroyAllWindows"].assert_called_once()
                title = self.gui["setWindowTitle"].call_args.args[1]
                self.assertIn("warming_up", title)
                self.assertIn("1.234", title)
                self.assertIn("Q / Esc", title)

    def test_receipt_times_precede_processing_and_camera_elapsed_starts_at_zero(self):
        clock = {"seconds": 100.0}
        epoch = datetime(2026, 11, 2, tzinfo=timezone.utc)
        original_prepare = read_meter.prepare_frame
        original_recognize = read_meter.recognize_display

        def acquire_frame():
            clock["seconds"] += 0.25
            return True, self.frame

        def prepare_frame(frame):
            clock["seconds"] += 10.0
            return original_prepare(frame)

        def recognize_display(image):
            clock["seconds"] += 5.0
            return original_recognize(image)

        def current_datetime(zone=None):
            current = epoch + timedelta(seconds=clock["seconds"])
            if zone is None:
                return current.astimezone().replace(tzinfo=None)
            return current.astimezone(zone)

        fake_datetime = Mock()
        fake_datetime.now.side_effect = current_datetime
        self.capture.read.side_effect = acquire_frame
        self.gui["waitKey"].side_effect = [-1, ord("q")]
        with patch.object(read_meter, "datetime", fake_datetime):
            with patch.object(
                read_meter.time, "monotonic", side_effect=lambda: clock["seconds"]
            ):
                with patch.object(read_meter, "prepare_frame", side_effect=prepare_frame):
                    with patch.object(
                        read_meter, "recognize_display", side_effect=recognize_display
                    ):
                        records = self.run_reader()
        self.assertEqual(
            [record["received_at"] for record in records],
            ["2026-11-02T00:01:40.250+00:00", "2026-11-02T00:01:55.500+00:00"],
        )
        self.assertEqual(
            [record["source_time_seconds"] for record in records], [0.0, 15.25]
        )

    def test_interrupt_releases_camera_and_preserves_written_rows(self):
        self.capture.read.side_effect = [(True, self.frame), KeyboardInterrupt]
        self.gui["waitKey"].return_value = -1
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(io.StringIO()):
            with self.assertRaises(KeyboardInterrupt):
                read_meter.main()
        self.capture.release.assert_called_once()
        self.gui["destroyAllWindows"].assert_called_once()
        with only_readings_csv(self.csv_dir).open(
            encoding="utf-8", newline=""
        ) as file:
            records = list(csv.DictReader(file))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["raw_value"], "1.234")
        self.assertEqual(len(output.getvalue().splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
