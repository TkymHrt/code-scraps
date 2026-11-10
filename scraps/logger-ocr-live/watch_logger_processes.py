"""別のPowerShellから実行し、Python終了後もWAVE LOGGER PROのGUIを監視する。

Windowsのtasklist /vを使用する。COMや計測器には接続しない。
"""

import argparse
import csv
import io
import json
import locale
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# 対象が表示されない場合は、実際のexe名やウィンドウタイトルに合わせる。
PROCESS_KEYWORDS = ("wave", "logger", "ウェーブ", "ロガー")


def parse_tasklist(content):
    """tasklist /v /fo csv /nh の結果から対象プロセスを抜き出す。"""
    results = []
    for row in csv.reader(io.StringIO(content)):
        if len(row) < 9:
            continue
        image_name, pid_text = row[0], row[1]
        window_title = row[-1]
        searchable = (image_name + " " + window_title).casefold()
        if not any(keyword in searchable for keyword in PROCESS_KEYWORDS):
            continue
        if not pid_text.isdecimal():
            continue
        results.append(
            {
                "image": image_name,
                "pid": int(pid_text),
                "window_title": window_title,
            }
        )
    return sorted(results, key=lambda process: process["pid"])


def read_processes():
    if os.name != "nt":
        raise RuntimeError("Windows専用です")
    completed = subprocess.run(
        ["tasklist", "/v", "/fo", "csv", "/nh"],
        capture_output=True,
        text=True,
        encoding=locale.getpreferredencoding(False),
        errors="replace",
        timeout=8,
        check=True,
    )
    return parse_tasklist(completed.stdout)


def monitor(seconds, interval, output):
    deadline = time.monotonic() + seconds
    with output.open("w", encoding="utf-8") as logfile:
        while True:
            record = {
                "at": datetime.now(UTC).isoformat(timespec="milliseconds"),
                "event": "process_snapshot",
            }
            try:
                record["processes"] = read_processes()
            except (OSError, subprocess.SubprocessError, RuntimeError) as error:
                record["error"] = repr(error)
            logfile.write(json.dumps(record, ensure_ascii=False) + "\n")
            logfile.flush()
            if time.monotonic() >= deadline:
                return
            time.sleep(min(interval, max(0, deadline - time.monotonic())))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WAVE LOGGER PROのプロセス経過監視")
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--interval", type=float, default=0.5)
    options = parser.parse_args()
    if not (0 < options.seconds <= 600) or not (0 < options.interval <= 60):
        parser.error("--secondsは0より大きく600以下、--intervalは0より大きく60以下")
    suffix = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    path = Path.cwd() / f"logger_process_watch_{suffix}_{os.getpid()}.jsonl"
    print(f"プロセス監視ログ: {path}", file=sys.stderr, flush=True)
    monitor(options.seconds, options.interval, path)
