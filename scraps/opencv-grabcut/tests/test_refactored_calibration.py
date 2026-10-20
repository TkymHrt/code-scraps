"""失敗した校正写真の除外、再計算、係数と写真名の対応を確認する。"""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2 as cv
import numpy as np
from fisheye_scene import calibration_photos
from test_refactored_workflow import load_refactored


class RefactoredCalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.photos = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.photos.cleanup)
        cls.paths = calibration_photos(Path(cls.photos.name))

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.camera = load_refactored("00_2_calibrate_camera.py")

    def test_skips_unreadable_undetected_and_different_size_photos(self):
        blank = self.directory / "板なし.png"
        self.camera["write_png"](blank, np.full((120, 160, 3), 255, np.uint8))
        unreadable = self.directory / "読めない.png"
        unreadable.write_bytes(b"not an image")
        different_size = self.directory / "別解像度.png"
        photo = self.camera["read_image"](self.paths[0])
        self.camera["write_png"](different_size, cv.resize(photo, (1920, 1440)))
        paths = [blank, self.paths[0], unreadable, different_size, *self.paths[1:]]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            expected = self.camera["calibrate"](self.paths, self.directory / "expected")
            actual = self.camera["calibrate"](paths, self.directory / "actual")
        self.assertEqual(actual[0], expected[0])
        for before, after in zip(expected[1:4], actual[1:4]):
            np.testing.assert_array_equal(before, after)
        self.assertEqual(actual[4][:4], [None, expected[4][0], None, None])
        self.assertEqual(actual[4][4:], expected[4][1:])
        for path in (blank, different_size, *self.paths):
            self.assertTrue(
                (self.directory / "actual" / f"{path.name}_detected.png").is_file()
            )
        self.assertFalse(
            (self.directory / "actual" / f"{unreadable.name}_detected.png").exists()
        )
        self.assertIn(
            f"スキップ 4: {different_size.name} / 解像度が違います", output.getvalue()
        )
        self.assertIn("校正に使用: 12 / 15枚（スキップ: 3枚）", output.getvalue())

        # スキップ位置を詰めても、誤差を別の写真名に結び付けない。
        output = io.StringIO()
        with (
            contextlib.redirect_stdout(output),
            patch.dict(
                self.camera["main"].__globals__,
                {
                    "find_images": Mock(return_value=paths),
                    "calibrate": Mock(return_value=actual),
                },
            ),
        ):
            self.camera["main"]()
        for path, error in zip(self.paths, expected[4]):
            self.assertIn(f"  {path.name}: {error:.4f}px", output.getvalue())
        for path in (blank, unreadable, different_size):
            self.assertNotIn(f"  {path.name}:", output.getvalue())
        self.assertIn(self.camera["parameter_text"](*actual[:3]), output.getvalue())

    def test_retries_after_multiple_condition_errors_with_original_photo_indices(self):
        blank = self.directory / "板なし.png"
        self.camera["write_png"](blank, np.full((720, 960, 3), 255, np.uint8))
        paths = [blank, *self.paths]
        remaining_paths = self.paths[:3] + self.paths[5:]
        original_calibrate = cv.fisheye.calibrate
        attempts = []

        def calibrate_with_failures(
            objects, images, size, matrix, distortion, **options
        ):
            attempts.append(len(objects))
            np.testing.assert_array_equal(matrix, np.zeros((3, 3)))
            np.testing.assert_array_equal(distortion, np.zeros((4, 1)))
            if len(attempts) <= 2:
                matrix[:] = 123
                distortion[:] = 123
                raise cv.error("Ill-conditioned matrix for input array 3")
            return original_calibrate(
                objects, images, size, matrix, distortion, **options
            )

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            expected = self.camera["calibrate"](
                remaining_paths, self.directory / "expected"
            )
            with patch.object(
                cv.fisheye, "calibrate", side_effect=calibrate_with_failures
            ):
                actual = self.camera["calibrate"](paths, self.directory / "actual")
        self.assertEqual(attempts, [12, 11, 10])
        self.assertEqual(actual[0], expected[0])
        for before, after in zip(expected[1:4], actual[1:4]):
            np.testing.assert_array_equal(before, after)
        errors = []
        for error in actual[4]:
            if error is not None:
                errors.append(error)
        self.assertEqual(errors, expected[4])
        for index in (0, 4, 5):
            self.assertIsNone(actual[4][index])
        for index in (4, 5):
            self.assertIn(
                f"スキップ {index + 1}: {paths[index].name}", output.getvalue()
            )
            self.assertIn(f"{paths[index].name}_detected.png", output.getvalue())
        self.assertIn("校正に使用: 10 / 13枚（スキップ: 3枚）", output.getvalue())

    def test_no_usable_photos_stops_before_calibration(self):
        blank = self.directory / "板なし.png"
        self.camera["write_png"](blank, np.full((720, 960, 3), 255, np.uint8))
        unreadable = self.directory / "空.png"
        unreadable.write_bytes(b"")
        for paths in ([], [unreadable], [blank, unreadable]):
            with (
                self.subTest(paths=paths),
                contextlib.redirect_stdout(io.StringIO()),
                patch.object(cv.fisheye, "calibrate") as calibration,
                self.assertRaisesRegex(ValueError, "校正に使える写真がありません"),
            ):
                self.camera["calibrate"](paths, self.directory / "actual")
            calibration.assert_not_called()

    def test_unknown_errors_invalid_parameters_and_write_errors_still_stop(self):
        for message in (
            "cannot calibrate",
            "Ill-conditioned matrix for input array 100",
        ):
            with (
                self.subTest(message=message),
                contextlib.redirect_stdout(io.StringIO()),
                patch.object(
                    cv.fisheye, "calibrate", side_effect=cv.error(message)
                ) as calibration,
                self.assertRaisesRegex(ValueError, "カメラ校正に失敗しました"),
            ):
                self.camera["calibrate"](self.paths[:1], self.directory / "actual")
            calibration.assert_called_once()
        invalid_results = (
            (float("nan"), np.eye(3), np.zeros((4, 1)), [], []),
            (0.1, np.zeros((3, 3)), np.zeros((4, 1)), [], []),
            (0.1, np.eye(3), np.full((4, 1), np.nan), [], []),
        )
        for result in invalid_results:
            with (
                contextlib.redirect_stdout(io.StringIO()),
                patch.object(
                    cv.fisheye, "calibrate", return_value=result
                ) as calibration,
                self.assertRaisesRegex(ValueError, "校正係数が不正です"),
            ):
                self.camera["calibrate"](self.paths[:1], self.directory / "actual")
            calibration.assert_called_once()
        with (
            patch.dict(
                self.camera["calibrate"].__globals__,
                {"write_png": Mock(side_effect=OSError("保存失敗"))},
            ),
            self.assertRaisesRegex(OSError, "保存失敗"),
        ):
            self.camera["calibrate"](self.paths[:1], self.directory / "actual")


if __name__ == "__main__":
    unittest.main()
