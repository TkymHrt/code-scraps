"""ChArUcoの複数写真から、換算GUIへ貼るカメラ行列と歪み係数を求める."""

from pathlib import Path

import cv2 as cv
import numpy as np

# この撮影モード・解像度で撮った校正板の写真だけを入れる。
INPUT_DIRECTORY = "input/camera_calibration"

# generate_charuco_board.pyと換算GUIと同じ板。
BOARD_SQUARES = (7, 5)
SQUARE_MM = 30.0
MARKER_MM = 18.0


def calibrate(paths: list[Path]) -> tuple:
    if len(paths) < 10:
        raise ValueError(
            "位置・傾き・距離を変えた校正板の写真を10枚以上用意してください"
        )
    dictionary = cv.aruco.getPredefinedDictionary(cv.aruco.DICT_4X4_50)
    board = cv.aruco.CharucoBoard(BOARD_SQUARES, SQUARE_MM, MARKER_MM, dictionary)
    detector = cv.aruco.CharucoDetector(board)
    object_points = []
    image_points = []
    image_size = None
    for path in paths:
        image = cv.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"画像を読み込めません: {path.name}")
        height, width = image.shape[:2]
        if image_size is not None and image_size != (width, height):
            raise ValueError(f"校正写真の解像度を揃えてください: {path.name}")
        image_size = (width, height)
        corners, ids, _, _ = detector.detectBoard(image)
        if ids is None or len(ids) < 6 or board.checkCharucoCornersCollinear(ids):
            raise ValueError(f"板の角を縦横に6点以上読める写真が必要です: {path.name}")
        all_board_points = np.array(board.getChessboardCorners(), dtype=np.float32)
        board_points = all_board_points[ids.astype(np.int32).ravel()]
        detected_points = corners
        object_points.append(board_points)
        image_points.append(detected_points)

    assert image_size is not None
    rms, matrix, distortion, rotations, translations = cv.calibrateCamera(
        object_points, image_points, image_size, None, None
    )
    if (
        not np.isfinite(rms)
        or not np.isfinite(matrix).all()
        or not np.isfinite(distortion).all()
        or matrix[0, 0] <= 0
        or matrix[1, 1] <= 0
    ):
        raise ValueError(
            "校正できません。板の位置・傾き・距離を変えて撮り直してください"
        )
    # 全体のRMSだけでは、読取りの悪い1枚を見落とすため各写真も表示する。
    errors = []
    for index, points in enumerate(object_points):
        projected, _ = cv.projectPoints(
            points, rotations[index], translations[index], matrix, distortion
        )
        difference = projected.reshape(-1, 2) - image_points[index].reshape(-1, 2)
        error_px = float(np.sqrt(np.mean(np.sum(difference**2, axis=1))))
        errors.append(error_px)
    return image_size, matrix, distortion, float(rms), errors


def parameter_text(
    image_size: tuple, matrix: np.ndarray, distortion: np.ndarray
) -> str:
    lines = [f"CALIBRATION_SIZE = {image_size!r}", "CAMERA_MATRIX = ["]
    for row in matrix:
        lines.append(f"    [{row[0]:.12g}, {row[1]:.12g}, {row[2]:.12g}],")
    lines.append("]")
    values = []
    for value in distortion.ravel():
        values.append(f"{value:.12g}")
    lines.append("DIST_COEFFS = [" + ", ".join(values) + "]")
    return "\n".join(lines)


def main() -> None:
    directory = Path(__file__).resolve().parent
    input_directory = directory / INPUT_DIRECTORY
    paths = []
    if input_directory.is_dir():
        for path in sorted(input_directory.iterdir()):
            if path.is_file() and path.suffix.lower() in (
                ".png",
                ".jpg",
                ".jpeg",
                ".bmp",
                ".tif",
                ".tiff",
            ):
                paths.append(path)
    if len(paths) < 10:
        print(
            f"次に{input_directory}へ、校正板の写真を10枚以上入れて再実行してください。"
        )
        return
    image_size, matrix, distortion, rms, errors = calibrate(paths)
    print(f"再投影誤差 RMS: {rms:.4f}px（実寸精度の保証値ではありません）")
    for path, error in zip(paths, errors):
        print(f"  {path.name}: {error:.4f}px")
    print("\nrectify_image_gui.pyの冒頭の3設定を、以下に置き換えてください。\n")
    print(parameter_text(image_size, matrix, distortion))


if __name__ == "__main__":
    main()
