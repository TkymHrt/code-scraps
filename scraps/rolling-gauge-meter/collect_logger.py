import math
import time
from collections import deque

SETTINGS_FILE = r"D:\measurement\test.ucf"
DEVICE_ID = 0
CHANNELS = [
    (1, 0),
    (1, 1),
    (1, 2),
    (1, 3),
    (1, 4),
    (1, 5),
    (1, 6),
    (1, 7),
]
READ_INTERVAL = 0.2
WINDOW_SECONDS = 60


def main():
    import matplotlib
    import pythoncom
    from win32com.client import dynamic

    matplotlib.use("TkAgg")
    import matplotlib.pyplot as plt

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
        raise RuntimeError(result)
    result = logger.OpenFile(SETTINGS_FILE)
    if result != 0:
        raise RuntimeError(result)
    waveform = logger.GetActiveFile()
    waveform._FlagAsMethod("GetCurrentData")

    figure, axes = plt.subplots(figsize=(10, 5), layout="constrained")
    axes.set_axis_off()
    channel_labels = []
    lines = []
    for unit, channel in CHANNELS:
        label = f"U{unit}_CH{channel + 1}"
        channel_labels.append(label)
        (line,) = axes.plot([], [], marker=".", markersize=3, label=label)
        lines.append(line)
    axes.legend(loc="upper left", bbox_to_anchor=(1, 1))
    plt.show(block=False)

    result = logger.Start()
    if result != 0:
        plt.close(figure)
        raise RuntimeError(result)

    try:
        started_at = time.monotonic()
        samples = deque()
        was_active = False
        print("elapsed_s", *channel_labels, sep=",", flush=True)
        while plt.fignum_exists(figure.number):
            state = logger.GetState()
            if state == 11:
                raise RuntimeError(logger.GetErrorCode())
            if state < 0:
                raise RuntimeError(state)
            if state == 1:
                if was_active:
                    break
                plt.pause(READ_INTERVAL)
                continue
            was_active = True

            values = []
            for unit, channel in CHANNELS:
                value = waveform.GetCurrentData(unit, channel)
                if not math.isfinite(value) or abs(value) >= 3.3e38:
                    value = math.nan
                values.append(value)

            elapsed = time.monotonic() - started_at
            samples.append((elapsed, values))
            print(elapsed, *values, sep=",", flush=True)

            window_start = elapsed - WINDOW_SECONDS
            while samples and samples[0][0] < window_start:
                samples.popleft()
            times = [sample_time for sample_time, _ in samples]
            for channel_index, line in enumerate(lines):
                channel_values = [values[channel_index] for _, values in samples]
                line.set_data(times, channel_values)
            axes.set_xlim(window_start, elapsed)
            axes.relim()
            axes.autoscale_view(scalex=False)
            plt.pause(READ_INTERVAL)
    except KeyboardInterrupt:
        return
    finally:
        logger.Stop()
        plt.close(figure)


if __name__ == "__main__":
    main()
