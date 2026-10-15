"""ChArUcoの複数写真から、魚眼モデルのカメラ行列と4つの歪み係数を求める."""

import re
from pathlib import Path

import cv2 as cv
import numpy as np

# この撮影モード・解像度で撮った校正板の写真だけを入れる。
INPUT_DIRECTORY = "input/camera_calibration"
OUTPUT_DIRECTORY = "output/camera_detection"

# generate_charuco_board.pyとrectify_image.pyと同じ板。
BOARD_SQUARES = (7, 5)
SQUARE_MM = 30.0
MARKER_MM = 18.0


def calibrate(paths: list[Path], output_directory: Path) -> tuple:
    dictionary = cv.aruco.getPredefinedDictionary(cv.aruco.DICT_4X4_50)
    board = cv.aruco.CharucoBoard(BOARD_SQUARES, SQUARE_MM, MARKER_MM, dictionary)
    detector = cv.aruco.CharucoDetector(board)
    all_board_points = np.array(board.getChessboardCorners(), dtype=np.float64)
    object_points = []
    image_points = []
    image_size = None
    for index, path in enumerate(paths):
        image = cv.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"画像を読み込めません: {path.name}")
        height, width = image.shape[:2]
        if image_size is not None and image_size != (width, height):
            raise ValueError(f"校正写真の解像度を揃えてください: {path.name}")
        image_size = (width, height)
        corners, ids, markers, marker_ids = detector.detectBoard(image)
        corner_count = 0
        if ids is not None:
            corner_count = len(ids)
        usable = corner_count >= 6 and not board.checkCharucoCornersCollinear(ids)
        check_image = image.copy()
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
        check_path = output_directory / f"{path.name}_detected.png"
        success, encoded = cv.imencode(".png", check_image)
        if not success:
            raise OSError(f"PNGにできません: {check_path.name}")
        check_path.parent.mkdir(parents=True, exist_ok=True)
        check_path.write_bytes(encoded.tobytes())
        print(f"読取確認 {index + 1}: {path.name} / {status} / 角{corner_count}点")
        if not usable:
            raise ValueError(f"板の角を縦横に6点以上読める写真が必要です: {path.name}")
        board_points = all_board_points[ids.astype(np.int32).ravel()]
        # OpenCV 5の魚眼校正へ、1行に全点を並べた形で渡す。
        detected_points = np.array(corners, dtype=np.float64).reshape(1, -1, 2)
        object_points.append(board_points.reshape(1, -1, 3))
        image_points.append(detected_points)

    if len(paths) < 10:
        raise ValueError(
            "位置・傾き・距離を変えた校正板の写真を10枚以上用意してください"
        )
    assert image_size is not None
    matrix = np.zeros((3, 3), dtype=np.float64)
    distortion = np.zeros((4, 1), dtype=np.float64)
    flags = cv.CALIB_RECOMPUTE_EXTRINSIC | cv.CALIB_CHECK_COND | cv.CALIB_FIX_SKEW
    try:
        rms, matrix, distortion, rotations, translations = cv.fisheye.calibrate(
            object_points,
            image_points,
            image_size,
            matrix,
            distortion,
            flags=flags,
            criteria=(cv.TERM_CRITERIA_EPS + cv.TERM_CRITERIA_MAX_ITER, 100, 1e-8),
        )
    except cv.error as error:
        match = re.search(r"Ill-conditioned matrix for input array (\d+)", str(error))
        if match is None:
            raise
        photo_index = int(match.group(1))
        photo_path = paths[photo_index]
        check_path = output_directory / f"{photo_path.name}_detected.png"
        raise ValueError(
            f"魚眼校正で姿勢を安定して求められません: {photo_index + 1}枚目 / {photo_path.name}\n"
            f"確認画像: {check_path}\n"
            "角を読めても校正できない場合があります。確認画像を見て、この写真を入力フォルダ外へ移すか撮り直し、"
            "残り10枚以上で再実行してください。"
        ) from error
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
        projected, _ = cv.fisheye.projectPoints(
            points, rotations[index], translations[index], matrix, distortion
        )
        difference = projected.reshape(-1, 2) - image_points[index].reshape(-1, 2)
        error_px = float(np.sqrt(np.mean(np.sum(difference**2, axis=1))))
        errors.append(error_px)
    return image_size, matrix, distortion, float(rms), errors


def parameter_text(
    image_size: tuple, matrix: np.ndarray, distortion: np.ndarray
) -> str:
    return (
        f"CALIBRATION_SIZE = {image_size!r}\n"
        f"CAMERA_MATRIX = {matrix.tolist()!r}\n"
        f"DIST_COEFFS = {distortion.ravel().tolist()!r}"
    )


def main() -> None:
    directory = Path(__file__).resolve().parent
    input_directory = (directory / INPUT_DIRECTORY).resolve()
    output_directory = (directory / OUTPUT_DIRECTORY).resolve()
    if input_directory == output_directory:
        raise ValueError("入力と出力は別のフォルダにしてください")
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
    image_size, matrix, distortion, rms, errors = calibrate(paths, output_directory)
    print(f"魚眼モデル / 再投影誤差 RMS: {rms:.4f}px（実寸精度の保証値ではありません）")
    for path, error in zip(paths, errors):
        print(f"  {path.name}: {error:.4f}px")
    print("\nrectify_image.pyの冒頭の3設定を、以下に置き換えてください。\n")
    print(parameter_text(image_size, matrix, distortion))


if __name__ == "__main__":
    main()
