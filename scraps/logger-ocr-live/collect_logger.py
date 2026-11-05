"""NR-600から指定チャンネルの最新電圧を取得し、JSONLで出力する。"""

import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Thread

# 実機の設定に合わせる。
SETTINGS_FILE = None  # 例は r"D:\measurement\test.ucf"
DEVICE_ID = 0
READ_INTERVAL = 0.2


def watch_parent(stop_requested):
    # 計算側が標準入力のパイプを閉じると、次の読出し前に終了できる。
    os.read(sys.stdin.fileno(), 1)
    stop_requested.set()


def main(channel_names, managed):
    if not channel_names:
        raise ValueError("U1_CH1のような形式で取得する電圧CHを指定してください。")
    channels = {}
    for name in channel_names:
        match = re.fullmatch(r"U1_CH([1-8])", name)
        if match is None:
            raise ValueError(f"電圧CHはU1_CH1〜U1_CH8で指定してください（{name}）。")
        api_channel = int(match.group(1)) - 1  # APIのCH番号は0始まり。
        channels[name] = (1, api_channel)

    if SETTINGS_FILE is None or not Path(SETTINGS_FILE).is_file():
        raise ValueError("SETTINGS_FILEに既存の.ucfファイルを指定してください。")
    if not 0 <= DEVICE_ID <= 3:
        raise ValueError("DEVICE_IDは0〜3にしてください。")
    if not math.isfinite(READ_INTERVAL) or READ_INTERVAL <= 0:
        raise ValueError("READ_INTERVALには正の秒数を指定してください。")

    import pythoncom
    from win32com.client import dynamic

    stop_requested = Event()
    if managed:
        Thread(target=watch_parent, args=(stop_requested,), daemon=True).start()

    dispatch = pythoncom.CoCreateInstance(
        "WaveLoggerPro2.Application",
        None,
        pythoncom.CLSCTX_SERVER,
        pythoncom.IID_IDispatch,
    )
    logger = dynamic.Dispatch(dispatch)
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
    if result != 0:
        raise RuntimeError(f"機器IDの設定に失敗しました（{result}）。")
    result = logger.OpenFile(str(Path(SETTINGS_FILE).resolve()))
    if result != 0:
        raise RuntimeError(f"設定ファイルを開けませんでした（{result}）。")
    waveform = logger.GetActiveFile()
    waveform._FlagAsMethod("GetCurrentData")

    if stop_requested.is_set():
        return
    start_result = None
    try:
        start_result = logger.Start()
        if start_result != 0:
            raise RuntimeError(f"収集を開始できませんでした（{start_result}）。")
        was_active = False
        while not stop_requested.is_set():
            state = logger.GetState()
            if state == 11:
                raise RuntimeError(
                    f"ロガーがエラー停止しました（{logger.GetErrorCode()}）。"
                )
            if state < 0:
                raise RuntimeError(f"収集状態を取得できませんでした（{state}）。")
            # Startの直後は、状態が更新されるまで停止が返ることがある。
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

            received_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
            message = {"received_at": received_at, "voltages": voltages}
            print(json.dumps(message, allow_nan=False), flush=True)
            stop_requested.wait(READ_INTERVAL)
    finally:
        # Startの応答待ちで割り込まれた場合も、収集が始まっている可能性がある。
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
        print("ロガー取得を終了しました。", file=sys.stderr)
