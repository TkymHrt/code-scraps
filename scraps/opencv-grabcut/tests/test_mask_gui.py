"""01のGUI版の表示と初期指定を、提出版01・02と照合する."""

import ast
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2 as cv
import numpy as np


class MaskGuiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = Path(__file__).resolve().parents[1]
        self.submissions = self.project / "submissions"
        self.gui = runpy.run_path(str(self.submissions / "01_initial_regions_gui.py"))
        self.regions = {
            cv.GC_PR_FGD: [self.gui["CANDIDATE_RECT"]],
            cv.GC_BGD: list(self.gui["BACKGROUND_RECTS"]),
            cv.GC_FGD: list(self.gui["FOREGROUND_RECTS"]),
        }

    def temporary_directory(self) -> tempfile.TemporaryDirectory[str]:
        results = self.project / "tests" / "results"
        results.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=results)
        if not Path(temporary.name).resolve().is_relative_to(results.resolve()):
            raise ValueError("検証用の一時領域が試験結果フォルダ外にあります")
        return temporary

    def copy_submission(self, filename: str, directory: Path, settings: str) -> Path:
        """GUIでコピーした値を、提出版の同名の設定へ貼り付ける."""
        values = {}
        exec(settings, values)
        source = (self.submissions / filename).read_text(encoding="utf-8")
        lines = source.splitlines(keepends=True)
        for node in ast.parse(source).body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                if name in values:
                    lines[node.lineno - 1] = f"{name} = {values[name]!r}\n"
        path = directory / filename
        path.write_text("".join(lines), encoding="utf-8")
        return path

    def test_overlay_and_copied_settings_match_submissions_at_original_resolution(
        self,
    ) -> None:
        """細かい小数・重複・画像端までの指定が、01の表示と02の入力に一致する."""
        image = np.full((239, 317, 3), 100, np.uint8)
        self.regions[cv.GC_PR_FGD] = [
            (0.1234567890123456, 0.0, 0.7135678912345678, 1.0)
        ]
        self.regions[cv.GC_FGD] = [(0.3012345678912345, 0.4, 0.5678912345678912, 0.6)]
        expected_labels = self.gui["make_labels"](image, self.regions)
        self.assertEqual(expected_labels.shape, (239, 317))
        # 確実な背景の中にも、最後に重ねる確実な前景が残る。
        self.assertEqual(expected_labels[120, 99], cv.GC_FGD)
        with self.temporary_directory() as temporary:
            directory = Path(temporary)
            input_path = directory / "input.png"
            self.assertTrue(cv.imwrite(str(input_path), image))
            settings = self.gui["settings_text"](input_path, self.regions)
            script = self.copy_submission("01_initial_regions.py", directory, settings)
            with patch.object(
                cv, "grabCut", side_effect=AssertionError("Unexpected GrabCut")
            ):
                runpy.run_path(str(script))
            overlay = cv.imread(str(directory / "results/01_initial_regions.png"))
            np.testing.assert_array_equal(
                self.gui["initial_overlay"](image, self.regions), overlay
            )

            def inspect_labels(
                image: np.ndarray, labels: np.ndarray, *unused: object
            ) -> None:
                np.testing.assert_array_equal(labels, expected_labels)
                labels[:] = cv.GC_BGD

            script = self.copy_submission("02_grabcut_mask.py", directory, settings)
            with patch.object(cv, "grabCut", side_effect=inspect_labels):
                runpy.run_path(str(script))

    def test_invalid_rectangles_are_rejected(self) -> None:
        image = np.full((100, 100, 3), 100, np.uint8)
        for regions, message in (
            ({cv.GC_PR_FGD: [(-0.1, 0, 0.8, 1)], cv.GC_BGD: [], cv.GC_FGD: []}, "0〜1"),
            (
                {cv.GC_PR_FGD: [(0.8, 0, 0.2, 1)], cv.GC_BGD: [], cv.GC_FGD: []},
                "左 < 右",
            ),
            (
                {cv.GC_PR_FGD: [(0, 0, 0.001, 1)], cv.GC_BGD: [], cv.GC_FGD: []},
                "1画素未満",
            ),
        ):
            with (
                self.subTest(message=message),
                patch.object(
                    cv, "grabCut", side_effect=AssertionError("Unexpected GrabCut")
                ),
                self.assertRaisesRegex(ValueError, message),
            ):
                self.gui["make_labels"](image, regions)

    def test_settings_require_one_candidate_and_allow_no_definite_foreground(
        self,
    ) -> None:
        self.regions[cv.GC_FGD] = []
        text = self.gui["settings_text"](Path("C:/sample.png"), self.regions)
        self.assertIn("FOREGROUND_RECTS = ()", text)
        copied = {}
        exec(text, copied)
        self.assertEqual(
            set(copied) - {"__builtins__"},
            {"INPUT_PATH", "CANDIDATE_RECT", "BACKGROUND_RECTS", "FOREGROUND_RECTS"},
        )
        self.regions[cv.GC_PR_FGD] = []
        with self.assertRaisesRegex(ValueError, "前景候補"):
            self.gui["settings_text"](Path("C:/sample.png"), self.regions)


if __name__ == "__main__":
    unittest.main()
