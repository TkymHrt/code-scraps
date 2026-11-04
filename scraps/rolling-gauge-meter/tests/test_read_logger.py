"""実機やpywin32を使わず、1CH読出しと停止処理を確認する。"""

from contextlib import redirect_stdout
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, call, patch


SCRIPT = Path(__file__).resolve().parents[1] / "read_logger.py"
SPEC = importlib.util.spec_from_file_location("read_logger_under_test", SCRIPT)
read_logger = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(read_logger)


class ReadLoggerTests(unittest.TestCase):
    def setUp(self):
        self.waveform = Mock(spec_set=["_FlagAsMethod", "GetDataCount", "GetData"])
        self.waveform.GetDataCount.return_value = 3
        self.waveform.GetData.return_value = 12.5
        self.logger = Mock(spec_set=[
            "_FlagAsMethod", "Initialize", "Visible", "SetIdentifier", "SetLanConfig",
            "ConnectLan", "OpenFile", "GetActiveFile", "Start", "GetState",
            "GetErrorCode", "Stop", "Quit",
        ])
        self.logger.SetIdentifier.return_value = 0
        self.logger.SetLanConfig.return_value = 0
        self.logger.ConnectLan.return_value = 0
        self.logger.OpenFile.return_value = 0
        self.logger.Start.return_value = 0
        self.logger.GetState.return_value = 2
        self.logger.GetActiveFile.return_value = self.waveform
        self.com_calls = Mock()
        self.com_calls.attach_mock(self.logger, "logger")
        self.com_calls.attach_mock(self.waveform, "waveform")

        # import先も偽物にする。実PCのCOM登録にはアクセスしない。
        self.fake_pythoncom = types.ModuleType("pythoncom")
        self.fake_pythoncom.CLSCTX_SERVER = 21
        self.fake_pythoncom.IID_IDispatch = object()
        self.dispatch = object()
        self.fake_pythoncom.CoCreateInstance = Mock(return_value=self.dispatch)
        self.fake_dynamic = types.ModuleType("win32com.client.dynamic")
        self.fake_dynamic.Dispatch = Mock(return_value=self.logger)
        fake_client = types.ModuleType("win32com.client")
        fake_client.dynamic = self.fake_dynamic
        fake_win32com = types.ModuleType("win32com")
        fake_win32com.client = fake_client
        modules = patch.dict(sys.modules, {
            "pythoncom": self.fake_pythoncom,
            "win32com": fake_win32com,
            "win32com.client": fake_client,
            "win32com.client.dynamic": self.fake_dynamic,
        })
        modules.start()
        self.addCleanup(modules.stop)

        settings_dir = tempfile.TemporaryDirectory()
        self.addCleanup(settings_dir.cleanup)
        self.settings_path = Path(settings_dir.name).resolve() / "test.ucf"
        self.settings_path.touch()
        constants = patch.multiple(
            read_logger, READ_COUNT=1, CONNECTION="USB", DEVICE_ID=0,
            SETTINGS_FILE=str(self.settings_path),
        )
        constants.start()
        self.addCleanup(constants.stop)
        sleeping = patch.object(read_logger.time, "sleep")
        sleeping.start()
        self.addCleanup(sleeping.stop)
        self.output = io.StringIO()
        printing = redirect_stdout(self.output)
        printing.__enter__()
        self.addCleanup(printing.__exit__, None, None, None)

    def test_prints_value_and_stops(self):
        read_logger.main()

        self.fake_pythoncom.CoCreateInstance.assert_called_once_with(
            "WaveLoggerPro2.Application", None, self.fake_pythoncom.CLSCTX_SERVER,
            self.fake_pythoncom.IID_IDispatch,
        )
        self.fake_dynamic.Dispatch.assert_called_once_with(self.dispatch)
        first_call = self.logger.mock_calls[0]
        self.assertEqual(first_call[0], "_FlagAsMethod")
        self.assertCountEqual(first_call.args, [
            "Initialize", "SetIdentifier", "OpenFile", "GetActiveFile", "Start",
            "GetState", "GetErrorCode", "Stop",
        ])
        self.assertIs(self.logger.Visible, True)
        self.com_calls.assert_has_calls([
            call.logger.Initialize(),
            call.logger.SetIdentifier(4),
            call.logger.OpenFile(str(self.settings_path)),
            call.logger.GetActiveFile(),
            call.waveform._FlagAsMethod("GetDataCount", "GetData"),
            call.logger.Start(),
        ])
        self.waveform.GetData.assert_called_once_with(read_logger.UNIT, read_logger.CHANNEL, 2)
        self.assertIn("index=2, raw=12.5", self.output.getvalue())
        self.assertIn("数値を取得できました: 1回", self.output.getvalue())
        self.logger.Stop.assert_called_once()
        self.logger.Quit.assert_not_called()

    def test_connects_lan_before_opening_settings(self):
        with patch.multiple(read_logger, CONNECTION="LAN", DEVICE_ID=2):
            read_logger.main()

        self.logger.assert_has_calls([
            call._FlagAsMethod("SetLanConfig", "ConnectLan"),
            call.SetLanConfig(2, *read_logger.IP_ADDRESS, read_logger.PORT),
            call.ConnectLan(),
            call.OpenFile(str(self.settings_path)),
        ])
        self.logger.SetIdentifier.assert_called_once_with(10)

    def test_missing_settings_file_does_not_create_com_instance(self):
        self.settings_path.unlink()

        with self.assertRaisesRegex(FileNotFoundError, r"test\.ucf"):
            read_logger.main()

        self.fake_pythoncom.CoCreateInstance.assert_not_called()

    def test_missing_waveform_does_not_start(self):
        self.logger.GetActiveFile.return_value = None

        with self.assertRaisesRegex(RuntimeError, "GetActiveFile"):
            read_logger.main()

        self.logger.Start.assert_not_called()
        self.logger.Stop.assert_not_called()

    def test_read_exception_still_stops(self):
        self.waveform.GetData.side_effect = RuntimeError("mock read failure")

        with self.assertRaisesRegex(RuntimeError, "mock read failure"):
            read_logger.main()

        self.logger.Stop.assert_called_once()

    def test_explicit_start_rejection_does_not_stop(self):
        self.logger.Start.return_value = 0x2013

        with self.assertRaisesRegex(RuntimeError, "収集を開始できませんでした: 0x2013"):
            read_logger.main()

        self.logger.Stop.assert_not_called()
        self.waveform.GetData.assert_not_called()

    def test_no_data_is_failure(self):
        self.waveform.GetDataCount.return_value = 0

        with self.assertRaisesRegex(RuntimeError, "数値を取得できませんでした"):
            read_logger.main()

        self.logger.Stop.assert_called_once()
        self.waveform.GetData.assert_not_called()
        self.assertNotIn("数値を取得できました:", self.output.getvalue())

    def test_invalid_value_is_failure_and_stops(self):
        self.waveform.GetData.return_value = 3.4028235e38

        with self.assertRaisesRegex(RuntimeError, "無効な値"):
            read_logger.main()

        self.logger.Stop.assert_called_once()
        self.assertNotIn("数値を取得できました:", self.output.getvalue())


if __name__ == "__main__":
    unittest.main()
