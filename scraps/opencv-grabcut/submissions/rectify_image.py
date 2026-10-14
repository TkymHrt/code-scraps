"""固定したカメラ係数とChArUcoで、一定のmm/pxの補正PNGを保存する."""

import math
from pathlib import Path

import cv2 as cv
import numpy as np

INPUT_PATH = "input/赤茶色の床と剥離した金属帯.png"
OUTPUT_IMAGE_PATH = "results/rectified.png"

# camera_calibration.pyの出力を、この3設定へ一度貼り付ける。
CALIBRATION_SIZE: tuple[int, int] | None = None
CAMERA_MATRIX: list[list[float]] | None = None
DIST_COEFFS: list[float] | None = None

# カメラ校正と同じ板を、試料の計測面と同じ高さに置く。
BOARD_SQUARES = (7, 5)
SQUARE_MM = 30.0
MARKER_MM = 18.0
# 01_initial_regions_gui.pyにも同じ値を設定する。
MM_PER_PX = 0.25


def rectify_image(image: np.ndarray) -> dict:
    if CALIBRATION_SIZE is None or CAMERA_MATRIX is None or DIST_COEFFS is None:
        raise ValueError("コード冒頭へcamera_calibration.pyの3設定を貼り付けてください")
    height, width = image.shape[:2]
    if (width, height) != tuple(CALIBRATION_SIZE):
        raise ValueError("カメラ校正と同じ解像度・撮影モードの画像を指定してください")
    matrix = np.array(CAMERA_MATRIX, dtype=np.float64)
    distortion = np.array(DIST_COEFFS, dtype=np.float64)
    if (
        matrix.shape != (3, 3)
        or distortion.size != 5
        or not np.isfinite(matrix).all()
        or not np.isfinite(distortion).all()
        or matrix[0, 0] <= 0
        or matrix[1, 1] <= 0
        or not math.isfinite(MM_PER_PX)
        or MM_PER_PX <= 0
    ):
        raise ValueError("貼り付けたカメラ係数とMM_PER_PXを確認してください")
    undistorted = cv.undistort(image, matrix, distortion, None, matrix)
    dictionary = cv.aruco.getPredefinedDictionary(cv.aruco.DICT_4X4_50)
    board = cv.aruco.CharucoBoard(BOARD_SQUARES, SQUARE_MM, MARKER_MM, dictionary)
    detector = cv.aruco.CharucoDetector(board)
    corners, ids, _, _ = detector.detectBoard(undistorted)
    if ids is None or len(ids) < 6 or board.checkCharucoCornersCollinear(ids):
        raise ValueError("ChArUco板の角を縦横に6点以上読める画像を指定してください")
    all_board_points = np.array(board.getChessboardCorners(), dtype=np.float32)
    object_points = all_board_points[ids.astype(np.int32).ravel()]
    board_xy = object_points.reshape(-1, 3)[:, :2]
    detected_xy = corners.reshape(-1, 2)
    # 板のmm座標へ写す。試料の形を基準に変形すると伸びを消すため、使わない。
    homography, _ = cv.findHomography(detected_xy, board_xy)
    if homography is None or not np.isfinite(homography).all():
        raise ValueError("板から遠近補正を求められません")
    predicted = cv.perspectiveTransform(
        board_xy.reshape(-1, 1, 2), np.linalg.inv(homography)
    ).reshape(-1, 2)
    error_px = float(np.sqrt(np.mean(np.sum((predicted - detected_xy) ** 2, axis=1))))
    if error_px > 2.0:
        raise ValueError(f"板の再投影誤差が大きいため保存しません: {error_px:.3f}px")

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
    directory = Path(__file__).resolve().parent
    input_path = (directory / INPUT_PATH).resolve()
    image_path = (directory / OUTPUT_IMAGE_PATH).resolve()
    if input_path == image_path:
        raise ValueError("元画像と補正PNGは別のパスにしてください")
    if image_path.suffix.lower() != ".png":
        raise ValueError("保存先の拡張子は .png にしてください")
    image = cv.imdecode(
        np.frombuffer(input_path.read_bytes(), np.uint8), cv.IMREAD_COLOR
    )
    if image is None:
        raise ValueError(f"画像を読み込めません: {input_path}")
    correction = rectify_image(image)
    success, encoded = cv.imencode(".png", correction["image"])
    if not success:
        raise OSError("補正画像をPNGにできません")
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(encoded.tobytes())
    print(
        f"検出した角: {correction['corner_count']}点、再投影誤差: {correction['error_px']:.3f}px"
    )
    print(f"補正PNG: {image_path}")
    print(f"補正画像の倍率: {correction['mm_per_px']:g}mm/px")


if __name__ == "__main__":
    main()
