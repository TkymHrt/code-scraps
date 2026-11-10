"""プロセス監視ログの抽出と記録を実機なしで確認する。"""

import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "watch_logger_processes.py"
SPEC = importlib.util.spec_from_file_location("watch_logger_processes", SCRIPT)
watcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watcher)


class WatchLoggerProcessesTests(unittest.TestCase):
    def test_matches_image_or_window_title_and_preserves_pid(self):
        output = (
            '"WaveLoggerPro2.exe","1234","Console","1","0 K","Running",'
            '"User","0:00:00","WAVE LOGGER PRO"\n'
            '"other.exe","5678","Console","1","0 K","Running",'
            '"User","0:00:00","other program"\n'
            '"sample.exe","7890","Console","1","0 K","Running",'
            '"User","0:00:00","ウェーブロガー"\n'
        )
        rows = watcher.parse_tasklist(output)
        self.assertEqual([row["pid"] for row in rows], [1234, 7890])
        self.assertEqual(rows[0]["image"], "WaveLoggerPro2.exe")

    def test_process_monitor_flushes_samples_to_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "monitor.jsonl"
            with (
                patch.object(
                    watcher,
                    "read_processes",
                    side_effect=[
                        [{"image": "WaveLoggerPro2.exe", "pid": 1234, "window_title": ""}],
                        [],
                    ],
                ),
                patch.object(watcher.time, "monotonic", side_effect=[0, 0, 1, 1]),
                patch.object(watcher.time, "sleep"),
            ):
                watcher.monitor(1, 0.5, path)
            rows = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["processes"][0]["pid"], 1234)
        self.assertEqual(rows[1]["processes"], [])


if __name__ == "__main__":
    unittest.main()
