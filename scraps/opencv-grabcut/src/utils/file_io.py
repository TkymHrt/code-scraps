"""日本語パスでの画像入出力と、出力先の確認。"""

from pathlib import Path

import cv2 as cv
import numpy as np


def find_images(directory: Path) -> list[Path]:
    """フォルダ直下の対応画像を名前順に返す。"""
    if not directory.is_dir():
        raise ValueError(f"入力フォルダがありません: {directory}")
    paths = []
    for path in sorted(directory.iterdir()):
        if path.is_file() and path.suffix.lower() in (
            ".png",
            ".jpg",
            ".jpeg",
            ".bmp",
            ".tif",
            ".tiff",
        ):
            paths.append(path)
    if not paths:
        raise ValueError(f"画像がありません: {directory}")
    return paths


def read_image(path: Path) -> np.ndarray:
    try:
        data = np.frombuffer(path.read_bytes(), np.uint8)
        image = cv.imdecode(data, cv.IMREAD_COLOR)
    except (OSError, cv.error) as error:
        raise ValueError(f"画像を読み込めません: {path.name}") from error
    if image is None:
        raise ValueError(f"画像を読み込めません: {path.name}")
    return image


def encode_png(image: np.ndarray) -> bytes:
    """保存前にPNGへ変換する。CSVと画像を組で保存するときにも使う。"""
    try:
        success, encoded = cv.imencode(".png", image)
    except cv.error as error:
        raise OSError("PNGを作成できません") from error
    if not success:
        raise OSError("PNGを作成できません")
    return encoded.tobytes()


def write_png(path: Path, image: np.ndarray) -> None:
    path = check_output_path(path, ".png", [])
    png_data = encode_png(image)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png_data)


def check_output_path(path: Path, suffix: str, inputs: list[Path]) -> Path:
    path = path.resolve()
    if path.suffix.lower() != suffix:
        raise ValueError(f"保存先の拡張子は {suffix} にしてください")
    for input_path in inputs:
        if path == input_path.resolve():
            raise ValueError("入力ファイルと別の保存先を選んでください")
    return path
