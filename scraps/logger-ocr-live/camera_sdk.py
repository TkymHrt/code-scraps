from contextlib import ExitStack, contextmanager

import pytelicam


def check_teli_status(status, operation):
    if status != pytelicam.CamApiStatus.Success:
        raise RuntimeError(f"{operation}: {status}")


@contextmanager
def open_teli_camera(camera_index, stop_requested):
    with ExitStack() as camera_cleanup:
        camera_system = pytelicam.get_camera_system()
        camera_cleanup.callback(camera_system.terminate)
        if not 0 <= camera_index < camera_system.get_num_of_cameras():
            raise IndexError(f"カメラ番号範囲外（{camera_index}）")

        device = camera_system.create_device_object(camera_index)
        device.open()
        camera_cleanup.callback(device.close)

        trigger_status = device.cam_control.set_trigger_mode(False)
        check_teli_status(trigger_status, "set_trigger_mode")

        frame_ready_signal = camera_system.create_signal()
        camera_cleanup.callback(camera_system.close_signal, frame_ready_signal)
        stream = device.cam_stream
        stream.open(frame_ready_signal)
        camera_cleanup.callback(stream.close)
        stream.start()
        camera_cleanup.callback(stream.stop)

        last_delivered_image_id = None
        wait_timeout_ms = 1000

        @contextmanager
        def read_next_frame():
            nonlocal last_delivered_image_id

            while not stop_requested.is_set():
                wait_status = camera_system.wait_for_signal(
                    frame_ready_signal, wait_timeout_ms
                )
                timed_out = wait_status == pytelicam.CamApiStatus.Timeout
                if timed_out and stop_requested.is_set():
                    break
                check_teli_status(wait_status, "wait_for_signal")

                buffered_image = stream.get_current_buffered_image()
                try:
                    check_teli_status(
                        buffered_image.status, "get_current_buffered_image"
                    )
                    image_id = buffered_image.image_id
                    if image_id == last_delivered_image_id:
                        continue
                    pixel_format_name = buffered_image.pixel_format.name
                    if pixel_format_name.startswith("Mono"):
                        raise RuntimeError(f"モノクロ画像: {pixel_format_name}")
                    frame = buffered_image.get_ndarray(pytelicam.OutputImageType.Bgr24)
                    last_delivered_image_id = image_id
                    yield frame
                    return
                finally:
                    buffered_image.release()

            yield None

        yield read_next_frame
