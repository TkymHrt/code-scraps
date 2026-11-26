import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

FOLDER = Path(__file__).resolve().parents[1] / "sandbox" / "ocr-comparison"


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, FOLDER / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


capture = load_script("capture_bayer")


class CaptureTests(unittest.TestCase):
    def make_sdk(self):
        sdk = MagicMock()
        sdk.CamApiStatus = SimpleNamespace(Success=0)
        sdk.CameraType = SimpleNamespace(Gev=2)
        sdk.CameraPixelFormat = SimpleNamespace(BayerBG8=object())
        sdk.OutputImageType = SimpleNamespace(Raw=object())
        system = sdk.get_camera_system.return_value
        system.get_num_of_cameras.return_value = 1
        system.wait_for_signal.return_value = 0
        device = system.create_device_object.return_value
        control = device.cam_control
        control.set_trigger_mode.return_value = 0
        control.set_pixel_format.return_value = 0
        control.get_reverse_x.return_value = (0, False)
        control.get_reverse_y.return_value = (0, False)
        features = {"Width": 8, "Height": 6, "OffsetX": 4, "OffsetY": 2}
        device.genapi.get_int_value.side_effect = lambda name: (0, features[name])
        raw = np.arange(48, dtype=np.uint8).reshape(6, 8)
        image = MagicMock(status=0, pixel_format=SimpleNamespace(name="BayerBG8"))
        image.get_ndarray.return_value = raw
        image.__enter__.return_value = image
        image.__exit__.side_effect = lambda *_: raw.fill(0)
        device.cam_stream.get_current_buffered_image.return_value = image
        return sdk, system, device, image

    def test_capture_saves_one_raw_frame_before_buffer_is_reused(self):
        sdk, system, device, image = self.make_sdk()
        with TemporaryDirectory() as directory:
            folder = Path(directory) / "撮影"
            with (
                patch.dict(sys.modules, {"pytelicam": sdk}),
                redirect_stderr(io.StringIO()),
            ):
                capture.main(folder)
            self.assertEqual(
                [path.name for path in folder.iterdir()], ["frame-000000.npy"]
            )
            np.testing.assert_array_equal(
                np.load(folder / "frame-000000.npy"),
                np.arange(48, dtype=np.uint8).reshape(6, 8),
            )
        system.wait_for_signal.assert_called_once()
        device.cam_stream.get_current_buffered_image.assert_called_once()
        image.get_ndarray.assert_called_once_with(sdk.OutputImageType.Raw)
        image.__exit__.assert_called_once()
        device.cam_stream.stop.assert_called_once()
        device.cam_stream.close.assert_called_once()
        device.close.assert_called_once()
        system.close_signal.assert_called_once()
        system.terminate.assert_called_once()

    def test_save_failure_releases_camera_and_does_not_publish_incomplete_frame(self):
        sdk, system, device, image = self.make_sdk()
        with TemporaryDirectory() as directory:
            folder = Path(directory) / "failed"
            with (
                patch.dict(sys.modules, {"pytelicam": sdk}),
                patch.object(capture.np, "save", side_effect=OSError("disk full")),
                redirect_stderr(io.StringIO()),
                self.assertRaisesRegex(OSError, "disk full"),
            ):
                capture.main(folder)
            self.assertFalse((folder / "frame-000000.npy").exists())
        image.__exit__.assert_called_once()
        device.cam_stream.stop.assert_called_once()
        device.cam_stream.close.assert_called_once()
        device.close.assert_called_once()
        system.terminate.assert_called_once()

    def test_camera_reflection_is_rejected_before_capture(self):
        sdk, system, device, _image = self.make_sdk()
        device.cam_control.get_reverse_x.return_value = (0, True)
        with TemporaryDirectory() as directory:
            folder = Path(directory) / "not-created"
            with (
                patch.dict(sys.modules, {"pytelicam": sdk}),
                self.assertRaises(ValueError),
            ):
                capture.main(folder)
            self.assertFalse(folder.exists())
        device.cam_stream.start.assert_not_called()
        device.close.assert_called_once()
        system.terminate.assert_called_once()

    def test_existing_output_folder_is_not_overwritten(self):
        with TemporaryDirectory() as directory:
            with self.assertRaises(FileExistsError):
                capture.main(Path(directory))


if __name__ == "__main__":
    unittest.main()
