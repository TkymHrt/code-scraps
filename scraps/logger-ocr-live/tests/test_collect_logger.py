"""実機を使わず、現在値のJSONL出力と収集停止を確認する。"""

from contextlib import ExitStack, redirect_stdout
from datetime import datetime
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, call, patch


SCRIPT = Path(__file__).resolve().parents[1] / "collect_logger.py"
SPEC = importlib.util.spec_from_file_location("live_collect_logger", SCRIPT)
collect_logger = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collect_logger)


class CollectLoggerTests(unittest.TestCase):
    def setUp(self):
        self.contexts = ExitStack()
        self.addCleanup(self.contexts.close)
        self.waveform = Mock(spec_set=["_FlagAsMethod", "GetCurrentData"])
        self.waveform.GetCurrentData.return_value = 1.25
        self.logger = Mock()
        self.logger.SetIdentifier.return_value = 0
        self.logger.OpenFile.return_value = 0
        self.logger.Start.return_value = 0
        self.logger.GetActiveFile.return_value = self.waveform
        self.logger.GetState.side_effect = [5, 1]

        pythoncom = types.SimpleNamespace(
            CoCreateInstance=Mock(), CLSCTX_SERVER=21, IID_IDispatch=object()
        )
        dynamic = types.SimpleNamespace(Dispatch=Mock(return_value=self.logger))
        modules = {
            "pythoncom": pythoncom,
            "win32com": types.SimpleNamespace(),
            "win32com.client": types.SimpleNamespace(dynamic=dynamic),
        }
        self.contexts.enter_context(patch.dict(sys.modules, modules))
        folder = self.contexts.enter_context(tempfile.TemporaryDirectory())
        settings_file = Path(folder) / "test.ucf"
        settings_file.touch()
        self.contexts.enter_context(patch.object(collect_logger, "SETTINGS_FILE", settings_file))
        self.stop_requested = Mock()
        self.stop_requested.is_set.return_value = False
        self.contexts.enter_context(patch.object(collect_logger, "Event", return_value=self.stop_requested))
        self.output = io.StringIO()
        self.contexts.enter_context(redirect_stdout(self.output))

    def test_outputs_repeated_current_values_for_requested_channels(self):
        self.logger.GetState.side_effect = [5, 5, 1]
        self.waveform.GetCurrentData.side_effect = [0.0, 1.25, 0.0, 1.25]

        collect_logger.main(["U1_CH8", "U1_CH1"], managed=False)

        messages = [json.loads(line) for line in self.output.getvalue().splitlines()]
        self.assertEqual(len(messages), 2)
        for message in messages:
            self.assertEqual(message["voltages"], {"U1_CH8": 0.0, "U1_CH1": 1.25})
            self.assertIsNotNone(datetime.fromisoformat(message["received_at"]).tzinfo)
        self.assertEqual(self.waveform.GetCurrentData.call_args_list, [
            call(1, 7), call(1, 0), call(1, 7), call(1, 0),
        ])
        self.logger.Stop.assert_called_once()

    def test_rejects_channels_outside_the_single_eight_channel_unit(self):
        for channel in ("U2_CH1", "U1_CH0", "U1_CH9"):
            with self.subTest(channel=channel):
                with self.assertRaisesRegex(ValueError, "U1_CH1〜U1_CH8"):
                    collect_logger.main([channel], managed=False)
        self.logger.Start.assert_not_called()

    def test_invalid_values_are_json_null(self):
        self.waveform.GetCurrentData.side_effect = [
            3.4028235e38, -3.4028235e38, float("nan"), float("inf"), -float("inf"),
        ]

        collect_logger.main(["U1_CH1", "U1_CH2", "U1_CH3", "U1_CH4", "U1_CH5"], managed=False)

        message = json.loads(self.output.getvalue())
        self.assertEqual(list(message["voltages"].values()), [None] * 5)
        self.assertNotIn("NaN", self.output.getvalue())
        self.assertNotIn("Infinity", self.output.getvalue())

    def test_waits_for_startup_without_reading_a_stopped_device(self):
        self.logger.GetState.side_effect = [1, 5, 1]

        collect_logger.main(["U1_CH1"], managed=False)

        self.waveform.GetCurrentData.assert_called_once_with(1, 0)
        self.assertEqual(self.stop_requested.wait.call_count, 2)
        self.assertEqual(len(self.output.getvalue().splitlines()), 1)

    def test_read_failure_still_stops_collection(self):
        self.waveform.GetCurrentData.side_effect = RuntimeError("read failed")

        with self.assertRaisesRegex(RuntimeError, "read failed"):
            collect_logger.main(["U1_CH1"], managed=False)

        self.logger.Stop.assert_called_once()
        self.assertEqual(self.output.getvalue(), "")

    def test_error_state_stops_without_reading(self):
        self.logger.GetState.side_effect = [11]
        self.logger.GetErrorCode.return_value = 123

        with self.assertRaisesRegex(RuntimeError, "123"):
            collect_logger.main(["U1_CH1"], managed=False)

        self.waveform.GetCurrentData.assert_not_called()
        self.logger.Stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
