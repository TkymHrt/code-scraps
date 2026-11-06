"""点の周囲での色判定と、連携用JSONLの確定・欠測を確認する。"""

import importlib.util
import io
import json
import unittest
from contextlib import redirect_stdout
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

SCRIPT = Path(__file__).resolve().parents[1] / "read_meter.py"
SPEC = importlib.util.spec_from_file_location("logger_reader_under_test", SCRIPT)
reader = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reader)

LIT_SEGMENTS = {
    "0": "abcdef",
    "1": "bc",
    "2": "abdeg",
    "3": "abcdg",
    "4": "bcfg",
    "5": "acdfg",
    "6": "acdefg",
    "7": "abc",
    "8": "abcdefg",
    "9": "abcdfg",
    " ": "",
}


def make_image(display):
    width, height = reader.FRAME_SIZE
    image = np.full((height, width, 3), 8, dtype=np.uint8)
    for digit, points in zip(display, reader.SEGMENT_POINTS):
        for name, (x, y) in zip("abcdefg", points):
            if name in LIT_SEGMENTS[digit]:
                image[y - 1 : y + 2, x - 1 : x + 2] = (12, 17, 230)
    return image


class ReadMeterTests(unittest.TestCase):
    def test_digits_in_each_position_and_numeric_zero(self):
        for position in range(6):
            for digit in "0123456789":
                symbols = list("123456")
                symbols[position] = digit
                display = "".join(symbols)
                with self.subTest(position=position, digit=digit):
                    value = reader.recognize_display(make_image(display))
                    self.assertEqual(value, int(display) / 1000)
        self.assertEqual(reader.recognize_display(make_image("  0000")), 0.0)
        for display in ("      ", "12 456", "123 56", "12345 "):
            self.assertIsNone(reader.recognize_display(make_image(display)))

    def test_white_at_any_selected_point_is_unreadable(self):
        for digit_index, points in enumerate(reader.SEGMENT_POINTS):
            for segment_index, (x, y) in enumerate(points):
                with self.subTest(digit=digit_index, segment=segment_index):
                    image = make_image("888888")
                    image[y - 1 : y + 2, x - 1 : x + 2] = 255
                    self.assertIsNone(reader.recognize_display(image))

    def test_high_red_fraction_does_not_override_excess_white(self):
        image = make_image("888888")
        x, y = reader.SEGMENT_POINTS[0][0]
        image[y - 1, x - 1 : x + 1] = 255
        self.assertIsNone(reader.recognize_display(image))

    def test_one_noise_pixel_is_tolerated_but_ambiguous_sample_is_not(self):
        image = make_image("123456")
        for digit, points in zip("123456", reader.SEGMENT_POINTS):
            for name, (x, y) in zip("abcdefg", points):
                if name in LIT_SEGMENTS[digit]:
                    image[y, x] = 8
                else:
                    image[y, x] = (12, 17, 230)
        self.assertEqual(reader.recognize_display(image), 123.456)
        x, y = reader.SEGMENT_POINTS[0][1]
        image[y - 1 : y + 2, x - 1 : x + 1] = 8
        self.assertIsNone(reader.recognize_display(image))

    def test_radius_controls_the_sample_and_white_outside_is_ignored(self):
        image = make_image("888888")
        x, y = reader.SEGMENT_POINTS[0][0]
        image[y - 1 : y + 2, x + 2 : x + 5] = 255
        self.assertEqual(reader.recognize_display(image), 888.888)
        with patch.object(reader, "SAMPLE_RADIUS", 2):
            self.assertIsNone(reader.recognize_display(image))
        with patch.object(reader, "SAMPLE_RADIUS", 0):
            self.assertEqual(reader.recognize_display(image), 888.888)

    def test_invalid_points_and_radius_prevent_opening_input(self):
        invalid_settings = []
        for radius in (-1, 1.5):
            invalid_settings.append({"SAMPLE_RADIUS": radius})
        invalid_settings.append({"SEGMENT_POINTS": []})
        missing_segment = deepcopy(reader.SEGMENT_POINTS)
        missing_segment[0].pop()
        invalid_settings.append({"SEGMENT_POINTS": missing_segment})
        bad_points = [
            [10], [10, 10, 20], [10.5, 10], [0, 10], [10, 0], [959, 10], [10, 359]
        ]
        for point in bad_points:
            points = deepcopy(reader.SEGMENT_POINTS)
            points[0][0] = point
            invalid_settings.append({"SEGMENT_POINTS": points})
        for settings in invalid_settings:
            with self.subTest(settings=settings):
                with patch.object(reader, "SOURCE", 0):
                    with patch.multiple(reader, **settings):
                        with patch.object(reader.cv2, "VideoCapture") as capture:
                            with self.assertRaises(ValueError):
                                reader.main()
                            capture.assert_not_called()

    def test_jsonl_white_frame_resets_stability_and_keeps_output_shape(self):
        normal = make_image("888888")
        white = normal.copy()
        x, y = reader.SEGMENT_POINTS[0][6]
        white[y - 1 : y + 2, x - 1 : x + 2] = 255
        frames = [normal, normal, normal, white, normal, normal, normal]
        capture = Mock()
        capture.isOpened.return_value = True
        capture.get.return_value = 30.0
        capture.read.side_effect = [(True, frame) for frame in frames] + [(False, None)]
        output = io.StringIO()
        with patch.multiple(reader, SOURCE="test.avi", REFLECTION="none"):
            with patch.object(reader.cv2, "VideoCapture", return_value=capture):
                with redirect_stdout(output):
                    reader.main()
        messages = []
        for line in output.getvalue().splitlines():
            message = json.loads(line)
            self.assertEqual(set(message), {"received_at", "value"})
            messages.append(message["value"])
        self.assertEqual(messages, [None, None, 888.888, None, None, None, 888.888])
        capture.release.assert_called_once()


if __name__ == "__main__":
    unittest.main()
