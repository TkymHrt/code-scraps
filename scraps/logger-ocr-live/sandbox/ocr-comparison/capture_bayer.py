import sys
from contextlib import ExitStack
from pathlib import Path

import numpy as np

FOLDER = Path(__file__).resolve().parent
CAMERA_INDEX = 0
OUTPUT_DIR = FOLDER / "captures/run-01"


def check_status(status, operation):
    import pytelicam

    if status != pytelicam.CamApiStatus.Success:
        raise RuntimeError(f"{operation}: {status}")


def checked_value(result, operation):
    status, value = result
    check_status(status, operation)
    return value


def main(output_dir):
    if output_dir.exists():
        raise FileExistsError(f"保存先が既に存在（{output_dir}）")

    import pytelicam

    with ExitStack() as cleanup:
        system = pytelicam.get_camera_system(int(pytelicam.CameraType.Gev))
        cleanup.callback(system.terminate)
        if not 0 <= CAMERA_INDEX < system.get_num_of_cameras():
            raise IndexError(f"カメラ番号範囲外（{CAMERA_INDEX}）")
        device = system.create_device_object(CAMERA_INDEX)
        device.open()
        cleanup.callback(device.close)
        control = device.cam_control
        genapi = device.genapi

        check_status(control.set_trigger_mode(False), "TriggerMode=Off")
        check_status(
            control.set_pixel_format(pytelicam.CameraPixelFormat.BayerBG8),
            "PixelFormat=BayerBG8",
        )
        reverse_x = checked_value(control.get_reverse_x(), "ReverseX")
        reverse_y = checked_value(control.get_reverse_y(), "ReverseY")
        if reverse_x or reverse_y:
            raise ValueError("カメラのReverseX・ReverseYはOffに設定")
        offset_x = checked_value(genapi.get_int_value("OffsetX"), "OffsetX")
        offset_y = checked_value(genapi.get_int_value("OffsetY"), "OffsetY")
        if offset_x % 2 or offset_y % 2:
            raise ValueError("OffsetX・OffsetYは偶数に設定")
        width = checked_value(genapi.get_int_value("Width"), "Width")
        height = checked_value(genapi.get_int_value("Height"), "Height")

        signal = system.create_signal()
        cleanup.callback(system.close_signal, signal)
        stream = device.cam_stream
        stream.open(signal)
        cleanup.callback(stream.close)
        stream.start()
        cleanup.callback(stream.stop)

        check_status(system.wait_for_signal(signal, 1000), "wait_for_signal")
        with stream.get_current_buffered_image() as image:
            check_status(image.status, "get_current_buffered_image")
            if image.pixel_format.name != "BayerBG8":
                raise ValueError(f"画像形式不一致（{image.pixel_format.name}）")
            raw = image.get_ndarray(pytelicam.OutputImageType.Raw).copy()
            if raw.shape != (height, width) or raw.dtype != np.uint8:
                raise ValueError(f"BayerBG8画像不正（{raw.shape}, {raw.dtype}）")

    output_dir.mkdir(parents=True)
    path = output_dir / "frame-000000.npy"
    raw_file = path.open("xb")
    try:
        with raw_file:
            np.save(raw_file, raw, allow_pickle=False)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    print(f"保存完了: {path}", file=sys.stderr)


if __name__ == "__main__":
    try:
        main(OUTPUT_DIR)
    except KeyboardInterrupt:
        print("撮影中断", file=sys.stderr)
        sys.exit(130)
