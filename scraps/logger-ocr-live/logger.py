import json
import math
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread

from win32com.client import DispatchEx, dynamic

SETTINGS_FILE = None
DEVICE_ID = 0
UNIT_NUMBER = 1
READ_INTERVAL = 0.2
CHANNEL_NAMES = [f"U{UNIT_NUMBER}_CH{channel}" for channel in range(1, 9)]


def main(channel_names, managed):
    if not channel_names and not managed:
        channel_names = CHANNEL_NAMES
    channel_indexes = get_channel_indexes(channel_names)

    if SETTINGS_FILE is None or not Path(SETTINGS_FILE).is_file():
        raise ValueError("SETTINGS_FILE に既存の .ucf ファイルを指定")
    if not 0 <= DEVICE_ID <= 3:
        raise ValueError("DEVICE_ID は0〜3")
    if not math.isfinite(READ_INTERVAL) or READ_INTERVAL <= 0:
        raise ValueError("READ_INTERVAL は正の秒数")

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
            if collection_state == 11:
                error_code = logger.GetErrorCode()
                raise RuntimeError(f"収集異常停止（{error_code}）")
            if collection_state < 0:
                raise RuntimeError(f"収集状態取得失敗（{collection_state}）")
            if collection_state == 1:
                if has_started_reading:
                    break
                stop_requested.wait(READ_INTERVAL)
                continue
            has_started_reading = True

            voltages = {}
            for channel_name, channel_index in channel_indexes.items():
                voltage = waveform.GetCurrentData(UNIT_NUMBER, channel_index)
                if not math.isfinite(voltage) or abs(voltage) >= 3.3e38:
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
            time.sleep(10)


def get_channel_indexes(channel_names):
    if not channel_names:
        raise ValueError(f"取得する電圧CHを指定（例 U{UNIT_NUMBER}_CH1）")
    if not isinstance(UNIT_NUMBER, int) or isinstance(UNIT_NUMBER, bool) or UNIT_NUMBER < 1:
        raise ValueError("UNIT_NUMBERは1以上の整数")

    channel_pattern = re.compile(rf"U{UNIT_NUMBER}_CH([1-8])")
    channel_indexes = {}
    for channel_name in channel_names:
        channel_match = channel_pattern.fullmatch(channel_name)
        if channel_match is None:
            raise ValueError(
                f"電圧CHはU{UNIT_NUMBER}_CH1〜U{UNIT_NUMBER}_CH8（指定値 {channel_name}）"
            )
        channel_indexes[channel_name] = int(channel_match.group(1)) - 1
    return channel_indexes


def watch_parent(stop_requested):
    os.read(sys.stdin.fileno(), 1)
    stop_requested.set()


def prepare_logger(settings_file, device_id):
    application = DispatchEx("WaveLoggerPro2.Application")
    logger = dynamic.Dispatch(application)
    logger._FlagAsMethod("GetActiveFile", "Start", "GetState")
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
