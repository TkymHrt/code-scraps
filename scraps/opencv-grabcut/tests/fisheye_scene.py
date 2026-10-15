"""現行の魚眼モデル用に、ChArUco板と独立した150mm区間の写真を描く。"""

from pathlib import Path

import cv2 as cv
import numpy as np

IMAGE_SIZE = (960, 720)
MATRIX = np.array([[600.0, 0, 480], [0, 610, 360], [0, 0, 1]])
DISTORTION = np.array([-0.04, 0.005, -0.001, 0.0001])


def rendered_scene(rotation, translation, partial=False):
    dictionary = cv.aruco.getPredefinedDictionary(cv.aruco.DICT_4X4_50)
    board = cv.aruco.CharucoBoard((7, 5), 30.0, 18.0, dictionary)
    texture = np.full((1200, 1760, 3), 180, np.uint8)
    texture[80:840, 80:1080] = 255
    board_image = board.generateImage((840, 600))
    texture[160:760, 160:1000] = cv.cvtColor(board_image, cv.COLOR_GRAY2BGR)
    if partial:
        texture[160:760, 160:400] = 255
    # 板に使わない40×150mmの試料。1mmは元の平面画像の4px。
    texture[220:821, 1160:1321] = (50, 110, 180)
    width, height = IMAGE_SIZE
    ys, xs = np.indices((height, width), dtype=np.float64)
    pixels = np.column_stack((xs.ravel(), ys.ravel())).reshape(-1, 1, 2)
    normalized = cv.fisheye.undistortPoints(pixels, MATRIX, DISTORTION).reshape(-1, 2)
    rays_camera = np.column_stack((normalized, np.ones(len(normalized))))
    rotation_matrix, _ = cv.Rodrigues(np.array(rotation, np.float64))
    camera_origin_world = -rotation_matrix.T @ np.array(translation, np.float64)
    rays_world = rays_camera @ rotation_matrix
    distances = -camera_origin_world[2] / rays_world[:, 2]
    plane_points = camera_origin_world + rays_world * distances[:, None]
    map_x = (plane_points[:, 0] * 4 + 160).reshape(height, width).astype(np.float32)
    map_y = (plane_points[:, 1] * 4 + 160).reshape(height, width).astype(np.float32)
    return cv.remap(
        texture,
        map_x,
        map_y,
        cv.INTER_LINEAR,
        borderMode=cv.BORDER_CONSTANT,
        borderValue=(180, 180, 180),
    )


def calibration_photos(directory: Path):
    poses = [
        ((0.10, -0.25, -0.08), (-100, -60, 400)),
        ((-0.25, 0.18, 0.10), (-230, -75, 450)),
        ((0.30, 0.12, -0.14), (20, 10, 430)),
        ((-0.15, -0.32, 0.15), (-280, -90, 470)),
        ((0.32, -0.10, 0.05), (-130, -220, 450)),
        ((-0.28, 0.26, -0.10), (20, -160, 400)),
        ((0.12, 0.35, 0.18), (-260, 50, 470)),
        ((0.25, -0.30, -0.18), (20, -200, 440)),
        ((-0.34, -0.12, 0.12), (-260, -200, 430)),
        ((0.18, 0.20, -0.20), (-100, -65, 350)),
        ((-0.22, -0.25, 0.20), (-120, -70, 370)),
        ((0.25, 0.28, 0.08), (-100, -60, 650)),
    ]
    paths = []
    for index, (rotation, translation) in enumerate(poses):
        image = rendered_scene(rotation, translation)
        path = directory / f"校正 {index + 1:02d}.png"
        _, encoded = cv.imencode(".png", image)
        path.write_bytes(encoded.tobytes())
        paths.append(path)
    return paths


def configure(rectification, matrix=MATRIX, distortion=DISTORTION):
    settings = rectification["rectify_image"].__globals__
    settings["CALIBRATION_SIZE"] = IMAGE_SIZE
    settings["CAMERA_MATRIX"] = matrix.tolist()
    settings["DIST_COEFFS"] = distortion.ravel().tolist()


def specimen_size(image, mm_per_px=0.25):
    mask = cv.inRange(image, (20, 75, 145), (90, 145, 220))
    ys, _ = np.nonzero(mask)
    # 微小な傾きによる外接矩形の拡大を幅に含めず、各行の幅の中央値を使う。
    row_widths = np.count_nonzero(mask, axis=1)
    widths = row_widths[row_widths > 0] - 1
    return (ys.max() - ys.min()) * mm_per_px, np.median(widths) * mm_per_px


def distort(image, matrix, coefficients, background):
    height, width = image.shape[:2]
    ys, xs = np.indices((height, width), dtype=np.float32)
    pixels = np.column_stack((xs.ravel(), ys.ravel())).reshape(-1, 1, 2)
    source = cv.fisheye.undistortPoints(pixels, matrix, coefficients, P=matrix).reshape(
        -1, 2
    )
    map_x = source[:, 0].reshape(height, width)
    map_y = source[:, 1].reshape(height, width)
    return cv.remap(
        image,
        map_x,
        map_y,
        cv.INTER_LINEAR,
        borderMode=cv.BORDER_CONSTANT,
        borderValue=background,
    )
