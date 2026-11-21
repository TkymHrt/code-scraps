"""点の周囲での色判定と、連携用JSONLの確定・欠測を確認する。"""

import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

SCRIPT = Path(__file__).resolve().parents[1] / "src" / "counter.py"
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
    for digit, points in zip(display, reader.SEGMENT_POINTS, strict=True):
        for name, (x, y) in zip("abcdefg", points, strict=True):
            if name in LIT_SEGMENTS[digit]:
                image[y - 1 : y + 2, x - 1 : x + 2] = (12, 17, 230)
    return image


def recognize(image):
    sample_coordinates = reader.prepare_samples("none")
    return reader.recognize_display(image, sample_coordinates)


class ReadMeterTests(unittest.TestCase):
    def test_digits_in_each_position_and_numeric_zero(self):
        for position in range(6):
            for digit in "0123456789":
                symbols = list("123456")
                symbols[position] = digit
                display = "".join(symbols)
                with self.subTest(position=position, digit=digit):
                    value = recognize(make_image(display))
                    self.assertEqual(value, int(display) / 1000)
        self.assertEqual(recognize(make_image("  0000")), 0.0)
        for display in ("     0", "     1", "    12", "   123", "  1234"):
            with self.subTest(display=display):
                self.assertEqual(recognize(make_image(display)), int(display) / 1000)
        for display in ("      ", "12 456", "123 56", "12345 "):
            self.assertIsNone(recognize(make_image(display)))

    def test_white_at_any_selected_point_is_unreadable(self):
        for digit_index, points in enumerate(reader.SEGMENT_POINTS):
            for segment_index, (x, y) in enumerate(points):
                with self.subTest(digit=digit_index, segment=segment_index):
                    image = make_image("888888")
                    image[y - 1 : y + 2, x - 1 : x + 2] = 255
                    self.assertIsNone(recognize(image))

    def test_high_red_fraction_does_not_override_excess_white(self):
        image = make_image("888888")
        x, y = reader.SEGMENT_POINTS[0][0]
        image[y - 1, x - 1 : x + 1] = 255
        self.assertIsNone(recognize(image))

    def test_one_noise_pixel_is_tolerated_but_ambiguous_sample_is_not(self):
        image = make_image("123456")
        for digit, points in zip("123456", reader.SEGMENT_POINTS, strict=True):
            for name, (x, y) in zip("abcdefg", points, strict=True):
                if name in LIT_SEGMENTS[digit]:
                    image[y, x] = 8
                else:
                    image[y, x] = (12, 17, 230)
        self.assertEqual(recognize(image), 123.456)
        x, y = reader.SEGMENT_POINTS[0][1]
        image[y - 1 : y + 2, x - 1 : x + 1] = 8
        self.assertIsNone(recognize(image))

    def test_radius_controls_the_sample_and_white_outside_is_ignored(self):
        image = make_image("888888")
        x, y = reader.SEGMENT_POINTS[0][0]
        image[y - 1 : y + 2, x + 2 : x + 5] = 255
        self.assertEqual(recognize(image), 888.888)
        with patch.object(reader, "SAMPLE_RADIUS", 2):
            self.assertIsNone(recognize(image))
        with patch.object(reader, "SAMPLE_RADIUS", 0):
            self.assertEqual(recognize(image), 888.888)

    def test_blue_sample_does_not_wrap_into_a_red_sample(self):
        image = make_image("123456")
        x, y = reader.SEGMENT_POINTS[0][0]
        image[y - 1 : y + 2, x - 1 : x + 2] = (180, 100, 120)
        self.assertEqual(recognize(image), 123.456)

    def test_calibrated_red_excess_reads_weak_red_and_rejects_ambiguity(self):
        image = make_image("123456")
        lit = image[:, :, 2] == 230
        image[:] = (100, 100, 105)
        image[lit] = (100, 100, 130)
        self.assertIsNone(recognize(image))

        x, y = reader.SEGMENT_POINTS[0][1]
        with patch.object(reader, "RED_EXCESS_LIMITS", (5, 30)):
            self.assertEqual(recognize(image), 123.456)
            image[y - 1, x - 1 : x + 1] = 255
            self.assertIsNone(recognize(image))
            image[y - 1 : y + 2, x - 1 : x + 2] = (100, 100, 115)
            self.assertIsNone(recognize(image))

    def test_long_sample_follows_the_segment_and_ignores_white_beside_it(self):
        width, height = reader.FRAME_SIZE
        image = np.full((height, width, 3), 8, dtype=np.uint8)
        for digit, points in zip("123456", reader.SEGMENT_POINTS, strict=True):
            for name, (x, y) in zip("abcdefg", points, strict=True):
                if name not in LIT_SEGMENTS[digit]:
                    continue
                if name in "adg":
                    image[y - 1 : y + 2, x - 4 : x + 5] = (12, 17, 230)
                    image[y + 2, x - 4 : x + 5] = 255
                else:
                    image[y - 4 : y + 5, x - 1 : x + 2] = (12, 17, 230)
                    image[y - 4 : y + 5, x + 2] = 255
                image[y - 1 : y + 2, x - 1 : x + 2] = 8

        self.assertIsNone(recognize(image))
        with patch.object(reader, "SAMPLE_LENGTH_RADIUS", 4):
            self.assertEqual(recognize(image), 123.456)

    def test_invalid_calibration_prevents_opening_input(self):
        invalid_settings = []
        for radius in (-1, 1.5):
            invalid_settings.append({"SAMPLE_RADIUS": radius})
        for radius in (0, 4.5):
            invalid_settings.append({"SAMPLE_LENGTH_RADIUS": radius})
        for limits in ((20, 10), (20,), (0, 256)):
            invalid_settings.append({"RED_EXCESS_LIMITS": limits})
        edge_points = deepcopy(reader.SEGMENT_POINTS)
        edge_points[0][0] = [2, 110]
        invalid_settings.append(
            {"SAMPLE_LENGTH_RADIUS": 4, "SEGMENT_POINTS": edge_points}
        )
        invalid_settings.append({"SEGMENT_POINTS": []})
        missing_segment = deepcopy(reader.SEGMENT_POINTS)
        missing_segment[0].pop()
        invalid_settings.append({"SEGMENT_POINTS": missing_segment})
        bad_points = [
            [10],
            [10, 10, 20],
            [10.5, 10],
            [0, 10],
            [10, 0],
            [959, 10],
            [10, 359],
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
                            with self.assertRaises((TypeError, ValueError)):
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
        diagnostics = io.StringIO()
        with (
            patch.multiple(
                reader, SOURCE="test.avi", REFLECTION="none", STABLE_FRAMES=3
            ),
            patch.object(reader.cv2, "VideoCapture", return_value=capture),
            patch.object(sys, "argv", ["counter.py", "--segment-scores"]),
            redirect_stdout(output),
            redirect_stderr(diagnostics),
        ):
            reader.main()
        messages = []
        for line in output.getvalue().splitlines():
            message = json.loads(line)
            self.assertEqual(set(message), {"received_at", "acquired_mono_ns", "value"})
            messages.append(message["value"])
        self.assertEqual(messages, [None, None, 888.888, None, None, None, 888.888])
        lines = diagnostics.getvalue().splitlines()
        self.assertEqual(len(lines), len(frames))
        for index, line in enumerate(lines):
            scores, white_segments = line.removeprefix("red_excess=").split(
                " white_segments="
            )
            self.assertEqual(len(json.loads(scores)), 42)
            self.assertEqual(json.loads(white_segments), [7] if index == 3 else [])
        capture.release.assert_called_once()

    def test_default_reports_changing_values_without_waiting_for_equal_frames(self):
        self.assertEqual(reader.STABLE_FRAMES, 1)
        frames = [make_image(text) for text in ("     0", "     1", "      ", "    12")]
        capture = Mock()
        capture.isOpened.return_value = True
        capture.get.return_value = 1000.0
        capture.read.side_effect = [(True, frame) for frame in frames] + [(False, None)]
        output = io.StringIO()
        with (
            patch.multiple(reader, SOURCE="test.avi", REFLECTION="none"),
            patch.object(reader.cv2, "VideoCapture", return_value=capture),
            redirect_stdout(output),
        ):
            reader.main()
        values = [json.loads(line)["value"] for line in output.getvalue().splitlines()]
        self.assertEqual(values, [0.0, 0.001, None, 0.012])

    def test_video_mirror_directions_read_the_same_value_without_flipping_frame(self):
        image = make_image("123456")
        x, y = reader.SEGMENT_POINTS[0][1]
        image[y - 1 : y + 2, x - 1 : x + 2] = 255
        image[y, x] = (12, 17, 230)
        reflections = {
            "none": image,
            "horizontal": np.flip(image, axis=1),
            "vertical": np.flip(image, axis=0),
            "both": np.flip(image, axis=(0, 1)),
        }
        for reflection, frame in reflections.items():
            with self.subTest(reflection=reflection):
                capture = Mock()
                capture.isOpened.return_value = True
                capture.get.return_value = 1000.0
                capture.read.side_effect = [(True, frame.copy()), (False, None)]
                output = io.StringIO()
                with (
                    patch.multiple(
                        reader,
                        SOURCE="test.avi",
                        REFLECTION=reflection,
                        SAMPLE_RADIUS=0,
                        STABLE_FRAMES=1,
                    ),
                    patch.object(reader.cv2, "VideoCapture", return_value=capture),
                    patch.object(reader.cv2, "flip") as flip,
                    redirect_stdout(output),
                ):
                    reader.main()
                self.assertEqual(json.loads(output.getvalue())["value"], 123.456)
                flip.assert_not_called()


if __name__ == "__main__":
    unittest.main()
