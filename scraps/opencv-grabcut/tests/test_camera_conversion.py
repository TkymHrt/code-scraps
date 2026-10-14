"""既知のカメラで描いた板と150mmの試料で、校正・補正・換算を確認する."""

import ast
import contextlib
import csv
import io
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2 as cv
import numpy as np

PROJECT = Path(__file__).resolve().parents[1]
IMAGE_SIZE = (960, 720)
MATRIX = np.array([[1000.0, 0, 480], [0, 1010, 360], [0, 0, 1]])
DISTORTION = np.array([-0.18, 0.055, 0.001, -0.002, 0.0])


def rendered_scene(rotation, translation, partial=False):
    dictionary = cv.aruco.getPredefinedDictionary(cv.aruco.DICT_4X4_50)
    board = cv.aruco.CharucoBoard((7, 5), 30.0, 18.0, dictionary)
    # 平面の原点から右に離して、板に使わない150mmの直線区間を描く。
    texture = np.full((1200, 1760, 3), 180, np.uint8)
    texture[80:840, 80:1080] = 255
    board_image = board.generateImage((840, 600))
    texture[160:760, 160:1000] = cv.cvtColor(board_image, cv.COLOR_GRAY2BGR)
    if partial:
        texture[160:760, 160:400] = 255
    texture[220:821, 1160:1321] = (50, 110, 180)
    width, height = IMAGE_SIZE
    ys, xs = np.indices((height, width), dtype=np.float64)
    camera_pixels = np.column_stack((xs.ravel(), ys.ravel())).reshape(-1, 1, 2)
    normalized = cv.undistortPoints(camera_pixels, MATRIX, DISTORTION).reshape(-1, 2)
    rays_camera = np.column_stack((normalized, np.ones(len(normalized))))
    rotation_matrix, _ = cv.Rodrigues(np.array(rotation, np.float64))
    camera_origin_world = -rotation_matrix.T @ np.array(translation, np.float64)
    rays_world = rays_camera @ rotation_matrix
    distances = -camera_origin_world[2] / rays_world[:, 2]
    plane_points = camera_origin_world + rays_world * distances[:, None]
    map_x = (plane_points[:, 0] * 4 + 160).reshape(height, width).astype(np.float32)
    map_y = (plane_points[:, 1] * 4 + 160).reshape(height, width).astype(np.float32)
    return cv.remap(
        texture,
        map_x,
        map_y,
        cv.INTER_LINEAR,
        borderMode=cv.BORDER_CONSTANT,
        borderValue=(180, 180, 180),
    )


def calibration_photos(directory):
    poses = [
        ((0.10, -0.25, -0.08), (-100, -60, 560)),
        ((-0.25, 0.18, 0.10), (-130, -75, 600)),
        ((0.30, 0.12, -0.14), (-60, -30, 530)),
        ((-0.15, -0.32, 0.15), (-190, -90, 620)),
        ((0.32, -0.10, 0.05), (-130, -140, 580)),
        ((-0.28, 0.26, -0.10), (-75, -110, 560)),
        ((0.12, 0.35, 0.18), (-160, -30, 620)),
        ((0.25, -0.30, -0.18), (-70, -130, 590)),
        ((-0.34, -0.12, 0.12), (-170, -130, 580)),
        ((0.18, 0.20, -0.20), (-100, -65, 490)),
        ((-0.22, -0.25, 0.20), (-120, -70, 510)),
        ((0.25, 0.28, 0.08), (-100, -60, 650)),
    ]
    paths = []
    for index, (rotation, translation) in enumerate(poses):
        image = rendered_scene(rotation, translation)
        path = directory / f"校正 {index + 1:02d}.png"
        _, encoded = cv.imencode(".png", image)
        path.write_bytes(encoded.tobytes())
        paths.append(path)
    return paths


def configure(gui, matrix=MATRIX, distortion=DISTORTION):
    # 独立スクリプトで、実運用のコピペと同じ3設定だけを置き換える。
    settings = gui["rectify_image"].__globals__
    settings["CALIBRATION_SIZE"] = IMAGE_SIZE
    settings["CAMERA_MATRIX"] = matrix.tolist()
    settings["DIST_COEFFS"] = distortion.ravel().tolist()


class CameraConversionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (PROJECT / "tests/results").mkdir(parents=True, exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(dir=PROJECT / "tests/results")
        cls.directory = Path(cls.temporary.name)
        cls.camera = runpy.run_path(str(PROJECT / "submissions/camera_calibration.py"))
        cls.paths = calibration_photos(cls.directory)
        cls.calibration = cls.camera["calibrate"](cls.paths)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.gui = runpy.run_path(str(PROJECT / "submissions/rectify_image_gui.py"))

    def test_board_generation_and_camera_calibration_are_separate(self):
        with tempfile.TemporaryDirectory(dir=self.directory) as temporary:
            directory = Path(temporary)
            generator = directory / "generate_charuco_board.py"
            generator.write_bytes(
                (PROJECT / "submissions/generate_charuco_board.py").read_bytes()
            )
            with contextlib.redirect_stdout(io.StringIO()):
                settings = runpy.run_path(str(generator))
            board_path = directory / "results/charuco_board.png"
            image = cv.imdecode(
                np.frombuffer(board_path.read_bytes(), np.uint8), cv.IMREAD_GRAYSCALE
            )
            assert image is not None
            self.assertEqual(image.shape, (1700, 2300))
            self.assertTrue(np.all(image[:100] == 255))
            # 校正側と換算側の仕様で読め、各角が実寸に対応した位置に並ぶ。
            dictionary = cv.aruco.getPredefinedDictionary(cv.aruco.DICT_4X4_50)
            for script in (self.camera, self.gui):
                board = cv.aruco.CharucoBoard(
                    script["BOARD_SQUARES"],
                    script["SQUARE_MM"],
                    script["MARKER_MM"],
                    dictionary,
                )
                corners, ids, _, _ = cv.aruco.CharucoDetector(board).detectBoard(image)
                assert ids is not None and corners is not None
                self.assertEqual(len(ids), 24)
                world_points = np.array(board.getChessboardCorners())
                detected_world = world_points[ids.astype(np.int32).ravel(), :2]
                expected = (detected_world + settings["MARGIN_MM"]) * settings[
                    "PIXELS_PER_MM"
                ]
                np.testing.assert_allclose(corners.reshape(-1, 2), expected, atol=1)
            # 係数算出の実行は、板を新規生成も上書きもしない。
            calibration = directory / "camera_calibration.py"
            calibration.write_bytes(
                (PROJECT / "submissions/camera_calibration.py").read_bytes()
            )
            board_path.write_bytes(b"keep existing board")
            with contextlib.redirect_stdout(io.StringIO()):
                runpy.run_path(str(calibration), run_name="__main__")
            self.assertEqual(board_path.read_bytes(), b"keep existing board")
            board_path.unlink()
            with contextlib.redirect_stdout(io.StringIO()):
                runpy.run_path(str(calibration), run_name="__main__")
            self.assertFalse(board_path.exists())

    def test_camera_parameters_are_recovered_and_copyable(self):
        size, matrix, distortion, rms, errors = self.calibration
        self.assertEqual(size, IMAGE_SIZE)
        self.assertLess(rms, 0.5)
        self.assertLess(max(errors), 0.6)
        np.testing.assert_allclose(matrix[:2, :2], MATRIX[:2, :2], atol=15)
        np.testing.assert_allclose(matrix[:2, 2], MATRIX[:2, 2], atol=10)
        self.assertAlmostEqual(distortion.ravel()[0], DISTORTION[0], delta=0.06)
        block = self.camera["parameter_text"](size, matrix, distortion)
        assignments = ast.parse(block).body
        self.assertEqual(len(assignments), 3)
        for statement in assignments:
            self.assertIsInstance(statement, ast.Assign)
            value = ast.literal_eval(statement.value)
            self.gui["rectify_image"].__globals__[statement.targets[0].id] = value
        image = rendered_scene((0.12, -0.22, 0.03), (-170, -65, 600))
        correction = self.gui["rectify_image"](image)
        self.assertLess(correction["error_px"], 1)

    def test_length_is_consistent_across_pose_distance_and_partial_board(self):
        configure(self.gui, self.calibration[1], self.calibration[2])
        measured = []
        for rotation, translation, partial in [
            ((0.12, -0.22, 0.03), (-170, -65, 600), False),
            ((-0.20, 0.18, -0.10), (-150, -100, 650), False),
            ((0.20, 0.15, 0.12), (-160, -90, 560), True),
        ]:
            correction = self.gui["rectify_image"](
                rendered_scene(rotation, translation, partial)
            )
            image = correction["image"]
            # 校正板から離れた試料の色だけを拾い、補正を独立に検証する。
            mask = cv.inRange(image, (20, 75, 145), (90, 145, 220))
            ys, xs = np.nonzero(mask)
            length_mm = (ys.max() - ys.min()) * correction["mm_per_px"]
            width_mm = (xs.max() - xs.min()) * correction["mm_per_px"]
            measured.append(length_mm)
            self.assertAlmostEqual(length_mm, 150, delta=1.0)
            self.assertAlmostEqual(width_mm, 40, delta=1.0)
        self.assertLess(max(measured) - min(measured), 1.0)

    def test_unconfigured_wrong_size_and_no_board_are_rejected(self):
        image = rendered_scene((0.12, -0.22, 0.03), (-170, -65, 600))
        with self.assertRaisesRegex(ValueError, "貼り付け"):
            self.gui["rectify_image"](image)
        configure(self.gui)
        with self.assertRaisesRegex(ValueError, "解像度"):
            self.gui["rectify_image"](image[:500])
        with self.assertRaisesRegex(ValueError, "6点"):
            self.gui["rectify_image"](np.zeros_like(image))
        ai_path = PROJECT / "submissions/input/赤茶色の床と剥離した金属帯.png"
        if ai_path.exists():
            ai = cv.imdecode(
                np.frombuffer(ai_path.read_bytes(), np.uint8), cv.IMREAD_COLOR
            )
            assert ai is not None
            self.gui["rectify_image"].__globals__["CALIBRATION_SIZE"] = ai.shape[1::-1]
            with self.assertRaisesRegex(ValueError, "6点"):
                self.gui["rectify_image"](ai)

    def test_camera_input_errors_stop_without_parameters(self):
        with self.assertRaisesRegex(ValueError, "10枚"):
            self.camera["calibrate"](self.paths[:9])
        path = self.directory / "no_board.png"
        _, encoded = cv.imencode(".png", np.zeros((720, 960, 3), np.uint8))
        path.write_bytes(encoded.tobytes())
        with self.assertRaisesRegex(ValueError, "6点"):
            self.camera["calibrate"](self.paths[:9] + [path])
        _, encoded = cv.imencode(".png", np.zeros((100, 100, 3), np.uint8))
        path.write_bytes(encoded.tobytes())
        with self.assertRaisesRegex(ValueError, "解像度"):
            self.camera["calibrate"](self.paths[:9] + [path])

    def test_invalid_homography_is_stopped_before_allocating_image(self):
        configure(self.gui)
        image = rendered_scene((0.12, -0.22, 0.03), (-170, -65, 600))
        with patch.object(cv, "findHomography", return_value=(None, None)):
            with self.assertRaisesRegex(ValueError, "遠近補正"):
                self.gui["rectify_image"](image)
        self.gui["rectify_image"].__globals__["MM_PER_PX"] = 0.0001
        with self.assertRaisesRegex(ValueError, "大きすぎ"):
            self.gui["rectify_image"](image)

    def test_mm_csv_is_compatible_and_input_files_are_protected(self):
        configure(self.gui)
        image = rendered_scene((0.12, -0.22, 0.03), (-170, -65, 600))
        correction = self.gui["rectify_image"](image)
        source_path = self.directory / "撮影元.png"
        source_path.write_bytes(b"original")
        image_path = self.directory / "補正.png"
        self.gui["save_image"](image_path, correction, source_path)
        csv_path = self.directory / "03.csv"
        with csv_path.open("w", encoding="utf-8-sig", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(("edge", "length_px", "start_y", "end_y"))
            for edge, length in (("left", 600), ("right", 600), ("total", 1200)):
                writer.writerow((edge, length, 100, 700))
        row = self.gui["convert_lengths"](csv_path, image_path, correction)
        self.assertEqual(
            (row["left_mm"], row["right_mm"], row["total_mm"]), (150, 150, 300)
        )
        saved_path = self.directory / "校正済み.csv"
        self.gui["save_lengths"](saved_path, row, source_path)
        comparison = runpy.run_path(
            str(PROJECT / "submissions/length_comparison_gui.py")
        )
        saved = comparison["read_calibrated_lengths"](saved_path)
        self.assertEqual(saved["left_mm"], 150)
        for protected in (source_path, image_path, csv_path):
            before = protected.read_bytes()
            with self.assertRaises(ValueError):
                self.gui["save_lengths"](protected, row, source_path)
            self.assertEqual(protected.read_bytes(), before)
        with self.assertRaises(ValueError):
            self.gui["save_image"](source_path, correction, source_path)
        csv_path.write_text(
            csv_path.read_text(encoding="utf-8-sig").replace("1200", "1250"),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "合計"):
            self.gui["convert_lengths"](csv_path, image_path, correction)
        csv_path.write_text(
            "edge,length_px,start_y,end_y\nleft,,100,700\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "空欄"):
            self.gui["convert_lengths"](csv_path, image_path, correction)


if __name__ == "__main__":
    (PROJECT / "tests/results").mkdir(parents=True, exist_ok=True)
    unittest.main()
