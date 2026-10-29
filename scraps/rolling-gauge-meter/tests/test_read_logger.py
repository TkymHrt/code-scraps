"""実機やpywin32を使わず、1CH読出しと停止処理を確認する。"""

from contextlib import redirect_stdout
import importlib.util
import io
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).resolve().parents[1] / "read_logger.py"
SPEC = importlib.util.spec_from_file_location("read_logger_under_test", SCRIPT)
read_logger = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(read_logger)


class ReadLoggerTests(unittest.TestCase):
    def setUp(self):
        self.waveform = Mock()
        self.waveform.GetDataCount.return_value = 3
        self.waveform.GetData.return_value = 12.5
        self.logger = Mock()
        self.logger.SetIdentifier.return_value = 0
        self.logger.OpenFile.return_value = 0
        self.logger.Start.return_value = 0
        self.logger.GetState.return_value = 2
        self.logger.GetActiveFile.return_value = self.waveform

        # import先も偽物にする。実PCのCOM登録にはアクセスしない。
        fake_client = types.ModuleType("win32com.client")
        fake_client.DispatchEx = Mock(return_value=self.logger)
        fake_win32com = types.ModuleType("win32com")
        fake_win32com.client = fake_client
        modules = patch.dict(sys.modules, {
            "win32com": fake_win32com,
            "win32com.client": fake_client,
        })
        modules.start()
        self.addCleanup(modules.stop)

        constants = patch.multiple(read_logger, READ_COUNT=1, CONNECTION="USB")
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

        self.waveform.GetData.assert_called_once_with(read_logger.UNIT, read_logger.CHANNEL, 2)
        self.assertIn("index=2, raw=12.5", self.output.getvalue())
        self.assertIn("数値を取得できました: 1回", self.output.getvalue())
        self.logger.Stop.assert_called_once()
        self.logger.Quit.assert_not_called()

    def test_read_exception_still_stops(self):
        self.waveform.GetData.side_effect = RuntimeError("mock read failure")

        with self.assertRaisesRegex(RuntimeError, "mock read failure"):
            read_logger.main()

        self.logger.Stop.assert_called_once()

    def test_explicit_start_rejection_does_not_stop(self):
        self.logger.Start.return_value = 0x2013

        with self.assertRaisesRegex(RuntimeError, "収集を開始できません"):
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
