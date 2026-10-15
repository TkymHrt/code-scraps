"""指定フォルダの写真を、魚眼モデルの固定係数とChArUcoで補正してPNGへ保存する."""

import math
from pathlib import Path

import cv2 as cv
import numpy as np

INPUT_DIRECTORY = "input"
OUTPUT_DIRECTORY = "output/rectified"

# camera_calibration.pyの出力を、この3設定へ一度貼り付ける。
# DIST_COEFFSは魚眼モデルのk1, k2, k3, k4。通常モデルの係数は使わない。
CALIBRATION_SIZE: tuple[int, int] | None = None
CAMERA_MATRIX: list[list[float]] | None = None
DIST_COEFFS: list[float] | None = None

# カメラ校正と同じ板を、試料の計測面と同じ高さに置く。
BOARD_SQUARES = (7, 5)
SQUARE_MM = 30.0
MARKER_MM = 18.0
# initial_regions_gui.pyにも同じ値を設定する。
MM_PER_PX = 0.25


def save_png(path: Path, image: np.ndarray) -> None:
    success, encoded = cv.imencode(".png", image)
    if not success:
        raise OSError(f"PNGにできません: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded.tobytes())


def rectify_image(image: np.ndarray, check_path: Path) -> dict:
    if CALIBRATION_SIZE is None or CAMERA_MATRIX is None or DIST_COEFFS is None:
        raise ValueError("コード冒頭へcamera_calibration.pyの3設定を貼り付けてください")
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
        raise ValueError(
            "魚眼モデルのカメラ係数（歪み係数4個）とMM_PER_PXを確認してください"
        )
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
    corners, ids, markers, marker_ids = detector.detectBoard(undistorted)
    corner_count = 0
    if ids is not None:
        corner_count = len(ids)
    usable = corner_count >= 6 and not board.checkCharucoCornersCollinear(ids)
    check_image = undistorted.copy()
    if marker_ids is not None:
        cv.aruco.drawDetectedMarkers(check_image, markers, marker_ids)
    if corner_count > 0:
        cv.aruco.drawDetectedCornersCharuco(
            check_image, corners.reshape(-1, 1, 2), ids, (0, 0, 255)
        )
    status = "OK" if usable else "NG"
    cv.putText(
        check_image,
        f"{status}: {corner_count} corners",
        (20, 40),
        cv.FONT_HERSHEY_SIMPLEX,
        1,
        (0, 255, 255),
        2,
    )
    save_png(check_path, check_image)
    print(f"読取確認: {check_path.name} / {status} / 角{corner_count}点")
    if not usable:
        raise ValueError("ChArUco板の角を縦横に6点以上読める画像を指定してください")
    all_board_points = np.array(board.getChessboardCorners(), dtype=np.float32)
    board_xy = all_board_points[ids.astype(np.int32).ravel(), :2]
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
        "corner_count": corner_count,
        "error_px": error_px,
    }


def main() -> None:
    directory = Path(__file__).resolve().parent
    input_directory = (directory / INPUT_DIRECTORY).resolve()
    output_directory = (directory / OUTPUT_DIRECTORY).resolve()
    if input_directory == output_directory:
        raise ValueError("入力と出力は別のフォルダにしてください")
    if not input_directory.is_dir():
        raise ValueError(f"入力フォルダがありません: {input_directory}")
    input_paths = []
    output_names = []
    for path in sorted(input_directory.iterdir()):
        if not path.is_file() or path.suffix.lower() not in (
            ".png",
            ".jpg",
            ".jpeg",
            ".bmp",
            ".tif",
            ".tiff",
        ):
            continue
        output_name = f"{path.stem}.png"
        if output_name.casefold() in output_names:
            raise ValueError(
                f"出力名が重複します。入力名を変えてください: {output_name}"
            )
        input_paths.append(path)
        output_names.append(output_name.casefold())
    if not input_paths:
        raise ValueError("入力フォルダに画像がありません")

    for input_path in input_paths:
        output_path = output_directory / f"{input_path.stem}.png"
        check_path = output_directory / "detected" / f"{input_path.name}_detected.png"
        image = cv.imdecode(
            np.frombuffer(input_path.read_bytes(), np.uint8), cv.IMREAD_COLOR
        )
        if image is None:
            raise ValueError(f"画像を読み込めません: {input_path.name}")
        correction = rectify_image(image, check_path)
        save_png(output_path, correction["image"])
        print(
            f"保存: {output_path.name} / 角{correction['corner_count']}点 / "
            f"再投影誤差{correction['error_px']:.3f}px"
        )
    print(f"完了: {len(input_paths)}枚 → {output_directory}")


if __name__ == "__main__":
    main()
