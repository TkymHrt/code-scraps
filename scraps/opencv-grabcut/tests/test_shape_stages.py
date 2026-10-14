"""幅・基準線・凹み候補の各提出版を、既知形状で単独検証する."""

import ast
import csv
import math
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import cv2 as cv
import numpy as np


class ShapeStageTests(unittest.TestCase):
    def temporary_directory(self) -> tempfile.TemporaryDirectory[str]:
        results = Path(__file__).resolve().parents[1] / "tests/results"
        results.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=results)
        if not Path(temporary.name).resolve().is_relative_to(results.resolve()):
            raise ValueError("検証用の一時領域が試験結果フォルダ外にあります")
        return temporary

    def script_source(self, filename: str, **overrides: object) -> str:
        path = (
            Path(__file__).resolve().parents[1]
            / "sandbox/previous_submissions"
            / filename
        )
        source = path.read_text(encoding="utf-8")
        settings = {
            "INPUT_CSVS": (("A", "A.csv"), ("B", "B.csv")),
            "BASELINE_ID": "A",
            "INPUT_PATH": "input.png",
            "OUTPUT_IMAGE_PATH": f"results/{path.stem}.png",
            "OUTPUT_CSV_PATH": f"results/{path.stem}.csv",
            "OUTPUT_COUNTS_PATH": "results/07_candidate_counts.csv",
            "OUTPUT_SUMMARY_PATH": "results/08_candidate_summary.csv",
            "CANDIDATE_RECT": (0.34, 0.0, 0.705, 1.0),
            "BACKGROUND_RECTS": ((0.0, 0.0, 0.33, 1.0), (0.72, 0.0, 1.0, 1.0)),
            "FOREGROUND_RECTS": ((0.48, 0.4, 0.56, 0.6),),
            "ITERATIONS": 5,
            "RANDOM_SEED": 0,
            "START_Y": 20,
            "END_Y": 140,
            "LEFT_REFERENCE_RANGES": ((20, 40), (120, 140)),
            "RIGHT_REFERENCE_RANGES": ((20, 40), (120, 140)),
            "MIN_INWARD_PX": 5.0,
            "MIN_ROWS": 3,
        }
        settings.update(overrides)
        lines = source.splitlines(keepends=True)
        for node in reversed(ast.parse(source).body):
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                if name in settings:
                    lines[node.lineno - 1 : node.end_lineno] = [
                        f"{name} = {settings[name]!r}\n"
                    ]
        return "".join(lines)

    def save_image(self, directory: Path, mask: np.ndarray) -> np.ndarray:
        image = np.full((*mask.shape, 3), 35, np.uint8)
        image[mask > 0] = 200
        success, encoded = cv.imencode(".png", image)
        self.assertTrue(success)
        (directory / "input.png").write_bytes(encoded.tobytes())
        return image

    def run_script(self, directory: Path, filename: str, **settings: object) -> dict:
        script = directory / filename
        script.write_text(self.script_source(filename, **settings), encoding="utf-8")
        return runpy.run_path(str(script))

    def read_csv(self, path: Path) -> list[dict[str, str]]:
        with path.open(encoding="utf-8-sig", newline="") as source:
            return list(csv.DictReader(source))

    def test_widths_match_all_rows_and_keep_missing_rows_blank(self) -> None:
        """画素中心の幅、切欠き、穴埋め、未観測行の空欄とグラフの切れ目を確認する."""
        with self.temporary_directory() as temporary:
            for shape in ("rectangle", "notch", "hole"):
                with self.subTest(shape=shape):
                    directory = Path(temporary) / shape
                    directory.mkdir()
                    mask = np.zeros((160, 140), np.uint8)
                    mask[20:141, 50:91] = 255
                    if shape == "notch":
                        mask[75:90, 50:60] = 0
                    if shape == "hole":
                        mask[50:65, 55:61] = 0
                    self.save_image(directory, mask)
                    values = self.run_script(
                        directory, "05_widths.py", START_Y=0, END_Y=None
                    )
                    rows = self.read_csv(directory / "results/05_widths.csv")
                    self.assertEqual(len(rows), 160)
                    self.assertEqual([int(row["y"]) for row in rows], list(range(160)))
                    for y, row in enumerate(rows):
                        if 20 <= y <= 140:
                            expected_left = (
                                60 if shape == "notch" and 75 <= y < 90 else 50
                            )
                            self.assertEqual(int(row["left_x"]), expected_left)
                            self.assertEqual(row["right_x"], "90")
                            self.assertEqual(int(row["width_px"]), 90 - expected_left)
                        else:
                            self.assertEqual(
                                (row["left_x"], row["right_x"], row["width_px"]),
                                ("", "", ""),
                            )
                    plotted = values["axes"].lines[0].get_ydata()
                    self.assertTrue(np.isnan(plotted[0]))
                    self.assertEqual(plotted[20], 40)
                    self.assertTrue((directory / "results/05_widths.png").is_file())

    def test_widths_reject_empty_measurement_range(self) -> None:
        with self.temporary_directory() as temporary:
            directory = Path(temporary)
            mask = np.zeros((160, 140), np.uint8)
            mask[20:141, 50:91] = 255
            self.save_image(directory, mask)
            with self.assertRaisesRegex(ValueError, "計測範囲に試料がありません"):
                self.run_script(directory, "05_widths.py", START_Y=0, END_Y=10)
            self.assertFalse((directory / "results").exists())

    def test_reference_lines_and_signed_inward_offsets(self) -> None:
        """傾いた正常端を除去し、左右の内向きと外向きの符号を確認する."""
        with self.temporary_directory() as temporary:
            directory = Path(temporary)
            mask = np.zeros((160, 180), np.uint8)
            for y in range(20, 141):
                left = 45 + (y - 20) // 4
                right = left + 45
                if 75 <= y < 90:
                    left += 10
                    right -= 7
                if 95 <= y < 105:
                    left -= 6
                mask[y, left : right + 1] = 255
            self.save_image(directory, mask)
            values = self.run_script(
                directory,
                "06_reference_edges.py",
                CANDIDATE_RECT=(0.23, 0.0, 0.7, 1.0),
                BACKGROUND_RECTS=((0.0, 0.0, 0.21, 1.0), (0.71, 0.0, 1.0, 1.0)),
                FOREGROUND_RECTS=((0.42, 0.4, 0.46, 0.6),),
            )
            rows = self.read_csv(directory / "results/06_reference_edges.csv")
            self.assertEqual(len(rows), 121)
            self.assertAlmostEqual(values["left_slope"], 0.25, delta=0.001)
            self.assertAlmostEqual(values["right_slope"], 0.25, delta=0.001)
            for row in rows:
                y = int(row["y"])
                left = float(row["left_inward_px"])
                right = float(row["right_inward_px"])
                if 75 <= y < 90:
                    self.assertAlmostEqual(left, 10, delta=0.8)
                    self.assertAlmostEqual(right, 7, delta=0.8)
                elif 95 <= y < 105:
                    self.assertAlmostEqual(left, -6, delta=0.8)
                else:
                    self.assertAlmostEqual(left, 0, delta=0.8)
                expected_sample = 20 <= y <= 40 or 120 <= y <= 140
                self.assertEqual(
                    row["left_reference_sample"], str(int(expected_sample))
                )

    def test_reference_ranges_reject_unavailable_or_invalid_points(self) -> None:
        with self.temporary_directory() as temporary:
            directory = Path(temporary)
            mask = np.zeros((160, 140), np.uint8)
            mask[20:141, 50:91] = 255
            self.save_image(directory, mask)
            for ranges in (
                (),
                ((20, 20),),
                ((10, 19),),
                ((40, 20),),
                ((20, 30), (30, 40)),
            ):
                with self.subTest(ranges=ranges):
                    with self.assertRaises(ValueError):
                        self.run_script(
                            directory,
                            "06_reference_edges.py",
                            LEFT_REFERENCE_RANGES=ranges,
                            START_Y=0,
                            END_Y=159,
                        )
                    self.assertFalse((directory / "results").exists())

    def test_candidate_count_rule_keeps_sides_separate_and_requires_continuity(
        self,
    ) -> None:
        """しきい値ちょうど・短すぎる凹み・別の凹み・左右を同じ既知形状で確認する."""
        with self.temporary_directory() as temporary:
            directory = Path(temporary)
            mask = np.zeros((160, 140), np.uint8)
            mask[20:141, 50:91] = 255
            mask[50:54, 50:55] = 0
            mask[57:59, 50:60] = 0
            mask[75:90, 50:60] = 0
            mask[75:80, 84:91] = 0
            self.save_image(directory, mask)
            values = self.run_script(directory, "07_notch_candidates.py")
            rows = self.read_csv(directory / "results/07_notch_candidates.csv")
            self.assertEqual(
                [
                    (
                        row["candidate_id"],
                        row["edge"],
                        row["start_y"],
                        row["end_y"],
                        row["point_count"],
                    )
                    for row in rows
                ],
                [
                    ("L01", "left", "50", "53", "4"),
                    ("L02", "left", "75", "89", "15"),
                    ("R01", "right", "75", "79", "5"),
                ],
            )
            counts = self.read_csv(directory / "results/07_candidate_counts.csv")
            self.assertEqual(
                [row["candidate_count"] for row in counts], ["2", "1", "3"]
            )
            self.assertEqual(
                [candidate["max_inward_px"] for candidate in values["candidates"]],
                [5, 10, 7],
            )
            self.assertTrue(all(row["touches_boundary"] == "0" for row in rows))

    def test_candidates_zero_and_measurement_boundary(self) -> None:
        with self.temporary_directory() as temporary:
            directory = Path(temporary)
            mask = np.zeros((160, 140), np.uint8)
            mask[20:141, 50:91] = 255
            self.save_image(directory, mask)
            self.run_script(directory, "07_notch_candidates.py")
            self.assertEqual(
                self.read_csv(directory / "results/07_notch_candidates.csv"), []
            )
            counts = self.read_csv(directory / "results/07_candidate_counts.csv")
            self.assertEqual(
                [row["candidate_count"] for row in counts], ["0", "0", "0"]
            )
            mask[20:26, 50:60] = 0
            self.save_image(directory, mask)
            self.run_script(
                directory,
                "07_notch_candidates.py",
                LEFT_REFERENCE_RANGES=((40, 60), (120, 140)),
            )
            rows = self.read_csv(directory / "results/07_notch_candidates.csv")
            self.assertEqual(len(rows), 1)
            self.assertEqual(
                (rows[0]["start_y"], rows[0]["end_y"], rows[0]["touches_boundary"]),
                ("20", "25", "1"),
            )

    def test_candidate_sizes_match_known_depth_and_span(self) -> None:
        """15行の切欠きは影響範囲14px。左右別と候補ゼロの集計も確認する."""
        with self.temporary_directory() as temporary:
            directory = Path(temporary)
            mask = np.zeros((160, 140), np.uint8)
            mask[20:141, 50:91] = 255
            mask[75:90, 50:60] = 0
            self.save_image(directory, mask)
            self.run_script(directory, "08_candidate_sizes.py")
            rows = self.read_csv(directory / "results/08_candidate_sizes.csv")
            self.assertEqual(len(rows), 1)
            self.assertEqual(
                (
                    rows[0]["max_inward_px"],
                    rows[0]["span_y_px"],
                    rows[0]["span_along_reference_px"],
                ),
                ("10.00", "14", "14.00"),
            )
            summary = self.read_csv(directory / "results/08_candidate_summary.csv")
            self.assertEqual(
                [row["candidate_count"] for row in summary], ["1", "0", "1"]
            )
            self.assertEqual(
                [row["max_inward_px"] for row in summary], ["10.00", "0.00", "10.00"]
            )
            self.assertEqual(
                [row["total_span_px"] for row in summary], ["14.00", "0.00", "14.00"]
            )
            mask[75:90, 50:60] = 255
            self.save_image(directory, mask)
            self.run_script(directory, "08_candidate_sizes.py")
            self.assertEqual(
                self.read_csv(directory / "results/08_candidate_sizes.csv"), []
            )
            summary = self.read_csv(directory / "results/08_candidate_summary.csv")
            self.assertTrue(
                all(
                    row["candidate_count"] == "0"
                    and row["max_inward_px"] == "0.00"
                    and row["total_span_px"] == "0.00"
                    for row in summary
                )
            )

    def test_candidate_span_follows_sloped_reference(self) -> None:
        with self.temporary_directory() as temporary:
            directory = Path(temporary)
            mask = np.zeros((160, 180), np.uint8)
            for y in range(20, 141):
                left = 45 + (y - 20) // 4
                right = left + 45
                if 75 <= y < 90:
                    left += 10
                mask[y, left : right + 1] = 255
            self.save_image(directory, mask)
            reference_ranges = ((20, 20), (40, 40), (120, 120), (140, 140))
            self.run_script(
                directory,
                "08_candidate_sizes.py",
                CANDIDATE_RECT=(0.23, 0.0, 0.7, 1.0),
                BACKGROUND_RECTS=((0.0, 0.0, 0.21, 1.0), (0.71, 0.0, 1.0, 1.0)),
                FOREGROUND_RECTS=((0.42, 0.4, 0.46, 0.6),),
                LEFT_REFERENCE_RANGES=reference_ranges,
                RIGHT_REFERENCE_RANGES=reference_ranges,
            )
            rows = self.read_csv(directory / "results/08_candidate_sizes.csv")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["max_inward_px"], "10.00")
            self.assertEqual(
                float(rows[0]["span_along_reference_px"]),
                round(math.hypot(14 * 0.25, 14), 2),
            )

    def write_summary(self, path: Path, left: tuple, right: tuple) -> None:
        """count, max_inward, total_span, boundary_count の既知値を08の形式で保存する."""
        total = (
            left[0] + right[0],
            max(left[1], right[1]),
            left[2] + right[2],
            left[3] + right[3],
        )
        with path.open("w", encoding="utf-8", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(
                (
                    "edge",
                    "candidate_count",
                    "max_inward_px",
                    "total_span_px",
                    "boundary_candidate_count",
                    "start_y",
                    "end_y",
                    "threshold_px",
                    "min_rows",
                    "left_reference_ranges",
                    "right_reference_ranges",
                )
            )
            for edge, values in (("left", left), ("right", right), ("total", total)):
                writer.writerow(
                    (
                        edge,
                        *values,
                        20,
                        140,
                        5,
                        3,
                        "((20, 40), (120, 140))",
                        "((20, 40), (120, 140))",
                    )
                )

    def test_candidate_comparison_accepts_zero_baseline_and_known_differences(
        self,
    ) -> None:
        with self.temporary_directory() as temporary:
            directory = Path(temporary)
            self.write_summary(directory / "A.csv", (1, 10, 14, 0), (1, 7, 4, 0))
            self.write_summary(directory / "B.csv", (0, 0, 0, 0), (0, 0, 0, 0))
            values = self.run_script(
                directory, "09_compare_candidates.py", BASELINE_ID="B"
            )
            rows = self.read_csv(directory / "results/09_compare_candidates.csv")
            self.assertEqual(len(rows), 6)
            self.assertTrue(all(row["baseline_id"] == "B" for row in rows))
            self.assertEqual(
                [
                    (
                        row["edge"],
                        row["delta_candidate_count"],
                        row["delta_max_inward_px"],
                        row["delta_total_span_px"],
                    )
                    for row in rows[:3]
                ],
                [
                    ("left", "1", "10.00", "14.00"),
                    ("right", "1", "7.00", "4.00"),
                    ("total", "2", "10.00", "18.00"),
                ],
            )
            self.assertTrue(
                all(
                    row["delta_candidate_count"] == "0"
                    and row["delta_max_inward_px"] == "0.00"
                    and row["delta_total_span_px"] == "0.00"
                    for row in rows[3:]
                )
            )
            self.assertEqual(
                [bar.get_height() for bar in values["axes"][0].patches], [1, 0, 1, 0]
            )
            self.assertEqual(
                [bar.get_height() for bar in values["axes"][1].patches], [10, 0, 7, 0]
            )
            self.assertEqual(
                [bar.get_height() for bar in values["axes"][2].patches], [14, 0, 4, 0]
            )
            self.assertIn("Baseline: B", values["figure"]._suptitle.get_text())
            self.assertTrue((directory / "results/09_compare_candidates.png").is_file())
            self.run_script(directory, "09_compare_candidates.py", BASELINE_ID="A")
            rows = self.read_csv(directory / "results/09_compare_candidates.csv")
            self.assertEqual(rows[-1]["delta_candidate_count"], "-2")
            self.assertEqual(rows[-1]["delta_max_inward_px"], "-10.00")

    def test_candidate_comparison_rejects_mismatched_or_invalid_summary(self) -> None:
        with self.temporary_directory() as temporary:
            directory = Path(temporary)
            self.write_summary(directory / "A.csv", (1, 10, 14, 0), (0, 0, 0, 0))
            valid = (directory / "A.csv").read_text(encoding="utf-8")
            cases = {
                "wrong_total": valid.replace("total,1,10,14,0", "total,2,10,14,0"),
                "different_threshold": valid.replace(",20,140,5,3,", ",20,140,6,3,"),
                "different_range": valid.replace(",20,140,5,3,", ",21,140,5,3,"),
                "different_normal_parts": valid.replace("(20, 40)", "(21, 40)"),
                "negative_count": valid.replace("left,1,10,14,0", "left,-1,10,14,0"),
                "nan": valid.replace("left,1,10,14,0", "left,1,nan,14,0"),
                "zero_with_size": valid.replace("left,1,10,14,0", "left,0,10,14,0"),
                "boundary_count": valid.replace("left,1,10,14,0", "left,1,10,14,2"),
                "below_threshold": valid.replace("left,1,10,14,0", "left,1,4,14,0"),
                "missing_column": valid.replace("max_inward_px", "depth_mm"),
                "duplicate_edge": valid + valid.splitlines()[1] + "\n",
                "missing_edge": "\n".join(valid.splitlines()[:-1]),
            }
            for case, text in cases.items():
                with self.subTest(case=case):
                    (directory / "B.csv").write_text(text, encoding="utf-8")
                    with self.assertRaises(ValueError):
                        self.run_script(directory, "09_compare_candidates.py")
                    self.assertFalse((directory / "results").exists())

    def test_candidate_comparison_paths_and_settings_protect_input(self) -> None:
        with self.temporary_directory() as temporary:
            directory = Path(temporary)
            self.write_summary(directory / "A.csv", (0, 0, 0, 0), (0, 0, 0, 0))
            self.write_summary(directory / "B.csv", (0, 0, 0, 0), (0, 0, 0, 0))
            originals = [(directory / name).read_bytes() for name in ("A.csv", "B.csv")]
            for settings in (
                {"OUTPUT_CSV_PATH": "A.csv"},
                {"OUTPUT_IMAGE_PATH": "nested/../B.csv"},
                {"OUTPUT_IMAGE_PATH": "results/09_compare_candidates.csv"},
                {"BASELINE_ID": "missing"},
                {"INPUT_CSVS": (("A", "A.csv"),)},
                {"INPUT_CSVS": (("A", "A.csv"), ("A", "B.csv"))},
            ):
                with self.subTest(settings=settings):
                    with self.assertRaises(ValueError):
                        self.run_script(
                            directory, "09_compare_candidates.py", **settings
                        )
                    self.assertEqual(
                        [
                            (directory / name).read_bytes()
                            for name in ("A.csv", "B.csv")
                        ],
                        originals,
                    )
                    self.assertFalse((directory / "results").exists())

    def test_image_stage_output_paths_and_invalid_range_protect_input(self) -> None:
        with self.temporary_directory() as temporary:
            directory = Path(temporary)
            mask = np.zeros((160, 140), np.uint8)
            mask[20:141, 50:91] = 255
            self.save_image(directory, mask)
            original = (directory / "input.png").read_bytes()
            for filename in (
                "05_widths.py",
                "06_reference_edges.py",
                "07_notch_candidates.py",
                "08_candidate_sizes.py",
            ):
                for settings in (
                    {"OUTPUT_IMAGE_PATH": "input.png"},
                    {"OUTPUT_CSV_PATH": "nested/../input.png"},
                    {"START_Y": -1},
                    {"START_Y": 141},
                    {"END_Y": 160},
                ):
                    with self.subTest(filename=filename, settings=settings):
                        with self.assertRaises(ValueError):
                            self.run_script(directory, filename, **settings)
                        self.assertEqual(
                            (directory / "input.png").read_bytes(), original
                        )
                        self.assertFalse((directory / "results").exists())
            for filename, extra_output in (
                ("07_notch_candidates.py", "OUTPUT_COUNTS_PATH"),
                ("08_candidate_sizes.py", "OUTPUT_SUMMARY_PATH"),
            ):
                for settings in (
                    {extra_output: "input.png"},
                    {extra_output: f"results/{Path(filename).stem}.csv"},
                    {"MIN_INWARD_PX": 0},
                    {"MIN_INWARD_PX": float("inf")},
                    {"MIN_ROWS": 1},
                    {"MIN_ROWS": 2.5},
                    {"START_Y": 0, "END_Y": 159},
                ):
                    with self.subTest(filename=filename, settings=settings):
                        if settings.get("MIN_INWARD_PX") == float("inf"):
                            # ソース置換時にも、infを名前として書かない。
                            source = self.script_source(filename).replace(
                                "MIN_INWARD_PX = 5.0", 'MIN_INWARD_PX = float("inf")'
                            )
                            script = directory / filename
                            script.write_text(source, encoding="utf-8")
                            with self.assertRaises(ValueError):
                                runpy.run_path(str(script))
                        else:
                            with self.assertRaises(ValueError):
                                self.run_script(directory, filename, **settings)
                        self.assertEqual(
                            (directory / "input.png").read_bytes(), original
                        )
                        self.assertFalse((directory / "results").exists())

    def test_new_stages_run_alone_with_unicode_relative_and_absolute_paths(
        self,
    ) -> None:
        """日本語と空白を含むパスで、各スクリプトを別フォルダから単独実行する."""
        project = Path(__file__).resolve().parents[1]
        with self.temporary_directory() as temporary:
            workspace = Path(temporary) / "日本語 フォルダ"
            inputs = workspace / "入力 資料"
            inputs.mkdir(parents=True)
            mask = np.zeros((160, 140), np.uint8)
            mask[20:141, 50:91] = 255
            self.save_image(inputs, mask)
            input_path = inputs / "試料 画像.png"
            (inputs / "input.png").rename(input_path)
            self.write_summary(inputs / "基準 集計.csv", (0, 0, 0, 0), (0, 0, 0, 0))
            self.write_summary(inputs / "比較 集計.csv", (1, 10, 14, 0), (0, 0, 0, 0))
            original = input_path.read_bytes()
            for mode in ("relative", "absolute"):
                directory = workspace / mode
                directory.mkdir()
                for filename in (
                    "05_widths.py",
                    "06_reference_edges.py",
                    "07_notch_candidates.py",
                    "08_candidate_sizes.py",
                    "09_compare_candidates.py",
                ):
                    with self.subTest(mode=mode, filename=filename):
                        stem = Path(filename).stem
                        settings = {
                            "INPUT_PATH": "../入力 資料/試料 画像.png"
                            if mode == "relative"
                            else str(input_path),
                            "INPUT_CSVS": (
                                (
                                    "基準",
                                    "../入力 資料/基準 集計.csv"
                                    if mode == "relative"
                                    else str(inputs / "基準 集計.csv"),
                                ),
                                (
                                    "比較",
                                    "../入力 資料/比較 集計.csv"
                                    if mode == "relative"
                                    else str(inputs / "比較 集計.csv"),
                                ),
                            ),
                            "BASELINE_ID": "基準",
                        }
                        for name, suffix in (
                            ("OUTPUT_IMAGE_PATH", ".png"),
                            ("OUTPUT_CSV_PATH", ".csv"),
                            ("OUTPUT_COUNTS_PATH", "_counts.csv"),
                            ("OUTPUT_SUMMARY_PATH", "_summary.csv"),
                        ):
                            relative = f"出力 結果/{stem}{suffix}"
                            settings[name] = (
                                relative
                                if mode == "relative"
                                else str(directory / relative)
                            )
                        script = directory / filename
                        script.write_text(
                            self.script_source(filename, **settings), encoding="utf-8"
                        )
                        completed = subprocess.run(
                            [sys.executable, str(script)],
                            cwd=project,
                            capture_output=True,
                            check=False,
                        )
                        self.assertEqual(
                            completed.returncode,
                            0,
                            completed.stderr.decode(errors="replace"),
                        )
                        self.assertNotIn(b"Glyph", completed.stderr)
                        output_image = directory / f"出力 結果/{stem}.png"
                        output_csv = directory / f"出力 結果/{stem}.csv"
                        self.assertTrue(
                            output_image.read_bytes().startswith(b"\x89PNG")
                        )
                        self.assertTrue(output_csv.is_file())
            self.assertEqual(input_path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
