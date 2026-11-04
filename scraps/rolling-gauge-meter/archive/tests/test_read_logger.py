"""実機やpywin32を使わず、複数CHの読出しと停止処理を確認する。"""

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
        self.waveform = Mock(spec_set=["_FlagAsMethod", "GetDataCount", "GetData", "GetAutosaveCount"])
        self.waveform.GetDataCount.return_value = 3
        self.waveform.GetData.return_value = 12.5
        self.waveform.GetAutosaveCount.return_value = 0
        self.logger = Mock(spec_set=[
            "_FlagAsMethod", "Initialize", "Visible", "SetIdentifier", "OpenFile",
            "GetActiveFile", "Start", "GetState", "GetErrorCode", "Stop", "Quit",
        ])
        self.logger.SetIdentifier.return_value = 0
        self.logger.OpenFile.return_value = 0
        self.logger.Start.return_value = 0
        self.logger.GetState.return_value = 5
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
            read_logger, CHANNELS=[(1, 0), (2, 1)], DEVICE_ID=0,
            SETTINGS_FILE=str(self.settings_path), READ_INTERVAL=1.0,
        )
        constants.start()
        self.addCleanup(constants.stop)
        sleeping = patch.object(read_logger.time, "sleep")
        self.sleep = sleeping.start()
        self.sleep.side_effect = KeyboardInterrupt
        self.addCleanup(sleeping.stop)
        self.output = io.StringIO()
        printing = redirect_stdout(self.output)
        printing.__enter__()
        self.addCleanup(printing.__exit__, None, None, None)

    def test_prints_values_until_ctrl_c_and_stops(self):
        self.waveform.GetDataCount.side_effect = [3, 4]
        self.waveform.GetData.side_effect = [12.5, 13.5, 14.5, 15.5]
        self.sleep.side_effect = [None, KeyboardInterrupt]

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
        self.waveform._FlagAsMethod.assert_called_once()
        waveform_methods = self.waveform._FlagAsMethod.call_args.args
        self.assertCountEqual(waveform_methods, ["GetDataCount", "GetData", "GetAutosaveCount"])
        self.com_calls.assert_has_calls([
            call.logger.Initialize(),
            call.logger.SetIdentifier(4),
            call.logger.OpenFile(str(self.settings_path)),
            call.logger.GetActiveFile(),
            call.waveform._FlagAsMethod(*waveform_methods),
            call.logger.Start(),
        ])
        self.assertEqual(self.waveform.GetData.call_args_list, [
            call(1, 0, 2), call(2, 1, 2), call(1, 0, 3), call(2, 1, 3),
        ])
        self.assertIn("index=2, raw[U1/CH0]=12.5, raw[U2/CH1]=13.5", self.output.getvalue())
        self.assertIn("index=3, raw[U1/CH0]=14.5, raw[U2/CH1]=15.5", self.output.getvalue())
        self.assertIn("Ctrl+C", self.output.getvalue())
        self.logger.Stop.assert_called_once()
        self.logger.Quit.assert_not_called()

    def test_identifier_rejection_reports_code_before_opening_settings(self):
        self.logger.SetIdentifier.return_value = 261

        with patch.object(read_logger, "DEVICE_ID", 2):
            with self.assertRaisesRegex(RuntimeError, r"SetIdentifier\(6\).*261 \(0x0105\)"):
                read_logger.main()

        self.logger.SetIdentifier.assert_called_once_with(6)
        self.logger.OpenFile.assert_not_called()
        self.logger.Start.assert_not_called()

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

    def test_waits_when_no_data_is_available(self):
        self.waveform.GetDataCount.return_value = 0

        read_logger.main()

        self.logger.Stop.assert_called_once()
        self.waveform.GetData.assert_not_called()
        self.assertIn("データ待ち", self.output.getvalue())

    def test_invalid_value_is_displayed_as_na(self):
        self.waveform.GetData.side_effect = [3.4028235e38, 13.5]

        read_logger.main()

        self.assertIn("index=2, raw[U1/CH0]=NA, raw[U2/CH1]=13.5", self.output.getvalue())
        self.logger.Stop.assert_called_once()

    def test_drops_row_if_save_number_changes_while_reading(self):
        self.waveform.GetAutosaveCount.side_effect = [0, 1, 1, 1]
        self.waveform.GetDataCount.side_effect = [3, 2]
        self.sleep.side_effect = [None, KeyboardInterrupt]

        read_logger.main()

        self.com_calls.assert_has_calls([
            call.waveform.GetAutosaveCount(),
            call.waveform.GetDataCount(),
            call.waveform.GetData(1, 0, 2),
            call.waveform.GetData(2, 1, 2),
            call.waveform.GetAutosaveCount(),
        ])
        self.assertNotIn("index=2, raw", self.output.getvalue())
        self.assertIn("index=1, raw[U1/CH0]=12.5, raw[U2/CH1]=12.5", self.output.getvalue())

    def test_stops_when_logger_stops_after_startup(self):
        self.logger.GetState.side_effect = [5, 1]
        self.sleep.side_effect = [None, KeyboardInterrupt]

        read_logger.main()

        self.sleep.assert_called_once_with(1.0)
        self.assertEqual(self.waveform.GetData.call_args_list, [call(1, 0, 2), call(2, 1, 2)])
        self.logger.Stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
