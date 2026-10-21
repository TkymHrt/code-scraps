"""固定カメラの基準画像で補正を求め、ボードのないフレームへ同じ補正を適用する。"""

import math
from pathlib import Path

import cv2 as cv
import numpy as np

from utils.file_io import check_output_path, find_images, read_image, write_png
from workflow_settings import (
    BOARD_SQUARES,
    INPUT_DIRECTORY,
    MARKER_MM,
    MM_PER_PX,
    OUTPUT_DIRECTORY,
    RECTIFY_ROI,
    SQUARE_MM,
)

# FFmpegなどで、基準画像と各フレームを同じ動画条件・元解像度で書き出す。
REFERENCE_IMAGE_PATH = INPUT_DIRECTORY / "video_reference" / "reference.png"
FRAMES_DIRECTORY = INPUT_DIRECTORY / "video_frames"
RECTIFIED_FRAMES_DIRECTORY = OUTPUT_DIRECTORY / "rectified_frames"

# 動画の撮影条件に合う00_2の出力を、この3設定へ貼り付ける。
# 既存の01_rectify_images.pyに貼った値は、このスクリプトには反映されない。
CALIBRATION_SIZE: tuple[int, int] | None = None
CAMERA_MATRIX: list[list[float]] | None = None
DIST_COEFFS: list[float] | None = None


def prepare_rectification(reference_image: np.ndarray) -> dict:
    """基準画像だけから、全フレームで固定する歪み・遠近補正を求める。"""
    if CALIBRATION_SIZE is None or CAMERA_MATRIX is None or DIST_COEFFS is None:
        raise ValueError(
            "コード冒頭へ動画の撮影条件に合う00_2の3設定を貼り付けてください"
        )
    height, width = reference_image.shape[:2]
    if (width, height) != tuple(CALIBRATION_SIZE):
        raise ValueError(
            "カメラ校正と同じ解像度・撮影モードの基準画像を指定してください"
        )
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
        raise ValueError("カメラ係数（魚眼の歪み係数4個）・MM_PER_PXを確認してください")

    new_matrix = cv.fisheye.estimateNewCameraMatrixForUndistortRectify(
        matrix, distortion, (width, height), np.eye(3), balance=1.0
    )
    undistorted = cv.fisheye.undistortImage(
        reference_image, matrix, distortion, Knew=new_matrix, new_size=(width, height)
    )
    dictionary = cv.aruco.getPredefinedDictionary(cv.aruco.DICT_4X4_50)
    board = cv.aruco.CharucoBoard(BOARD_SQUARES, SQUARE_MM, MARKER_MM, dictionary)
    detector = cv.aruco.CharucoDetector(board)
    corners, ids, _, _ = detector.detectBoard(undistorted)
    if ids is None or len(ids) < 6 or board.checkCharucoCornersCollinear(ids):
        raise ValueError("ChArUco板の角を縦横に6点以上読める基準画像を指定してください")
    all_board_points = np.array(board.getChessboardCorners(), dtype=np.float32)
    board_xy = all_board_points[ids.astype(np.int32).ravel(), :2]
    detected_xy = corners.reshape(-1, 2)
    homography, _ = cv.findHomography(detected_xy, board_xy)
    if homography is None or not np.isfinite(homography).all():
        raise ValueError("基準画像の板から遠近補正を求められません")
    try:
        board_to_image = np.linalg.inv(homography)
    except np.linalg.LinAlgError as error:
        raise ValueError("基準画像の板から遠近補正を求められません") from error
    predicted = cv.perspectiveTransform(
        board_xy.reshape(-1, 1, 2), board_to_image
    ).reshape(-1, 2)
    error_px = float(np.sqrt(np.mean(np.sum((predicted - detected_xy) ** 2, axis=1))))
    if error_px > 2.0:
        raise ValueError(
            f"基準画像の再投影誤差が大きいため保存しません: {error_px:.3f}px"
        )

    # 既存の01と同じく写真内の向きを残し、試料の長手を縦にして測る。
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

    left, top, right, bottom = RECTIFY_ROI
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
        raise ValueError("RECTIFY_ROIは0〜1の範囲で、左 < 右、上 < 下にしてください")
    left_px = left * (width - 1)
    right_px = right * (width - 1)
    top_px = top * (height - 1)
    bottom_px = bottom * (height - 1)
    frame_corners = np.array(
        [
            [left_px, top_px],
            [right_px, top_px],
            [right_px, bottom_px],
            [left_px, bottom_px],
        ],
        dtype=np.float64,
    )
    denominators = frame_corners @ homography[2, :2] + homography[2, 2]
    if not (np.all(denominators > 0) or np.all(denominators < 0)):
        raise ValueError(
            "基準画像の撮影角度が浅すぎます。計測面へ向けて撮り直してください"
        )
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
        raise ValueError(
            "補正画像が大きすぎます。基準画像の撮影角度・板の寸法を確認してください"
        )
    world_to_pixels = np.array(
        [[1 / MM_PER_PX, 0, -minimum[0]], [0, 1 / MM_PER_PX, -minimum[1]], [0, 0, 1]],
        dtype=np.float64,
    )
    transform = world_to_pixels @ homography
    return {
        "matrix": matrix,
        "distortion": distortion,
        "new_matrix": new_matrix,
        "input_size": (width, height),
        "transform": transform,
        "output_size": (output_width, output_height),
        "mm_per_px": MM_PER_PX,
        "corner_count": len(ids),
        "error_px": error_px,
    }


def rectify_frame(image: np.ndarray, correction: dict) -> np.ndarray:
    """各フレームのボードは読まず、基準画像と同じ座標・倍率へ補正する。"""
    height, width = image.shape[:2]
    if (width, height) != correction["input_size"]:
        raise ValueError("基準画像と同じ解像度のフレームを指定してください")
    undistorted = cv.fisheye.undistortImage(
        image,
        correction["matrix"],
        correction["distortion"],
        Knew=correction["new_matrix"],
        new_size=correction["input_size"],
    )
    corrected = cv.warpPerspective(
        undistorted,
        correction["transform"],
        correction["output_size"],
        flags=cv.INTER_LINEAR,
    )
    return corrected


def main() -> None:
    reference_path = Path(REFERENCE_IMAGE_PATH).resolve()
    input_directory = Path(FRAMES_DIRECTORY).resolve()
    output_directory = Path(RECTIFIED_FRAMES_DIRECTORY).resolve()
    if input_directory == output_directory:
        raise ValueError("入力と出力は別のフォルダにしてください")
    input_paths = find_images(input_directory)
    protected_paths = [reference_path]
    protected_paths.extend(input_paths)
    reference_output_path = check_output_path(
        output_directory / "reference" / f"{reference_path.stem}.png",
        ".png",
        protected_paths,
    )
    output_names = []
    for input_path in input_paths:
        output_name = f"{input_path.stem}.png"
        if output_name.casefold() in output_names:
            raise ValueError(
                f"出力名が重複します。入力名を変えてください: {output_name}"
            )
        output_names.append(output_name.casefold())
        check_output_path(output_directory / output_name, ".png", protected_paths)

    reference_image = read_image(reference_path)
    correction = prepare_rectification(reference_image)
    corrected_reference = rectify_frame(reference_image, correction)
    write_png(reference_output_path, corrected_reference)
    print(
        f"基準: {reference_path} / 角{correction['corner_count']}点 / "
        f"再投影誤差{correction['error_px']:.3f}px"
    )
    print(f"基準の補正画像: {reference_output_path}")
    print(f"固定倍率: {correction['mm_per_px']}mm/px")
    output_width, output_height = correction["output_size"]
    print(f"出力サイズ: {output_width}×{output_height}px")
    for input_path in input_paths:
        image = read_image(input_path)
        try:
            corrected = rectify_frame(image, correction)
        except ValueError as error:
            raise ValueError(f"{input_path.name}: {error}") from error
        output_path = output_directory / f"{input_path.stem}.png"
        write_png(output_path, corrected)
        print(f"保存: {output_path.name}")
    print(f"完了: {len(input_paths)}枚 → {output_directory}")


if __name__ == "__main__":
    main()
