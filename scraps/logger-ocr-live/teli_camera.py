from contextlib import ExitStack, contextmanager

import pytelicam


def check_teli_status(status, operation):
    if status != pytelicam.CamApiStatus.Success:
        raise RuntimeError(f"{operation}: {status}")


@contextmanager
def open_teli_camera(camera_index, stop_requested):
    with ExitStack() as resources:
        system = pytelicam.get_camera_system()
        resources.callback(system.terminate)
        if not 0 <= camera_index < system.get_num_of_cameras():
            raise IndexError(f"カメラ番号: {camera_index}")

        device = system.create_device_object(camera_index)
        check_teli_status(device.open(), "device.open")
        resources.callback(device.close)
        signal = system.create_signal()
        resources.callback(system.close_signal, signal)
        stream = device.cam_stream
        check_teli_status(stream.open(signal), "stream.open")
        resources.callback(stream.close)
        check_teli_status(stream.start(), "stream.start")
        resources.callback(stream.stop)
        previous_image_id = None

        @contextmanager
        def read_frame():
            nonlocal previous_image_id

            while not stop_requested.is_set():
                status = system.wait_for_signal(signal, 1000)
                if status == pytelicam.CamApiStatus.Timeout and stop_requested.is_set():
                    break
                check_teli_status(status, "wait_for_signal")
                image = stream.get_current_buffered_image()
                try:
                    check_teli_status(image.status, "get_current_buffered_image")
                    image_id = image.image_id
                    if image_id == previous_image_id:
                        continue
                    if image.pixel_format.name.startswith("Mono"):
                        raise RuntimeError(f"モノクロ画像: {image.pixel_format.name}")
                    frame = image.get_ndarray(pytelicam.OutputImageType.Bgr24)
                    previous_image_id = image_id
                    yield frame
                    return
                finally:
                    image.release()

            yield None

        yield read_frame
