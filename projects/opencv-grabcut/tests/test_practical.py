"""独立実行、元の解像度、上下辺を含めない計測を確認する."""

import contextlib
import csv
import io
import json
import math
import runpy
import tempfile
import unittest
from pathlib import Path
from typing import override
from unittest.mock import patch

import cv2 as cv
import numpy as np


class PracticalTests(unittest.TestCase):
    """スクリプト1本だけを別フォルダへ置き、既知の形状で検証する."""

    @override
    def setUp(self) -> None:
        """試験結果フォルダ内に検証用の一時領域を作る."""
        self.project = Path(__file__).resolve().parents[1]
        result_directory = self.project / "experiments" / "results"
        result_directory.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=result_directory)
        self.directory = Path(temporary.name).resolve()
        if not self.directory.is_relative_to(result_directory.resolve()):
            msg = "検証用の一時領域が試験結果フォルダ外にあります"
            raise ValueError(msg)
        self.addCleanup(temporary.cleanup)

    def run_script(self, filename: str, raw_mask: np.ndarray) -> None:
        """入力と保存先だけを書き換えた1本を、既知の抽出結果で実行する."""
        script_directory = self.directory / Path(filename).stem
        script_directory.mkdir(exist_ok=True)
        image = np.full((*raw_mask.shape, 3), 100, np.uint8)
        input_path = self.directory / "input.png"
        self.assertTrue(cv.imwrite(str(input_path), image))
        source = (self.project / "practical" / filename).read_text(encoding="utf-8")
        source = source.replace(
            'INPUT_PATH = "input.png"', f"INPUT_PATH = {str(input_path)!r}"
        )
        source = source.replace(
            'OUTPUT_DIRECTORY = "results"',
            f"OUTPUT_DIRECTORY = {str(self.directory)!r}",
        )
        (script_directory / filename).write_text(source, encoding="utf-8")

        def fixed_grabcut(
            source: np.ndarray, labels: np.ndarray, *unused: object
        ) -> None:
            """元サイズの画像が渡されていることを確認し、既知の結果を返す."""
            self.assertEqual(source.shape, image.shape)
            labels[:] = cv.GC_BGD
            labels[raw_mask > 0] = cv.GC_PR_FGD

        with (
            patch.object(cv, "grabCut", side_effect=fixed_grabcut),
            patch.object(cv, "resize", side_effect=AssertionError("Unexpected resize")),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            runpy.run_path(str(script_directory / filename), run_name="__main__")

    def read_lengths(self) -> dict[str, float]:
        """side_lengths.pyが保存した左・右・合計のCSVを読む."""
        with (self.directory / "result_05.csv").open(
            encoding="utf-8", newline=""
        ) as output:
            return {
                row["edge"]: float(row["length_px"]) for row in csv.DictReader(output)
            }

    def test_rectangle_excludes_top_and_bottom(self) -> None:
        """幅が変わっても左右の高さだけを計測する."""
        for right in (40, 80):
            with self.subTest(right=right):
                mask = np.zeros((100, 120), np.uint8)
                mask[10:91, 20:right] = 255
                self.run_script("side_lengths.py", mask)
                lengths = self.read_lengths()
                self.assertEqual(lengths["left"], 80.0)
                self.assertEqual(lengths["right"], 80.0)
                self.assertEqual(lengths["total"], 160.0)

    def test_diagonal_edges_include_horizontal_distance(self) -> None:
        """斜めの側辺は行数だけでなく斜めの距離を計測する."""
        mask = np.zeros((100, 220), np.uint8)
        for row in range(10, 91):
            left = 10 + 2 * (row - 10)
            mask[row, left : left + 20] = 255
        self.run_script("side_lengths.py", mask)
        expected = round(80 * math.sqrt(5), 2)
        lengths = self.read_lengths()
        self.assertEqual(lengths["left"], expected)
        self.assertEqual(lengths["right"], expected)
        self.assertEqual(lengths["total"], round(160 * math.sqrt(5), 2))

    def test_fullsize_outputs_share_mask_and_conditions(self) -> None:
        """3本が細い突起を残し、同一条件と一致するCSVを保存する."""
        expected_mask = np.zeros((73, 113), np.uint8)
        expected_mask[12:64, 40:76] = 255
        expected_mask[38, 30:40] = 255
        raw_mask = expected_mask.copy()
        raw_mask[3:6, 3:6] = 255
        filenames = (
            "outline.py",
            "side_edges.py",
            "side_lengths.py",
        )
        conditions: list[dict[str, object]] = []
        for number, filename in zip(range(3, 6), filenames, strict=True):
            self.run_script(filename, raw_mask)
            prefix = f"result_{number:02}"
            mask = cv.imread(
                str(self.directory / f"{prefix}_mask.png"), cv.IMREAD_GRAYSCALE
            )
            if mask is None:
                self.fail("保存したマスクを読み込めません")
            self.assertTrue(np.array_equal(mask, expected_mask))
            result = cv.imread(str(self.directory / f"{prefix}.png"))
            if result is None:
                self.fail("保存した結果画像を読み込めません")
            self.assertEqual(result.shape, (73, 113, 3))
            saved_raw = cv.imread(
                str(self.directory / f"{prefix}_raw_mask.png"), cv.IMREAD_GRAYSCALE
            )
            if saved_raw is None:
                self.fail("保存した抽出直後のマスクを読み込めません")
            self.assertTrue(np.array_equal(saved_raw, raw_mask))
            path = self.directory / f"{prefix}_conditions.json"
            conditions.append(json.loads(path.read_text(encoding="utf-8")))
        self.assertEqual(conditions[0], conditions[1])
        self.assertEqual(conditions[1], conditions[2])
        self.assertEqual(conditions[0]["processing_scale"], 1.0)
        lengths = self.read_lengths()
        left = 49 + 2 * math.sqrt(101)
        right = 51.0
        self.assertEqual(lengths["left"], round(left, 2))
        self.assertEqual(lengths["right"], right)
        self.assertEqual(lengths["total"], round(left + right, 2))

    def test_unreadable_input_reports_path(self) -> None:
        """入力を読めない場合はファイルの場所を示す."""
        input_path = self.directory / "input.png"
        with (
            patch.object(cv, "imread", return_value=None),
            self.assertRaises(FileNotFoundError) as error,
        ):
            self.run_script("side_lengths.py", np.zeros((30, 40), np.uint8))
        self.assertIn(str(input_path), str(error.exception))

    def test_empty_mask_rejects_measurement(self) -> None:
        """試料がない場合にゼロ長の結果を保存しない."""
        with self.assertRaises(ValueError):
            self.run_script("side_lengths.py", np.zeros((30, 40), np.uint8))
        self.assertFalse((self.directory / "result_05.csv").exists())


if __name__ == "__main__":
    unittest.main()
