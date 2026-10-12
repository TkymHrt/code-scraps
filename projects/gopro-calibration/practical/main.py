"""チェッカーボードから魚眼レンズを校正し、写真の歪みを補正する。"""

import argparse
import json
from glob import glob
from pathlib import Path

import cv2
import numpy as np


def read_image(path):
    """8bitのJPG/PNGを読む。自動回転しない。"""
    path = Path(path)
    if path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
        raise ValueError("入力はJPGまたはPNGを指定してください。")
    # imread/imwriteの代わりに使うと、Windowsの日本語パスにも対応できる。
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError(f"画像を読み込めません: {path}")
    if image.dtype != np.uint8:
        raise ValueError(f"8bitの画像を使ってください: {path}")
    return image


def write_image(path, image):
    """補正結果をPNGで保存する。"""
    path = Path(path)
    if path.suffix.lower() != ".png":
        raise ValueError("出力は .png を指定してください。")
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(path.suffix, image)
    if not ok:
        raise ValueError(f"画像を保存できません: {path}")
    encoded.tofile(path)


def calibrate(images, pattern=(9, 6), square=25.0, out="calibration.json"):
    """複数写真の既知の格子点から、K（内部パラメータ）とD（歪み）を求める。"""
    if min(pattern) < 3 or not np.isfinite(square) or square <= 0:
        raise ValueError(
            "内側の交点数は各3以上、マスの一辺は正の数を指定してください。"
        )
    paths = [Path(name) for name in sorted(glob(str(images))) if Path(name).is_file()]
    if not paths:
        raise ValueError(f"画像が見つかりません: {images}")
    out = Path(out)
    debug_dir = out.parent / (out.stem + "_corners")
    # 1. 盤の実際の交点位置を作る。平らな盤なので高さは0。
    columns, rows = pattern
    object_points = []
    for row in range(rows):
        for column in range(columns):
            object_points.append([column * square, row * square, 0])
    object_points = np.array([object_points], dtype=np.float64)
    image_points = []
    image_size = None

    # 2. 各写真から同じ交点を検出する。
    corner_flags = (
        cv2.CALIB_CB_NORMALIZE_IMAGE | cv2.CALIB_CB_EXHAUSTIVE | cv2.CALIB_CB_ACCURACY
    )
    for path in paths:
        image = read_image(path)
        size = (image.shape[1], image.shape[0])  # OpenCVは（幅, 高さ）の順。
        if image_size is not None and size != image_size:
            raise ValueError(f"解像度が混在しています: {path}: {size} != {image_size}")
        image_size = size
        gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        found, corners = cv2.findChessboardCornersSB(gray, pattern, flags=corner_flags)
        if not found:
            print(f"SKIP  {path.name}: 全交点を検出できませんでした。")
            continue
        image_points.append(corners.astype(np.float64))
        preview = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        cv2.drawChessboardCorners(preview, pattern, corners, True)
        write_image(debug_dir / (path.name + ".png"), preview)
        print(f"OK    {path.name}")

    if len(image_points) < 10:
        raise ValueError(
            f"検出できた画像は{len(image_points)}枚です。異なる位置・傾きで10枚以上必要です。"
        )
    # 3. 実際の位置と写真上の位置から、カメラ行列と歪み係数を求める。
    calibration_flags = (
        cv2.fisheye.CALIB_RECOMPUTE_EXTRINSIC
        | cv2.fisheye.CALIB_CHECK_COND
        | cv2.fisheye.CALIB_FIX_SKEW
    )
    try:
        rms, camera_matrix, distortion, _, _ = cv2.fisheye.calibrate(
            [object_points] * len(image_points),
            image_points,
            image_size,
            np.zeros((3, 3)),
            np.zeros((4, 1)),
            flags=calibration_flags,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 100, 1e-7),
        )
    except cv2.error as error:
        raise ValueError(
            "校正に失敗しました。検出図を確認し、位置・距離・傾きを変えて撮り直してください。"
        ) from error

    # 4. 別の写真にも使えるよう、係数をJSONに保存する。
    data = {
        "model": "opencv_fisheye",
        "image_size": list(image_size),
        "pattern": list(pattern),
        "square_mm": square,
        "K": camera_matrix.tolist(),
        "D": distortion.ravel().tolist(),
        "rms_px": float(rms),
        "image_count": len(image_points),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    print(f"保存: {out} / 検出図: {debug_dir} / 再投影RMS: {rms:.4f} px")
    if rms > 1:
        print("RMSが1pxを超えています。検出図を確認してください。")


def undistort(calibration, image_path, out="corrected.png", balance=0.0):
    """校正時と同じサイズの画像を透視投影に変換する。"""
    if not np.isfinite(balance) or not 0 <= balance <= 1:
        raise ValueError("balanceは0〜1を指定してください。")
    if Path(image_path).resolve() == Path(out).resolve():
        raise ValueError("入力画像と出力画像は別のパスを指定してください。")
    data = json.loads(Path(calibration).read_text(encoding="utf-8"))
    if data["model"] != "opencv_fisheye":
        raise ValueError("このスクリプトの魚眼モデルで校正したJSONを使ってください。")
    image = read_image(image_path)
    size = (image.shape[1], image.shape[0])
    if size != tuple(data["image_size"]):
        raise ValueError(f"校正時と解像度が異なります: {size} != {data['image_size']}")
    camera_matrix = np.array(data["K"], dtype=np.float64)
    distortion = np.array(data["D"], dtype=np.float64).reshape(4, 1)
    new_matrix = cv2.fisheye.estimateNewCameraMatrixForUndistortRectify(
        camera_matrix, distortion, size, np.eye(3), balance=balance
    )
    corrected = cv2.fisheye.undistortImage(
        image, camera_matrix, distortion, Knew=new_matrix
    )
    write_image(out, corrected)
    # 補正後の画像で座標計算をするときは元のKではなく、このKを使う。
    metadata = {
        "model": "pinhole",
        "image_size": list(size),
        "K": new_matrix.tolist(),
        "D": [0, 0, 0, 0, 0],
    }
    Path(str(out) + ".json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    print(f"保存: {out} ({corrected.dtype}) / 補正後のK: {out}.json")


def main():
    """コマンドは校正・補正の2つだけ。"""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    cal = commands.add_parser("calibrate", help="チェッカーボード写真から校正")
    cal.add_argument("images", help='校正写真。例: "photos/*.JPG"')
    cal.add_argument(
        "--pattern",
        nargs=2,
        type=int,
        default=(9, 6),
        metavar=("COLS", "ROWS"),
        help="内側の交点数（横 縦）",
    )
    cal.add_argument("--square", type=float, default=25.0, help="1マスのmm")
    cal.add_argument("--out", default="calibration.json", help="保存先")
    fix = commands.add_parser("undistort", help="保存済みの校正JSONで画像を補正")
    fix.add_argument("calibration", help="校正JSON")
    fix.add_argument("image", help="補正したい画像")
    fix.add_argument("--out", default="corrected.png", help="保存先")
    fix.add_argument(
        "--balance",
        type=float,
        default=0.0,
        help="0: 余白を減らす / 1: 画角を残す",
    )
    args = parser.parse_args()
    try:
        if args.command == "calibrate":
            calibrate(args.images, tuple(args.pattern), args.square, args.out)
        else:
            undistort(args.calibration, args.image, args.out, args.balance)
    except (OSError, ValueError, cv2.error) as error:
        parser.exit(1, f"エラー: {error}\n")


if __name__ == "__main__":
    main()
