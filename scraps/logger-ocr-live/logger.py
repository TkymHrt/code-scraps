import json
import math
import os
import re
import sys
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread

from win32com.client import DispatchEx, dynamic

SETTINGS_FILE = None
DEVICE_ID = 0
UNIT_NUMBER = 1
CHANNEL_NUMBERS = [1, 2, 3, 6, 7]
READ_INTERVAL = 0.2


def main(channel_names, managed):
    if not channel_names and not managed:
        channel_names = [f"U{UNIT_NUMBER}_CH{number}" for number in CHANNEL_NUMBERS]

    stop_requested = Event()
    if managed:
        parent_watcher = Thread(
            target=watch_parent, args=(stop_requested,), daemon=True
        )
        parent_watcher.start()

    with closing(read_logger(channel_names, stop_requested)) as readings:
        for message in readings:
            print(json.dumps(message, allow_nan=False), flush=True)


def read_logger(channel_names, stop_requested):
    if UNIT_NUMBER < 1:
        raise ValueError("UNIT_NUMBER は1以上を指定")

    if not channel_names:
        raise ValueError(f"取得する電圧CHを指定（例 U{UNIT_NUMBER}_CH1）")

    channel_indexes = {}
    for channel_name in channel_names:
        match = re.fullmatch(rf"U{UNIT_NUMBER}_CH([1-8])", channel_name)
        if match is None:
            raise ValueError(
                f"電圧CHはU{UNIT_NUMBER}_CH1〜U{UNIT_NUMBER}_CH8（指定値 {channel_name}）"
            )
        channel_indexes[channel_name] = int(match.group(1)) - 1

    if SETTINGS_FILE is None or not Path(SETTINGS_FILE).is_file():
        raise ValueError("SETTINGS_FILEに既存の .ucf を指定")
    if not 0 <= DEVICE_ID <= 3:
        raise ValueError("DEVICE_IDは0〜3")
    if not math.isfinite(READ_INTERVAL) or READ_INTERVAL <= 0:
        raise ValueError("READ_INTERVALは正の秒数")

    logger, waveform = prepare_logger(SETTINGS_FILE, DEVICE_ID)
    if stop_requested.is_set():
        return
    check_com_result(logger.Start(), "収集開始失敗")
    try:
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
            yield {
                "received_at": received_at,
                "acquired_mono_ns": time.monotonic_ns(),
                "voltages": voltages,
            }
            stop_requested.wait(READ_INTERVAL)
    finally:
        logger.Stop()
        time.sleep(10)
        stopped_state = logger.GetState()
        if stopped_state != 1:
            raise RuntimeError(f"収集停止未確認（状態 {stopped_state}）")


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
