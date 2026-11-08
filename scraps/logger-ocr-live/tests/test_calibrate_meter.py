"""この題材だけで校正し、読み取りへ設定を渡せることを模擬GUIで確認する。"""

import ast
import importlib.util
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import cv2
import numpy as np

TOPIC = Path(__file__).resolve().parents[1]
reader_spec = importlib.util.spec_from_file_location(
    "logger_reader_for_calibration", TOPIC / "read_meter.py"
)
read_meter = importlib.util.module_from_spec(reader_spec)
reader_spec.loader.exec_module(read_meter)

calibration_spec = importlib.util.spec_from_file_location(
    "logger_calibration_under_test", TOPIC / "calibrate_meter.py"
)
calibrate_meter = importlib.util.module_from_spec(calibration_spec)
calibration_spec.loader.exec_module(calibrate_meter)


class CalibrationTests(unittest.TestCase):
    def test_png_with_japanese_path_is_read_once_for_calibration(self):
        image = np.zeros((20, 40, 3), dtype=np.uint8)
        image[:, :10] = (10, 20, 230)
        encoded, data = cv2.imencode(".png", image)
        self.assertTrue(encoded)
        with TemporaryDirectory() as folder:
            path = Path(folder) / "校正画像.png"
            path.write_bytes(data.tobytes())
            with (
                patch.multiple(calibrate_meter, SOURCE=path, REFLECTION="horizontal"),
                patch.multiple(
                    cv2,
                    namedWindow=Mock(),
                    resizeWindow=Mock(),
                    setWindowTitle=Mock(),
                    waitKey=Mock(side_effect=[ord("n"), ord("q")]),
                    getWindowProperty=Mock(return_value=1),
                    destroyAllWindows=Mock(),
                ),
                patch.object(cv2, "VideoCapture") as capture,
                patch.object(cv2, "flip", wraps=cv2.flip) as flip,
                patch.object(cv2, "imshow") as show,
            ):
                calibrate_meter.main()
        capture.assert_not_called()
        flip.assert_called_once()
        self.assertEqual(show.call_count, 2)
        np.testing.assert_array_equal(show.call_args.args[1], image[:, ::-1])

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
            frame = np.zeros((360, 960, 3), dtype=np.uint8)
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

        settings = {}
        for line in output.getvalue().splitlines():
            name, literal = line.split("=", 1)
            settings[name.strip()] = ast.literal_eval(literal.strip())
        return settings, mouse_events

    def test_printed_calibration_can_be_copied_into_reader(self):
        settings, mouse_events = self.run_calibration()
        self.assertEqual(
            set(settings),
            {
                "FRAME_SIZE",
                "REFLECTION",
                "SAMPLE_RADIUS",
                "SAMPLE_LENGTH_RADIUS",
                "SEGMENT_POINTS",
            },
        )
        self.assertEqual(settings["FRAME_SIZE"], [960, 360])
        self.assertEqual(settings["SAMPLE_RADIUS"], 1)
        self.assertIsNone(settings["SAMPLE_LENGTH_RADIUS"])
        self.assertEqual(settings["SEGMENT_POINTS"], read_meter.SEGMENT_POINTS)
        self.assertEqual(len(mouse_events), 42)
        image = np.zeros((360, 960, 3), dtype=np.uint8)
        for points in settings["SEGMENT_POINTS"]:
            for x, y in points:
                image[y - 1 : y + 2, x - 1 : x + 2] = (12, 17, 230)
        with patch.multiple(read_meter, **settings):
            sample_coordinates = read_meter.prepare_samples("none")
            value = read_meter.recognize_display(image, sample_coordinates)
        self.assertEqual(value, 888.888)

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

    def test_long_radius_checks_bounds_along_horizontal_and_vertical_segments(self):
        points = self.calibration_points()
        actions = [ord(" "), (1, 45), points[0], (400, 1)] + points[1:] + [13]
        with patch.object(calibrate_meter, "SAMPLE_LENGTH_RADIUS", 4):
            settings, mouse_events = self.run_calibration(actions)
        self.assertEqual(settings["SAMPLE_LENGTH_RADIUS"], 4)
        self.assertEqual(settings["SEGMENT_POINTS"], read_meter.SEGMENT_POINTS)
        self.assertEqual(len(mouse_events), 44)

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


if __name__ == "__main__":
    unittest.main()
