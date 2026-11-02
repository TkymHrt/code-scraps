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

# 描画用の720×200画像を直接調べるテストだけで使う枠。
FLAT_BOXES = []
for digit_index in range(6):
    digit_boxes = []
    for left, top, right, bottom in [
        [42, 15, 78, 25],
        [95, 41, 104, 76],
        [95, 124, 104, 159],
        [42, 175, 78, 185],
        [16, 124, 25, 159],
        [16, 41, 25, 76],
        [42, 95, 78, 105],
    ]:
        offset = digit_index * 120
        digit_boxes.append([left + offset, top, right + offset, bottom])
    FLAT_BOXES.append(digit_boxes)


class CalibrationTests(unittest.TestCase):
    def run_calibration(self, rois):
        frame = simulate_meter.make_frame("  1234", reflection="vertical")
        capture = Mock()
        capture.isOpened.return_value = True
        capture.read.return_value = (True, frame)

        output = io.StringIO()
        select_roi = Mock(side_effect=rois)
        with patch.multiple(calibrate_meter, SOURCE=0, REFLECTION="vertical"):
            with patch.multiple(
                calibrate_meter.cv2,
                VideoCapture=Mock(return_value=capture),
                namedWindow=Mock(),
                resizeWindow=Mock(),
                imshow=Mock(),
                waitKey=Mock(return_value=ord(" ")),
                selectROI=select_roi,
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
        return settings, select_roi

    def test_printed_calibration_can_be_copied_into_reader(self):
        boxes = deepcopy(read_meter.SEGMENT_BOXES)
        rois = []
        for digit_boxes in boxes:
            for left, top, right, bottom in digit_boxes:
                rois.append((left, top, right - left, bottom - top))
        settings, select_roi = self.run_calibration(rois)
        self.assertEqual(
            set(settings),
            {"FRAME_SIZE", "REFLECTION", "SEGMENT_BOXES"},
        )
        self.assertEqual(settings["SEGMENT_BOXES"], boxes)
        self.assertEqual(settings["FRAME_SIZE"], [960, 360])
        self.assertEqual(select_roi.call_count, 42)
        self.assertEqual(select_roi.call_args_list[0].args[1].shape, (360, 960, 3))
        with patch.multiple(read_meter, **settings):
            read_meter.validate_segment_boxes()
            frame = simulate_meter.make_frame("  1234", reflection="vertical")
            image = read_meter.prepare_frame(frame)
            reading, _ = read_meter.recognize_display(image)
        self.assertEqual(reading["raw_value"], "1.234")

    def test_cancel_during_segment_selection_prints_no_partial_settings(self):
        rois = [(42, 15, 36, 10), (95, 41, 9, 35), (0, 0, 0, 0)]
        settings, select_roi = self.run_calibration(rois)
        self.assertEqual(settings, {})
        self.assertEqual(select_roi.call_count, 3)

    def test_outside_segment_selection_is_retried(self):
        boxes = deepcopy(read_meter.SEGMENT_BOXES)
        rois = [(959, 10, 10, 10)]
        for digit_boxes in boxes:
            for left, top, right, bottom in digit_boxes:
                rois.append((left, top, right - left, bottom - top))
        settings, select_roi = self.run_calibration(rois)
        self.assertEqual(settings["SEGMENT_BOXES"], boxes)
        self.assertEqual(select_roi.call_count, 43)


class ConfigurationTests(unittest.TestCase):
    def test_segment_boxes_require_six_digits_and_seven_segments(self):
        missing_digit = deepcopy(read_meter.SEGMENT_BOXES)
        missing_digit.pop()
        extra_digit = deepcopy(read_meter.SEGMENT_BOXES)
        extra_digit.append(deepcopy(extra_digit[0]))
        missing_segment = deepcopy(read_meter.SEGMENT_BOXES)
        missing_segment[2].pop()
        extra_segment = deepcopy(read_meter.SEGMENT_BOXES)
        extra_segment[2].append([10, 10, 20, 20])
        for boxes in [[], missing_digit, extra_digit, missing_segment, extra_segment]:
            with self.subTest(boxes=boxes):
                with patch.object(read_meter, "SEGMENT_BOXES", boxes):
                    with self.assertRaises(ValueError):
                        read_meter.validate_segment_boxes()

    def test_segment_boxes_require_integer_coordinates_and_nonempty_image_area(self):
        frame_width, frame_height = read_meter.FRAME_SIZE
        bad_boxes = [
            [10, 10, 20],
            [10, 10, 20, 20, 30],
            [10, 10, 10, 20],
            [10, 20, 20, 20],
            [20, 10, 10, 20],
            [-1, 10, 20, 20],
            [10, -1, 20, 20],
            [10, 10, frame_width + 1, 20],
            [10, 10, 20, frame_height + 1],
            [10.5, 10, 20, 20],
            ["10", 10, 20, 20],
            [float("nan"), 10, 20, 20],
        ]
        for box in bad_boxes:
            with self.subTest(box=box):
                boxes = deepcopy(read_meter.SEGMENT_BOXES)
                boxes[0][0] = box
                with patch.object(read_meter, "SEGMENT_BOXES", boxes):
                    with self.assertRaises(ValueError):
                        read_meter.validate_segment_boxes()

    def test_white_recovery_thresholds_are_checked_before_opening_input(self):
        invalid_settings = [
            {"WHITE_MIN": -1},
            {"WHITE_MIN": 256},
            {"RED_SEED_FRACTION": 0},
            {"RED_SEED_FRACTION": 1.1},
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
            SEGMENT_BOXES=FLAT_BOXES,
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

    def test_white_cores_with_red_edges_are_read_for_every_digit(self):
        segment_names = "abcdefg"
        for digit in "0123456789":
            display = digit * 6
            image = simulate_meter.draw_display(display)
            for digit_boxes in read_meter.SEGMENT_BOXES:
                for segment_index, box in enumerate(digit_boxes):
                    name = segment_names[segment_index]
                    if name in simulate_meter.LIT_SEGMENTS[digit]:
                        left, top, right, bottom = box
                        image[top + 1 : bottom - 1, left + 1 : right - 1] = 255
            with self.subTest(digit=digit):
                reading, mask = read_meter.recognize_display(image)
                expected = str(int(display[:3])) + "." + display[3:]
                self.assertEqual(reading["raw_value"], expected)
                self.assertEqual(reading["display"], display)
                for digit_index, digit_boxes in enumerate(read_meter.SEGMENT_BOXES):
                    for segment_index, box in enumerate(digit_boxes):
                        name = segment_names[segment_index]
                        if name in simulate_meter.LIT_SEGMENTS[digit]:
                            left, top, right, bottom = box
                            core_mask = mask[top + 1 : bottom - 1, left + 1 : right - 1]
                            self.assertTrue(np.all(core_mask == 255))
                            fraction = reading["fractions"][digit_index][segment_index]
                            self.assertGreaterEqual(fraction, read_meter.ON_FRACTION)

    def test_fully_white_segment_is_uncertain_instead_of_becoming_another_digit(self):
        for digit_index, digit_boxes in enumerate(read_meter.SEGMENT_BOXES):
            for segment_index, box in enumerate(digit_boxes):
                with self.subTest(digit=digit_index, segment=segment_index):
                    image = simulate_meter.draw_display("888888")
                    left, top, right, bottom = box
                    image[top:bottom, left:right] = 255
                    reading, mask = read_meter.recognize_display(image)
                    self.assertIsNone(reading["raw_value"])
                    self.assertEqual(reading["reason"], "uncertain_segments")
                    self.assertEqual(
                        reading["patterns"][digit_index][segment_index], "?"
                    )
                    self.assertEqual(cv2.countNonZero(mask[top:bottom, left:right]), 0)

    def test_disconnected_white_blob_does_not_use_nearby_red_as_a_seed(self):
        image = simulate_meter.draw_display("888888")
        left, top, right, bottom = read_meter.SEGMENT_BOXES[0][0]
        region = image[top:bottom, left:right]
        region[:] = 8
        region[:, :3] = (12, 17, 230)
        region[:, 6:] = 255
        reading, mask = read_meter.recognize_display(image)
        self.assertIsNone(reading["raw_value"])
        self.assertEqual(reading["patterns"][0][0], "?")
        self.assertEqual(cv2.countNonZero(mask[top:bottom, left + 6 : right]), 0)

    def test_one_red_noise_pixel_does_not_seed_a_broad_white_reflection(self):
        image = simulate_meter.draw_display("888888")
        left, top, right, bottom = read_meter.SEGMENT_BOXES[0][0]
        region = image[top:bottom, left:right]
        region[:] = 255
        region[0, 0] = (12, 17, 230)
        reading, mask = read_meter.recognize_display(image)
        self.assertIsNone(reading["raw_value"])
        self.assertEqual(reading["patterns"][0][0], "?")
        accepted_pixels = cv2.countNonZero(mask[top:bottom, left:right])
        self.assertLessEqual(accepted_pixels, 1)

    def test_each_digit_uses_its_individually_selected_absolute_boxes(self):
        image = np.full((200, 720, 3), 8, dtype=np.uint8)
        display = "123456"
        boxes = []
        segment_names = "abcdefg"
        for digit_index, digit in enumerate(display):
            digit_boxes = []
            for segment_index, name in enumerate(segment_names):
                left = digit_index * 120 + 5 + segment_index * 13
                top = 10 + digit_index * 7 + segment_index * 15
                right = left + 8 + digit_index
                bottom = top + 6 + segment_index
                digit_boxes.append([left, top, right, bottom])
                if name in simulate_meter.LIT_SEGMENTS[digit]:
                    image[top:bottom, left:right] = (12, 17, 230)
            boxes.append(digit_boxes)
        with patch.object(read_meter, "SEGMENT_BOXES", boxes):
            read_meter.validate_segment_boxes()
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

    def test_video_to_jsonl_and_csv_with_stability_reset(self):
        csv_dir = self.output / "readings"
        output = self.run_reader(csv_dir)
        records = []
        for line in output.splitlines():
            records.append(json.loads(line))
        with (self.output / "truth.csv").open(encoding="utf-8", newline="") as file:
            truth = list(csv.DictReader(file))
        with (csv_dir / "readings_001.csv").open(
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

    def test_repeated_runs_choose_free_numbers_and_preserve_existing_files(self):
        csv_dir = self.output / "numbered"
        csv_dir.mkdir()
        original = "以前の測定値\n123.456\n"
        for number in [1, 3]:
            path = csv_dir / f"readings_{number:03d}.csv"
            path.write_text(original, encoding="utf-8")
        self.run_reader(csv_dir)
        second_path = csv_dir / "readings_002.csv"
        second_contents = second_path.read_bytes()
        self.run_reader(csv_dir)
        self.assertTrue((csv_dir / "readings_004.csv").is_file())
        self.assertEqual(second_path.read_bytes(), second_contents)
        for number in [1, 3]:
            path = csv_dir / f"readings_{number:03d}.csv"
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_csv_name_collision_retries_exclusive_creation(self):
        csv_dir = self.output / "collision"
        original_open = Path.open
        attempted_names = []
        original = "別の処理が保存した測定値\n"

        def open_with_collision(path, mode="r", *args, **kwargs):
            if path.parent == csv_dir and mode == "x":
                attempted_names.append(path.name)
                if path.name == "readings_001.csv":
                    with original_open(path, "x", encoding="utf-8") as file:
                        file.write(original)
                    raise FileExistsError("保存直前に同名のCSVが作られた")
            return original_open(path, mode, *args, **kwargs)

        with patch.object(Path, "open", new=open_with_collision):
            self.run_reader(csv_dir)
        self.assertEqual(attempted_names, ["readings_001.csv", "readings_002.csv"])
        self.assertEqual(
            (csv_dir / "readings_001.csv").read_text(encoding="utf-8"), original
        )
        self.assertTrue((csv_dir / "readings_002.csv").is_file())

    def test_white_cores_survive_perspective_and_compressed_video(self):
        original_draw_display = simulate_meter.draw_display

        def draw_overexposed_display(display, brightness=230):
            image = original_draw_display(display, brightness)
            for digit, digit_boxes in zip(display, FLAT_BOXES):
                for name, box in zip("abcdefg", digit_boxes):
                    if name in simulate_meter.LIT_SEGMENTS[digit]:
                        left, top, right, bottom = box
                        image[top + 1 : bottom - 1, left + 1 : right - 1] = 255
            return image

        video_path = self.output / "white_cores.avi"
        writer = cv2.VideoWriter(
            str(video_path), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, (960, 360)
        )
        self.assertTrue(writer.isOpened())
        try:
            with patch.object(
                simulate_meter, "draw_display", side_effect=draw_overexposed_display
            ):
                for display in ["  1234", "888888"]:
                    for frame_index in range(4):
                        frame = simulate_meter.make_frame(
                            display, "horizontal", seed=frame_index
                        )
                        writer.write(frame)
        finally:
            writer.release()
        output = self.run_reader(self.output / "white_cores", video_path)
        records = []
        for line in output.splitlines():
            records.append(json.loads(line))
        self.assertEqual(len(records), 8)
        expected_values = ["1.234"] * 4 + ["888.888"] * 4
        for record, expected in zip(records, expected_values):
            self.assertEqual(record["raw_value"], expected)
        self.assertEqual(records[3]["value"], "1.234")
        self.assertEqual(records[7]["value"], "888.888")

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
        output = self.run_reader(self.output / "interrupted", video_path=video_path)
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
        with (csv_dir / "readings_001.csv").open(encoding="utf-8", newline="") as file:
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


if __name__ == "__main__":
    unittest.main()
