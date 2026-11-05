"""実機や画面を使わず、現在値のCSV出力とグラフ履歴を確認する。"""

from contextlib import ExitStack, redirect_stdout
import csv
import importlib.util
import io
import math
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, call, patch


SCRIPT = Path(__file__).resolve().parents[1] / "collect_logger.py"
SPEC = importlib.util.spec_from_file_location("gauge_collect_logger", SCRIPT)
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

        self.figure = Mock()
        self.axes = Mock()
        self.lines = [Mock() for _ in range(8)]
        self.axes.plot.side_effect = [[line] for line in self.lines]
        self.plt = Mock()
        self.plt.subplots.return_value = (self.figure, self.axes)
        self.plt.fignum_exists.return_value = True
        pythoncom = types.SimpleNamespace(
            CoCreateInstance=Mock(), CLSCTX_SERVER=21, IID_IDispatch=object()
        )
        dynamic = types.SimpleNamespace(Dispatch=Mock(return_value=self.logger))
        modules = {
            "pythoncom": pythoncom,
            "win32com": types.SimpleNamespace(),
            "win32com.client": types.SimpleNamespace(dynamic=dynamic),
            "matplotlib": types.SimpleNamespace(use=Mock(), pyplot=self.plt),
            "matplotlib.pyplot": self.plt,
        }
        self.contexts.enter_context(patch.dict(sys.modules, modules))
        self.clock = self.contexts.enter_context(patch.object(collect_logger.time, "monotonic"))
        self.clock.side_effect = [100.0, 100.2]
        self.output = io.StringIO()
        self.contexts.enter_context(redirect_stdout(self.output))

    def test_csv_keeps_repeated_values_without_waveform_positions(self):
        self.logger.GetState.side_effect = [5, 5, 1]
        self.clock.side_effect = [100.0, 100.2, 100.4]

        collect_logger.main()

        rows = list(csv.reader(io.StringIO(self.output.getvalue())))
        self.assertEqual(rows[0], ["elapsed_s"] + [f"U1_CH{channel}" for channel in range(1, 9)])
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1][1:], ["1.25"] * 8)
        self.assertEqual(rows[2][1:], rows[1][1:])
        self.assertEqual(self.waveform.GetCurrentData.call_args_list,
                         [call(1, channel) for channel in range(8)] * 2)
        self.logger.Stop.assert_called_once()
        self.plt.close.assert_called_once_with(self.figure)

    def test_invalid_current_values_break_the_graph_line(self):
        self.waveform.GetCurrentData.side_effect = [3.4028235e38, float("nan")] + [1.25] * 6

        collect_logger.main()

        rows = list(csv.reader(io.StringIO(self.output.getvalue())))
        self.assertEqual(rows[1][1:], ["nan", "nan"] + ["1.25"] * 6)
        for line in self.lines[:2]:
            values = line.set_data.call_args.args[1]
            self.assertTrue(math.isnan(values[0]))

    def test_history_discards_points_older_than_the_time_window(self):
        self.logger.GetState.side_effect = [5, 5, 5, 1]
        self.clock.side_effect = [100.0, 101.0, 102.0, 104.0]
        self.waveform.GetCurrentData.side_effect = list(range(1, 25))

        with patch.object(collect_logger, "WINDOW_SECONDS", 2):
            collect_logger.main()

        self.lines[0].set_data.assert_called_with([2.0, 4.0], [9, 17])
        self.lines[7].set_data.assert_called_with([2.0, 4.0], [16, 24])
        self.axes.set_xlim.assert_called_with(2.0, 4.0)

    def test_waits_for_startup_before_reading(self):
        self.logger.GetState.side_effect = [1, 5, 1]

        collect_logger.main()

        self.assertEqual(self.waveform.GetCurrentData.call_count, 8)
        self.assertEqual(self.plt.pause.call_count, 2)
        self.logger.Stop.assert_called_once()

    def test_read_failure_stops_collection_and_closes_the_graph(self):
        self.waveform.GetCurrentData.side_effect = RuntimeError("read failed")

        with self.assertRaisesRegex(RuntimeError, "read failed"):
            collect_logger.main()

        self.logger.Stop.assert_called_once()
        self.plt.close.assert_called_once_with(self.figure)


if __name__ == "__main__":
    unittest.main()
