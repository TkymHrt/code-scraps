"""指定フォルダの写真を、魚眼モデルの固定係数とChArUcoで補正してPNGへ保存する."""

import math
from pathlib import Path

import cv2 as cv
import numpy as np
from file_io import find_images, read_image, write_png
from workflow_settings import (
    BOARD_SQUARES,
    INPUT_DIRECTORY,
    MARKER_MM,
    MM_PER_PX,
    RECTIFIED_DIRECTORY,
    SQUARE_MM,
)

# 00_2_calibrate_camera.pyの出力を、この3設定へ一度貼り付ける。
# DIST_COEFFSは魚眼モデルのk1, k2, k3, k4。通常モデルの係数は使わない。
CALIBRATION_SIZE: tuple[int, int] | None = None
CAMERA_MATRIX: list[list[float]] | None = None
DIST_COEFFS: list[float] | None = None


def rectify_image(image: np.ndarray) -> dict:
    if CALIBRATION_SIZE is None or CAMERA_MATRIX is None or DIST_COEFFS is None:
        raise ValueError(
            "コード冒頭へ00_2_calibrate_camera.pyの3設定を貼り付けてください"
        )
    height, width = image.shape[:2]
    if (width, height) != tuple(CALIBRATION_SIZE):
        raise ValueError("カメラ校正と同じ解像度・撮影モードの画像を指定してください")
    matrix = np.array(CAMERA_MATRIX, dtype=np.float64)
    distortion = np.array(DIST_COEFFS, dtype=np.float64)
    if (
        matrix.shape != (3, 3)
        or distortion.shape != (4,)
        or not np.isfinite(matrix).all()
        or not np.isfinite(distortion).all()
        or matrix[0, 0] <= 0
        or matrix[1, 1] <= 0
        or not math.isfinite(MM_PER_PX)
        or MM_PER_PX <= 0
    ):
        raise ValueError("カメラ係数（歪み係数4個）・MM_PER_PXを確認してください")
    # 周辺をなるべく残す画角で、魚眼画像を平面の画像へ直す。
    new_matrix = cv.fisheye.estimateNewCameraMatrixForUndistortRectify(
        matrix, distortion, (width, height), np.eye(3), balance=1.0
    )
    undistorted = cv.fisheye.undistortImage(
        image, matrix, distortion, Knew=new_matrix, new_size=(width, height)
    )
    dictionary = cv.aruco.getPredefinedDictionary(cv.aruco.DICT_4X4_50)
    board = cv.aruco.CharucoBoard(BOARD_SQUARES, SQUARE_MM, MARKER_MM, dictionary)
    detector = cv.aruco.CharucoDetector(board)
    corners, ids, _, _ = detector.detectBoard(undistorted)
    if ids is None or len(ids) < 6 or board.checkCharucoCornersCollinear(ids):
        raise ValueError("ChArUco板の角を縦横に6点以上読める画像を指定してください")
    all_board_points = np.array(board.getChessboardCorners(), dtype=np.float32)
    board_xy = all_board_points[ids.astype(np.int32).ravel(), :2]
    detected_xy = corners.reshape(-1, 2)
    # 板のmm座標へ写す。試料の形を基準に変形すると伸びを消すため、使わない。
    homography, _ = cv.findHomography(detected_xy, board_xy)
    if homography is None or not np.isfinite(homography).all():
        raise ValueError("板から遠近補正を求められません")
    board_to_image = np.linalg.inv(homography)
    predicted = cv.perspectiveTransform(
        board_xy.reshape(-1, 1, 2), board_to_image
    ).reshape(-1, 2)
    error_px = float(np.sqrt(np.mean(np.sum((predicted - detected_xy) ** 2, axis=1))))
    if error_px > 2.0:
        raise ValueError(f"板の再投影誤差が大きいため保存しません: {error_px:.3f}px")

    # 板の横軸が写真に写る向きを残し、板の配置に合わせた回転を防ぐ。
    center = board_xy.mean(axis=0)
    board_axis = np.array([center, center + [SQUARE_MM, 0]], dtype=np.float64)
    image_axis = cv.perspectiveTransform(
        board_axis.reshape(-1, 1, 2), board_to_image
    ).reshape(-1, 2)
    direction = image_axis[1] - image_axis[0]
    direction = direction / np.linalg.norm(direction)
    dx, dy = direction
    rotation = np.array([[dx, -dy, 0], [dy, dx, 0], [0, 0, 1]])
    homography = rotation @ homography

    frame_corners = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
        dtype=np.float64,
    )
    # 画面内に消失線がある場合、全体を有限の平面画像にはできない。
    denominators = frame_corners @ homography[2, :2] + homography[2, 2]
    if not (np.all(denominators > 0) or np.all(denominators < 0)):
        raise ValueError("撮影角度が浅すぎます。計測面へ向けて撮り直してください")
    world_corners = cv.perspectiveTransform(
        frame_corners.reshape(-1, 1, 2), homography
    ).reshape(-1, 2)
    pixel_corners = world_corners / MM_PER_PX
    if not np.isfinite(pixel_corners).all():
        raise ValueError("補正画像の範囲を求められません")
    minimum = np.floor(pixel_corners.min(axis=0))
    maximum = np.ceil(pixel_corners.max(axis=0))
    output_width = int(maximum[0] - minimum[0] + 1)
    output_height = int(maximum[1] - minimum[1] + 1)
    if (
        min(output_width, output_height) < 2
        or max(output_width, output_height) >= 32767
        or output_width * output_height > 20_000_000
    ):
        raise ValueError("補正画像が大きすぎます。撮影角度・板の寸法を確認してください")
    world_to_pixels = np.array(
        [[1 / MM_PER_PX, 0, -minimum[0]], [0, 1 / MM_PER_PX, -minimum[1]], [0, 0, 1]],
        dtype=np.float64,
    )
    transform = world_to_pixels @ homography
    corrected = cv.warpPerspective(
        undistorted, transform, (output_width, output_height), flags=cv.INTER_LINEAR
    )
    return {
        "image": corrected,
        "mm_per_px": MM_PER_PX,
        "corner_count": len(ids),
        "error_px": error_px,
    }


def main() -> None:
    input_directory = Path(INPUT_DIRECTORY).resolve()
    output_directory = Path(RECTIFIED_DIRECTORY).resolve()
    if input_directory == output_directory:
        raise ValueError("入力と出力は別のフォルダにしてください")
    input_paths = find_images(input_directory)
    output_names = []
    for path in input_paths:
        output_name = f"{path.stem}.png"
        if output_name.casefold() in output_names:
            raise ValueError(
                f"出力名が重複します。入力名を変えてください: {output_name}"
            )
        output_names.append(output_name.casefold())
    for input_path in input_paths:
        output_path = output_directory / f"{input_path.stem}.png"
        image = read_image(input_path)
        correction = rectify_image(image)
        write_png(output_path, correction["image"])
        print(
            f"保存: {output_path.name} / 角{correction['corner_count']}点 / "
            f"再投影誤差{correction['error_px']:.3f}px"
        )
    print(f"完了: {len(input_paths)}枚 → {output_directory}")


if __name__ == "__main__":
    main()
