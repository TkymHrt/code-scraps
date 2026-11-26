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
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

FOLDER = Path(__file__).resolve().parents[1] / "sandbox" / "ocr-comparison"


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, FOLDER / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


capture = load_script("capture_bayer")
bgr_reader = load_script("read_bgr_fraction")
bayer_reader = load_script("read_bayer_red")

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
    points = []
    for digit in range(6):
        x = 20 + digit * 100
        points.append(
            [
                [x + 20, 25],
                [x + 35, 50],
                [x + 35, 100],
                [x + 20, 125],
                [x + 5, 100],
                [x + 5, 50],
                [x + 20, 75],
            ]
        )
    if reflection in ("horizontal", "both"):
        for digit in points:
            for point in digit:
                point[0] = 640 - 1 - point[0]
    if reflection in ("vertical", "both"):
        for digit in points:
            for point in digit:
                point[1] = 160 - 1 - point[1]
    return {
        "FRAME_SIZE": [640, 160],
        "REFLECTION": reflection,
        "SAMPLE_RADIUS": 2,
        "SAMPLE_LENGTH_RADIUS": None,
        "SEGMENT_POINTS": points,
    }


def make_raw(display):
    raw = np.full((160, 640), 8, dtype=np.uint8)
    points = calibration_settings()["SEGMENT_POINTS"]
    for digit, digit_points in zip(display, points, strict=True):
        for name, (x, y) in zip("abcdefg", digit_points, strict=True):
            if name in SEGMENTS[digit]:
                rows, columns = np.indices((11, 11))
                rows += y - 5
                columns += x - 5
                raw[rows, columns] = 17
                red = (rows % 2 == 1) & (columns % 2 == 1)
                blue = (rows % 2 == 0) & (columns % 2 == 0)
                raw[rows[red], columns[red]] = 230
                raw[rows[blue], columns[blue]] = 12
    return raw


def write_recording(folder, displays, reflection="none"):
    session = {
        "pixel_format": "BayerBG8",
        "frame_size": [640, 160],
        "offset": [4, 2],
        "reverse_x": False,
        "reverse_y": False,
    }
    (folder / "session.json").write_text(json.dumps(session), encoding="utf-8")
    calibration_file = folder / "calibration.json"
    calibration_file.write_text(
        json.dumps(calibration_settings(reflection)), encoding="utf-8-sig"
    )
    records = []
    for index, display in enumerate(displays):
        filename = f"frame-{index:06d}.npy"
        np.save(folder / filename, make_raw(display), allow_pickle=False)
        records.append(
            {
                "file": filename,
                "block_id": index + 10,
                "received_at": "2026-11-11T00:00:00.000+00:00",
                "timestamp_ticks": index * 10000,
            }
        )
    (folder / "frames.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )
    return calibration_file


class ComparisonTests(unittest.TestCase):
    def test_standalone_readers_agree_on_changing_and_zero_suppressed_values(self):
        displays = [
            "     0",
            "     1",
            "    12",
            "   123",
            "  1234",
            "123456",
            "      ",
            "12 456",
            "12345 ",
        ]
        expected = [0, 1, 12, 123, 1234, 123456, None, None, None]
        with TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "captures/run-01"
            folder.mkdir(parents=True)
            write_recording(folder, displays).rename(root / "calibration-single.json")
            for name in ("read_bgr_fraction", "read_bayer_red"):
                with self.subTest(method=name):
                    script = shutil.copy(FOLDER / f"{name}.py", root)
                    run = subprocess.run(
                        [sys.executable, "-B", script],
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    results = [json.loads(line) for line in run.stdout.splitlines()]
                    self.assertEqual([row["raw_value"] for row in results], expected)
                    self.assertEqual(results[2]["value"], 0.012)
                    for row in results:
                        self.assertEqual(len(row["segment_scores"]), 42)
                        self.assertEqual(
                            row["received_at"], "2026-11-11T00:00:00.000+00:00"
                        )
                    config, summary = [
                        json.loads(line) for line in run.stderr.splitlines()
                    ]
                    self.assertTrue(all(n > 0 for n in config["samples_per_segment"]))
                    self.assertEqual(summary["readable"], 6)
                    self.assertEqual(summary["unreadable"], 3)

    def test_all_digits_and_reflections_preserve_native_bayer_red_positions(self):
        for reflection in ("none", "horizontal", "vertical", "both"):
            with TemporaryDirectory() as directory:
                folder = Path(directory)
                displays = [digit * 6 for digit in "0123456789"]
                calibration_file = write_recording(folder, displays, reflection)
                for reader in (bgr_reader, bayer_reader):
                    with self.subTest(reflection=reflection, method=reader.__name__):
                        output = io.StringIO()
                        with redirect_stdout(output), redirect_stderr(io.StringIO()):
                            reader.main(folder, calibration_file)
                        results = [
                            json.loads(line) for line in output.getvalue().splitlines()
                        ]
                        self.assertEqual(
                            [r["raw_value"] for r in results], list(map(int, displays))
                        )
                        if reader is bayer_reader:
                            self.assertEqual(results[-1]["segment_scores"][0], 230)
                            self.assertTrue(all(r["convert_ms"] == 0 for r in results))

    def test_bgr_channel_order_and_white_reflection_guard(self):
        raw = make_raw("888888")
        image = cv2.cvtColor(raw, cv2.COLOR_BayerBGGR2BGR)
        np.testing.assert_array_equal(image[25, 40], [12, 17, 230])
        calibration = calibration_settings()
        coordinates = bgr_reader.prepare_samples(calibration, [640, 160])
        raw[20:31, 35:46] = 230
        image = cv2.cvtColor(raw, cv2.COLOR_BayerBGGR2BGR)
        self.assertEqual(bgr_reader.recognize_display(image, coordinates)[2], "white")

    def test_ambiguous_scores_and_invalid_patterns_stay_unreadable(self):
        for reader, off, on in ((bgr_reader, 0.15, 0.65), (bayer_reader, 30, 70)):
            scores = np.full(42, on)
            scores[0] = (off + on) / 2
            self.assertEqual(reader.decode_segments(scores, off, on)[2], "ambiguous")
            scores[:7] = off
            scores[0] = on
            self.assertEqual(
                reader.decode_segments(scores, off, on)[2], "invalid_pattern"
            )

    def test_bad_calibration_missing_red_pixels_and_corrupt_arrays_fail(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            calibration_file = write_recording(folder, ["123456"])
            settings = calibration_settings()
            settings["SAMPLE_RADIUS"] = 0
            settings["SEGMENT_POINTS"][0][0] = [40, 24]
            calibration_file.write_text(json.dumps(settings), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "赤画素なし"):
                bayer_reader.main(folder, calibration_file)
            settings["FRAME_SIZE"] = [641, 160]
            calibration_file.write_text(json.dumps(settings), encoding="utf-8")
            for reader in (bgr_reader, bayer_reader):
                with self.assertRaisesRegex(ValueError, "FRAME_SIZE"):
                    reader.main(folder, calibration_file)
            calibration_file = write_recording(folder, ["123456"])
            np.save(folder / "frame-000000.npy", np.zeros((160, 640), dtype=np.uint16))
            for reader in (bgr_reader, bayer_reader):
                with (
                    redirect_stderr(io.StringIO()),
                    self.assertRaisesRegex(ValueError, "画像不正"),
                ):
                    reader.main(folder, calibration_file)


class CaptureTests(unittest.TestCase):
    def make_sdk(self, image_ids=(5, 5, 7)):
        sdk = MagicMock()
        sdk.CamApiStatus = SimpleNamespace(Success=0)
        sdk.CameraType = SimpleNamespace(Gev=2)
        sdk.CameraPixelFormat = SimpleNamespace(BayerBG8=object())
        sdk.OutputImageType = SimpleNamespace(Raw=object())
        sdk.CameraBalanceRatioSelector = SimpleNamespace(Red=0, Blue=1)
        system = sdk.get_camera_system.return_value
        system.get_num_of_cameras.return_value = 1
        system.get_camera_information.return_value = SimpleNamespace(
            cam_model="BG505LMCF", cam_serial_number="test", cam_version="test"
        )
        system.wait_for_signal.return_value = 0
        device = system.create_device_object.return_value
        control = device.cam_control
        control.set_trigger_mode.return_value = 0
        control.set_pixel_format.return_value = 0
        control.get_exposure_time_control.return_value = (
            0,
            SimpleNamespace(name="Manual"),
        )
        control.get_gain_auto.return_value = (0, SimpleNamespace(name="Off"))
        control.get_balance_white_auto.return_value = (0, SimpleNamespace(name="Off"))
        control.get_pixel_format.return_value = (0, SimpleNamespace(name="BayerBG8"))
        control.get_exposure_time.return_value = (0, 5000.0)
        control.get_gain.return_value = (0, 0.0)
        control.get_gamma.return_value = (0, 1.0)
        control.get_black_level.return_value = (0, 0.0)
        control.get_balance_ratio.return_value = (0, 1.0)
        control.get_reverse_x.return_value = (0, False)
        control.get_reverse_y.return_value = (0, False)
        integers = {
            "Width": 640,
            "Height": 160,
            "OffsetX": 4,
            "OffsetY": 2,
            "GevTimestampTickFrequency": 1000000,
        }
        device.genapi.get_int_value.side_effect = lambda name: (0, integers[name])
        device.genapi.get_enum_str_value.return_value = (0, "Full")
        images = []
        for image_id in image_ids:
            raw = make_raw("123456")
            image = MagicMock(
                status=0,
                image_id=image_id,
                block_id=image_id,
                timestamp=image_id * 10000,
            )
            image.pixel_format = SimpleNamespace(name="BayerBG8")
            image.get_ndarray.return_value = raw
            image.__enter__.return_value = image
            image.__exit__.side_effect = lambda *args, raw=raw: raw.fill(0)
            images.append(image)
        stream = device.cam_stream
        stream.get_current_buffered_image.side_effect = images
        return sdk, system, device, images

    def test_capture_copies_before_release_skips_duplicates_and_replays_saved_frames(
        self,
    ):
        sdk, system, device, images = self.make_sdk()
        with TemporaryDirectory() as directory:
            folder = Path(directory) / "撮影"
            with (
                patch.dict(sys.modules, {"pytelicam": sdk}),
                redirect_stderr(io.StringIO()),
            ):
                capture.main(2, folder)
            session = json.loads((folder / "session.json").read_text(encoding="utf-8"))
            self.assertEqual(session["timestamp_tick_frequency_hz"], 1000000)
            self.assertEqual(session["camera_settings"]["exposure_us"], 5000)
            records = [
                json.loads(line)
                for line in (folder / "frames.jsonl").read_text().splitlines()
            ]
            self.assertEqual([r["block_id"] for r in records], [5, 7])
            self.assertEqual([r["block_gap"] for r in records], [None, 1])
            self.assertEqual(np.load(folder / records[0]["file"])[51, 55], 230)
            self.assertTrue((folder / "preview.png").is_file())
            calibration_file = folder / "calibration.json"
            calibration_file.write_text(
                json.dumps(calibration_settings()), encoding="utf-8"
            )
            for reader in (bgr_reader, bayer_reader):
                output = io.StringIO()
                with redirect_stdout(output), redirect_stderr(io.StringIO()):
                    reader.main(folder, calibration_file)
                self.assertEqual(
                    [
                        json.loads(line)["value"]
                        for line in output.getvalue().splitlines()
                    ],
                    [123.456, 123.456],
                )
        self.assertEqual(system.wait_for_signal.call_count, 3)
        images[1].get_ndarray.assert_not_called()
        for image in images:
            image.__exit__.assert_called_once()
        device.cam_stream.stop.assert_called_once()
        device.cam_stream.close.assert_called_once()
        device.close.assert_called_once()
        system.close_signal.assert_called_once()
        system.terminate.assert_called_once()

    def test_save_failure_releases_camera_and_does_not_publish_incomplete_frame(self):
        sdk, system, device, images = self.make_sdk((5,))
        with TemporaryDirectory() as directory:
            folder = Path(directory) / "failed"
            with (
                patch.dict(sys.modules, {"pytelicam": sdk}),
                patch.object(capture.np, "save", side_effect=OSError("disk full")),
                redirect_stderr(io.StringIO()),
                self.assertRaisesRegex(OSError, "disk full"),
            ):
                capture.main(1, folder)
            self.assertEqual((folder / "frames.jsonl").read_text(), "")
        images[0].__exit__.assert_called_once()
        device.cam_stream.stop.assert_called_once()
        device.cam_stream.close.assert_called_once()
        device.close.assert_called_once()
        system.terminate.assert_called_once()

    def test_camera_reflection_is_rejected_before_capture(self):
        sdk, system, device, _images = self.make_sdk()
        device.cam_control.get_reverse_x.return_value = (0, True)
        with TemporaryDirectory() as directory:
            folder = Path(directory) / "not-created"
            with (
                patch.dict(sys.modules, {"pytelicam": sdk}),
                self.assertRaises(ValueError),
            ):
                capture.main(1, folder)
            self.assertFalse(folder.exists())
        device.cam_stream.start.assert_not_called()
        device.close.assert_called_once()
        system.terminate.assert_called_once()

    def test_existing_output_folder_is_not_overwritten(self):
        with TemporaryDirectory() as directory:
            with self.assertRaises(FileExistsError):
                capture.main(1, Path(directory))


if __name__ == "__main__":
    unittest.main()
