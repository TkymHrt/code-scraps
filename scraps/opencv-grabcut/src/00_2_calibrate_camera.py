"""ChArUcoの複数写真から、魚眼モデルのカメラ行列と4つの歪み係数を求める."""

import re
from pathlib import Path

import cv2 as cv
import numpy as np

from utils.file_io import find_images, read_image, write_png
from workflow_settings import (
    BOARD_SQUARES,
    CALIBRATION_DIRECTORY,
    DETECTION_DIRECTORY,
    MARKER_MM,
    SQUARE_MM,
)


def calibrate(paths: list[Path], output_directory: Path) -> tuple:
    """使える写真で校正し、入力順の誤差を返す。除外した写真の誤差はNone。"""
    dictionary = cv.aruco.getPredefinedDictionary(cv.aruco.DICT_4X4_50)
    board = cv.aruco.CharucoBoard(BOARD_SQUARES, SQUARE_MM, MARKER_MM, dictionary)
    detector = cv.aruco.CharucoDetector(board)
    all_board_points = np.array(board.getChessboardCorners(), dtype=np.float64)
    object_points = []
    image_points = []
    used_indices = []
    image_size = None
    for index, path in enumerate(paths):
        try:
            image = read_image(path)
        except ValueError as error:
            print(f"スキップ {index + 1}: {error}")
            continue
        height, width = image.shape[:2]
        corners, ids, markers, marker_ids = detector.detectBoard(image)
        corner_count = 0
        if ids is not None:
            corner_count = len(ids)
        skip_reason = None
        if corner_count < 6 or board.checkCharucoCornersCollinear(ids):
            skip_reason = "板の角を縦横に6点以上読めません"
        elif image_size is not None and image_size != (width, height):
            skip_reason = f"解像度が違います: {(width, height)} / 使用: {image_size}"
        check_image = image.copy()
        if marker_ids is not None:
            cv.aruco.drawDetectedMarkers(check_image, markers, marker_ids)
        if corner_count > 0:
            cv.aruco.drawDetectedCornersCharuco(
                check_image, corners.reshape(-1, 1, 2), ids, (0, 0, 255)
            )
        status = "OK" if skip_reason is None else "NG"
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
        write_png(check_path, check_image)
        print(f"読取確認 {index + 1}: {path.name} / {status} / 角{corner_count}点")
        if skip_reason is not None:
            print(f"スキップ {index + 1}: {path.name} / {skip_reason}")
            print(f"確認画像: {check_path}")
            continue
        image_size = (width, height)
        board_points = all_board_points[ids.astype(np.int32).ravel()]
        # OpenCV 5の魚眼校正へ、1行に全点を並べた形で渡す。
        detected_points = np.array(corners, dtype=np.float64).reshape(1, -1, 2)
        object_points.append(board_points.reshape(1, -1, 3))
        image_points.append(detected_points)
        used_indices.append(index)

    flags = cv.CALIB_RECOMPUTE_EXTRINSIC | cv.CALIB_CHECK_COND | cv.CALIB_FIX_SKEW
    while True:
        if not object_points or image_size is None:
            raise ValueError(
                "校正に使える写真がありません。スキップ理由と確認画像を確認してください"
            )
        # 失敗した計算で書き換わった係数を、次の計算へ引き継がない。
        matrix = np.zeros((3, 3), dtype=np.float64)
        distortion = np.zeros((4, 1), dtype=np.float64)
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
            break
        except cv.error as error:
            match = re.search(
                r"Ill-conditioned matrix for input array (\d+)", str(error)
            )
            if match is None:
                raise ValueError("カメラ校正に失敗しました") from error
            photo_index = int(match.group(1))
            if photo_index >= len(used_indices):
                raise ValueError("カメラ校正に失敗しました") from error
            input_index = used_indices.pop(photo_index)
            photo_path = paths[input_index]
            check_path = output_directory / f"{photo_path.name}_detected.png"
            print(
                f"スキップ {input_index + 1}: {photo_path.name} / 校正計算が不安定です"
            )
            print(f"確認画像: {check_path}")
            del object_points[photo_index]
            del image_points[photo_index]
    if (
        not np.isfinite(rms)
        or not np.isfinite(matrix).all()
        or not np.isfinite(distortion).all()
        or matrix[0, 0] <= 0
        or matrix[1, 1] <= 0
    ):
        raise ValueError("校正係数が不正です。写真を確認してください")
    # 全体のRMSだけでは、読取りの悪い1枚を見落とすため各写真も表示する。
    errors: list[float | None] = [None] * len(paths)
    for index, points in enumerate(object_points):
        projected, _ = cv.fisheye.projectPoints(
            points, rotations[index], translations[index], matrix, distortion
        )
        difference = projected.reshape(-1, 2) - image_points[index].reshape(-1, 2)
        error_px = float(np.sqrt(np.mean(np.sum(difference**2, axis=1))))
        input_index = used_indices[index]
        errors[input_index] = error_px
    print(
        f"校正に使用: {len(used_indices)} / {len(paths)}枚"
        f"（スキップ: {len(paths) - len(used_indices)}枚）"
    )
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
    input_directory = CALIBRATION_DIRECTORY.resolve()
    output_directory = DETECTION_DIRECTORY.resolve()
    if input_directory == output_directory:
        raise ValueError("入力と出力は別のフォルダにしてください")
    paths = find_images(input_directory)
    image_size, matrix, distortion, rms, errors = calibrate(paths, output_directory)
    print(f"魚眼モデル / 再投影誤差 RMS: {rms:.4f}px（実寸精度の保証値ではありません）")
    for path, error in zip(paths, errors):
        if error is not None:
            print(f"  {path.name}: {error:.4f}px")
    print("\n補正スクリプトの冒頭の3設定を、以下に置き換えてください。\n")
    print(parameter_text(image_size, matrix, distortion))


if __name__ == "__main__":
    main()
