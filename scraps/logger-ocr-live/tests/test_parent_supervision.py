"""模擬データと実際の子プロセスで、親の監視と終了処理を確認する。"""

import csv
import importlib.util
import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from queue import Queue
from threading import Event, Thread
from unittest.mock import Mock, patch

SCRIPT = Path(__file__).resolve().parents[1] / "main.py"
SPEC = importlib.util.spec_from_file_location("parent_under_test", SCRIPT)
parent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(parent)
POPEN = subprocess.Popen


class ParentSupervisionTests(unittest.TestCase):
    def setUp(self):
        self.output = io.StringIO()
        self.notices = io.StringIO()
        self.enterContext(redirect_stdout(self.output))
        self.enterContext(redirect_stderr(self.notices))
        self.processes = []
        self.addCleanup(self.reap_children)
        self.enterContext(
            patch.multiple(
                parent,
                STARTUP_TIMEOUT=3.0,
                INPUT_TIMEOUT=0.2,
                FAILURE_TIMEOUT=0.6,
                STOP_TIMEOUT=1.0,
            )
        )

    def reap_children(self):
        for process in self.processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            process.stdin.close()
            process.stdout.close()

    def child_code(self, source, *, after_sample="sys.stdin.buffer.read()"):
        if source == "logger":
            fields = {"voltages": {name: 1.0 for name in parent.CHANNELS}}
        else:
            fields = {"value": 1.234}
        return f"""
import json, sys, time
from datetime import UTC, datetime
message = {fields!r}
message['received_at'] = datetime.now(UTC).isoformat()
message['acquired_mono_ns'] = time.monotonic_ns()
print(json.dumps(message), flush=True)
{after_sample}
"""

    def launch_children(self, codes):
        def launch(command, **kwargs):
            source = "logger" if Path(command[1]).name == "logger.py" else "ocr"
            code = codes[source]
            if isinstance(code, Exception):
                raise code
            process = POPEN([sys.executable, "-u", "-c", code], **kwargs)
            self.processes.append(process)
            return process

        self.enterContext(patch.object(parent.subprocess, "Popen", side_effect=launch))

    def test_normal_eof_stops_other_child(self):
        self.launch_children(
            {
                "logger": self.child_code("logger"),
                "ocr": self.child_code("ocr", after_sample=""),
            }
        )
        parent.main()
        self.assertEqual([process.returncode for process in self.processes], [0, 0])
        self.assertIn("ocr 取得終了", self.notices.getvalue())

    def test_child_crash_is_reported_and_other_child_stops(self):
        self.launch_children(
            {"logger": "import sys; sys.exit(7)", "ocr": self.child_code("ocr")}
        )
        with self.assertRaises(RuntimeError):
            parent.main()
        self.assertEqual([process.returncode for process in self.processes], [7, 0])
        self.assertIn("logger 異常終了（コード 7）", self.notices.getvalue())
        self.assertNotIn("取得終了", self.notices.getvalue())

    def test_decode_failure_reaches_parent(self):
        bad_output = r"import sys; sys.stdout.buffer.write(b'\xff\n'); sys.stdout.flush(); sys.stdin.buffer.read()"
        self.launch_children({"logger": self.child_code("logger"), "ocr": bad_output})
        with self.assertRaisesRegex(RuntimeError, "ocr 出力読取失敗"):
            parent.main()
        self.assertTrue(all(process.poll() is not None for process in self.processes))

    def test_silent_child_is_stopped_while_other_child_keeps_updating(self):
        self.enterContext(patch.object(parent, "STOP_TIMEOUT", 0.3))
        keep_updating = """
from threading import Event, Thread
stop = Event()
def watch_stdin():
    sys.stdin.buffer.read()
    stop.set()
Thread(target=watch_stdin, daemon=True).start()
while not stop.wait(0.02):
    message['received_at'] = datetime.now(UTC).isoformat()
    message['acquired_mono_ns'] = time.monotonic_ns()
    print(json.dumps(message), flush=True)
"""
        self.launch_children(
            {
                "logger": self.child_code("logger", after_sample="time.sleep(60)"),
                "ocr": self.child_code("ocr", after_sample=keep_updating),
            }
        )
        with self.assertRaisesRegex(RuntimeError, "logger 更新停止"):
            parent.main()
        self.assertIsNotNone(self.processes[0].returncode)
        self.assertEqual(self.processes[1].returncode, 0)
        self.assertIn("logger 強制終了", self.notices.getvalue())

    def test_bad_json_is_preserved_when_child_needs_forced_stop(self):
        self.enterContext(patch.object(parent, "STOP_TIMEOUT", 0.1))
        self.launch_children(
            {
                "logger": self.child_code("logger"),
                "ocr": "import time; print('broken json', flush=True); time.sleep(60)",
            }
        )
        with self.assertRaisesRegex(RuntimeError, "ocr 出力データ不正"):
            parent.main()
        self.assertTrue(all(process.poll() is not None for process in self.processes))
        self.assertIn("ocr 強制終了", self.notices.getvalue())
        self.assertIn("機器の停止未確認", self.notices.getvalue())

    def test_second_child_start_failure_stops_first_child(self):
        self.launch_children(
            {"logger": self.child_code("logger"), "ocr": OSError("起動失敗")}
        )
        with self.assertRaisesRegex(OSError, "起動失敗"):
            parent.main()
        self.assertEqual(len(self.processes), 1)
        self.assertEqual(self.processes[0].returncode, 0)

    def test_keyboard_interrupt_stops_both_children(self):
        self.launch_children(
            {"logger": self.child_code("logger"), "ocr": self.child_code("ocr")}
        )
        with patch.object(parent, "write_readings_csv", side_effect=KeyboardInterrupt):
            parent.main()
        self.assertEqual([process.returncode for process in self.processes], [0, 0])
        self.assertIn("照合終了", self.notices.getvalue())

    def test_output_failure_stops_both_children(self):
        self.launch_children(
            {"logger": self.child_code("logger"), "ocr": self.child_code("ocr")}
        )
        with patch.object(self.output, "write", side_effect=OSError("保存失敗")):
            with self.assertRaisesRegex(OSError, "保存失敗"):
                parent.main()
        self.assertEqual([process.returncode for process in self.processes], [0, 0])

    def test_normal_shutdown_waits_for_child_cleanup(self):
        self.launch_children(
            {
                "logger": self.child_code(
                    "logger", after_sample="sys.stdin.buffer.read(); time.sleep(0.3)"
                ),
                "ocr": self.child_code("ocr", after_sample=""),
            }
        )
        parent.main()
        self.assertEqual([process.returncode for process in self.processes], [0, 0])
        self.assertNotIn("強制終了", self.notices.getvalue())

    def test_reader_failure_during_shutdown_is_not_normal_completion(self):
        output_queue = Queue()
        reader_errors = Queue()

        def stop_with_reader_failure(processes, readers, stop_readers):
            reader_errors.put(("ocr", OSError("終了中の読取失敗")))
            return True

        with (
            patch.object(parent, "Queue", side_effect=[output_queue, reader_errors]),
            patch.object(parent.subprocess, "Popen"),
            patch.object(parent, "Thread"),
            patch.object(parent, "write_readings_csv", return_value="logger"),
            patch.object(parent, "stop_children", side_effect=stop_with_reader_failure),
        ):
            with self.assertRaisesRegex(RuntimeError, "正常に終了できない"):
                parent.main()
        self.assertIn("ocr 出力読取失敗", self.notices.getvalue())
        self.assertNotIn("取得終了", self.notices.getvalue())

    def test_shutdown_drains_stdout_when_data_queue_is_full(self):
        code = "import sys; [print('sample', flush=True) for _ in range(10000)]; sys.stdin.buffer.read()"
        process = POPEN(
            [sys.executable, "-u", "-c", code],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            encoding="utf-8",
        )
        self.processes.append(process)
        output_queue = Queue(maxsize=1)
        output_queue.put("full")
        reader_errors = Queue()
        stop_readers = Event()
        reader = Thread(
            target=parent.read_child_output,
            args=("logger", process.stdout, output_queue, reader_errors, stop_readers),
            daemon=True,
        )
        reader.start()
        self.assertTrue(
            parent.stop_children({"logger": process}, [reader], stop_readers)
        )
        self.assertEqual(process.returncode, 0)
        self.assertFalse(reader.is_alive())
        self.assertTrue(reader_errors.empty())

    def test_stop_error_does_not_skip_other_child(self):
        failed_process = Mock()
        failed_process.wait.side_effect = OSError("待機失敗")
        other_process = Mock(returncode=0)
        self.assertFalse(
            parent.stop_children(
                {"logger": failed_process, "ocr": other_process}, [], Event()
            )
        )
        failed_process.stdin.close.assert_called_once()
        other_process.stdin.close.assert_called_once()
        other_process.wait.assert_called_once()
        self.assertIn("logger 終了確認失敗", self.notices.getvalue())

    def test_startup_timeout_without_any_output(self):
        with patch.object(parent.time, "monotonic", side_effect=[0.0, 3.1]):
            with self.assertRaisesRegex(RuntimeError, "logger 起動タイムアウト"):
                parent.write_readings_csv(Queue(), Queue(), {})

    def test_sustained_silence_raises_even_when_child_is_alive(self):
        output_queue = Queue()
        message = {
            "received_at": "2026-11-12T00:00:00+00:00",
            "acquired_mono_ns": 0,
            "value": None,
        }
        output_queue.put(("ocr", json.dumps(message), 0.0))
        running_process = Mock()
        running_process.poll.return_value = None
        with patch.object(parent.time, "monotonic", side_effect=[0.0, 0.0, 0.7]):
            with self.assertRaisesRegex(RuntimeError, "ocr 更新停止"):
                parent.write_readings_csv(
                    output_queue, Queue(), {"ocr": running_process}
                )

    def test_fresh_pipe_read_does_not_make_old_sample_current(self):
        output_queue = Queue()
        message = {
            "received_at": "2026-11-12T00:00:00+00:00",
            "acquired_mono_ns": 0,
            "voltages": {name: 1.0 for name in parent.CHANNELS},
        }
        output_queue.put(("logger", json.dumps(message), 2.0))
        output_queue.put(("logger", "", 2.0))
        with patch.object(parent.time, "monotonic", return_value=2.0):
            self.assertEqual(
                parent.write_readings_csv(output_queue, Queue(), {}), "logger"
            )
        self.assertEqual(list(csv.DictReader(io.StringIO(self.output.getvalue()))), [])

    def test_unreadable_ocr_samples_still_count_as_updates(self):
        output_queue = Queue()
        clock_times = [0.0]
        for index in range(16):
            acquired_at = index / 10
            message = {
                "received_at": "2026-11-12T00:00:00+00:00",
                "acquired_mono_ns": index * 100_000_000,
                "value": None,
            }
            output_queue.put(("ocr", json.dumps(message), acquired_at))
            clock_times.append(acquired_at)
        output_queue.put(("ocr", "", 1.6))
        clock_times.append(1.6)
        with patch.object(parent.time, "monotonic", side_effect=clock_times):
            self.assertEqual(
                parent.write_readings_csv(output_queue, Queue(), {}), "ocr"
            )
        self.assertNotIn("タイムアウト", self.notices.getvalue())

    def test_reader_error_is_not_hidden_by_full_data_queue(self):
        output_queue = Queue(maxsize=1)
        output_queue.put(("logger", "bad json", 0.0))
        reader_errors = Queue()
        reader_errors.put(("ocr", OSError("読取失敗")))
        with self.assertRaisesRegex(RuntimeError, "ocr 出力読取失敗"):
            parent.write_readings_csv(output_queue, reader_errors, {})

    def test_malformed_sample_fields_are_attributed_to_source(self):
        valid_message = {
            "received_at": "2026-11-12T00:00:00+00:00",
            "acquired_mono_ns": 0,
            "value": None,
        }
        for field, value in (
            ("received_at", "2026-11-12T00:00:00"),
            ("acquired_mono_ns", -1),
            ("acquired_mono_ns", True),
            ("acquired_mono_ns", 1_000_000_000),
            ("value", "1.234"),
        ):
            with self.subTest(field=field, value=value):
                message = dict(valid_message)
                message[field] = value
                output_queue = Queue()
                output_queue.put(("ocr", json.dumps(message), 0.0))
                with self.assertRaisesRegex(RuntimeError, "ocr 出力データ不正"):
                    parent.write_readings_csv(output_queue, Queue(), {})


if __name__ == "__main__":
    unittest.main()
