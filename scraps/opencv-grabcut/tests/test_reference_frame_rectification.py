"""基準画像から固定した補正を、ボードなしフレームと既存の計測へ渡す。"""

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2 as cv
import numpy as np
from fisheye_scene import (
    DISTORTION,
    IMAGE_SIZE,
    MATRIX,
    configure,
    rendered_scene,
    specimen_size,
)
from test_refactored_workflow import copy_refactored, load_refactored

SCRIPT = "01_rectify_frames_from_reference.py"
ROTATION = (0.12, -0.22, 0.03)
TRANSLATION = (-170, -65, 400)


def specimen_frame(offset=(0, 0, 0), rotation=ROTATION):
    # カメラを固定したまま、同じ平面の試料だけを移動した写真を作る。
    rotation_matrix, _ = cv.Rodrigues(np.array(rotation, np.float64))
    translation = np.array(TRANSLATION) + rotation_matrix @ np.array(offset)
    scene = rendered_scene(rotation, translation)
    mask = cv.inRange(scene, (20, 75, 145), (90, 145, 220))
    frame = np.full_like(scene, 180)
    frame[mask != 0] = scene[mask != 0]
    return frame


class ReferenceFrameRectificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference = rendered_scene(ROTATION, TRANSLATION)
        cls.frame = specimen_frame()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.script = load_refactored(SCRIPT)
        self.settings = self.script["prepare_rectification"].__globals__
        self.settings["CALIBRATION_SIZE"] = IMAGE_SIZE
        self.settings["CAMERA_MATRIX"] = MATRIX.tolist()
        self.settings["DIST_COEFFS"] = DISTORTION.tolist()
        self.files = load_refactored("file_io.py")

    def set_batch_paths(self):
        reference_path = self.directory / "基準画像/reference.png"
        input_directory = self.directory / "入力 フレーム"
        output_directory = self.directory / "補正 フレーム"
        self.files["write_png"](reference_path, self.reference)
        self.files["write_png"](input_directory / "frame_001.png", self.frame)
        self.settings["REFERENCE_IMAGE_PATH"] = reference_path
        self.settings["FRAMES_DIRECTORY"] = input_directory
        self.settings["RECTIFIED_FRAMES_DIRECTORY"] = output_directory
        return reference_path, input_directory, output_directory

    def run_batch(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.script["main"]()
        return output.getvalue()

    def test_reference_matches_existing_rectification(self):
        previous = load_refactored("01_rectify_images.py")
        configure(previous)
        for partial in (False, True):
            with self.subTest(partial=partial):
                image = rendered_scene(ROTATION, TRANSLATION, partial)
                expected = previous["rectify_image"](image)
                correction = self.script["prepare_rectification"](image)
                actual = self.script["rectify_frame"](image, correction)
                np.testing.assert_array_equal(actual, expected["image"])
                self.assertEqual(correction["corner_count"], expected["corner_count"])
                self.assertEqual(correction["error_px"], expected["error_px"])

    def test_board_free_frames_keep_known_size_and_fixed_output(self):
        previous = load_refactored("01_rectify_images.py")
        configure(previous)
        with self.assertRaisesRegex(ValueError, "ChArUco"):
            previous["rectify_image"](self.frame)
        correction = self.script["prepare_rectification"](self.reference)
        sizes = []
        for offset in ((0, 0, 0), (-15, 20, 0), (10, -15, 0)):
            frame = specimen_frame(offset)
            with patch.object(cv.aruco, "CharucoDetector", side_effect=AssertionError):
                corrected = self.script["rectify_frame"](frame, correction)
            sizes.append(corrected.shape)
            length_mm, width_mm = specimen_size(corrected)
            self.assertAlmostEqual(length_mm, 150.0, delta=1.0)
            self.assertAlmostEqual(width_mm, 40.0, delta=1.0)
        self.assertEqual(sizes, [sizes[0]] * 3)

    def test_central_output_reduces_pixels_without_resizing_the_specimen(self):
        full_roi = (0, 0, 1, 1)
        with patch.dict(self.settings, {"RECTIFY_ROI": full_roi}):
            full = self.script["prepare_rectification"](self.reference)
        central = self.script["prepare_rectification"](self.reference)
        full_width, full_height = full["output_size"]
        width, height = central["output_size"]
        self.assertLess(width * height, full_width * full_height * 0.6)
        self.assertEqual(central["mm_per_px"], full["mm_per_px"])
        for correction in (full, central):
            image = self.script["rectify_frame"](self.frame, correction)
            length_mm, width_mm = specimen_size(image)
            self.assertAlmostEqual(length_mm, 150, delta=1)
            self.assertAlmostEqual(width_mm, 40, delta=1)

    def test_both_rectifiers_reject_invalid_output_regions(self):
        single = load_refactored("01_rectify_images.py")
        configure(single)
        for function in (single["rectify_image"], self.script["prepare_rectification"]):
            for roi in (
                (-0.1, 0, 1, 1),
                (0.5, 0, 0.5, 1),
                (0, 0, 1, 1.1),
                (0, float("nan"), 1, 1),
            ):
                with self.subTest(function=function.__name__, roi=roi):
                    with patch.dict(function.__globals__, {"RECTIFY_ROI": roi}):
                        with self.assertRaisesRegex(ValueError, "RECTIFY_ROI"):
                            function(self.reference)

    def test_corrected_frame_can_be_measured_and_saved_as_existing_csv(self):
        reference = rendered_scene((0, 0, 0), TRANSLATION)
        correction = self.script["prepare_rectification"](reference)
        corrected = self.script["rectify_frame"](
            specimen_frame(rotation=(0, 0, 0)), correction
        )
        mask = cv.inRange(corrected, (20, 75, 145), (90, 145, 220))
        x, y, width, height = cv.boundingRect(cv.findNonZero(mask))
        # 画素寸法を保ったまま試料付近だけを使い、GrabCutの検証画素数を絞る。
        corrected = corrected[y - 8 : y + height + 8, x - 8 : x + width + 8]
        image_path = self.directory / "frame.png"
        self.files["write_png"](image_path, corrected)
        x = y = 8
        image_height, image_width = corrected.shape[:2]
        regions = {
            cv.GC_BGD: [(0, 0, 4 / image_width, 1), (1 - 4 / image_width, 0, 1, 1)],
            cv.GC_FGD: [],
            cv.GC_PR_FGD: [
                (
                    (x - 6) / image_width,
                    (y - 6) / image_height,
                    (x + width + 6) / image_width,
                    (y + height + 6) / image_height,
                )
            ],
        }
        start_y = y + 10
        end_y = y + height - 11
        measurement = load_refactored("02_measure_edge_lengths_gui.py")
        row, overlay = measurement["measure_lengths"](
            corrected, regions, start_y, end_y
        )
        expected_mm = (end_y - start_y) * 0.25
        # 側辺長には画素の段差も入る。実寸の精度は上の独立した外接矩形で確認する。
        self.assertEqual(row["mm_per_px"], correction["mm_per_px"])
        self.assertGreaterEqual(row["left_mm"], expected_mm)
        self.assertGreaterEqual(row["right_mm"], expected_mm)
        csv_path = self.directory / "frame_lengths.csv"
        initial = measurement["initial_overlay"](corrected, regions)
        measurement["write_measurement"](csv_path, image_path, row, initial, overlay)
        csv_reader = load_refactored("measurement_csv.py")
        saved = csv_reader["read_lengths"](csv_path)
        self.assertEqual(saved["mm_per_px"], 0.25)
        self.assertEqual(saved["interval_length_mm"], expected_mm)
        self.assertGreaterEqual(saved["left_per_100mm"], 100)
        self.assertTrue((self.directory / "frame_lengths.png").is_file())
        self.assertTrue((self.directory / "frame_lengths_initial.png").is_file())

    def test_invalid_calibration_and_reference_are_rejected(self):
        for name, value in (
            ("CAMERA_MATRIX", None),
            ("CAMERA_MATRIX", np.zeros((3, 3)).tolist()),
            ("DIST_COEFFS", [0.0] * 5),
            ("DIST_COEFFS", [float("nan"), 0, 0, 0]),
            ("MM_PER_PX", 0),
        ):
            with self.subTest(name=name, value=value):
                with patch.dict(self.settings, {name: value}):
                    with self.assertRaises(ValueError):
                        self.script["prepare_rectification"](self.reference)
        with self.assertRaisesRegex(ValueError, "解像度"):
            self.script["prepare_rectification"](self.reference[::2, ::2])
        with self.assertRaisesRegex(ValueError, "ChArUco"):
            self.script["prepare_rectification"](self.frame)

    def test_bad_reference_geometry_and_oversized_output_are_rejected(self):
        for homography in (None, np.zeros((3, 3)), np.eye(3)):
            with self.subTest(homography=homography):
                with patch.object(
                    cv, "findHomography", return_value=(homography, None)
                ):
                    with self.assertRaises(ValueError):
                        self.script["prepare_rectification"](self.reference)
        with patch.dict(self.settings, {"MM_PER_PX": 0.00001}):
            with self.assertRaisesRegex(ValueError, "大きすぎ"):
                self.script["prepare_rectification"](self.reference)

    def test_frame_size_must_match_reference(self):
        correction = self.script["prepare_rectification"](self.reference)
        for frame in (self.frame[::2, ::2], np.rot90(self.frame)):
            with self.assertRaisesRegex(ValueError, "同じ解像度"):
                self.script["rectify_frame"](frame, correction)

    def test_batch_saves_fixed_frames_and_corrected_reference(self):
        reference_path, inputs, outputs = self.set_batch_paths()
        self.files["write_png"](inputs / "frame_002.png", specimen_frame((10, 15, 0)))
        original_reference = reference_path.read_bytes()
        original_frame = (inputs / "frame_001.png").read_bytes()
        log = self.run_batch()
        self.assertIn("完了: 2枚", log)
        self.assertEqual(log.count("再投影誤差"), 1)
        correction = self.script["prepare_rectification"](self.reference)
        expected = self.script["rectify_frame"](self.frame, correction)
        actual = self.files["read_image"](outputs / "frame_001.png")
        np.testing.assert_array_equal(actual, expected)
        preview = self.files["read_image"](outputs / "reference/reference.png")
        expected_reference = self.script["rectify_frame"](self.reference, correction)
        np.testing.assert_array_equal(preview, expected_reference)
        self.assertEqual(reference_path.read_bytes(), original_reference)
        self.assertEqual((inputs / "frame_001.png").read_bytes(), original_frame)

    def test_batch_rejects_duplicate_names_and_same_directory(self):
        _, inputs, outputs = self.set_batch_paths()
        self.settings["RECTIFIED_FRAMES_DIRECTORY"] = inputs
        with self.assertRaisesRegex(ValueError, "別のフォルダ"):
            self.run_batch()
        self.settings["RECTIFIED_FRAMES_DIRECTORY"] = outputs
        (inputs / "frame_001.jpg").write_bytes(b"duplicate name")
        with self.assertRaisesRegex(ValueError, "出力名が重複"):
            self.run_batch()
        self.assertFalse(outputs.exists())

    def test_batch_protects_reference_and_frames_from_output_overwrite(self):
        for mode in ("reference", "reference_preview", "frame_preview"):
            with self.subTest(mode=mode):
                directory = self.directory / mode
                inputs = directory / "inputs"
                outputs = directory / "outputs"
                reference_path = outputs / "frame.png"
                if mode == "reference_preview":
                    reference_path = outputs / "reference/frame.png"
                elif mode == "frame_preview":
                    reference_path = directory / "frame.png"
                    inputs = outputs / "reference"
                frame_path = inputs / "frame.png"
                self.files["write_png"](reference_path, self.reference)
                self.files["write_png"](frame_path, self.frame)
                original_reference = reference_path.read_bytes()
                original_frame = frame_path.read_bytes()
                self.settings["REFERENCE_IMAGE_PATH"] = reference_path
                self.settings["FRAMES_DIRECTORY"] = inputs
                self.settings["RECTIFIED_FRAMES_DIRECTORY"] = outputs
                with self.assertRaisesRegex(ValueError, "入力ファイルと別"):
                    self.run_batch()
                self.assertEqual(reference_path.read_bytes(), original_reference)
                self.assertEqual(frame_path.read_bytes(), original_frame)

    def test_missing_or_unreadable_board_reference_stops_before_saving(self):
        reference_path, _, outputs = self.set_batch_paths()
        reference_path.unlink()
        with self.assertRaisesRegex(ValueError, "読み込めません"):
            self.run_batch()
        self.assertFalse(outputs.exists())
        self.files["write_png"](reference_path, self.frame)
        with self.assertRaisesRegex(ValueError, "ChArUco"):
            self.run_batch()
        self.assertFalse(outputs.exists())

    def test_bad_frame_size_reports_filename_and_stops(self):
        _, inputs, outputs = self.set_batch_paths()
        self.files["write_png"](inputs / "frame_002.png", self.frame[::2, ::2])
        with self.assertRaisesRegex(ValueError, "frame_002.png.*同じ解像度"):
            self.run_batch()
        self.assertTrue((outputs / "frame_001.png").is_file())
        self.assertFalse((outputs / "frame_002.png").exists())

    def test_copied_script_runs_from_another_working_directory(self):
        reference_path, inputs, outputs = self.set_batch_paths()
        copied_directory = self.directory / "持ち出し フォルダ"
        copied_directory.mkdir()
        script = copy_refactored(
            SCRIPT,
            copied_directory,
            REFERENCE_IMAGE_PATH=str(reference_path),
            FRAMES_DIRECTORY=str(inputs),
            RECTIFIED_FRAMES_DIRECTORY=str(outputs),
            CALIBRATION_SIZE=IMAGE_SIZE,
            CAMERA_MATRIX=MATRIX.tolist(),
            DIST_COEFFS=DISTORTION.tolist(),
        )
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=self.directory,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((outputs / "frame_001.png").is_file())
        self.assertTrue((outputs / "reference/reference.png").is_file())


if __name__ == "__main__":
    unittest.main()
