"""既知の魚眼カメラの疑似写真を生成し、検出→校正→補正を検証する。"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

MAIN = Path(__file__).resolve().parents[1] / "practical" / "main.py"
SIZE = (960, 720)
PATTERN = (9, 6)
SQUARE = 25.0
CAMERA = np.array([[490.0, 0, 477.0], [0, 495.0, 359.0], [0, 0, 1]])
DISTORTION = np.array([-0.12, 0.025, -0.004, 0.0005])


def run_command(*arguments):
    """本体の内部関数を使わず、利用者と同じコマンドを実行する。"""
    subprocess.run([sys.executable, str(MAIN), *map(str, arguments)], check=True)


def read_image(path):
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)


def write_image(path, image):
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    encoded.tofile(path)


def detect_corners(image, pattern):
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    found, corners = cv2.findChessboardCornersSB(
        gray,
        pattern,
        flags=(
            cv2.CALIB_CB_NORMALIZE_IMAGE
            | cv2.CALIB_CB_EXHAUSTIVE
            | cv2.CALIB_CB_ACCURACY
        ),
    )
    return gray, corners if found else None


def verify_inputs(folder):
    """入力ミスも内部関数の呼び出しではなく、コマンドから確認する。"""
    calibration = folder / "calibration.json"
    image = folder / "held_out.jpg"
    passed = 0

    def expect_error(message, *arguments):
        nonlocal passed
        result = subprocess.run(
            [sys.executable, str(MAIN), *map(str, arguments)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        assert result.returncode == 1 and message in result.stderr, result.stderr
        passed += 1

    with tempfile.TemporaryDirectory(dir=folder) as temporary:
        work = Path(temporary)
        output = work / "corrected.png"
        expect_error("見つかりません", "calibrate", work / "missing/*.jpg")
        expect_error("JPGまたはPNG", "undistort", calibration, work / "image.bmp")
        expect_error("正の数", "calibrate", folder / "photos/*.jpg", "--square", 0)
        expect_error(
            "9枚",
            "calibrate",
            folder / "photos/board_0[0-8].jpg",
            "--out",
            work / "few.json",
        )
        write_image(work / "small.png", np.zeros((100, 100, 3), np.uint8))
        expect_error("解像度", "undistort", calibration, work / "small.png")
        for balance in (-0.1, 1.1, "nan"):
            expect_error(
                "balance", "undistort", calibration, image, "--balance", balance
            )
        expect_error("別のパス", "undistort", calibration, image, "--out", image)
        expect_error("出力", "undistort", calibration, image, "--out", work / "out.jpg")
        mixed = work / "mixed"
        mixed.mkdir()
        write_image(mixed / "a.png", read_image(image))
        write_image(mixed / "b.png", np.zeros((100, 100), np.uint8))
        expect_error(
            "解像度が混在", "calibrate", mixed / "*.png", "--out", work / "mixed.json"
        )
        write_image(work / "input16.png", np.full((100, 100), 40000, np.uint16))
        expect_error("8bit", "undistort", calibration, work / "input16.png")
        japanese = work / "日本語画像.png"
        write_image(japanese, np.full((SIZE[1], SIZE[0], 3), 123, np.uint8))
        run_command("undistort", calibration, japanese, "--out", output)
        restored = read_image(output)
        assert restored.dtype == np.uint8 and np.all(
            restored[SIZE[1] // 2, SIZE[0] // 2] == 123
        )
        passed += 1
    assert passed == 13
    return passed


def make_rays(scale=2):
    """各画素から出る光線を作る。2倍で描画して縮小し、ギザギザを減らす。"""
    width, height = SIZE
    yy, xx = np.mgrid[: height * scale, : width * scale]
    pixels = np.stack(((xx + 0.5) / scale - 0.5, (yy + 0.5) / scale - 0.5), axis=-1)
    xy = cv2.fisheye.undistortPoints(pixels.reshape(-1, 1, 2), CAMERA, DISTORTION)
    return np.column_stack((xy.reshape(-1, 2), np.ones(xx.size)))


def render_board(rays, rotation_vector, translation):
    """光線と盤の平面の交点から白黒を決める。ホモグラフィだけでは魚眼にならない。"""
    rotation, _ = cv2.Rodrigues(rotation_vector)
    normal = rotation[:, 2]
    distance = (normal @ translation) / (rays @ normal)
    local = (rays * distance[:, None] - translation) @ rotation
    col = np.floor(local[:, 0] / SQUARE).astype(int) + 1
    row = np.floor(local[:, 1] / SQUARE).astype(int) + 1
    inside = (
        (distance > 0)
        & (col >= 0)
        & (col <= PATTERN[0])
        & (row >= 0)
        & (row <= PATTERN[1])
    )
    pixels = np.full(len(rays), 160, np.uint8)
    pixels[inside] = np.where((col[inside] + row[inside]) % 2 == 0, 20, 235)
    width, height = SIZE
    return cv2.resize(
        pixels.reshape(height * 2, width * 2), SIZE, interpolation=cv2.INTER_AREA
    )


def line_rms(points):
    """盤の各行・列を直線に当てはめ、直線からの距離のRMSを求める。"""
    grid = points.reshape(PATTERN[1], PATTERN[0], 2)
    distances = []
    for line in list(grid) + list(grid.transpose(1, 0, 2)):
        centered = line - line.mean(axis=0)
        _, _, axes = np.linalg.svd(centered, full_matrices=False)
        distances.extend(centered @ axes[-1])
    return float(np.sqrt(np.mean(np.square(distances))))


def render_grid(rays):
    """歪みを見やすくするため、画面全体を覆う平面の格子も描く。"""
    tiles = np.floor(rays[:, :2] / 0.35).astype(int).sum(axis=1) % 2
    pixels = np.where(tiles == 0, 35, 225).astype(np.uint8)
    width, height = SIZE
    return cv2.resize(
        pixels.reshape(height * 2, width * 2), SIZE, interpolation=cv2.INTER_AREA
    )


def verify(folder):
    """点列を直接校正せず、JPGを書き出して本番と同じ交点検出を通す。"""
    folder = Path(folder)
    photos = folder / "photos"
    photos.mkdir(parents=True, exist_ok=True)
    # 固定名の出力先で古い画像が混ざらないよう、専用フォルダだけを使う。
    if list(photos.glob("*.jpg")):
        raise ValueError(
            "検証先にJPGが既にあります。別の --out フォルダを指定してください。"
        )
    rng = np.random.default_rng(42)
    rays = make_rays()
    center = np.array([(PATTERN[0] - 1) * SQUARE / 2, (PATTERN[1] - 1) * SQUARE / 2, 0])
    outer = np.array(
        [[[-25, -25, 0], [225, -25, 0], [225, 150, 0], [-25, 150, 0]]], dtype=np.float64
    )
    poses = []
    for _ in range(1000):
        rotation_vector = rng.uniform([-0.65, -0.65, -0.2], [0.65, 0.65, 0.2])
        rotation, _ = cv2.Rodrigues(rotation_vector)
        depth = rng.uniform(200, 340)
        target = np.array(
            [rng.uniform(-0.9, 0.9) * depth, rng.uniform(-0.65, 0.65) * depth, depth]
        )
        translation = target - rotation @ center
        border, _ = cv2.fisheye.projectPoints(
            outer, rotation_vector, translation, CAMERA, DISTORTION
        )
        border = border.reshape(-1, 2)
        if np.any(border < 24) or np.any(border > np.array(SIZE) - 24):
            continue
        poses.append((rotation_vector, translation))
        if len(poses) == 25:
            break
    if len(poses) != 25:
        raise AssertionError("疑似写真の姿勢を生成できませんでした。")
    for index, (rotation_vector, translation) in enumerate(poses):
        gray = render_board(rays, rotation_vector, translation)
        noise = rng.normal(0, 0.6, gray.shape)
        image = np.clip(gray.astype(float) + noise, 0, 255).astype(np.uint8)
        path = (
            photos / f"board_{index:02}.jpg" if index < 24 else folder / "held_out.jpg"
        )
        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 95])
        assert ok
        encoded.tofile(path)
    write_image(folder / "wide_grid.png", render_grid(rays))
    del rays

    calibration_file = folder / "calibration.json"
    run_command(
        "calibrate",
        photos / "*.jpg",
        "--pattern",
        *PATTERN,
        "--square",
        SQUARE,
        "--out",
        calibration_file,
    )
    data = json.loads(calibration_file.read_text(encoding="utf-8"))
    held_out = folder / "held_out.jpg"  # 校正に使わなかった別の姿勢。
    run_command(
        "undistort", calibration_file, held_out, "--out", folder / "corrected.png"
    )
    corrected = read_image(folder / "corrected.png")
    metadata = json.loads((folder / "corrected.png.json").read_text(encoding="utf-8"))
    new_matrix = np.array(metadata["K"])
    estimated_camera, estimated_distortion = np.array(data["K"]), np.array(data["D"])
    objects = np.zeros((1, PATTERN[0] * PATTERN[1], 3), np.float64)
    objects[0, :, :2] = np.mgrid[: PATTERN[0], : PATTERN[1]].T.reshape(-1, 2) * SQUARE
    rotation_vector, translation = poses[-1]
    observed, _ = cv2.fisheye.projectPoints(
        objects, rotation_vector, translation, CAMERA, DISTORTION
    )
    predicted, _ = cv2.fisheye.projectPoints(
        objects,
        rotation_vector,
        translation,
        estimated_camera,
        estimated_distortion,
    )
    held_out_rms = float(np.sqrt(np.mean(np.sum((predicted - observed) ** 2, axis=2))))
    rectified = cv2.fisheye.undistortPoints(
        observed,
        estimated_camera,
        estimated_distortion,
        P=new_matrix,
    )
    before, after = line_rms(observed), line_rms(rectified)
    focal_error = float(
        np.max(np.abs(np.diag(estimated_camera)[:2] / np.diag(CAMERA)[:2] - 1))
    )
    assert data["image_count"] >= 20, "交点検出数が少なすぎます。"
    assert data["rms_px"] < 0.5, "再投影誤差が大きすぎます。"
    assert held_out_rms < 1.0, "未使用の姿勢で既知の投影を再現できません。"
    assert focal_error < 0.01, "焦点距離の推定誤差が1%を超えています。"
    assert after < 0.2 and after < before / 10, "直線への補正が不十分です。"

    # 実際の保存画像から再検出し、remapの結果でも直線に近づいたか確認する。
    _, corrected_corners = detect_corners(corrected, PATTERN)
    assert corrected_corners is not None
    image_line_rms = line_rms(corrected_corners)
    assert image_line_rms < 0.5

    wide_before = read_image(folder / "wide_grid.png")
    run_command(
        "undistort",
        calibration_file,
        folder / "wide_grid.png",
        "--out",
        folder / "wide_grid_corrected.png",
    )
    wide_after = read_image(folder / "wide_grid_corrected.png")
    small_before = cv2.resize(cv2.cvtColor(wide_before, cv2.COLOR_GRAY2BGR), (640, 480))
    small_after = cv2.resize(cv2.cvtColor(wide_after, cv2.COLOR_GRAY2BGR), (640, 480))
    comparison = np.hstack((small_before, small_after))
    cv2.putText(
        comparison, "Before", (20, 36), cv2.FONT_HERSHEY_SIMPLEX, 1, (30, 30, 255), 2
    )
    cv2.putText(
        comparison, "After", (660, 36), cv2.FONT_HERSHEY_SIMPLEX, 1, (30, 30, 255), 2
    )
    write_image(folder / "comparison.png", comparison)
    report = {
        "opencv": cv2.__version__,
        "numpy": np.__version__,
        "seed": 42,
        "generated_calibration_images": 24,
        "detected_images": data["image_count"],
        "calibration_rms_px": data["rms_px"],
        "held_out_projection_rms_px": held_out_rms,
        "focal_relative_error": focal_error,
        "line_rms_before_px": before,
        "line_rms_after_px": after,
        "corrected_image_line_rms_px": image_line_rms,
        "input_checks": verify_inputs(folder),
        "true_K": CAMERA.tolist(),
        "true_D": DISTORTION.tolist(),
        "note": "同じ魚眼モデルでの動作検証です。実機への適合性は未検証です。",
    }
    (folder / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=Path(__file__).parent / "demo",
        help="検証画像と結果の保存先（新しいフォルダ）",
    )
    options = parser.parse_args()
    verify(options.out)
