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

CHANNELS = {
    "U1_CH1": {
        "name": "rolling_speed",
        "unit": "",
        "low_point": (None, None),
        "high_point": (None, None),
    },
    "U1_CH2": {
        "name": "load_OP",
        "unit": "",
        "low_point": (None, None),
        "high_point": (None, None),
    },
    "U1_CH3": {
        "name": "load_DR",
        "unit": "",
        "low_point": (None, None),
        "high_point": (None, None),
    },
    "U1_CH4": {
        "name": "tension_in",
        "unit": "",
        "low_point": (None, None),
        "high_point": (None, None),
    },
    "U1_CH5": {
        "name": "tension_out",
        "unit": "",
        "low_point": (None, None),
        "high_point": (None, None),
    },
    "U1_CH6": {
        "name": "bender_Inc",
        "unit": "",
        "low_point": (None, None),
        "high_point": (None, None),
    },
    "U1_CH7": {
        "name": "bender_Dec",
        "unit": "",
        "low_point": (None, None),
        "high_point": (None, None),
    },
    "U1_CH8": {
        "name": "exit_thickness",
        "unit": "",
        "low_point": (None, None),
        "high_point": (None, None),
    },
}
MAX_TIME_GAP = 0.15
INPUT_TIMEOUT = 1.0


def main():
    validate_settings()

    folder = Path(__file__).resolve().parent
    logger_command = [sys.executable, str(folder / "collect_logger.py"), "--managed"]
    logger_command.extend(CHANNELS.keys())
    ocr_command = [sys.executable, str(folder / "read_meter.py"), "--managed"]
    commands = {"logger": logger_command, "ocr": ocr_command}

    received_lines = Queue(maxsize=64)
    stop_requested = Event()
    processes = {}
    try:
        for source, command in commands.items():
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                encoding="utf-8",
            )
            processes[source] = process

            reader = Thread(
                target=read_child_output,
                args=(source, process.stdout, received_lines, stop_requested),
                daemon=True,
            )
            reader.start()

        finished_source = write_readings_csv(received_lines)
    finally:
        stop_requested.set()
        for process in processes.values():
            process.stdin.close()
        for source, process in processes.items():
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print(f"{source} を強制終了（停止待ちタイムアウト）", file=sys.stderr)
                process.kill()
                process.wait()

    for source, process in processes.items():
        if process.returncode != 0:
            raise RuntimeError(
                f"{source} 取得異常終了（終了コード {process.returncode}）"
            )
    print(f"{finished_source} 取得終了", file=sys.stderr)


def validate_settings():
    if not CHANNELS:
        raise ValueError("CHANNELSにCHと換算設定を指定")
    if not math.isfinite(MAX_TIME_GAP) or MAX_TIME_GAP <= 0:
        raise ValueError("MAX_TIME_GAPは正の秒数")
    if not math.isfinite(INPUT_TIMEOUT) or INPUT_TIMEOUT <= 0:
        raise ValueError("INPUT_TIMEOUTは正の秒数")

    for channel, settings in CHANNELS.items():
        if not settings["unit"]:
            raise ValueError(f"{channel} のunitに換算後の単位を指定")
        low_voltage, low_value = settings["low_point"]
        high_voltage, high_value = settings["high_point"]
        for number in (low_voltage, low_value, high_voltage, high_value):
            if number is None or not math.isfinite(number):
                raise ValueError(f"{channel} のlow_pointとhigh_pointに有限の数値を指定")
        if not -10.0 <= low_voltage < high_voltage <= 10.0:
            raise ValueError(f"{channel} の基準電圧は-10〜10Vで low_point < high_point")


def read_child_output(source, stream, received_lines, stop_requested):
    with stream:
        while True:
            line = stream.readline()
            line_read_at = time.monotonic()
            line_info = (source, line, line_read_at)
            while not stop_requested.is_set():
                try:
                    received_lines.put(line_info, timeout=0.1)
                    break
                except Full:
                    continue
            if line == "":
                break


def write_readings_csv(received_lines):
    writer = csv.writer(sys.stdout, lineterminator="\n")
    columns = ["received_at"]
    for channel, settings in CHANNELS.items():
        columns.extend([f"{channel}_V", f"{settings['name']}_{settings['unit']}"])
    columns.extend(
        ["ocr_received_at", "ocr_value", "time_gap_s", "voltage_status", "ocr_status"]
    )
    writer.writerow(columns)
    sys.stdout.flush()

    latest_ocr = None
    started_at = time.monotonic()
    last_read_at_by_source = {"logger": started_at, "ocr": started_at}
    while True:
        try:
            line_info = received_lines.get(timeout=0.1)
        except Empty:
            line_info = None

        now = time.monotonic()
        for input_source, last_read_at in last_read_at_by_source.items():
            if last_read_at is not None and now - last_read_at > INPUT_TIMEOUT:
                print(f"{input_source} 受信停止（照合は欠測）", file=sys.stderr)
                last_read_at_by_source[input_source] = None
                if input_source == "ocr":
                    latest_ocr = None

        if line_info is None:
            continue
        source, line, line_read_at = line_info
        if line == "":
            return source
        if now - line_read_at > INPUT_TIMEOUT:
            continue

        message = json.loads(line)
        last_read_at_by_source[source] = line_read_at
        if source == "ocr":
            had_ocr_value = latest_ocr is not None and latest_ocr["value"] is not None
            if had_ocr_value and message["value"] is None:
                print("OCR値未確定（照合は欠測）", file=sys.stderr)
            latest_ocr = message
            continue

        row = build_csv_row(message, latest_ocr, CHANNELS, MAX_TIME_GAP)
        writer.writerow(row)
        sys.stdout.flush()


def build_csv_row(logger_message, latest_ocr, channels, max_time_gap):
    logger_received_at = logger_message["received_at"]
    row = [logger_received_at]
    voltages = logger_message["voltages"]
    voltage_status = "valid"
    for channel, settings in channels.items():
        if channel not in voltages:
            raise ValueError(f"ロガーの電圧欠落（{channel}）")
        voltage = voltages[channel]
        low_voltage, low_value = settings["low_point"]
        high_voltage, high_value = settings["high_point"]

        converted_value = None
        if voltage is not None and low_voltage <= voltage <= high_voltage:
            voltage_span = high_voltage - low_voltage
            value_change = high_value - low_value
            fraction = (voltage - low_voltage) / voltage_span
            converted_value = low_value + fraction * value_change
        else:
            voltage_status = "invalid"
        row.extend([voltage, converted_value])

    ocr_received_at = None
    ocr_value = None
    time_gap = None
    ocr_status = "waiting"
    if latest_ocr is not None:
        ocr_received_at = latest_ocr["received_at"]
        ocr_value = latest_ocr["value"]
        logger_time = datetime.fromisoformat(logger_received_at)
        ocr_time = datetime.fromisoformat(ocr_received_at)
        time_difference = logger_time - ocr_time
        time_gap = abs(time_difference.total_seconds())
        if ocr_value is None:
            ocr_status = "unreadable"
        elif time_gap > max_time_gap:
            ocr_status = "time_gap"
        else:
            ocr_status = "ready"
    row.extend([ocr_received_at, ocr_value, time_gap, voltage_status, ocr_status])
    return row


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("照合終了", file=sys.stderr)
