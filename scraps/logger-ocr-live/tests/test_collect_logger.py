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

        self.dispatch_ex = self.contexts.enter_context(
            patch.object(collect_logger, "DispatchEx")
        )
        self.dynamic_dispatch = self.contexts.enter_context(
            patch.object(collect_logger.dynamic, "Dispatch", return_value=self.logger)
        )
        folder = self.contexts.enter_context(tempfile.TemporaryDirectory())
        self.diagnostic_folder = Path(folder)
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

    def test_attach_reuses_running_app_without_spawning_one(self):
        with patch.object(collect_logger, "GetActiveObject") as active_app:
            collect_logger.main(["U1_CH1"], managed=False, attach=True)

        active_app.assert_called_once_with("WaveLoggerPro2.Application")
        self.dispatch_ex.assert_not_called()
        self.dynamic_dispatch.assert_called_once_with(active_app.return_value)
        self.logger.Stop.assert_called_once()

    def test_attach_fails_instead_of_starting_another_app(self):
        with patch.object(
            collect_logger, "GetActiveObject", side_effect=OSError("not registered")
        ):
            with self.assertRaisesRegex(RuntimeError, "起動済みのWAVE LOGGER PRO"):
                collect_logger.main(["U1_CH1"], managed=False, attach=True)

        self.dispatch_ex.assert_not_called()
        self.logger.Start.assert_not_called()

    def test_ctrl_c_requests_stop_and_restores_signal_handler(self):
        stop_state = {"requested": False}
        self.stop_requested.is_set.side_effect = lambda: stop_state["requested"]
        self.stop_requested.set.side_effect = lambda: stop_state.__setitem__(
            "requested", True
        )
        handlers = []
        original_handler = object()

        def register_handler(_signal_number, handler):
            handlers.append(handler)

        def get_state():
            handlers[0](2, None)
            return 5

        self.logger.GetState.side_effect = get_state
        with (
            patch.object(
                collect_logger.signal, "getsignal", return_value=original_handler
            ),
            patch.object(
                collect_logger.signal, "signal", side_effect=register_handler
            ),
        ):
            collect_logger.main(["U1_CH1"], managed=False)

        self.assertTrue(stop_state["requested"])
        self.logger.Stop.assert_called_once()
        self.assertEqual(handlers[-1], original_handler)

    def test_diagnostic_log_records_stop_result_and_confirmed_state(self):
        self.logger.GetState.side_effect = [5, 1, 1]
        self.logger.Stop.return_value = 0
        with patch.object(
            collect_logger.Path, "cwd", return_value=self.diagnostic_folder
        ):
            collect_logger.main(["U1_CH1"], managed=False, diagnose=True)
        logs = list(self.diagnostic_folder.glob("collect_logger_diag_*.jsonl"))
        self.assertEqual(len(logs), 1)
        events = [json.loads(line) for line in logs[0].read_text().splitlines()]
        named = {event["event"]: event for event in events}
        self.assertEqual(named["stop_result"]["result"], "0")
        self.assertTrue(named["get_state_after_stop"]["expected_stopped"])
        self.assertIn("releasing_com_references", named)
        self.assertIn("trace_close", named)

    def test_diagnostic_reports_failed_stop_and_running_state(self):
        self.logger.GetState.side_effect = [5, 1, 5]
        self.logger.Stop.return_value = 123
        with (
            patch.object(collect_logger.Path, "cwd", return_value=self.diagnostic_folder),
            patch.object(collect_logger, "DIAG_VERIFY_STOP_SECONDS", 0.0),
        ):
            collect_logger.main(["U1_CH1"], managed=False, diagnose=True)

        logs = list(self.diagnostic_folder.glob("collect_logger_diag_*.jsonl"))
        events = [json.loads(line) for line in logs[0].read_text().splitlines()]
        named = {event["event"]: event for event in events}
        self.assertFalse(named["stop_result"]["expected_success"])
        self.assertEqual(named["get_state_after_stop"]["state"], 5)
        self.assertFalse(named["get_state_after_stop"]["expected_stopped"])

    def test_diagnostic_skip_stop_requires_opt_in(self):
        self.logger.GetState.side_effect = [5, 1, 1]
        with (
            patch.object(collect_logger.Path, "cwd", return_value=self.diagnostic_folder),
            patch.object(collect_logger, "DIAG_SKIP_STOP", True),
        ):
            collect_logger.main(["U1_CH1"], managed=False, diagnose=True)
        self.logger.Stop.assert_not_called()
        logs = list(self.diagnostic_folder.glob("collect_logger_diag_*.jsonl"))
        self.assertIn("stop_skipped_by_experiment", logs[0].read_text())

    def test_diagnostic_attached_mode_can_skip_setup_operations(self):
        self.logger.GetState.side_effect = [5, 1, 1]
        with (
            patch.object(collect_logger.Path, "cwd", return_value=self.diagnostic_folder),
            patch.object(collect_logger, "GetActiveObject"),
            patch.object(collect_logger, "DIAG_SKIP_INITIALIZE_ON_ATTACH", True),
            patch.object(collect_logger, "DIAG_SKIP_IDENTIFIER_ON_ATTACH", True),
            patch.object(collect_logger, "DIAG_SKIP_OPEN_FILE_ON_ATTACH", True),
        ):
            collect_logger.main(["U1_CH1"], managed=False, attach=True, diagnose=True)
        self.logger.Initialize.assert_not_called()
        self.logger.SetIdentifier.assert_not_called()
        self.logger.OpenFile.assert_not_called()
        self.logger.Stop.assert_called_once()

    def test_diagnostic_hold_keeps_com_alive_after_stop(self):
        self.logger.GetState.side_effect = [5, 1, 1]
        with (
            patch.object(collect_logger.Path, "cwd", return_value=self.diagnostic_folder),
            patch.object(collect_logger, "DIAG_HOLD_COM_SECONDS", 3.0),
            patch.object(collect_logger.time, "sleep") as sleep,
        ):
            collect_logger.main(["U1_CH1"], managed=False, diagnose=True)
        self.logger.Stop.assert_called_once()
        sleep.assert_called_once_with(3.0)
        logs = list(self.diagnostic_folder.glob("collect_logger_diag_*.jsonl"))
        content = logs[0].read_text()
        self.assertIn("hold_com_begin", content)
        self.assertIn("hold_com_end", content)

    def test_rejects_channels_outside_the_single_eight_channel_unit(self):
        for channel in ("U2_CH1", "U1_CH0", "U1_CH9"):
            with self.subTest(channel=channel):
                with self.assertRaisesRegex(ValueError, "U1_CH1〜U1_CH8"):
                    collect_logger.main([channel], managed=False)
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
                    with self.assertRaisesRegex(RuntimeError, f"{error_message}（123）"):
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
