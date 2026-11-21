"""カメラ実機を開かずに画像取得とリソース解放を確認する。"""

import importlib.util
import io
import json
import sys
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import numpy as np

SCRIPT = Path(__file__).resolve().parents[1] / "src" / "counter.py"
SPEC = importlib.util.spec_from_file_location("logger_input_under_test", SCRIPT)
reader = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reader)


class MeterInputTests(unittest.TestCase):
    def setUp(self):
        # ファイルから直接読み込むテストでも、スクリプト起動時と同じ場所を探す。
        self.enterContext(patch.object(sys, "path", [str(SCRIPT.parent), *sys.path]))
        self.enterContext(patch.dict(sys.modules))
        sys.modules.pop("camera_sdk", None)

    def make_teli_camera(self):
        sdk = Mock()
        sdk.CamApiStatus = SimpleNamespace(Success=0, Error=1, Timeout=2)
        sdk.OutputImageType = SimpleNamespace(Bgr24=object())
        sdk.PytelicamError = type("PytelicamError", (Exception,), {})
        system = sdk.get_camera_system.return_value
        system.get_num_of_cameras.return_value = 2
        system.create_signal.return_value = object()
        system.wait_for_signal.side_effect = [
            sdk.CamApiStatus.Success,
            KeyboardInterrupt(),
        ]
        system.terminate.return_value = None
        system.close_signal.return_value = None
        device = system.create_device_object.return_value
        device.open.return_value = None
        device.close.return_value = None
        device.cam_control.set_trigger_mode.return_value = sdk.CamApiStatus.Success
        stream = device.cam_stream
        stream.open.return_value = None
        stream.start.return_value = None
        stream.stop.return_value = None
        stream.close.return_value = None
        image = self.make_teli_image(sdk, 0)
        stream.get_current_buffered_image.return_value = image
        return sdk, system, device, stream, image

    def make_teli_image(self, sdk, image_id):
        image = Mock(
            status=sdk.CamApiStatus.Success,
            image_id=image_id,
            pixel_format=SimpleNamespace(name="BayerRG8"),
        )
        width, height = reader.FRAME_SIZE
        image.get_ndarray.return_value = np.full((height, width, 3), 19, dtype=np.uint8)
        image.release.return_value = None
        return image

    def test_web_camera_sets_resolution_without_importing_teli_support(self):
        capture = Mock()
        capture.isOpened.return_value = True
        capture.read.return_value = (False, None)
        with patch.dict(sys.modules, {"camera_sdk": None, "pytelicam": None}):
            webcam_reader = importlib.util.module_from_spec(SPEC)
            SPEC.loader.exec_module(webcam_reader)
            with (
                patch.object(webcam_reader, "SOURCE", 2),
                patch.object(
                    webcam_reader.cv2, "VideoCapture", return_value=capture
                ) as video_capture,
                self.assertRaises(RuntimeError),
            ):
                webcam_reader.main()
        video_capture.assert_called_once_with(2)
        width, height = webcam_reader.FRAME_SIZE
        self.assertEqual(
            capture.set.call_args_list,
            [
                call(webcam_reader.cv2.CAP_PROP_FRAME_WIDTH, width),
                call(webcam_reader.cv2.CAP_PROP_FRAME_HEIGHT, height),
            ],
        )
        capture.release.assert_called_once()

    def test_teli_camera_reads_each_image_once_and_releases_resources_on_interrupt(
        self,
    ):
        sdk, system, device, stream, first_image = self.make_teli_camera()
        duplicate = self.make_teli_image(sdk, first_image.image_id)
        next_image = self.make_teli_image(sdk, 1)
        images = [first_image, duplicate, next_image]
        stream.get_current_buffered_image.side_effect = images
        system.wait_for_signal.side_effect = [sdk.CamApiStatus.Success] * len(
            images
        ) + [KeyboardInterrupt()]
        frame = first_image.get_ndarray.return_value
        first_image.release.side_effect = lambda: frame.fill(0)
        output = io.StringIO()

        def recognize_frame(frame, *args, **kwargs):
            self.assertEqual(int(frame[0, 0, 0]), 19)
            return 123.456

        with (
            patch.multiple(reader, SOURCE=("teli", 1), STABLE_FRAMES=2),
            patch.dict(sys.modules, {"pytelicam": sdk}),
            patch.object(reader.cv2, "VideoCapture") as video_capture,
            patch.object(
                reader, "recognize_display", side_effect=recognize_frame
            ) as recognize,
            redirect_stdout(output),
            self.assertRaises(KeyboardInterrupt),
        ):
            reader.main()
        video_capture.assert_not_called()
        system.create_device_object.assert_called_once_with(1)
        device.cam_control.set_trigger_mode.assert_called_once_with(False)
        signal = system.create_signal.return_value
        stream.open.assert_called_once_with(signal)
        self.assertEqual(
            system.wait_for_signal.call_args_list, [call(signal, 1000)] * 4
        )
        self.assertEqual(recognize.call_count, 2)
        duplicate.get_ndarray.assert_not_called()
        first_image.get_ndarray.assert_called_once_with(sdk.OutputImageType.Bgr24)
        next_image.get_ndarray.assert_called_once_with(sdk.OutputImageType.Bgr24)
        for image in images:
            image.release.assert_called_once()
        values = [json.loads(line)["value"] for line in output.getvalue().splitlines()]
        self.assertEqual(values, [None, 123.456])
        stream.stop.assert_called_once()
        stream.close.assert_called_once()
        system.close_signal.assert_called_once_with(signal)
        device.close.assert_called_once()
        system.terminate.assert_called_once()
        self.assertLess(
            sdk.mock_calls.index(
                call.get_camera_system()
                .create_device_object()
                .cam_control.set_trigger_mode(False)
            ),
            sdk.mock_calls.index(
                call.get_camera_system().create_device_object().cam_stream.start()
            ),
        )
        self.assertEqual(
            sdk.mock_calls[-5:],
            [
                call.get_camera_system().create_device_object().cam_stream.stop(),
                call.get_camera_system().create_device_object().cam_stream.close(),
                call.get_camera_system().close_signal(signal),
                call.get_camera_system().create_device_object().close(),
                call.get_camera_system().terminate(),
            ],
        )

    def test_teli_input_propagates_missing_sdk(self):
        with (
            patch.object(reader, "SOURCE", ("teli", 0)),
            patch.dict(sys.modules, {"pytelicam": None}),
            patch.object(reader.cv2, "VideoCapture") as video_capture,
            self.assertRaises(ModuleNotFoundError) as error,
        ):
            reader.main()
        self.assertEqual(error.exception.name, "pytelicam")
        video_capture.assert_not_called()

    def test_teli_no_camera_found_terminates_the_sdk(self):
        sdk, system, _, _, _ = self.make_teli_camera()
        system.get_num_of_cameras.return_value = 0
        with (
            patch.object(reader, "SOURCE", ("teli", 0)),
            patch.dict(sys.modules, {"pytelicam": sdk}),
            self.assertRaises(IndexError),
        ):
            reader.main()
        system.create_device_object.assert_not_called()
        system.create_signal.assert_not_called()
        system.terminate.assert_called_once()

    def test_teli_device_open_failure_terminates_the_sdk(self):
        sdk, system, device, stream, _ = self.make_teli_camera()
        error = sdk.PytelicamError("device.open")
        device.open.side_effect = error
        with (
            patch.object(reader, "SOURCE", ("teli", 0)),
            patch.dict(sys.modules, {"pytelicam": sdk}),
            self.assertRaises(sdk.PytelicamError) as caught,
        ):
            reader.main()
        self.assertIs(caught.exception, error)
        device.cam_control.set_trigger_mode.assert_not_called()
        system.create_signal.assert_not_called()
        stream.open.assert_not_called()
        device.close.assert_not_called()
        system.terminate.assert_called_once()

    def test_teli_trigger_mode_failure_closes_device_before_stream_is_opened(self):
        sdk, system, device, stream, _ = self.make_teli_camera()
        device.cam_control.set_trigger_mode.return_value = sdk.CamApiStatus.Error
        with (
            patch.object(reader, "SOURCE", ("teli", 0)),
            patch.dict(sys.modules, {"pytelicam": sdk}),
            self.assertRaisesRegex(RuntimeError, "set_trigger_mode"),
        ):
            reader.main()
        device.cam_control.set_trigger_mode.assert_called_once_with(False)
        system.create_signal.assert_not_called()
        stream.open.assert_not_called()
        device.close.assert_called_once()
        system.terminate.assert_called_once()

    def test_teli_stream_open_failure_closes_signal_and_device(self):
        sdk, system, device, stream, _ = self.make_teli_camera()
        error = sdk.PytelicamError("stream.open")
        stream.open.side_effect = error
        with (
            patch.object(reader, "SOURCE", ("teli", 0)),
            patch.dict(sys.modules, {"pytelicam": sdk}),
            self.assertRaises(sdk.PytelicamError) as caught,
        ):
            reader.main()
        self.assertIs(caught.exception, error)
        stream.start.assert_not_called()
        stream.stop.assert_not_called()
        stream.close.assert_not_called()
        system.close_signal.assert_called_once_with(system.create_signal.return_value)
        device.close.assert_called_once()
        system.terminate.assert_called_once()

    def test_teli_unusable_frame_is_released_before_closing_camera(self):
        for monochrome in (False, True):
            with self.subTest(monochrome=monochrome):
                sdk, system, device, stream, image = self.make_teli_camera()
                if monochrome:
                    image.pixel_format = SimpleNamespace(name="Mono8")
                else:
                    image.status = sdk.CamApiStatus.Error
                with (
                    patch.object(reader, "SOURCE", ("teli", 0)),
                    patch.dict(sys.modules, {"pytelicam": sdk}),
                    self.assertRaises(RuntimeError),
                ):
                    reader.main()
                image.get_ndarray.assert_not_called()
                image.release.assert_called_once()
                stream.stop.assert_called_once()
                stream.close.assert_called_once()
                system.close_signal.assert_called_once_with(
                    system.create_signal.return_value
                )
                device.close.assert_called_once()
                system.terminate.assert_called_once()

    def test_teli_start_failure_closes_open_stream_and_device(self):
        sdk, system, device, stream, _ = self.make_teli_camera()
        error = sdk.PytelicamError("stream.start")
        stream.start.side_effect = error
        with (
            patch.object(reader, "SOURCE", ("teli", 0)),
            patch.dict(sys.modules, {"pytelicam": sdk}),
            self.assertRaises(sdk.PytelicamError) as caught,
        ):
            reader.main()
        self.assertIs(caught.exception, error)
        stream.get_current_buffered_image.assert_not_called()
        stream.stop.assert_not_called()
        stream.close.assert_called_once()
        system.close_signal.assert_called_once_with(system.create_signal.return_value)
        device.close.assert_called_once()
        system.terminate.assert_called_once()

    def test_teli_conversion_failure_releases_image_and_closes_camera(self):
        sdk, system, device, stream, image = self.make_teli_camera()
        error = sdk.PytelicamError("get_ndarray")
        image.get_ndarray.side_effect = error
        with (
            patch.object(reader, "SOURCE", ("teli", 0)),
            patch.dict(sys.modules, {"pytelicam": sdk}),
            self.assertRaises(sdk.PytelicamError) as caught,
        ):
            reader.main()
        self.assertIs(caught.exception, error)
        image.release.assert_called_once()
        stream.stop.assert_called_once()
        stream.close.assert_called_once()
        system.close_signal.assert_called_once_with(system.create_signal.return_value)
        device.close.assert_called_once()
        system.terminate.assert_called_once()

    def test_teli_timeout_does_not_read_a_buffer_and_closes_camera(self):
        sdk, system, device, stream, _ = self.make_teli_camera()
        system.wait_for_signal.side_effect = None
        system.wait_for_signal.return_value = sdk.CamApiStatus.Timeout
        with (
            patch.object(reader, "SOURCE", ("teli", 0)),
            patch.dict(sys.modules, {"pytelicam": sdk}),
            self.assertRaises(RuntimeError),
        ):
            reader.main()
        stream.get_current_buffered_image.assert_not_called()
        stream.stop.assert_called_once()
        stream.close.assert_called_once()
        system.close_signal.assert_called_once_with(system.create_signal.return_value)
        device.close.assert_called_once()
        system.terminate.assert_called_once()

    def test_teli_timeout_during_requested_stop_exits_normally(self):
        sdk, system, _, stream, _ = self.make_teli_camera()
        stop_requested = Event()
        output = io.StringIO()

        def stop_while_waiting(signal, milliseconds):
            stop_requested.set()
            return sdk.CamApiStatus.Timeout

        system.wait_for_signal.side_effect = stop_while_waiting
        with (
            patch.object(reader, "SOURCE", ("teli", 0)),
            patch.object(reader, "Event", return_value=stop_requested),
            patch.dict(sys.modules, {"pytelicam": sdk}),
            redirect_stdout(output),
        ):
            reader.main()
        self.assertEqual(output.getvalue(), "")
        stream.get_current_buffered_image.assert_not_called()
        stream.stop.assert_called_once()
        system.terminate.assert_called_once()

    def test_read_counter_can_be_closed_without_json_or_stdout(self):
        capture = Mock()
        capture.isOpened.return_value = True
        width, height = reader.FRAME_SIZE
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        capture.read.return_value = (True, frame)
        output = io.StringIO()
        with (
            patch.object(reader.cv2, "VideoCapture", return_value=capture),
            patch.object(reader, "recognize_display", return_value=1.234),
            patch.object(reader.json, "dumps", side_effect=AssertionError),
            redirect_stdout(output),
            closing(reader.read_counter(0, Event())) as messages,
        ):
            message = next(messages)
            capture.release.assert_not_called()

        self.assertEqual(message["value"], 1.234)
        self.assertIsInstance(message["acquired_mono_ns"], int)
        self.assertEqual(output.getvalue(), "")
        capture.release.assert_called_once()

    def test_output_failure_still_releases_camera(self):
        capture = Mock()
        capture.isOpened.return_value = True
        width, height = reader.FRAME_SIZE
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        capture.read.return_value = (True, frame)
        with (
            patch.object(reader, "SOURCE", 0),
            patch.object(reader.cv2, "VideoCapture", return_value=capture),
            patch.object(reader.json, "dumps", side_effect=OSError("出力失敗")),
            self.assertRaisesRegex(OSError, "出力失敗"),
        ):
            reader.main()
        capture.release.assert_called_once()


if __name__ == "__main__":
    unittest.main()
