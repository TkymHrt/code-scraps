"""NR-600から1チャンネルの数値を読み、画面で確認するPoC。"""

import math
from pathlib import Path
import time

# 現場の設定に合わせて、ここを書き換える。
SETTINGS_FILE = r"D:\measurement\test.ucf"
CONNECTION = "USB"  # "USB" または "LAN"
DEVICE_ID = 0      # USB: 本体ID / LAN: 接続先IPの登録枠。どちらも0～3
UNIT = 1           # 入力ユニット番号は1始まり
CHANNEL = 0        # CH番号は0始まり。入力ユニットのCH対応表を確認
READ_COUNT = 10
READ_INTERVAL = 1.0  # Pythonの読出し間隔。装置の収集周期とは別

# LAN接続の場合だけ使用する。
IP_ADDRESS = (192, 168, 0, 120)
PORT = 24682


def main():
    import pythoncom
    from win32com.client import dynamic

    if CONNECTION not in ("USB", "LAN"):
        raise ValueError('CONNECTIONは"USB"または"LAN"にしてください。')
    if not 0 <= DEVICE_ID <= 3:
        raise ValueError("DEVICE_IDは0～3にしてください。")
    settings_path = Path(SETTINGS_FILE).expanduser().resolve()
    if not settings_path.is_file():
        raise FileNotFoundError(f"SETTINGS_FILEの設定ファイルが見つかりません: {settings_path}")

    try:
        dispatch = pythoncom.CoCreateInstance(
            "WaveLoggerPro2.Application", None, pythoncom.CLSCTX_SERVER, pythoncom.IID_IDispatch
        )
    except pythoncom.com_error as error:
        raise RuntimeError(
            "WaveLoggerPro2.Applicationを起動できません。製品版WAVE LOGGER PROを"
            "手動で起動して終了してから、もう一度試してください。"
        ) from error

    logger = dynamic.Dispatch(dispatch)
    # pywin32の動的な属性参照で、取説のメソッドをプロパティとして読まないようにする。
    logger._FlagAsMethod(
        "Initialize", "SetIdentifier", "OpenFile", "GetActiveFile",
        "Start", "GetState", "GetErrorCode", "Stop",
    )
    logger.Initialize()
    logger.Visible = True

    if CONNECTION == "USB":
        identifier = 4 + DEVICE_ID
    else:
        identifier = 8 + DEVICE_ID
    result = logger.SetIdentifier(identifier)
    if result != 0:
        raise RuntimeError(f"機器IDの設定に失敗しました: {result}")

    if CONNECTION == "LAN":
        logger._FlagAsMethod("SetLanConfig", "ConnectLan")
        result = logger.SetLanConfig(
            DEVICE_ID, IP_ADDRESS[0], IP_ADDRESS[1], IP_ADDRESS[2], IP_ADDRESS[3], PORT
        )
        if result != 0:
            raise RuntimeError(f"LAN設定に失敗しました: {result}")
        result = logger.ConnectLan()
        if result != 0:
            raise RuntimeError(f"LAN接続に失敗しました: {result}")

    result = logger.OpenFile(str(settings_path))
    if result != 0:
        raise RuntimeError(f"設定ファイルを開けませんでした: {settings_path} (戻り値 {result})")
    waveform = logger.GetActiveFile()
    if waveform is None:
        raise RuntimeError(f"GetActiveFileで設定ファイルのオブジェクトを取得できませんでした: {settings_path}")
    waveform._FlagAsMethod("GetDataCount", "GetData")

    result = logger.Start()
    if result != 0:
        raise RuntimeError(f"収集を開始できませんでした: {result:#06x}")

    received_count = 0
    try:
        for i in range(READ_COUNT):
            state = logger.GetState()
            if state == 11:
                error_code = logger.GetErrorCode()
                raise RuntimeError(f"ロガーがエラー停止しました: {error_code:#06x}")
            if state < 0:
                raise RuntimeError(f"状態の取得に失敗しました: {state}")

            data_count = waveform.GetDataCount()
            if data_count < 0:
                raise RuntimeError(f"データ数の取得に失敗しました: {data_count}")
            if data_count == 0:
                print(f"{i + 1}/{READ_COUNT}: データ待ち")
            else:
                sample_index = data_count - 1
                value = waveform.GetData(UNIT, CHANNEL, sample_index)
                # 約3.4e38は無効値。丸め差を含め、この付近の値は除外する。
                if not math.isfinite(value) or abs(value) >= 3.3e38:
                    raise RuntimeError(f"無効な値です: index={sample_index}, value={value}")
                print(f"{i + 1}/{READ_COUNT}: index={sample_index}, raw={value}")
                received_count += 1
            time.sleep(READ_INTERVAL)
    finally:
        # Startに成功した後は、読出しエラーやCtrl+Cでも停止を試みる。
        logger.Stop()
        print("Stopを実行しました。WAVE LOGGER PROの画面で状態を確認してください。")

    if received_count == 0:
        raise RuntimeError("数値を取得できませんでした。接続・CH・トリガ設定を確認してください。")
    print(f"数値を取得できました: {received_count}回")
    # Quitは呼ばず、ソフトの終了は画面で行う。


if __name__ == "__main__":
    main()
