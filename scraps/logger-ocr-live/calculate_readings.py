import csv
import json
import math
import os
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

# 連携起動の診断実験。単体での --stop-on-key と条件を分けて試す。
LOGGER_ATTACH = False
LOGGER_DIAGNOSE = False
CHILD_STOP_TIMEOUT = 5.0
# LOGGER_ATTACH = True
# LOGGER_DIAGNOSE = True
# CHILD_STOP_TIMEOUT = 20.0  # Stop()検証に時間がかかる場合のみ


def keyboard_stop_requested():
    """Windows端末でQキーが押されたら、Ctrl+Cを送らずに終了する。"""
    import msvcrt

    while msvcrt.kbhit():
        if msvcrt.getwch().lower() == "q":
            return True
    return False


def main(stop_on_key=False):
    validate_settings()
    if stop_on_key and (os.name != "nt" or not sys.stdin.isatty()):
        raise ValueError("--stop-on-keyはWindowsコンソールで指定")

    script_folder = Path(__file__).resolve().parent
    logger_script = script_folder / "collect_logger.py"
    ocr_script = script_folder / "read_meter.py"
    logger_command = [sys.executable, str(logger_script), "--managed"]
    if LOGGER_ATTACH:
        logger_command.append("--attach")
    if LOGGER_DIAGNOSE:
        logger_command.append("--diagnose")
    logger_command.extend(CHANNELS.keys())
    ocr_command = [sys.executable, str(ocr_script), "--managed"]
    commands_by_source = {"logger": logger_command, "ocr": ocr_command}

    output_queue = Queue(maxsize=64)
    stop_readers = Event()
    processes_by_source = {}
    try:
        for source, command in commands_by_source.items():
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                encoding="utf-8",
            )
            processes_by_source[source] = process

            stdout_reader = Thread(
                target=read_child_output,
                args=(source, process.stdout, output_queue, stop_readers),
                daemon=True,
            )
            stdout_reader.start()

        finished_source = write_readings_csv(output_queue, stop_on_key=stop_on_key)
    finally:
        stop_readers.set()
        for process in processes_by_source.values():
            process.stdin.close()
        for source, process in processes_by_source.items():
            try:
                process.wait(timeout=CHILD_STOP_TIMEOUT)
            except subprocess.TimeoutExpired:
                print(f"{source} 強制終了（停止タイムアウト）", file=sys.stderr)
                process.kill()
                process.wait()

    for source, process in processes_by_source.items():
        if process.returncode != 0:
            raise RuntimeError(f"{source} 異常終了（コード {process.returncode}）")
    print(f"{finished_source} 取得終了", file=sys.stderr)


def validate_settings():
    if not CHANNELS:
        raise ValueError("CHANNELS未設定")
    if not math.isfinite(MAX_TIME_GAP) or MAX_TIME_GAP <= 0:
        raise ValueError("MAX_TIME_GAPは正の秒数")
    if not math.isfinite(INPUT_TIMEOUT) or INPUT_TIMEOUT <= 0:
        raise ValueError("INPUT_TIMEOUTは正の秒数")

    for channel_name, channel_settings in CHANNELS.items():
        if not channel_settings["unit"]:
            raise ValueError(f"{channel_name} のunit未設定")
        low_voltage, low_value = channel_settings["low_point"]
        high_voltage, high_value = channel_settings["high_point"]
        for number in (low_voltage, low_value, high_voltage, high_value):
            if number is None or not math.isfinite(number):
                raise ValueError(f"{channel_name} のlow_point・high_pointは有限の数値")
        if not -10.0 <= low_voltage < high_voltage <= 10.0:
            raise ValueError(
                f"{channel_name} の基準電圧は-10〜10Vで low_point < high_point"
            )


def read_child_output(source, child_stdout, output_queue, stop_readers):
    with child_stdout:
        while True:
            line = child_stdout.readline()
            line_read_at = time.monotonic()
            queued_output = (source, line, line_read_at)
            while not stop_readers.is_set():
                try:
                    output_queue.put(queued_output, timeout=0.1)
                except Full:
                    continue
                break
            if line == "":
                return


def write_readings_csv(output_queue, stop_on_key=False):
    writer = csv.writer(sys.stdout, lineterminator="\n")
    columns = ["received_at"]
    for channel_name, channel_settings in CHANNELS.items():
        signal_name = channel_settings["name"]
        unit = channel_settings["unit"]
        columns.extend([f"{channel_name}_V", f"{signal_name}_{unit}"])
    columns.extend(
        ["ocr_received_at", "ocr_value", "time_gap_s", "voltage_status", "ocr_status"]
    )
    writer.writerow(columns)
    sys.stdout.flush()

    latest_ocr_message = None
    waiting_since = time.monotonic()
    last_read_at_by_source = {"logger": waiting_since, "ocr": waiting_since}
    while True:
        if stop_on_key and keyboard_stop_requested():
            return "キーボード"
        try:
            queued_output = output_queue.get(timeout=0.1)
        except Empty:
            queued_output = None

        processing_started_at = time.monotonic()
        for monitored_source, last_read_at in last_read_at_by_source.items():
            if last_read_at is None:
                continue
            seconds_since_last_read = processing_started_at - last_read_at
            if seconds_since_last_read > INPUT_TIMEOUT:
                print(f"{monitored_source} 受信タイムアウト", file=sys.stderr)
                last_read_at_by_source[monitored_source] = None
                if monitored_source == "ocr":
                    latest_ocr_message = None

        if queued_output is None:
            continue
        source, line, line_read_at = queued_output
        if line == "":
            return source
        line_age_seconds = processing_started_at - line_read_at
        if line_age_seconds > INPUT_TIMEOUT:
            continue

        message = json.loads(line)
        last_read_at_by_source[source] = line_read_at
        if source == "ocr":
            previous_value_confirmed = (
                latest_ocr_message is not None
                and latest_ocr_message["value"] is not None
            )
            if previous_value_confirmed and message["value"] is None:
                print("OCR値未確定", file=sys.stderr)
            latest_ocr_message = message
            continue

        row = build_csv_row(message, latest_ocr_message, CHANNELS, MAX_TIME_GAP)
        writer.writerow(row)
        sys.stdout.flush()


def build_csv_row(logger_message, latest_ocr_message, channels, max_time_gap):
    logger_received_at = logger_message["received_at"]
    row = [logger_received_at]
    voltages_by_channel = logger_message["voltages"]
    voltage_status = "valid"
    for channel_name, channel_settings in channels.items():
        if channel_name not in voltages_by_channel:
            raise ValueError(f"ロガーの電圧欠落（{channel_name}）")
        measured_voltage = voltages_by_channel[channel_name]
        low_voltage, low_value = channel_settings["low_point"]
        high_voltage, high_value = channel_settings["high_point"]

        converted_value = None
        if (
            measured_voltage is not None
            and low_voltage <= measured_voltage <= high_voltage
        ):
            voltage_span = high_voltage - low_voltage
            voltage_above_low = measured_voltage - low_voltage
            fraction_of_range = voltage_above_low / voltage_span
            value_change = high_value - low_value
            converted_value = low_value + fraction_of_range * value_change
        else:
            voltage_status = "invalid"
        row.extend([measured_voltage, converted_value])

    ocr_received_at = None
    ocr_value = None
    time_gap = None
    ocr_status = "waiting"
    if latest_ocr_message is not None:
        ocr_received_at = latest_ocr_message["received_at"]
        ocr_value = latest_ocr_message["value"]
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
        main(stop_on_key="--stop-on-key" in sys.argv)
    except KeyboardInterrupt:
        print("照合終了", file=sys.stderr)
