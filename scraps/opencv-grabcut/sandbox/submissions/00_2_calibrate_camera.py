"""ChArUcoの複数写真から、魚眼モデルのカメラ行列と4つの歪み係数を求める."""

import re
from pathlib import Path

import cv2 as cv
import numpy as np

# この撮影モード・解像度で撮った校正板の写真だけを入れる。
INPUT_DIRECTORY = "input/camera_calibration"
OUTPUT_DIRECTORY = "output/camera_detection"

# 00_1_generate_charuco_board.pyと01_rectify_images.pyと同じ板。
BOARD_SQUARES = (7, 5)
SQUARE_MM = 30.0
MARKER_MM = 18.0


def calibrate(input_paths: list[Path], output_directory: Path) -> tuple:
    dictionary = cv.aruco.getPredefinedDictionary(cv.aruco.DICT_4X4_50)
    board = cv.aruco.CharucoBoard(BOARD_SQUARES, SQUARE_MM, MARKER_MM, dictionary)
    detector = cv.aruco.CharucoDetector(board)
    all_board_points = np.array(board.getChessboardCorners(), dtype=np.float64)
    object_points = []
    image_points = []
    image_size = None
    for index, input_path in enumerate(input_paths):
        image = cv.imdecode(
            np.frombuffer(input_path.read_bytes(), np.uint8), cv.IMREAD_COLOR
        )
        if image is None:
            raise ValueError(f"画像を読み込めません: {input_path.name}")
        height, width = image.shape[:2]
        if image_size is not None and image_size != (width, height):
            raise ValueError(f"校正写真の解像度を揃えてください: {input_path.name}")
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
        check_path = output_directory / f"{input_path.name}_detected.png"
        success, encoded = cv.imencode(".png", check_image)
        if not success:
            raise OSError(f"PNGを作成できません: {check_path.name}")
        check_path.parent.mkdir(parents=True, exist_ok=True)
        check_path.write_bytes(encoded.tobytes())
        print(
            f"読取確認 {index + 1}: {input_path.name} / {status} / 角{corner_count}点"
        )
        if not usable:
            raise ValueError(
                f"板の角を縦横に6点以上読める写真が必要です: {input_path.name}"
            )
        board_points = all_board_points[ids.astype(np.int32).ravel()]
        # OpenCV 5の魚眼校正へ、1行に全点を並べた形で渡す。
        detected_points = np.array(corners, dtype=np.float64).reshape(1, -1, 2)
        object_points.append(board_points.reshape(1, -1, 3))
        image_points.append(detected_points)

    if len(input_paths) < 10:
        raise ValueError(
            "位置・傾き・距離を変えた校正板の写真を10枚以上用意してください"
        )
    assert image_size is not None
    camera_matrix = np.zeros((3, 3), dtype=np.float64)
    dist_coeffs = np.zeros((4, 1), dtype=np.float64)
    flags = cv.CALIB_RECOMPUTE_EXTRINSIC | cv.CALIB_CHECK_COND | cv.CALIB_FIX_SKEW
    try:
        rms_px, camera_matrix, dist_coeffs, rotations, translations = (
            cv.fisheye.calibrate(
                object_points,
                image_points,
                image_size,
                camera_matrix,
                dist_coeffs,
                flags=flags,
                criteria=(cv.TERM_CRITERIA_EPS + cv.TERM_CRITERIA_MAX_ITER, 100, 1e-8),
            )
        )
    except cv.error as error:
        match = re.search(r"Ill-conditioned matrix for input array (\d+)", str(error))
        if match is None:
            raise
        photo_index = int(match.group(1))
        photo_path = input_paths[photo_index]
        check_path = output_directory / f"{photo_path.name}_detected.png"
        raise ValueError(
            f"魚眼校正で姿勢を安定して求められません: {photo_index + 1}枚目 / {photo_path.name}\n"
            f"確認画像: {check_path}\n"
            "写真を入力フォルダ外へ移すか撮り直し、残り10枚以上で再実行してください。"
        ) from error
    if (
        not np.isfinite(rms_px)
        or not np.isfinite(camera_matrix).all()
        or not np.isfinite(dist_coeffs).all()
        or camera_matrix[0, 0] <= 0
        or camera_matrix[1, 1] <= 0
    ):
        raise ValueError(
            "校正できません。板の位置・傾き・距離を変えて撮り直してください"
        )
    # 全体のRMSだけでは、読取りの悪い1枚を見落とすため各写真も表示する。
    errors_px = []
    for index, points in enumerate(object_points):
        projected, _ = cv.fisheye.projectPoints(
            points, rotations[index], translations[index], camera_matrix, dist_coeffs
        )
        difference = projected.reshape(-1, 2) - image_points[index].reshape(-1, 2)
        error_px = float(np.sqrt(np.mean(np.sum(difference**2, axis=1))))
        errors_px.append(error_px)
    return image_size, camera_matrix, dist_coeffs, float(rms_px), errors_px


def parameter_text(
    image_size: tuple, camera_matrix: np.ndarray, dist_coeffs: np.ndarray
) -> str:
    return (
        f"CALIBRATION_SIZE = {image_size!r}\n"
        f"CAMERA_MATRIX = {camera_matrix.tolist()!r}\n"
        f"DIST_COEFFS = {dist_coeffs.ravel().tolist()!r}"
    )


def main() -> None:
    script_directory = Path(__file__).resolve().parent
    input_directory = (script_directory / INPUT_DIRECTORY).resolve()
    output_directory = (script_directory / OUTPUT_DIRECTORY).resolve()
    if input_directory == output_directory:
        raise ValueError("入力と出力は別のフォルダにしてください")
    if not input_directory.is_dir():
        raise ValueError(f"入力フォルダがありません: {input_directory}")
    input_paths = []
    for input_path in sorted(input_directory.iterdir()):
        if not input_path.is_file() or input_path.suffix.lower() not in (
            ".png",
            ".jpg",
            ".jpeg",
            ".bmp",
            ".tif",
            ".tiff",
        ):
            continue
        input_paths.append(input_path)
    if not input_paths:
        raise ValueError("入力フォルダに画像がありません")
    image_size, camera_matrix, dist_coeffs, rms_px, errors_px = calibrate(
        input_paths, output_directory
    )
    print(
        f"魚眼モデル / 再投影誤差 RMS: {rms_px:.4f}px（実寸精度の保証値ではありません）"
    )
    for input_path, error in zip(input_paths, errors_px):
        print(f"  {input_path.name}: {error:.4f}px")
    print("\n01_rectify_images.pyの冒頭の3設定を、以下に置き換えてください。\n")
    print(parameter_text(image_size, camera_matrix, dist_coeffs))


if __name__ == "__main__":
    main()
