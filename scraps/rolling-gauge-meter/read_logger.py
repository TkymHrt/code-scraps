"""NR-600から1チャンネルの数値を読み、画面で確認するPoC。"""

import math
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
    import win32com.client

    logger = win32com.client.DispatchEx("WaveLoggerPro2.Application")
    logger.Initialize()
    logger.Visible = True

    if CONNECTION == "USB":
        result = logger.SetIdentifier(4 + DEVICE_ID)
    elif CONNECTION == "LAN":
        result = logger.SetIdentifier(8 + DEVICE_ID)
    else:
        raise ValueError('CONNECTIONは"USB"または"LAN"にしてください。')
    if result != 0:
        raise RuntimeError(f"機器IDの設定に失敗しました: {result}")

    if CONNECTION == "LAN":
        result = logger.SetLanConfig(
            DEVICE_ID, IP_ADDRESS[0], IP_ADDRESS[1], IP_ADDRESS[2], IP_ADDRESS[3], PORT
        )
        if result != 0:
            raise RuntimeError(f"LAN設定に失敗しました: {result}")
        result = logger.ConnectLan()
        if result != 0:
            raise RuntimeError(f"LAN接続に失敗しました: {result}")

    result = logger.OpenFile(SETTINGS_FILE)
    if result != 0:
        raise RuntimeError(f"設定ファイルを開けませんでした: {result}")
    waveform = logger.GetActiveFile()

    result = logger.Start()
    if result != 0:
        raise RuntimeError(f"収集を開始できませんでした: {result}")

    received_count = 0
    try:
        for i in range(READ_COUNT):
            state = logger.GetState()
            if state == 11:
                error_code = logger.GetErrorCode()
                raise RuntimeError(f"ロガーがエラー停止しました: {error_code}")
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
