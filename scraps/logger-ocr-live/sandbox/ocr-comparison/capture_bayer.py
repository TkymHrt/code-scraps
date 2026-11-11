import argparse
import json
import sys
import time
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np


def check_status(status, operation):
    import pytelicam

    if status != pytelicam.CamApiStatus.Success:
        raise RuntimeError(f"{operation}: {status}")


def checked_value(result, operation):
    status, value = result
    check_status(status, operation)
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description="BG505LMCFのBayerBG8画像を保存する")
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument("--frames", type=int, default=100)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    if args.frames < 1:
        raise ValueError("--framesは1以上")
    if args.camera_index < 0:
        raise ValueError("--camera-indexは0以上")

    output_dir = args.output_dir
    if output_dir is None:
        run_name = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        output_dir = Path(__file__).resolve().parent / "captures" / run_name
    if output_dir.exists():
        raise FileExistsError(f"保存先が既に存在（{output_dir}）")

    import pytelicam

    with ExitStack() as cleanup:
        system = pytelicam.get_camera_system(int(pytelicam.CameraType.Gev))
        cleanup.callback(system.terminate)
        if args.camera_index >= system.get_num_of_cameras():
            raise IndexError(f"カメラ番号範囲外（{args.camera_index}）")
        camera_info = system.get_camera_information(args.camera_index)
        device = system.create_device_object(args.camera_index)
        device.open()
        cleanup.callback(device.close)
        control = device.cam_control
        genapi = device.genapi

        check_status(control.set_trigger_mode(False), "TriggerMode=Off")
        check_status(
            control.set_pixel_format(pytelicam.CameraPixelFormat.BayerBG8),
            "PixelFormat=BayerBG8",
        )
        settings = {
            "exposure_control": checked_value(
                control.get_exposure_time_control(), "ExposureAuto"
            ).name,
            "exposure_us": checked_value(control.get_exposure_time(), "ExposureTime"),
            "gain_auto": checked_value(control.get_gain_auto(), "GainAuto").name,
            "gain_db": checked_value(control.get_gain(), "Gain"),
            "bayer_processing_mode": checked_value(
                genapi.get_enum_str_value("BayerProcessingMode"), "BayerProcessingMode"
            ),
            "gamma": checked_value(control.get_gamma(), "Gamma"),
            "black_level": checked_value(control.get_black_level(), "BlackLevel"),
            "white_balance_red": checked_value(
                control.get_balance_ratio(pytelicam.CameraBalanceRatioSelector.Red),
                "BalanceRatio Red",
            ),
            "white_balance_blue": checked_value(
                control.get_balance_ratio(pytelicam.CameraBalanceRatioSelector.Blue),
                "BalanceRatio Blue",
            ),
            "white_balance_auto": checked_value(
                control.get_balance_white_auto(), "BalanceWhiteAuto"
            ).name,
        }
        if settings["exposure_control"] != "Manual" or settings["gain_auto"] != "Off":
            raise ValueError("露光はManual、GainAutoはOffに設定")
        if settings["white_balance_auto"] != "Off":
            raise ValueError("BalanceWhiteAutoはOffに設定")

        session = {
            "model": camera_info.cam_model,
            "serial_number": camera_info.cam_serial_number,
            "camera_version": camera_info.cam_version,
            "started_at": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "requested_frames": args.frames,
            "pixel_format": checked_value(
                control.get_pixel_format(), "PixelFormat"
            ).name,
            "frame_size": [
                checked_value(genapi.get_int_value("Width"), "Width"),
                checked_value(genapi.get_int_value("Height"), "Height"),
            ],
            "offset": [
                checked_value(genapi.get_int_value("OffsetX"), "OffsetX"),
                checked_value(genapi.get_int_value("OffsetY"), "OffsetY"),
            ],
            "reverse_x": checked_value(control.get_reverse_x(), "ReverseX"),
            "reverse_y": checked_value(control.get_reverse_y(), "ReverseY"),
            "timestamp_tick_frequency_hz": checked_value(
                genapi.get_int_value("GevTimestampTickFrequency"),
                "GevTimestampTickFrequency",
            ),
            "camera_settings": settings,
        }
        if session["pixel_format"] != "BayerBG8":
            raise ValueError(f"PixelFormat不一致（{session['pixel_format']}）")
        if session["reverse_x"] or session["reverse_y"]:
            raise ValueError("カメラのReverseX・ReverseYはOffに設定")
        if any(offset % 2 for offset in session["offset"]):
            raise ValueError("OffsetX・OffsetYは偶数に設定")
        if session["timestamp_tick_frequency_hz"] <= 0:
            raise ValueError("GevTimestampTickFrequencyは正の値")

        output_dir.mkdir(parents=True)
        (output_dir / "session.json").write_text(
            json.dumps(session, ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8",
        )
        manifest = cleanup.enter_context(
            (output_dir / "frames.jsonl").open("x", encoding="utf-8")
        )
        signal = system.create_signal()
        cleanup.callback(system.close_signal, signal)
        stream = device.cam_stream
        stream.open(signal)
        cleanup.callback(stream.close)
        stream.start()
        cleanup.callback(stream.stop)
        print(f"保存先: {output_dir.resolve()}", file=sys.stderr)

        saved_count = 0
        last_image_id = None
        last_block_id = None
        while saved_count < args.frames:
            wait_started = time.perf_counter()
            check_status(system.wait_for_signal(signal, 1000), "wait_for_signal")
            with stream.get_current_buffered_image() as image:
                received_at = datetime.now(UTC).isoformat(timespec="milliseconds")
                wait_ms = (time.perf_counter() - wait_started) * 1000
                check_status(image.status, "get_current_buffered_image")
                if image.image_id == last_image_id:
                    continue
                if image.pixel_format.name != "BayerBG8":
                    raise ValueError(f"画像形式不一致（{image.pixel_format.name}）")
                copy_started = time.perf_counter()
                raw = image.get_ndarray(pytelicam.OutputImageType.Raw).copy()
                copy_ms = (time.perf_counter() - copy_started) * 1000
                width, height = session["frame_size"]
                if raw.shape != (height, width) or raw.dtype != np.uint8:
                    raise ValueError(f"BayerBG8画像不正（{raw.shape}, {raw.dtype}）")
                frame_info = {
                    "file": f"frame-{saved_count:06d}.npy",
                    "received_at": received_at,
                    "image_id": image.image_id,
                    "block_id": image.block_id,
                    "timestamp_ticks": image.timestamp,
                    "wait_ms": wait_ms,
                    "copy_ms": copy_ms,
                }
                block_gap = None
                if last_block_id is not None and image.block_id > last_block_id:
                    block_gap = image.block_id - last_block_id - 1
                frame_info["block_gap"] = block_gap
                last_image_id = image.image_id
                last_block_id = image.block_id

            save_started = time.perf_counter()
            with (output_dir / frame_info["file"]).open("xb") as raw_file:
                np.save(raw_file, raw, allow_pickle=False)
            frame_info["save_ms"] = (time.perf_counter() - save_started) * 1000
            manifest.write(json.dumps(frame_info, allow_nan=False) + "\n")
            manifest.flush()
            saved_count += 1
            if saved_count == 1:
                preview = cv2.cvtColor(raw, cv2.COLOR_BayerBGGR2BGR)
                encoded, png = cv2.imencode(".png", preview)
                if not encoded:
                    raise RuntimeError("preview.png作成失敗")
                (output_dir / "preview.png").write_bytes(png.tobytes())

        print(f"保存完了: {saved_count}フレーム", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("撮影中断", file=sys.stderr)
