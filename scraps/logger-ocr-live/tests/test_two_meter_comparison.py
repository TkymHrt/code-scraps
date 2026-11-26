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
compare = load_script("compare")

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
        "sample_radius_px": 1,
        "sample_length_radius_px": 3,
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


def write_recording(folder, displays, reflection="none", red_only=False):
    folder.mkdir(parents=True)
    (folder / "session.json").write_text(
        json.dumps(
            {
                "frame_size": [640, 320],
                "pixel_format": "BayerBG8",
                "reverse_x": False,
                "reverse_y": False,
                "offset": [0, 0],
            }
        ),
        encoding="utf-8",
    )
    records = []
    for index, (op, dr) in enumerate(displays):
        name = f"frame-{index:06d}.npy"
        np.save(folder / name, make_raw(op, dr, red_only), allow_pickle=False)
        records.append(
            {"file": name, "block_id": index + 10, "timestamp_ticks": index * 1000}
        )
    (folder / "frames.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in records), encoding="utf-8"
    )
    calibration = folder.parent / "calibration.json"
    calibration.write_text(
        json.dumps(calibration_settings(reflection)), encoding="utf-8"
    )
    return calibration


class TwoMeterTests(unittest.TestCase):
    def run_comparison(self, source, calibration, output, thresholds=None):
        with patch.multiple(
            compare, SOURCE=source, CALIBRATION=calibration, OUTPUT_DIR=output
        ):
            with patch.object(compare, "THRESHOLDS", thresholds or compare.THRESHOLDS):
                with redirect_stdout(io.StringIO()):
                    compare.main()
        return [
            json.loads(line)
            for line in (output / "results.jsonl").read_text().splitlines()
        ]

    def test_all_digits_two_sides_and_reflections_with_native_red_sampling(self):
        displays = [(digit * 6, str(9 - int(digit)) * 6) for digit in "0123456789"]
        for reflection in ("none", "horizontal", "vertical", "both"):
            with self.subTest(reflection=reflection), TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "capture"
                calibration = write_recording(
                    source, displays, reflection, red_only=True
                )
                thresholds = {
                    side: dict(values, binary=50)
                    for side, values in compare.THRESHOLDS.items()
                }
                results = self.run_comparison(
                    source, calibration, root / "result", thresholds
                )
                self.assertEqual(len(results), 60)
                for row in results:
                    op, dr = displays[row["block_id"] - 10]
                    expected = int(op if row["side"] == "op" else dr)
                    self.assertEqual(row["raw_value"], expected, row)
                    self.assertEqual(row["value"], expected / 1000)
                    self.assertEqual(len(row["segment_scores"]), 42)
                    if row["method"] == "bayer_red":
                        self.assertTrue(set(row["segment_scores"]) <= {20.0, 240.0})

    def test_unreadable_side_does_not_discard_other_side_or_hold_old_value(self):
        displays = [
            ("123456", "     0"),
            ("      ", "    12"),
            ("12 456", "654321"),
            ("12345 ", "999999"),
        ]
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "capture"
            calibration = write_recording(source, displays)
            results = self.run_comparison(source, calibration, root / "result")
            for row in results:
                index = row["block_id"] - 10
                if row["side"] == "op" and index > 0:
                    self.assertIsNone(row["raw_value"])
                    self.assertEqual(row["reason"], "invalid_display")
                else:
                    self.assertEqual(
                        row["raw_value"], int(displays[index][row["side"] == "dr"])
                    )
            summary = json.loads((root / "result/summary.json").read_text())
            self.assertEqual(summary["counts"]["op/binary"]["invalid_display"], 3)

    def test_image_decoding_does_not_depend_on_extension_and_saves_masks(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            image = cv2.cvtColor(make_raw("123456", "654321"), cv2.COLOR_GRAY2BGR)
            settings = calibration_settings()
            calibration = root / "calibration.json"
            calibration.write_text(json.dumps(settings), encoding="utf-8")
            for extension in (".jpg", ".bmp", ".png"):
                source = root / f"画像{extension}.data"
                source.write_bytes(cv2.imencode(extension, image)[1].tobytes())
                output = root / extension[1:]
                results = self.run_comparison(source, calibration, output)
                self.assertEqual(len(results), 4)
                for row in results:
                    self.assertEqual(
                        row["raw_value"], 123456 if row["side"] == "op" else 654321
                    )
                saved = json.loads(
                    (output / "settings.json").read_text(encoding="utf-8")
                )
                for side in ("op", "dr"):
                    left, top, right, bottom = saved["preview_bounds_px"][side]
                    mask = compare.read_image(output / f"{side}-adaptive.png")[:, :, 0]
                    self.assertEqual(mask.shape, (bottom - top, right - left))
                    full = cv2.adaptiveThreshold(
                        cv2.cvtColor(compare.read_image(source), cv2.COLOR_BGR2GRAY),
                        255,
                        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                        cv2.THRESH_BINARY,
                        25,
                        0,
                    )
                    rows, columns = compare.prepare_samples(settings, side)
                    np.testing.assert_array_equal(
                        mask[rows - top, columns - left], full[rows, columns]
                    )

    def test_snapshot_runs_alone_with_raw_frame_and_optional_calibration(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "check_snapshot.py"
            shutil.copy(FOLDER / script.name, script)
            capture = root / "captures/run-01"
            capture.mkdir(parents=True)
            raw = make_raw("  0123", "456789", red_only=True)
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
            (root / "calibration.json").write_text(
                json.dumps(calibration_settings("both")), encoding="utf-8"
            )
            script.write_text(
                script.read_text(encoding="utf-8")
                .replace(
                    "CALIBRATION = None", 'CALIBRATION = FOLDER / "calibration.json"'
                )
                .replace("results/snapshot-01", "results/check"),
                encoding="utf-8",
            )
            run = subprocess.run(
                [sys.executable, "-I", script],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("OP '  0123' (ok)", run.stdout)
            self.assertIn("DR '456789' (ok)", run.stdout)

    def test_standalone_comparison_needs_no_project_imports_or_sdk(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copyfile(FOLDER / "compare.py", root / "compare.py")
            source = root / "captures/run-01"
            calibration = write_recording(source, [("123456", "654321")])
            shutil.move(calibration, root / "calibration.json")
            run = subprocess.run(
                [sys.executable, "-B", str(root / "compare.py")],
                cwd=root,
                capture_output=True,
                check=True,
            )
            self.assertEqual(run.returncode, 0)
            results = [
                json.loads(line)
                for line in (root / "results/run-01/results.jsonl")
                .read_text()
                .splitlines()
            ]
            self.assertEqual(
                [row["raw_value"] for row in results], [123456] * 3 + [654321] * 3
            )

    def test_ambiguity_and_invalid_pattern_are_not_guessed(self):
        scores = np.ones(42)
        scores[0] = 0.5
        self.assertEqual(
            compare.decode_segments(scores, 0.15, 0.65)["reason"], "ambiguous"
        )
        scores[:7] = 0
        scores[0] = 1
        self.assertEqual(
            compare.decode_segments(scores, 0.15, 0.65)["reason"], "invalid_pattern"
        )

    def test_frame_mismatch_bad_coordinates_and_existing_output_fail(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "capture"
            calibration = write_recording(source, [("123456", "654321")])
            settings = calibration_settings()
            settings["frame_size_px"] = [640, 321]
            calibration.write_text(json.dumps(settings), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "frame_size_px"):
                self.run_comparison(source, calibration, root / "mismatch")
            self.assertFalse((root / "mismatch").exists())
            settings = calibration_settings()
            settings["op_points_px"][0][0] = [0, 0]
            with self.assertRaisesRegex(ValueError, "画像外"):
                compare.prepare_samples(settings, "op")
            with self.assertRaisesRegex(FileExistsError, "既に存在"):
                self.run_comparison(source, calibration, source)
            self.assertTrue((source / "session.json").exists())


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
                    np.zeros((320, 640, 3), dtype=np.uint8), 1, 3
                )
        return actual, [call.args[1] for call in title.call_args_list]

    def test_clicks_label_sides_undo_boundary_and_keep_native_coordinates(self):
        points = self.points()
        actual, titles = self.run_selection(
            [
                *self.clicks([(0, 0)]),
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

    def test_general_image_input_saves_both_sides_and_cancel_does_not_save(self):
        settings = calibration_settings()
        points = self.points()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "校正画像.jpg"
            image = cv2.cvtColor(make_raw("123456", "654321"), cv2.COLOR_GRAY2BGR)
            source.write_bytes(cv2.imencode(".jpg", image)[1].tobytes())
            output = root / "calibration.json"
            with patch.multiple(
                calibrate,
                SOURCE=source,
                OUTPUT=output,
                REFLECTION="horizontal",
                SAMPLE_RADIUS=1,
                SAMPLE_LENGTH_RADIUS=3,
            ):
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
                    select.call_args.args[0], cv2.flip(compare.read_image(source), 1)
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
