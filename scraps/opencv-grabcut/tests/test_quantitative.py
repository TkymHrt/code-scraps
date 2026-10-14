"""既知の形状で、一括計測と独立した3種類の比較を確認する."""

import contextlib
import csv
import io
import math
import runpy
import tempfile
import unittest
from pathlib import Path
from typing import override

import cv2 as cv
import numpy as np


class QuantitativeTests(unittest.TestCase):
    """スクリプトを1本ずつコピーし、CSVを介した比較を検証する."""

    @override
    def setUp(self) -> None:
        """既存結果を変えない一時領域を、試験結果フォルダ内に作る."""
        self.project = Path(__file__).resolve().parents[1]
        results = self.project / "tests" / "results"
        results.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=results)
        self.directory = Path(temporary.name).resolve()
        if not self.directory.is_relative_to(results.resolve()):
            msg = "検証用の一時領域が試験結果フォルダ外にあります"
            raise ValueError(msg)
        self.addCleanup(temporary.cleanup)

    def run_script(self, filename: str, **settings: object) -> None:
        """設定だけを変えた独立ファイルを実行する."""
        source_path = self.project / "sandbox/previous_scripts" / filename
        lines = source_path.read_text(encoding="utf-8").splitlines()
        for name, value in settings.items():
            for index, line in enumerate(lines):
                if line.startswith((f"{name} = ", f"{name}:")):
                    lines[index] = f"{name} = {value!r}"
                    break
            else:
                self.fail(f"設定がありません: {name}")
        script = self.directory / filename
        script.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            runpy.run_path(str(script), run_name="__main__")

    def write_csv(self, name: str, rows: list[dict[str, object]]) -> Path:
        """検証用CSVを保存する."""
        path = self.directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return path

    def read_csv(self, name: str) -> list[dict[str, str]]:
        """出力CSVを読み込む."""
        with (self.directory / name).open(encoding="utf-8", newline="") as source:
            return list(csv.DictReader(source))

    def write_edges(self, sample_id: str, points: list[tuple[int, int, int]]) -> str:
        """y・左端・右端の既知の点列を保存する."""
        name = f"{sample_id}/edges.csv"
        self.write_csv(
            name,
            [
                {"y_px": y, "left_x_px": left, "right_x_px": right}
                for y, left, right in points
            ],
        )
        return name

    def test_batch_grabcut_matches_known_rectangle_and_diagonal(self) -> None:
        """実際のGrabCutから、直線・45度の側辺を縮小せずに測る."""
        rows: list[dict[str, object]] = []
        for sample_id in ("rectangle", "diagonal", "scaled"):
            pixel_scale = 2 if sample_id == "scaled" else 1
            height = 30 * pixel_scale + 1
            image = np.full((height, 200 * pixel_scale, 3), 30, np.uint8)
            for y in range(height):
                left = 70 + y if sample_id == "diagonal" else 70 * pixel_scale
                image[y, left : left + 35 * pixel_scale] = 180
            cv.imwrite(str(self.directory / f"{sample_id}.png"), image)
            rows.append(
                {
                    "sample_id": sample_id,
                    "image_path": f"{sample_id}.png",
                    "mm_per_px": 0.1 / pixel_scale,
                }
            )
        self.write_csv("samples.csv", rows)
        settings = {
            "INPUT_CSV": "samples.csv",
            "OUTPUT_DIRECTORY": "batch",
            "CANDIDATE_RECT": (0.3, 0.0, 0.7, 1.0),
            "BACKGROUND_RECTS": ((0.0, 0.0, 0.25, 1.0), (0.75, 0.0, 1.0, 1.0)),
            "FOREGROUND_RECTS": ((0.51, 0.1, 0.515, 0.9),),
        }
        self.run_script("measure_batch.py", **settings)
        measurements = self.read_csv("batch/measurements.csv")
        for row, expected in zip(
            measurements, (30.0, 30 * math.sqrt(2), 60), strict=True
        ):
            self.assertAlmostEqual(float(row["left_px"]), expected, places=5)
            self.assertAlmostEqual(float(row["right_px"]), expected, places=5)
            self.assertAlmostEqual(
                float(row["left_mm"]), expected * float(row["mm_per_px"]), places=5
            )
            points = self.read_csv(f"batch/{row['edges_path']}")
            self.assertEqual(len(points), int(row["vertical_span_px"]) + 1)

        # 抽出からmmでの比較までつなぎ、倍率2倍の長方形との一致を確認する。
        self.run_script(
            "compare_lengths.py",
            INPUT_CSV="batch/measurements.csv",
            OUTPUT_CSV="lengths.csv",
            BASELINE_ID="rectangle",
            UNIT="mm",
        )
        scaled = self.read_csv("lengths.csv")[2]
        self.assertEqual(float(scaled["total_change_pct"]), 0)

        # 下端は含めない。31行の画像なら行6〜23の端点間距離17pxになる。
        self.run_script(
            "measure_batch.py", **{**settings, "MEASURE_Y_RANGE": (0.2, 0.8)}
        )
        cropped = self.read_csv("batch/measurements.csv")
        for row, expected in zip(cropped, (17, 17 * math.sqrt(2), 35), strict=True):
            self.assertAlmostEqual(float(row["left_px"]), expected, places=5)
        self.assertEqual(cropped[0]["y_start_px"], "6")
        self.assertEqual(cropped[0]["y_end_px"], "23")
        self.assertEqual(cropped[0]["vertical_span_px"], "17")

    def test_batch_duplicate_ids_do_not_overwrite(self) -> None:
        """同じIDによる結果の上書きを、画像を読む前に止める."""
        self.write_csv(
            "samples.csv",
            [
                {"sample_id": "same", "image_path": "a.png", "mm_per_px": ""},
                {"sample_id": "same", "image_path": "b.png", "mm_per_px": ""},
            ],
        )
        with self.assertRaisesRegex(ValueError, "重複"):
            self.run_script("measure_batch.py", OUTPUT_DIRECTORY="batch")
        self.assertFalse((self.directory / "batch").exists())

    def test_length_comparison_uses_explicit_baseline_and_signed_difference(
        self,
    ) -> None:
        """一覧の先頭でなく指定した基準を使い、左右差の符号を保つ."""
        self.write_csv(
            "measurements.csv",
            [
                {"sample_id": "after", "left_px": 120, "right_px": 80, "total_px": 200},
                {
                    "sample_id": "before",
                    "left_px": 100,
                    "right_px": 100,
                    "total_px": 200,
                },
            ],
        )
        self.run_script(
            "compare_lengths.py",
            INPUT_CSV="measurements.csv",
            OUTPUT_CSV="lengths.csv",
            BASELINE_ID="before",
        )
        after, before = self.read_csv("lengths.csv")
        self.assertEqual(float(after["left_change_pct"]), 20)
        self.assertEqual(float(after["right_change_pct"]), -20)
        self.assertEqual(float(after["total_change_pct"]), 0)
        self.assertEqual(float(after["signed_left_minus_right_pct"]), 20)
        self.assertEqual(float(before["left_diff_px"]), 0)

    def test_length_mm_comparison_and_missing_scale(self) -> None:
        """倍率が違っても換算後は同じ長さになり、未換算は拒否する."""
        rows: list[dict[str, object]] = [
            {
                "sample_id": "before",
                "left_mm": "10",
                "right_mm": "10",
                "total_mm": "20",
            },
            {"sample_id": "after", "left_mm": "10", "right_mm": "10", "total_mm": "20"},
        ]
        self.write_csv("measurements.csv", rows)
        settings = {
            "INPUT_CSV": "measurements.csv",
            "OUTPUT_CSV": "lengths.csv",
            "BASELINE_ID": "before",
            "UNIT": "mm",
        }
        self.run_script("compare_lengths.py", **settings)
        saved_output = (self.directory / "lengths.csv").read_bytes()
        self.assertEqual(float(self.read_csv("lengths.csv")[1]["total_change_pct"]), 0)
        rows[1]["left_mm"] = ""
        self.write_csv("measurements.csv", rows)
        with self.assertRaisesRegex(ValueError, "空欄"):
            self.run_script("compare_lengths.py", **settings)
        self.assertEqual((self.directory / "lengths.csv").read_bytes(), saved_output)

    def test_sampling_keeps_endpoint_and_step_order_does_not_matter(self) -> None:
        """間隔で割り切れない末尾も使い、斜線の長さを保つ."""
        edges_path = self.write_edges(
            "slope", [(y, 2 * y, 2 * y + 10) for y in range(12)]
        )
        self.write_csv(
            "measurements.csv", [{"sample_id": "slope", "edges_path": edges_path}]
        )
        self.run_script(
            "compare_sampling.py",
            INPUT_CSV="measurements.csv",
            OUTPUT_CSV="sampling.csv",
            ROW_STEPS=(5, 2, 1),
        )
        for row in self.read_csv("sampling.csv"):
            self.assertAlmostEqual(float(row["length_px"]), 11 * math.sqrt(5), places=5)
            self.assertEqual(float(row["length_over_chord"]), 1)
            self.assertAlmostEqual(float(row["change_from_step1_pct"]), 0)

    def test_sampling_reports_sensitivity_to_fine_zigzag(self) -> None:
        """毎行の凹凸を飛ばすと長さが縮むことを検出する."""
        edges_path = self.write_edges("zigzag", [(y, y % 2, 10) for y in range(11)])
        self.write_csv(
            "measurements.csv", [{"sample_id": "zigzag", "edges_path": edges_path}]
        )
        self.run_script(
            "compare_sampling.py",
            INPUT_CSV="measurements.csv",
            OUTPUT_CSV="sampling.csv",
            ROW_STEPS=(1, 2),
        )
        left = [row for row in self.read_csv("sampling.csv") if row["side"] == "left"]
        self.assertAlmostEqual(float(left[0]["length_px"]), 10 * math.sqrt(2), places=5)
        self.assertEqual(float(left[1]["length_px"]), 10)
        self.assertAlmostEqual(
            float(left[1]["change_from_step1_pct"]),
            (1 / math.sqrt(2) - 1) * 100,
            places=5,
        )

    def test_width_normalization_and_interpolation(self) -> None:
        """高さ・位置が違う同じ幅変化を、相対高さで一致させる."""
        before = self.write_edges("before", [(10, 20, 30), (20, 20, 40)])
        after = self.write_edges("after", [(100, 70, 80), (140, 70, 90)])
        self.write_csv(
            "measurements.csv",
            [
                {"sample_id": "after", "edges_path": after, "mm_per_px": ""},
                {"sample_id": "before", "edges_path": before, "mm_per_px": ""},
            ],
        )
        self.run_script(
            "compare_widths.py",
            INPUT_CSV="measurements.csv",
            OUTPUT_CSV="widths.csv",
            BASELINE_ID="before",
            POSITION_COUNT=3,
        )
        rows = self.read_csv("widths.csv")
        self.assertEqual([float(row["width_px"]) for row in rows[:3]], [10, 15, 20])
        for row in rows:
            self.assertEqual(float(row["width_diff_px"]), 0)

    def test_width_mm_conversion_and_missing_scale(self) -> None:
        """幅が倍の画像でも1pxあたりの尺度が半分なら一致する."""
        before = self.write_edges("before", [(0, 10, 30), (10, 10, 30)])
        after = self.write_edges("after", [(0, 20, 60), (20, 20, 60)])
        rows: list[dict[str, object]] = [
            {"sample_id": "before", "edges_path": before, "mm_per_px": "0.1"},
            {"sample_id": "after", "edges_path": after, "mm_per_px": "0.05"},
        ]
        self.write_csv("measurements.csv", rows)
        settings = {
            "INPUT_CSV": "measurements.csv",
            "OUTPUT_CSV": "widths.csv",
            "BASELINE_ID": "before",
            "UNIT": "mm",
            "POSITION_COUNT": 3,
        }
        self.run_script("compare_widths.py", **settings)
        saved_output = (self.directory / "widths.csv").read_bytes()
        for row in self.read_csv("widths.csv"):
            self.assertEqual(float(row["width_mm"]), 2)
            self.assertEqual(float(row["width_diff_mm"]), 0)
        rows[1]["mm_per_px"] = ""
        self.write_csv("measurements.csv", rows)
        with self.assertRaisesRegex(ValueError, "空欄"):
            self.run_script("compare_widths.py", **settings)
        self.assertEqual((self.directory / "widths.csv").read_bytes(), saved_output)


if __name__ == "__main__":
    unittest.main()
