"""USB接続したNR-600の各チャンネルの現在値をグラフに表示する。"""

from collections import deque
import math
import time

# 現場の設定に合わせて、ここを書き換える。
SETTINGS_FILE = r"D:\measurement\test.ucf"
DEVICE_ID = 0  # NR-600本体のUSB ID（0～3）
CHANNELS = [  # (ユニット番号, APIのCH番号)
    (1, 0), (1, 1), (1, 2), (1, 3),
    (2, 0), (2, 1), (2, 2), (2, 3),
]
READ_INTERVAL = 1.0  # 表示の更新間隔（秒）
HISTORY_POINTS = 60  # グラフに残す点数


def main():
    import matplotlib
    import pythoncom
    from win32com.client import dynamic

    matplotlib.use("TkAgg")
    import matplotlib.pyplot as plt

    dispatch = pythoncom.CoCreateInstance(
        "WaveLoggerPro2.Application", None, pythoncom.CLSCTX_SERVER, pythoncom.IID_IDispatch
    )
    logger = dynamic.Dispatch(dispatch)
    # 取説でメソッドとされている名前をpywin32に明示する。
    logger._FlagAsMethod(
        "Initialize", "SetIdentifier", "OpenFile", "GetActiveFile",
        "Start", "GetState", "GetErrorCode", "Stop",
    )
    logger.Initialize()
    logger.Visible = True

    identifier = 4 + DEVICE_ID  # NR-600のUSB ID 0～3はAPIでは4～7。
    result = logger.SetIdentifier(identifier)
    if result != 0:
        raise RuntimeError(f"SetIdentifier({identifier}) に失敗しました ({result:#06x})。")
    result = logger.OpenFile(SETTINGS_FILE)
    if result != 0:
        raise RuntimeError(f"OpenFile に失敗しました ({result})。{SETTINGS_FILE}")
    waveform = logger.GetActiveFile()
    waveform._FlagAsMethod("GetCurrentData")

    figure, axes = plt.subplots(figsize=(10, 5), layout="constrained")
    axes.set_title("NR-600 | Current values")
    axes.set_xlabel("PC elapsed time (s)")
    axes.set_ylabel("Raw value")
    axes.grid(alpha=0.3)
    elapsed_times = deque(maxlen=HISTORY_POINTS)
    traces = []
    for unit, channel in CHANNELS:
        line, = axes.plot([], [], marker=".", label=f"U{unit} / CH{channel + 1}")
        history = deque(maxlen=HISTORY_POINTS)
        traces.append((line, history))
    axes.legend(loc="upper left", bbox_to_anchor=(1, 1))
    plt.show(block=False)

    result = logger.Start()
    if result != 0:
        plt.close(figure)
        raise RuntimeError(f"Start に失敗しました ({result:#06x})。")

    try:
        started_at = time.monotonic()
        was_active = False
        while plt.fignum_exists(figure.number):
            state = logger.GetState()
            if state == 11:
                error_code = logger.GetErrorCode()
                raise RuntimeError(f"ロガーがエラー停止しました ({error_code:#06x})。")
            if state < 0:
                raise RuntimeError(f"GetState に失敗しました ({state})。")
            # Start直後は状態が更新されるまで「停止」が返ることがある。
            if state == 1 and was_active:
                break
            if state != 1:
                was_active = True

            values = []
            for unit, channel in CHANNELS:
                value = waveform.GetCurrentData(unit, channel)
                # 無効値を欠損として扱い、グラフの線を途切れさせる。
                if not math.isfinite(value) or abs(value) >= 3.3e38:
                    value = math.nan
                values.append(value)

            elapsed_times.append(time.monotonic() - started_at)
            for trace, value in zip(traces, values):
                line, history = trace
                history.append(value)
                line.set_data(elapsed_times, history)
            axes.relim()
            axes.autoscale_view()
            plt.pause(READ_INTERVAL)
    except KeyboardInterrupt:
        print("\nCtrl+Cで停止します。")
    finally:
        logger.Stop()
        plt.close(figure)
        print("WAVE LOGGER PROの画面で停止を確認してください。")


if __name__ == "__main__":
    main()
