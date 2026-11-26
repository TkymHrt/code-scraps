import importlib.util
import io
import json
import shutil
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import cv2
import numpy as np

FOLDER = Path(__file__).resolve().parents[1] / "sandbox" / "ocr-comparison"


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, FOLDER / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


calibrate = load_script("calibrate")
snapshot = load_script("check_snapshot")

SEGMENTS = {
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


def calibration_settings(reflection="none"):
    settings = {
        "frame_size_px": [640, 320],
        "reflection": reflection,
    }
    for side, top in (("op", 0), ("dr", 160)):
        points = []
        for digit in range(6):
            x = 20 + digit * 100
            points.append(
                [
                    [x + 20, top + 25],
                    [x + 35, top + 50],
                    [x + 35, top + 100],
                    [x + 20, top + 125],
                    [x + 5, top + 100],
                    [x + 5, top + 50],
                    [x + 20, top + 75],
                ]
            )
        points = np.array(points)
        if reflection in ("horizontal", "both"):
            points[:, :, 0] = 639 - points[:, :, 0]
        if reflection in ("vertical", "both"):
            points[:, :, 1] = 319 - points[:, :, 1]
        settings[f"{side}_points_px"] = points.tolist()
    return settings


def make_raw(op, dr, red_only=False):
    raw = np.full((320, 640), 20, dtype=np.uint8)
    settings = calibration_settings()
    for side, display in (("op", op), ("dr", dr)):
        for digit, points in zip(display, settings[f"{side}_points_px"], strict=True):
            for segment, (x, y) in zip("abcdefg", points, strict=True):
                if segment in SEGMENTS[digit]:
                    raw[y - 5 : y + 6, x - 5 : x + 6] = 240
    if red_only:
        raw[::2, :] = 10
        raw[:, ::2] = 10
    return raw


class TwoMeterTests(unittest.TestCase):
    def test_snapshot_runs_alone_with_raw_frame_and_optional_calibration(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "check_snapshot.py"
            shutil.copy(FOLDER / script.name, script)
            capture = root / "captures/run-01"
            capture.mkdir(parents=True)
            raw = make_raw("888888", "888888", red_only=True)
            np.save(capture / "frame-000000.npy", raw)
            subprocess.run(
                [sys.executable, "-I", script], check=True, capture_output=True
            )
            result = root / "results/snapshot-01"
            gray = cv2.cvtColor(raw, cv2.COLOR_BayerBGGR2GRAY)
            for name, expected in (("gray", gray), ("binary", (gray > 50) * 255)):
                pixels = np.frombuffer((result / f"{name}.png").read_bytes(), np.uint8)
                np.testing.assert_array_equal(
                    cv2.imdecode(pixels, cv2.IMREAD_GRAYSCALE), expected
                )
            calibration_file = root / "calibration.json"
            settings = calibration_settings("both")
            points = np.array(settings["op_points_px"] + settings["dr_points_px"])
            with (
                patch.multiple(
                    calibrate,
                    SOURCE=result / "binary.png",
                    OUTPUT=calibration_file,
                    REFLECTION="both",
                ),
                patch.object(
                    calibrate,
                    "select_points",
                    return_value=points.reshape(84, 2).tolist(),
                ),
                redirect_stdout(io.StringIO()),
            ):
                calibrate.main()
            check = root / "captures/check"
            check.mkdir()
            np.save(
                check / "frame-000000.npy", make_raw("  0123", "456789", red_only=True)
            )
            script.write_text(
                script.read_text(encoding="utf-8")
                .replace(
                    "CALIBRATION = None", 'CALIBRATION = FOLDER / "calibration.json"'
                )
                .replace("results/snapshot-01", "results/check")
                .replace("captures/run-01", "captures/check"),
                encoding="utf-8",
            )
            run = subprocess.run(
                [sys.executable, "-I", script],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(run.stdout.splitlines()[-2:], ["OP 123", "DR 456789"])

    def test_invalid_display_and_single_pixel_sampling(self):
        settings = calibration_settings()
        binary = (make_raw("12 456", "     0") > 50).astype(np.uint8) * 255
        self.assertIsNone(snapshot.read_display(binary, settings["op_points_px"], "op"))
        self.assertEqual(
            snapshot.read_display(binary, settings["dr_points_px"], "dr"), 0
        )
        x, y = settings["dr_points_px"][-1][0]
        binary[y, x] = 0
        self.assertIsNone(snapshot.read_display(binary, settings["dr_points_px"], "dr"))

    def test_invalid_raw_and_calibration_are_rejected_before_saving(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            frame, calibration, output = (
                root / "input.npy",
                root / "cal.json",
                root / "out",
            )
            with patch.multiple(
                snapshot, FRAME=frame, CALIBRATION=calibration, OUTPUT_DIR=output
            ):
                np.save(frame, make_raw("123456", "654321").astype(np.uint16))
                with self.assertRaisesRegex(ValueError, "2次元uint8"):
                    snapshot.main()

                np.save(frame, make_raw("123456", "654321"))
                for key, value, message in (
                    ("frame_size_px", [641, 320], "画像サイズ"),
                    ("op_points_px", [[[1, 1]] * 7], "42点"),
                ):
                    settings = calibration_settings()
                    settings[key] = value
                    calibration.write_text(json.dumps(settings), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, message):
                        snapshot.main()

                settings = calibration_settings()
                settings["dr_points_px"][0][0] = [-1, 0]
                calibration.write_text(json.dumps(settings), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "dr: 校正点が画像外"):
                    snapshot.main()
                self.assertFalse(output.exists())


class TwoMeterCalibrationTests(unittest.TestCase):
    def points(self):
        settings = calibration_settings()
        return (
            np.array(settings["op_points_px"] + settings["dr_points_px"])
            .reshape(84, 2)
            .tolist()
        )

    def clicks(self, points):
        return [
            event
            for x, y in points
            for event in (
                (cv2.EVENT_LBUTTONDOWN, x, y, cv2.EVENT_FLAG_LBUTTON),
                (cv2.EVENT_LBUTTONUP, x, y, 0),
            )
        ]

    def run_selection(self, actions, visible=1):
        actions = iter(actions)
        callback = Mock()
        title = Mock()

        def wait(_delay):
            action = next(actions)
            if isinstance(action, tuple):
                callback.call_args.args[1](*action, None)
                return -1
            return action

        with patch.multiple(
            calibrate.cv2,
            namedWindow=Mock(),
            destroyAllWindows=Mock(),
            setMouseCallback=callback,
            setWindowTitle=title,
            imshow=Mock(),
            waitKey=Mock(side_effect=wait),
            getWindowProperty=Mock(return_value=visible),
        ):
            with redirect_stderr(io.StringIO()):
                actual = calibrate.select_points(
                    np.zeros((320, 640, 3), dtype=np.uint8)
                )
        return actual, [call.args[1] for call in title.call_args_list]

    def test_clicks_label_sides_undo_boundary_and_keep_native_coordinates(self):
        points = self.points()
        actual, titles = self.run_selection(
            [
                *self.clicks([(-1, 0)]),
                *self.clicks(points[:42]),
                ord("b"),
                *self.clicks(points[41:]),
                13,
            ]
        )
        self.assertEqual(actual, points)
        self.assertTrue(any("DR digit 1/6 top" in title for title in titles))
        self.assertIn("84/84", titles[-1])

    def test_qt_drag_and_wheel_do_not_select_points(self):
        points = self.points()
        actual, _ = self.run_selection(
            [
                (cv2.EVENT_LBUTTONDOWN, 40, 25, cv2.EVENT_FLAG_LBUTTON),
                (cv2.EVENT_MOUSEMOVE, 40, 25, cv2.EVENT_FLAG_LBUTTON),
                (cv2.EVENT_LBUTTONUP, 40, 25, 0),
                (cv2.EVENT_MOUSEWHEEL, 120, 80, 120 << 16),
                *self.clicks(points),
                13,
            ]
        )
        self.assertEqual(actual, points)

    def test_lost_release_and_wheel_during_press_do_not_select_points(self):
        points = self.points()
        actual, _ = self.run_selection(
            [
                (cv2.EVENT_LBUTTONDOWN, 40, 25, cv2.EVENT_FLAG_LBUTTON),
                (cv2.EVENT_MOUSEMOVE, 50, 30, 0),
                (cv2.EVENT_LBUTTONUP, 50, 30, 0),
                (cv2.EVENT_LBUTTONDOWN, 40, 25, cv2.EVENT_FLAG_LBUTTON),
                (cv2.EVENT_MOUSEWHEEL, 40, 25, 120 << 16),
                (cv2.EVENT_LBUTTONUP, 40, 25, 0),
                *self.clicks(points),
                13,
            ]
        )
        self.assertEqual(actual, points)

    def test_binary_input_saves_both_sides_and_cancel_does_not_save(self):
        settings = calibration_settings()
        points = self.points()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "校正画像.png"
            gray = make_raw("888888", "888888")
            binary = cv2.threshold(gray, 50, 255, cv2.THRESH_BINARY)[1]
            source.write_bytes(cv2.imencode(".png", gray)[1].tobytes())
            output = root / "calibration.json"
            with patch.multiple(
                calibrate,
                SOURCE=source,
                OUTPUT=output,
                REFLECTION="horizontal",
            ):
                with self.assertRaisesRegex(ValueError, "二値画像"):
                    calibrate.main()
                source.write_bytes(cv2.imencode(".png", binary)[1].tobytes())
                with (
                    patch.object(calibrate, "select_points", return_value=None),
                    redirect_stderr(io.StringIO()),
                ):
                    calibrate.main()
                self.assertFalse(output.exists())
                with (
                    patch.object(
                        calibrate, "select_points", return_value=points
                    ) as select,
                    redirect_stdout(io.StringIO()),
                ):
                    calibrate.main()
                np.testing.assert_array_equal(
                    select.call_args.args[0],
                    cv2.flip(cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR), 1),
                )
                saved = json.loads(output.read_text(encoding="utf-8"))
                self.assertEqual(saved["op_points_px"], settings["op_points_px"])
                self.assertEqual(saved["dr_points_px"], settings["dr_points_px"])
                self.assertEqual(saved["reflection"], "horizontal")
                with self.assertRaises(FileExistsError):
                    calibrate.main()
                self.assertEqual(json.loads(output.read_text(encoding="utf-8")), saved)

    def test_cancel_and_closed_window_return_no_partial_calibration(self):
        for key, visible in ((ord("q"), 1), (27, 1), (-1, 0)):
            actual, _ = self.run_selection([key], visible)
            self.assertIsNone(actual)


if __name__ == "__main__":
    unittest.main()
