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


def watch_parent(stop_requested):
    os.read(sys.stdin.fileno(), 1)
    stop_requested.set()


def check_com_result(result, error_message):
    if result != 0:
        raise RuntimeError(f"{error_message}（{result}）")


def main(channel_names, managed):
    if not channel_names and not managed:
        channel_names = CHANNEL_NAMES
    if not channel_names:
        raise ValueError("取得する電圧CHを指定（例 U1_CH1）")
    channels = {}
    for name in channel_names:
        match = re.fullmatch(r"U1_CH([1-8])", name)
        if match is None:
            raise ValueError(f"電圧CHはU1_CH1〜U1_CH8（指定値 {name}）")
        api_channel = int(match.group(1)) - 1
        channels[name] = (1, api_channel)

    if SETTINGS_FILE is None or not Path(SETTINGS_FILE).is_file():
        raise ValueError("SETTINGS_FILEに既存の .ucf を指定")
    if not 0 <= DEVICE_ID <= 3:
        raise ValueError("DEVICE_IDは0〜3")
    if not math.isfinite(READ_INTERVAL) or READ_INTERVAL <= 0:
        raise ValueError("READ_INTERVALは正の秒数")

    stop_requested = Event()
    if managed:
        Thread(target=watch_parent, args=(stop_requested,), daemon=True).start()

    logger = dynamic.Dispatch(DispatchEx("WaveLoggerPro2.Application"))
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

    result = logger.SetIdentifier(4 + DEVICE_ID)
    check_com_result(result, "機器ID設定失敗")
    result = logger.OpenFile(str(Path(SETTINGS_FILE).resolve()))
    check_com_result(result, "設定ファイル読込失敗")
    waveform = logger.GetActiveFile()
    waveform._FlagAsMethod("GetCurrentData")

    if stop_requested.is_set():
        return
    start_result = None
    try:
        start_result = logger.Start()
        check_com_result(start_result, "収集開始失敗")
        was_active = False
        while not stop_requested.is_set():
            state = logger.GetState()
            if state == 11:
                raise RuntimeError(f"収集異常停止（{logger.GetErrorCode()}）")
            if state < 0:
                raise RuntimeError(f"収集状態取得失敗（{state}）")
            if state == 1:
                if was_active:
                    break
                stop_requested.wait(READ_INTERVAL)
                continue
            was_active = True

            voltages = {}
            for name, (unit, channel) in channels.items():
                voltage = waveform.GetCurrentData(unit, channel)
                if not math.isfinite(voltage) or abs(voltage) >= 3.3e38:
                    voltage = None
                voltages[name] = voltage

            received_at = datetime.now(UTC).isoformat(timespec="milliseconds")
            message = {"received_at": received_at, "voltages": voltages}
            print(json.dumps(message, allow_nan=False), flush=True)
            stop_requested.wait(READ_INTERVAL)
    finally:
        if start_result is None or start_result == 0:
            logger.Stop()


if __name__ == "__main__":
    arguments = sys.argv[1:]
    managed = "--managed" in arguments
    if managed:
        arguments.remove("--managed")
    try:
        main(arguments, managed)
    except KeyboardInterrupt:
        print("ロガー取得終了", file=sys.stderr)
