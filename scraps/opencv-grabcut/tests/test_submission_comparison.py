"""提出版04の差分・棒グラフ・入力検証と、単独実行を確認する."""

import ast
import csv
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import cv2 as cv
import numpy as np


class SubmissionComparisonTests(unittest.TestCase):
    def script_source(self, **overrides: object) -> str:
        path = (
            Path(__file__).resolve().parents[1]
            / "sandbox/previous_submissions/04_compare_lengths.py"
        )
        source = path.read_text(encoding="utf-8")
        settings = {
            "INPUT_CSVS": (("A", "A.csv"), ("B", "B.csv")),
            "BASELINE_ID": "A",
            "OUTPUT_CSV_PATH": "comparison.csv",
            "OUTPUT_IMAGE_PATH": "comparison.png",
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

    def temporary_directory(self) -> tempfile.TemporaryDirectory[str]:
        results = Path(__file__).resolve().parents[1] / "tests/results"
        results.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=results)
        if not Path(temporary.name).resolve().is_relative_to(results.resolve()):
            raise ValueError("検証用の一時領域が試験結果フォルダ外にあります")
        return temporary

    def write_lengths(
        self,
        path: Path,
        lengths: tuple[float, float, float] = (120.0, 120.0, 240.0),
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(("edge", "length_px", "start_y", "end_y"))
            for edge, length in zip(("left", "right", "total"), lengths):
                writer.writerow((edge, f"{length:.2f}", 20, 140))

    def test_known_differences_and_graph_with_baseline_last(self) -> None:
        """3枚の既知値を比較し、負の差分・丸め・棒の値・基準表示を照合する."""
        with self.temporary_directory() as temporary:
            directory = Path(temporary)
            self.write_lengths(directory / "A.csv", (124.32, 124.32, 248.65))
            self.write_lengths(directory / "B.csv", (110.25, 125.5, 235.75))
            self.write_lengths(directory / "C.csv")
            script = directory / "04_compare_lengths.py"
            script.write_text(
                self.script_source(
                    INPUT_CSVS=(
                        ("左右切欠き", "A.csv"),
                        ("B", "B.csv"),
                        ("基準", "C.csv"),
                    ),
                    BASELINE_ID="基準",
                ),
                encoding="utf-8",
            )
            values = runpy.run_path(str(script))
            with (directory / "comparison.csv").open(
                encoding="utf-8", newline=""
            ) as saved:
                rows = list(csv.DictReader(saved))
            self.assertEqual(
                [row["sample_id"] for row in rows], ["左右切欠き", "B", "基準"]
            )
            self.assertEqual([row["baseline_id"] for row in rows], ["基準"] * 3)
            for row, expected in zip(
                rows,
                (
                    ("124.32", "124.32", "248.65", "4.32", "4.32", "8.65"),
                    ("110.25", "125.50", "235.75", "-9.75", "5.50", "-4.25"),
                    ("120.00", "120.00", "240.00", "0.00", "0.00", "0.00"),
                ),
            ):
                actual = tuple(
                    row[column]
                    for column in (
                        "left_px",
                        "right_px",
                        "total_px",
                        "delta_left_px",
                        "delta_right_px",
                        "delta_total_px",
                    )
                )
                self.assertEqual(actual, expected)
                self.assertEqual((row["start_y"], row["end_y"]), ("20", "140"))
            axes = values["axes"]
            self.assertEqual(
                [bar.get_height() for bar in axes.patches],
                [124.32, 110.25, 120.0, 124.32, 125.5, 120.0],
            )
            self.assertEqual(axes.get_title(), "Baseline: 基準 | y=20..140")
            self.assertEqual(axes.get_ylim()[0], 0)
            self.assertEqual(axes.get_ylabel(), "Side length (px)")
            image = cv.imdecode(
                np.frombuffer((directory / "comparison.png").read_bytes(), np.uint8),
                cv.IMREAD_COLOR,
            )
            if image is None:
                self.fail("比較の棒グラフを読み込めません")
            self.assertGreater(float(np.std(image)), 10)

    def test_unicode_relative_and_absolute_paths_run_alone(self) -> None:
        """日本語と空白を含むCSV・PNGのパスで、04を1本だけコピーして動かす."""
        project = Path(__file__).resolve().parents[1]
        with self.temporary_directory() as temporary:
            directory = Path(temporary) / "日本語 フォルダ"
            input_a = directory / "入力 資料/基準 長さ.csv"
            input_b = directory / "入力 資料/比較 長さ.csv"
            self.write_lengths(input_a)
            self.write_lengths(input_b, (138.1, 120.0, 258.1))
            original_bytes = (input_a.read_bytes(), input_b.read_bytes())
            for mode in ("relative", "absolute"):
                folder = directory / mode
                folder.mkdir()
                output_csv = folder / "出力 結果/比較 長さ.csv"
                output_image = folder / "出力 結果/棒グラフ.png"
                script = folder / "04_compare_lengths.py"
                script.write_text(
                    self.script_source(
                        INPUT_CSVS=(
                            (
                                "基準",
                                "../入力 資料/基準 長さ.csv"
                                if mode == "relative"
                                else str(input_a),
                            ),
                            (
                                "比較",
                                "../入力 資料/比較 長さ.csv"
                                if mode == "relative"
                                else str(input_b),
                            ),
                        ),
                        BASELINE_ID="基準",
                        OUTPUT_CSV_PATH="出力 結果/比較 長さ.csv"
                        if mode == "relative"
                        else str(output_csv),
                        OUTPUT_IMAGE_PATH="出力 結果/棒グラフ.png"
                        if mode == "relative"
                        else str(output_image),
                    ),
                    encoding="utf-8",
                )
                completed = subprocess.run(
                    [sys.executable, str(script)],
                    cwd=project,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(
                    completed.returncode, 0, completed.stderr.decode(errors="replace")
                )
                self.assertNotIn(b"Glyph", completed.stderr)
                self.assertTrue(output_csv.is_file())
                self.assertTrue(output_image.read_bytes().startswith(b"\x89PNG"))
            self.assertEqual(
                (input_a.read_bytes(), input_b.read_bytes()), original_bytes
            )

    def test_invalid_csv_data_stops_before_saving(self) -> None:
        """誤ったCSVや範囲の違いを検出し、先に読んだ入力と既存出力を保つ."""
        valid = "edge,length_px,start_y,end_y\nleft,120,20,140\nright,120,20,140\ntotal,240,20,140\n"
        invalid_cases = {
            "missing_column": valid.replace("length_px", "length_mm"),
            "missing_edge": valid.replace("total,240,20,140\n", ""),
            "duplicate_edge": valid + "left,120,20,140\n",
            "unknown_edge": valid.replace("left,", "top,"),
            "not_number": valid.replace("left,120", "left,abc"),
            "nan": valid.replace("left,120", "left,nan"),
            "infinity": valid.replace("left,120", "left,inf"),
            "negative": valid.replace("left,120", "left,-120"),
            "zero": valid.replace("left,120", "left,0"),
            "wrong_total": valid.replace("total,240", "total,241"),
            "mixed_range": valid.replace("left,120,20,140", "left,120,21,140"),
            "different_range": valid.replace(",20,140", ",21,140"),
            "reversed_range": valid.replace(",20,140", ",140,20"),
            "single_row": valid.replace(",20,140", ",20,20"),
            "empty": "",
        }
        with self.temporary_directory() as temporary:
            directory = Path(temporary)
            self.write_lengths(directory / "A.csv")
            original_a = (directory / "A.csv").read_bytes()
            script = directory / "04_compare_lengths.py"
            script.write_text(self.script_source(), encoding="utf-8")
            for case, content in invalid_cases.items():
                with self.subTest(case=case):
                    (directory / "B.csv").write_text(content, encoding="utf-8")
                    original_b = (directory / "B.csv").read_bytes()
                    for name in ("comparison.csv", "comparison.png"):
                        (directory / name).write_bytes(b"previous result")
                    with self.assertRaises(ValueError):
                        runpy.run_path(str(script))
                    self.assertEqual((directory / "A.csv").read_bytes(), original_a)
                    self.assertEqual((directory / "B.csv").read_bytes(), original_b)
                    for name in ("comparison.csv", "comparison.png"):
                        self.assertEqual(
                            (directory / name).read_bytes(), b"previous result"
                        )

    def test_invalid_settings_and_output_paths_protect_inputs(self) -> None:
        """識別名・基準・枚数・出力先の間違いで、入力CSVを上書きしない."""
        cases = (
            {"INPUT_CSVS": (("A", "A.csv"),)},
            {"INPUT_CSVS": (("A", "A.csv"), ("A", "B.csv"))},
            {"INPUT_CSVS": (("A", "A.csv"), (" ", "B.csv"))},
            {"BASELINE_ID": "missing"},
            {"OUTPUT_CSV_PATH": "A.csv"},
            {"OUTPUT_IMAGE_PATH": "B.csv"},
            {"OUTPUT_CSV_PATH": "alias/../B.csv"},
            {"OUTPUT_IMAGE_PATH": "comparison.csv"},
        )
        with self.temporary_directory() as temporary:
            directory = Path(temporary)
            self.write_lengths(directory / "A.csv")
            self.write_lengths(directory / "B.csv")
            originals = {
                name: (directory / name).read_bytes() for name in ("A.csv", "B.csv")
            }
            for settings in cases:
                with self.subTest(settings=settings):
                    script = directory / "04_compare_lengths.py"
                    script.write_text(self.script_source(**settings), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        runpy.run_path(str(script))
                    for name, content in originals.items():
                        self.assertEqual((directory / name).read_bytes(), content)
                    self.assertFalse((directory / "comparison.csv").exists())
                    self.assertFalse((directory / "comparison.png").exists())

    def test_missing_csv_stops_before_saving(self) -> None:
        with self.temporary_directory() as temporary:
            directory = Path(temporary)
            self.write_lengths(directory / "A.csv")
            script = directory / "04_compare_lengths.py"
            script.write_text(self.script_source(), encoding="utf-8")
            with self.assertRaises(FileNotFoundError):
                runpy.run_path(str(script))
            self.assertFalse((directory / "comparison.csv").exists())
            self.assertFalse((directory / "comparison.png").exists())


if __name__ == "__main__":
    unittest.main()
