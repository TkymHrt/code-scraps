import json
import math
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread

from win32com.client import DispatchEx, dynamic

SETTINGS_FILE = None
DEVICE_ID = 0
READ_INTERVAL = 0.2
CHANNEL_NAMES = [
    "U1_CH1",
    "U1_CH2",
    "U1_CH3",
    "U1_CH4",
    "U1_CH5",
    "U1_CH6",
    "U1_CH7",
    "U1_CH8",
]

COLLECTION_STOPPED = 1
COLLECTION_ERROR_STOPPED = 11
INVALID_VOLTAGE_THRESHOLD = 3.3e38


def main(channel_names, managed):
    if not channel_names and not managed:
        channel_names = CHANNEL_NAMES
    if not channel_names:
        raise ValueError("取得する電圧CHを指定（例 U1_CH1）")
    unit_number = 1
    channel_indexes = {}
    for channel_name in channel_names:
        channel_match = re.fullmatch(r"U1_CH([1-8])", channel_name)
        if channel_match is None:
            raise ValueError(f"電圧CHはU1_CH1〜U1_CH8（指定値 {channel_name}）")
        channel_number_text = channel_match.group(1)
        channel_number = int(channel_number_text)
        channel_indexes[channel_name] = channel_number - 1

    if SETTINGS_FILE is None or not Path(SETTINGS_FILE).is_file():
        raise ValueError("SETTINGS_FILEに既存の .ucf を指定")
    if not 0 <= DEVICE_ID <= 3:
        raise ValueError("DEVICE_IDは0〜3")
    if not math.isfinite(READ_INTERVAL) or READ_INTERVAL <= 0:
        raise ValueError("READ_INTERVALは正の秒数")

    stop_requested = Event()
    if managed:
        parent_watcher = Thread(
            target=watch_parent, args=(stop_requested,), daemon=True
        )
        parent_watcher.start()

    logger, waveform = prepare_logger(SETTINGS_FILE, DEVICE_ID)
    if stop_requested.is_set():
        return
    start_result = None
    try:
        start_result = logger.Start()
        check_com_result(start_result, "収集開始失敗")
        has_started_reading = False
        while not stop_requested.is_set():
            collection_state = logger.GetState()
            if collection_state == COLLECTION_ERROR_STOPPED:
                error_code = logger.GetErrorCode()
                raise RuntimeError(f"収集異常停止（{error_code}）")
            if collection_state < 0:
                raise RuntimeError(f"収集状態取得失敗（{collection_state}）")
            if collection_state == COLLECTION_STOPPED:
                if has_started_reading:
                    break
                stop_requested.wait(READ_INTERVAL)
                continue
            has_started_reading = True

            voltages = {}
            for channel_name, channel_index in channel_indexes.items():
                voltage = waveform.GetCurrentData(unit_number, channel_index)
                if (
                    not math.isfinite(voltage)
                    or abs(voltage) >= INVALID_VOLTAGE_THRESHOLD
                ):
                    voltage = None
                voltages[channel_name] = voltage

            received_at = datetime.now(UTC).isoformat(timespec="milliseconds")
            message = {"received_at": received_at, "voltages": voltages}
            json_line = json.dumps(message, allow_nan=False)
            print(json_line, flush=True)
            stop_requested.wait(READ_INTERVAL)
    finally:
        if start_result is None or start_result == 0:
            logger.Stop()


def watch_parent(stop_requested):
    os.read(sys.stdin.fileno(), 1)
    stop_requested.set()


def prepare_logger(settings_file, device_id):
    application = DispatchEx("WaveLoggerPro2.Application")
    logger = dynamic.Dispatch(application)
    logger._FlagAsMethod(
        "Initialize",
        "SetIdentifier",
        "OpenFile",
        "GetActiveFile",
        "Start",
        "GetState",
        "GetErrorCode",
        "Stop",
    )
    logger.Initialize()
    logger.Visible = True

    usb_identifier = 4 + device_id
    identifier_result = logger.SetIdentifier(usb_identifier)
    check_com_result(identifier_result, "機器ID設定失敗")

    absolute_settings_path = Path(settings_file).resolve()
    open_result = logger.OpenFile(str(absolute_settings_path))
    check_com_result(open_result, "設定ファイル読込失敗")
    waveform = logger.GetActiveFile()
    waveform._FlagAsMethod("GetCurrentData")
    return logger, waveform


def check_com_result(result, error_message):
    if result != 0:
        raise RuntimeError(f"{error_message}（{result}）")


if __name__ == "__main__":
    arguments = sys.argv[1:]
    managed = "--managed" in arguments
    if managed:
        arguments.remove("--managed")
    try:
        main(arguments, managed)
    except KeyboardInterrupt:
        print("ロガー取得終了", file=sys.stderr)
