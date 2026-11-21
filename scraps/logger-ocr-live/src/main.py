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
        "unit": "mpm",
        "low_point": (0.0, 0.0),
        "high_point": (8.0, 50),
    },
    "U1_CH2": {
        "name": "load_OP",
        "unit": "ton",
        "low_point": (0.0, 0.0),
        "high_point": (10.0, 300),
    },
    "U1_CH3": {
        "name": "load_DR",
        "unit": "ton",
        "low_point": (0.0, 0.0),
        "high_point": (10.0, 300),
    },
    # "U1_CH4": {
    #     "name": "tension_in",
    #     "unit": "kg",
    #     "low_point": (0.0, 0.0),
    #     "high_point": (8.0, 6000),
    # },
    # "U1_CH5": {
    #     "name": "tension_out",
    #     "unit": "kg",
    #     "low_point": (0.0, 0.0),
    #     "high_point": (8.0, 6000),
    # },
    "U1_CH6": {
        "name": "bender_Inc",
        "unit": "kg/cm²",
        "low_point": (1.0, 0.0),
        "high_point": (3.0, 100),
    },
    "U1_CH7": {
        "name": "bender_Dec",
        "unit": "kg/cm²",
        "low_point": (1.0, 0.0),
        "high_point": (3.0, 100),
    },
    # "U1_CH8": {
    #     "name": "exit_thickness",
    #     "unit": "mm",
    #     "low_point": (0.0, 0.0),
    #     "high_point": (10.0, 100),
    # },
}
MAX_TIME_GAP = 0.15
INPUT_TIMEOUT = 1.0
STARTUP_TIMEOUT = 30.0
FAILURE_TIMEOUT = 15.0
STOP_TIMEOUT = 15.0


def main():
    validate_settings()

    script_folder = Path(__file__).resolve().parent
    logger_script = script_folder / "logger.py"
    ocr_script = script_folder / "counter.py"
    logger_command = [sys.executable, str(logger_script), "--managed"]
    logger_command.extend(CHANNELS.keys())
    ocr_command = [sys.executable, str(ocr_script), "--managed"]
    commands_by_source = {"logger": logger_command, "ocr": ocr_command}

    output_queue = Queue(maxsize=64)
    reader_errors = Queue()
    stop_readers = Event()
    processes_by_source = {}
    stdout_readers = []
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
                args=(
                    source,
                    process.stdout,
                    output_queue,
                    reader_errors,
                    stop_readers,
                ),
                daemon=True,
            )
            stdout_reader.start()
            stdout_readers.append(stdout_reader)

        finished_source = write_readings_csv(
            output_queue, reader_errors, processes_by_source
        )
    except KeyboardInterrupt:
        finished_source = None
    finally:
        stopped_cleanly = stop_children(
            processes_by_source, stdout_readers, stop_readers
        )
        while True:
            try:
                failed_source, read_error = reader_errors.get_nowait()
            except Empty:
                break
            print(f"{failed_source} 出力読取失敗（{read_error}）", file=sys.stderr)
            stopped_cleanly = False

    if not stopped_cleanly:
        raise RuntimeError("取得を正常に終了できない（機器の停止を確認）")
    if finished_source is None:
        print("照合終了", file=sys.stderr)
    else:
        print(f"{finished_source} 取得終了", file=sys.stderr)


def stop_children(processes_by_source, stdout_readers, stop_readers):
    stop_readers.set()
    stopped_cleanly = True
    for source, process in processes_by_source.items():
        try:
            process.stdin.close()
        except OSError as error:
            print(f"{source} 停止要求失敗（{error}）", file=sys.stderr)
            stopped_cleanly = False

    stop_deadline = time.monotonic() + STOP_TIMEOUT
    for source, process in processes_by_source.items():
        try:
            remaining_seconds = max(0, stop_deadline - time.monotonic())
            try:
                process.wait(timeout=remaining_seconds)
            except subprocess.TimeoutExpired:
                print(
                    f"{source} 強制終了（停止タイムアウト、機器の停止未確認）",
                    file=sys.stderr,
                )
                stopped_cleanly = False
                process.kill()
                process.wait(timeout=5)
            if process.returncode != 0:
                print(
                    f"{source} 異常終了（コード {process.returncode}）",
                    file=sys.stderr,
                )
                stopped_cleanly = False
        except (OSError, subprocess.TimeoutExpired) as error:
            print(f"{source} 終了確認失敗（{error}）", file=sys.stderr)
            stopped_cleanly = False

    for stdout_reader in stdout_readers:
        stdout_reader.join(timeout=1)
        if stdout_reader.is_alive():
            print("出力読取スレッドの終了未確認", file=sys.stderr)
            stopped_cleanly = False
    return stopped_cleanly


def validate_settings():
    if not CHANNELS:
        raise ValueError("CHANNELS未設定")
    if not math.isfinite(MAX_TIME_GAP) or MAX_TIME_GAP <= 0:
        raise ValueError("MAX_TIME_GAPは正の秒数")
    timeouts = {
        "INPUT_TIMEOUT": INPUT_TIMEOUT,
        "STARTUP_TIMEOUT": STARTUP_TIMEOUT,
        "FAILURE_TIMEOUT": FAILURE_TIMEOUT,
        "STOP_TIMEOUT": STOP_TIMEOUT,
    }
    for name, seconds in timeouts.items():
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError(f"{name}は正の秒数")
    if FAILURE_TIMEOUT <= INPUT_TIMEOUT:
        raise ValueError("FAILURE_TIMEOUTはINPUT_TIMEOUTより長い秒数")

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


def read_child_output(source, child_stdout, output_queue, reader_errors, stop_readers):
    try:
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
    except Exception as error:
        reader_errors.put((source, error))


def write_readings_csv(output_queue, reader_errors, processes_by_source):
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
    last_fresh_at_by_source = {"logger": None, "ocr": None}
    timed_out_sources = set()
    while True:
        try:
            queued_output = output_queue.get(timeout=0.1)
        except Empty:
            queued_output = None

        processing_started_at = time.monotonic()
        try:
            failed_source, read_error = reader_errors.get_nowait()
        except Empty:
            pass
        else:
            raise RuntimeError(
                f"{failed_source} 出力読取失敗（{read_error}）"
            ) from read_error
        for monitored_source, process in processes_by_source.items():
            returncode = process.poll()
            if returncode is not None and returncode != 0:
                raise RuntimeError(
                    f"{monitored_source} 異常終了（コード {returncode}）"
                )

        logger_message = None
        if queued_output is not None:
            source, line, line_read_at = queued_output
            if line == "":
                return source
            try:
                message = json.loads(line)
                acquired_mono_ns = message["acquired_mono_ns"]
                if type(acquired_mono_ns) is not int or acquired_mono_ns < 0:
                    raise ValueError("acquired_mono_nsは0以上の整数")
                acquired_at = acquired_mono_ns / 1_000_000_000
                if acquired_at > line_read_at:
                    raise ValueError("取得時刻が受信時刻より未来")
                received_at = datetime.fromisoformat(message["received_at"])
                if received_at.tzinfo is None:
                    raise ValueError("received_atのタイムゾーン欠落")
                if source == "ocr":
                    value = message["value"]
                    if value is not None and (
                        type(value) not in (int, float) or not math.isfinite(value)
                    ):
                        raise ValueError("valueは有限の数値またはnull")
                else:
                    for channel_name in CHANNELS:
                        voltage = message["voltages"][channel_name]
                        if voltage is not None and type(voltage) not in (int, float):
                            raise ValueError(f"{channel_name}は数値またはnull")
            except (ValueError, KeyError, TypeError) as error:
                raise RuntimeError(f"{source} 出力データ不正（{error}）") from error

            sample_age_seconds = processing_started_at - acquired_at
            if sample_age_seconds <= INPUT_TIMEOUT:
                last_fresh_at_by_source[source] = acquired_at
                timed_out_sources.discard(source)
                if source == "ocr":
                    previous_value_confirmed = (
                        latest_ocr_message is not None
                        and latest_ocr_message["value"] is not None
                    )
                    if previous_value_confirmed and message["value"] is None:
                        print("OCR値未確定", file=sys.stderr)
                    latest_ocr_message = message
                else:
                    logger_message = message

        for monitored_source, last_fresh_at in last_fresh_at_by_source.items():
            if last_fresh_at is None:
                if processing_started_at - waiting_since > STARTUP_TIMEOUT:
                    raise RuntimeError(f"{monitored_source} 起動タイムアウト")
                continue
            seconds_since_last_fresh = processing_started_at - last_fresh_at
            if seconds_since_last_fresh > FAILURE_TIMEOUT:
                raise RuntimeError(f"{monitored_source} 更新停止（両方の取得を停止）")
            if seconds_since_last_fresh > INPUT_TIMEOUT:
                if monitored_source not in timed_out_sources:
                    print(f"{monitored_source} 受信タイムアウト", file=sys.stderr)
                    timed_out_sources.add(monitored_source)
                if monitored_source == "ocr":
                    latest_ocr_message = None

        if logger_message is not None:
            row = build_csv_row(
                logger_message, latest_ocr_message, CHANNELS, MAX_TIME_GAP
            )
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
        main()
    except (OSError, ValueError, RuntimeError) as error:
        print(error, file=sys.stderr)
        sys.exit(1)
