"""ロガーの電圧を換算し、時刻の近いOCR値と並べて表示する。"""

import csv
import json
import math
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Thread

# READMEの例を使い、実際に校正したチャンネルだけを設定する。
CHANNELS = {}
MAX_TIME_GAP = 0.15  # 2つのPC受領時刻の許容差（秒）。現場で調整する。
INPUT_TIMEOUT = 1.0  # 受信が止まったと判断するまでの秒数


def validate_settings():
    if not CHANNELS:
        raise ValueError("CHANNELSにチャンネルと換算の設定を指定してください。")
    for seconds in (MAX_TIME_GAP, INPUT_TIMEOUT):
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError(
                "MAX_TIME_GAPとINPUT_TIMEOUTには正の秒数を指定してください。"
            )

    for channel, settings in CHANNELS.items():
        low_voltage, low_value = settings["low_point"]
        high_voltage, high_value = settings["high_point"]
        valid_min, valid_max = settings["valid_voltage"]
        for number in (
            low_voltage,
            low_value,
            high_voltage,
            high_value,
            valid_min,
            valid_max,
        ):
            if not math.isfinite(number):
                raise ValueError(
                    f"{channel} の基準点と許容範囲には有限の数値を指定してください。"
                )
        if not low_voltage <= valid_min < valid_max <= high_voltage:
            raise ValueError(
                f"{channel} の許容電圧範囲を2つの基準点の間に指定してください。"
            )


def convert_voltage(voltage, settings):
    valid_min, valid_max = settings["valid_voltage"]
    if voltage is None or not valid_min <= voltage <= valid_max:
        return None

    low_voltage, low_value = settings["low_point"]
    high_voltage, high_value = settings["high_point"]
    fraction = (voltage - low_voltage) / (high_voltage - low_voltage)
    return low_value + fraction * (high_value - low_value)


def read_output(source, stream, events, stopping):
    # 片側のパイプの読出し待ちで、もう片側の受信を止めない。
    with stream:
        while True:
            line = stream.readline()
            event = (source, line or None, time.monotonic())
            # 終了時はキューが満杯でもパイプを読み続け、子が停止できるようにする。
            while not stopping.is_set():
                try:
                    events.put(event, timeout=0.1)
                    break
                except Full:
                    continue
            if not line:
                break


def show_readings(events):
    writer = csv.writer(sys.stdout, lineterminator="\n")
    columns = ["received_at"]
    for channel, settings in CHANNELS.items():
        columns.extend([f"{channel}_V", f"{settings['name']}_{settings['unit']}"])
    columns.extend(["ocr_received_at", "ocr_value", "time_gap_s", "status"])
    writer.writerow(columns)
    sys.stdout.flush()

    latest_ocr = None
    started_at = time.monotonic()
    last_arrived = {"logger": started_at, "ocr": started_at}
    while True:
        try:
            source, line, arrived_at = events.get(timeout=0.1)
        except Empty:
            source = None

        now = time.monotonic()
        for name, last_arrived_at in last_arrived.items():
            if last_arrived_at is not None and now - last_arrived_at > INPUT_TIMEOUT:
                print(f"{name} の受信が止まりました。照合は欠測です。", file=sys.stderr)
                last_arrived[name] = None
                if name == "ocr":
                    latest_ocr = None

        if source is None:
            continue
        if line is None:
            return source
        if now - arrived_at > INPUT_TIMEOUT:
            continue

        message = json.loads(line)
        last_arrived[source] = arrived_at
        if source == "ocr":
            had_value = latest_ocr is not None and latest_ocr["value"] is not None
            if had_value and message["value"] is None:
                print("OCR値が未確定になりました。照合は欠測です。", file=sys.stderr)
            latest_ocr = message
            continue

        row = [message["received_at"]]
        voltages = message["voltages"]
        all_voltages_valid = True
        for channel, settings in CHANNELS.items():
            if channel not in voltages:
                raise ValueError(f"ロガーから {channel} の電圧が届きませんでした。")
            voltage = voltages[channel]
            value = convert_voltage(voltage, settings)
            if value is None:
                all_voltages_valid = False
            row.extend([voltage, value])

        ocr_received_at = None
        ocr_value = None
        time_gap = None
        status = "waiting_ocr"
        if latest_ocr is not None:
            ocr_received_at = latest_ocr["received_at"]
            ocr_value = latest_ocr["value"]
            logger_time = datetime.fromisoformat(message["received_at"])
            ocr_time = datetime.fromisoformat(ocr_received_at)
            time_gap = abs((logger_time - ocr_time).total_seconds())
            if ocr_value is None:
                status = "ocr_unreadable"
            elif time_gap > MAX_TIME_GAP:
                status = "time_gap"
            elif not all_voltages_valid:
                status = "invalid_voltage"
            else:
                status = "ready"
        row.extend([ocr_received_at, ocr_value, time_gap, status])
        writer.writerow(row)
        sys.stdout.flush()


def main():
    validate_settings()
    folder = Path(__file__).resolve().parent
    events = Queue(maxsize=64)
    stopping = Event()
    processes = {}
    try:
        for source, script in (
            ("logger", "collect_logger.py"),
            ("ocr", "read_meter.py"),
        ):
            command = [sys.executable, str(folder / script), "--managed"]
            if source == "logger":
                command.extend(CHANNELS)
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                encoding="utf-8",
            )
            processes[source] = process
            reader = Thread(
                target=read_output,
                args=(source, process.stdout, events, stopping),
                daemon=True,
            )
            reader.start()

        finished_source = show_readings(events)
        print(f"{finished_source} の取得が終了しました。", file=sys.stderr)
    finally:
        # 先に両方へ停止を伝えてから、COMとカメラの後始末を待つ。
        stopping.set()
        for process in processes.values():
            process.stdin.close()
        for source, process in processes.items():
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print(f"{source} が応答しないため強制終了します。", file=sys.stderr)
                process.kill()
                process.wait()

    for source, process in processes.items():
        if process.returncode != 0:
            raise RuntimeError(
                f"{source} の取得が異常終了しました（終了コード {process.returncode}）。"
            )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("照合を終了しました。", file=sys.stderr)
