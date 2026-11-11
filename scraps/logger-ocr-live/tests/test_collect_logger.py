"""実機を使わず、現在値のJSONL出力と収集停止を確認する。"""

import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, call, patch

SCRIPT = Path(__file__).resolve().parents[1] / "logger.py"
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

        self.dispatch_ex = self.contexts.enter_context(
            patch.object(collect_logger, "DispatchEx")
        )
        self.dynamic_dispatch = self.contexts.enter_context(
            patch.object(collect_logger.dynamic, "Dispatch", return_value=self.logger)
        )
        folder = self.contexts.enter_context(tempfile.TemporaryDirectory())
        settings_file = Path(folder) / "test.ucf"
        settings_file.touch()
        self.contexts.enter_context(
            patch.object(collect_logger, "SETTINGS_FILE", settings_file)
        )
        self.stop_requested = Mock()
        self.stop_requested.is_set.return_value = False
        self.contexts.enter_context(
            patch.object(collect_logger, "Event", return_value=self.stop_requested)
        )
        self.output = io.StringIO()
        self.contexts.enter_context(redirect_stdout(self.output))
        self.contexts.enter_context(patch.object(collect_logger.time, "sleep"))

    def test_outputs_repeated_current_values_for_requested_channels(self):
        self.logger.GetState.side_effect = [5, 5, 1]
        self.waveform.GetCurrentData.side_effect = [0.0, 1.25, 0.0, 1.25]

        collect_logger.main(["U1_CH8", "U1_CH1"], managed=False)

        self.dispatch_ex.assert_called_once_with("WaveLoggerPro2.Application")
        self.dynamic_dispatch.assert_called_once_with(self.dispatch_ex.return_value)
        self.logger.Initialize.assert_called_once_with()
        self.assertIs(self.logger.Visible, True)
        self.waveform._FlagAsMethod.assert_called_once_with("GetCurrentData")

        messages = [json.loads(line) for line in self.output.getvalue().splitlines()]
        self.assertEqual(len(messages), 2)
        for message in messages:
            self.assertEqual(message["voltages"], {"U1_CH8": 0.0, "U1_CH1": 1.25})
            self.assertIsNotNone(datetime.fromisoformat(message["received_at"]).tzinfo)
        self.assertEqual(
            self.waveform.GetCurrentData.call_args_list,
            [
                call(1, 7),
                call(1, 0),
                call(1, 7),
                call(1, 0),
            ],
        )
        self.logger.Stop.assert_called_once()

    def test_standalone_without_arguments_reads_default_eight_channels(self):
        with patch.object(collect_logger, "Thread") as parent_watcher:
            collect_logger.main([], managed=False)
        parent_watcher.assert_not_called()
        message = json.loads(self.output.getvalue())
        self.assertEqual(
            list(message["voltages"]),
            [
                "U1_CH1",
                "U1_CH2",
                "U1_CH3",
                "U1_CH4",
                "U1_CH5",
                "U1_CH6",
                "U1_CH7",
                "U1_CH8",
            ],
        )
        self.assertEqual(
            self.waveform.GetCurrentData.call_args_list,
            [
                call(1, 0),
                call(1, 1),
                call(1, 2),
                call(1, 3),
                call(1, 4),
                call(1, 5),
                call(1, 6),
                call(1, 7),
            ],
        )
        self.logger.Stop.assert_called_once()

    def test_standalone_uses_channels_configured_at_top_of_script(self):
        with patch.object(collect_logger, "CHANNEL_NAMES", ["U1_CH3", "U1_CH5"]):
            collect_logger.main([], managed=False)
        message = json.loads(self.output.getvalue())
        self.assertEqual(message["voltages"], {"U1_CH3": 1.25, "U1_CH5": 1.25})
        self.assertEqual(
            self.waveform.GetCurrentData.call_args_list, [call(1, 2), call(1, 4)]
        )

    def test_explicit_channels_override_standalone_defaults(self):
        with patch.object(collect_logger, "CHANNEL_NAMES", ["U1_CH1"]):
            collect_logger.main(["U1_CH8"], managed=False)
        message = json.loads(self.output.getvalue())
        self.assertEqual(message["voltages"], {"U1_CH8": 1.25})
        self.waveform.GetCurrentData.assert_called_once_with(1, 7)

    def test_empty_standalone_configuration_is_rejected(self):
        with patch.object(collect_logger, "CHANNEL_NAMES", []):
            with self.assertRaisesRegex(ValueError, "取得する電圧CH"):
                collect_logger.main([], managed=False)
        self.logger.Start.assert_not_called()

    def test_managed_run_requires_channels_from_parent(self):
        with self.assertRaisesRegex(ValueError, "取得する電圧CH"):
            collect_logger.main([], managed=True)
        self.logger.Start.assert_not_called()

    def test_managed_run_keeps_parent_watcher_and_explicit_channels(self):
        with patch.object(collect_logger, "Thread") as parent_watcher:
            collect_logger.main(["U1_CH2"], managed=True)
        parent_watcher.assert_called_once_with(
            target=collect_logger.watch_parent,
            args=(self.stop_requested,),
            daemon=True,
        )
        parent_watcher.return_value.start.assert_called_once()
        message = json.loads(self.output.getvalue())
        self.assertEqual(message["voltages"], {"U1_CH2": 1.25})
        self.waveform.GetCurrentData.assert_called_once_with(1, 1)
        self.logger.Stop.assert_called_once()

    def test_rejects_channels_outside_the_single_eight_channel_unit(self):
        for channel in ("U2_CH1", "U1_CH0", "U1_CH9"):
            with self.subTest(channel=channel):
                with self.assertRaisesRegex(ValueError, "U1_CH1〜U1_CH8"):
                    collect_logger.main([channel], managed=False)
        self.logger.Start.assert_not_called()

    def test_configured_unit_number_controls_channel_validation_and_com_reads(self):
        with patch.object(collect_logger, "UNIT_NUMBER", 2):
            collect_logger.main(["U2_CH8", "U2_CH1"], managed=False)

        message = json.loads(self.output.getvalue())
        self.assertEqual(message["voltages"], {"U2_CH8": 1.25, "U2_CH1": 1.25})
        self.assertEqual(
            self.waveform.GetCurrentData.call_args_list,
            [call(2, 7), call(2, 0)],
        )

    def test_rejects_channels_from_a_different_unit(self):
        with patch.object(collect_logger, "UNIT_NUMBER", 2):
            with self.assertRaisesRegex(ValueError, "U2_CH1〜U2_CH8"):
                collect_logger.main(["U1_CH1"], managed=False)
        self.logger.Start.assert_not_called()

    def test_rejects_invalid_unit_number(self):
        with patch.object(collect_logger, "UNIT_NUMBER", 0):
            with self.assertRaisesRegex(ValueError, "UNIT_NUMBER"):
                collect_logger.main(["U0_CH1"], managed=False)
        self.logger.Start.assert_not_called()

    def test_invalid_values_are_json_null(self):
        self.waveform.GetCurrentData.side_effect = [
            3.4028235e38,
            -3.4028235e38,
            float("nan"),
            float("inf"),
            -float("inf"),
        ]

        collect_logger.main(
            ["U1_CH1", "U1_CH2", "U1_CH3", "U1_CH4", "U1_CH5"], managed=False
        )

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

    def test_com_setup_and_start_errors_report_the_operation_and_code(self):
        cases = (
            ("SetIdentifier", "機器ID設定失敗"),
            ("OpenFile", "設定ファイル読込失敗"),
            ("Start", "収集開始失敗"),
        )
        for operation, error_message in cases:
            with self.subTest(operation=operation):
                with patch.object(self.logger, operation, return_value=123):
                    with self.assertRaisesRegex(
                        RuntimeError, f"{error_message}（123）"
                    ):
                        collect_logger.main(["U1_CH1"], managed=False)

        self.logger.GetState.assert_not_called()
        self.logger.Stop.assert_not_called()
        self.assertEqual(self.output.getvalue(), "")

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
