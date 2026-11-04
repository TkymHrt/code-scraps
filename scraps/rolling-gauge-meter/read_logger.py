"""USB接続したNR-600の複数チャンネルの最新値を表示する。"""

import math
from pathlib import Path
import time

# 現場の設定に合わせて、ここを書き換える。
SETTINGS_FILE = r"D:\measurement\test.ucf"
DEVICE_ID = 0  # NR-600本体のUSB ID（0～3）
# (ユニット番号, APIのCH番号)。NR-HA08を2台使う場合の電圧CH1～8。
CHANNELS = [
    (1, 0), (1, 1), (1, 2), (1, 3), (1, 4), (1, 5), (1, 6), (1, 7),
    (2, 0), (2, 1), (2, 2), (2, 3), (2, 4), (2, 5), (2, 6), (2, 7),
]
READ_INTERVAL = 1.0  # Pythonの読出し間隔。装置の収集周期とは別


def main():
    import pythoncom
    from win32com.client import dynamic

    if not 0 <= DEVICE_ID <= 3:
        raise ValueError("DEVICE_IDは0～3にしてください。")
    if not CHANNELS:
        raise ValueError("CHANNELSに読み出すユニットとCHを指定してください。")
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

    # SetIdentifierでは、NR-600のUSB ID 0～3を4～7で指定する。
    identifier = 4 + DEVICE_ID
    result = logger.SetIdentifier(identifier)
    if result != 0:
        raise RuntimeError(
            f"機器ID {DEVICE_ID} の設定に失敗しました。"
            f"SetIdentifier({identifier}) の戻り値は {result} ({result:#06x}) です。"
            "WAVE LOGGER PROをすべて終了してから再実行してください。"
        )

    result = logger.OpenFile(str(settings_path))
    if result != 0:
        raise RuntimeError(f"設定ファイルを開けませんでした: {settings_path} (戻り値 {result})")
    waveform = logger.GetActiveFile()
    if waveform is None:
        raise RuntimeError(f"GetActiveFileで設定ファイルのオブジェクトを取得できませんでした: {settings_path}")
    waveform._FlagAsMethod("GetDataCount", "GetData", "GetAutosaveCount")

    result = logger.Start()
    if result != 0:
        raise RuntimeError(f"収集を開始できませんでした: {result:#06x}")

    was_active = False
    try:
        print("収集を開始しました。終了するにはCtrl+Cを押してください。", flush=True)
        while True:
            state = logger.GetState()
            if state == 11:
                error_code = logger.GetErrorCode()
                raise RuntimeError(f"ロガーがエラー停止しました: {error_code:#06x}")
            if state < 0:
                raise RuntimeError(f"状態の取得に失敗しました: {state}")
            # Start直後は状態が更新されるまで「停止」が返ることがある。
            if state == 1 and was_active:
                print("ロガーの収集が停止しました。", flush=True)
                break
            if state != 1:
                was_active = True

            save_number = waveform.GetAutosaveCount()
            data_count = waveform.GetDataCount()
            if data_count < 0:
                raise RuntimeError(f"データ数の取得に失敗しました: {data_count}")
            if data_count == 0:
                print("データ待ち", flush=True)
            else:
                sample_index = data_count - 1
                fields = [f"index={sample_index}"]
                for unit, channel in CHANNELS:
                    value = waveform.GetData(unit, channel, sample_index)
                    raw = str(value)
                    # 約3.4e38はデータがない場合などに返る無効値。
                    if not math.isfinite(value) or abs(value) >= 3.3e38:
                        raw = "NA"
                    fields.append(f"raw[U{unit}/CH{channel}]={raw}")
                # 読出し中に分割保存が切り替わると、同じindexでも別の点を指す。
                if save_number == waveform.GetAutosaveCount():
                    print(", ".join(fields), flush=True)
            time.sleep(READ_INTERVAL)
    except KeyboardInterrupt:
        print("\nCtrl+Cで停止します。", flush=True)
    finally:
        # Startに成功した後は、読出しエラーやCtrl+Cでも停止を試みる。
        logger.Stop()
        print("Stopを実行しました。WAVE LOGGER PROの画面で状態を確認してください。")


if __name__ == "__main__":
    main()
