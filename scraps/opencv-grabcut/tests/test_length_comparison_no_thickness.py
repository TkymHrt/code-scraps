"""厚さのないCSVで、グラフの値・GUIなしの実行・入力保護を確認する。"""

import contextlib
import csv
import io
import os
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_current_workflow import copy_current


class NoThicknessGraphTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def sample(self, name, left, right):
        path = self.directory / f"{name}.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(["image_path", "left_mm", "right_mm"])
            writer.writerow([f"{name}.png", left, right])
        return path

    def execute(self, paths, **settings):
        script = copy_current(
            "length_comparison_no_thickness.py",
            self.directory,
            source_directory="sandbox/previous_submissions/comparison_variants",
            INPUT_CSVS=[str(path) for path in paths],
            **settings,
        )
        with contextlib.redirect_stdout(io.StringIO()):
            return runpy.run_path(str(script), run_name="__main__")

    def test_known_values_and_standalone_execution_without_tkinter(self):
        paths = [
            self.sample("初期", 100, 100),
            self.sample("撮影1", 210, 200),
            self.sample("撮影2", 420, 390),
        ]
        original = [path.read_bytes() for path in paths]
        result = self.execute(paths)
        lines = result["axis"].lines
        self.assertEqual(len(lines), 2)
        self.assertEqual(list(lines[0].get_ydata()), [100, 210, 420])
        self.assertEqual(list(lines[1].get_ydata()), [100, 200, 390])
        self.assertEqual(list(lines[0].get_xdata()), [1, 2, 3])
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "utf-8"
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "import runpy,sys; sys.modules['tkinter']=None; runpy.run_path(sys.argv[1],run_name='__main__')",
                str(self.directory / "length_comparison_no_thickness.py"),
            ],
            cwd=self.directory,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        image = self.directory / "output/length_comparison_no_thickness.png"
        self.assertEqual(image.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(original, [path.read_bytes() for path in paths])

    def test_single_and_twenty_csvs_follow_configuration_order(self):
        paths = [self.sample(f"撮影{i + 1}", 100 + i, 100) for i in range(20)]
        single = self.execute(paths[:1])
        self.assertEqual(single["axis"].get_xlim(), (0.5, 1.5))
        result = self.execute(list(reversed(paths)))
        self.assertEqual(result["left_values"], list(range(119, 99, -1)))
        self.assertEqual(result["right_values"], [100] * 20)

    def test_invalid_csvs_preserve_results_and_source_image(self):
        valid = self.sample("入力", 100, 110)
        output = self.directory / "output/length_comparison_no_thickness.png"
        output.parent.mkdir()
        output.write_bytes(b"previous graph")
        for left, right in ((0, 100), (100, -1), ("nan", 100), (100, "inf"), ("", 100)):
            invalid = self.sample("不正値", left, right)
            with self.subTest(left=left, right=right), self.assertRaises(ValueError):
                self.execute([valid, invalid])
            self.assertEqual(output.read_bytes(), b"previous graph")
        for paths in ([], [valid, valid]):
            with self.assertRaises(ValueError):
                self.execute(paths)
        image = self.directory / "入力.png"
        image.write_bytes(b"protected image")
        with self.assertRaisesRegex(ValueError, "別の保存先"):
            self.execute([valid], OUTPUT_PATH=str(image))
        self.assertEqual(image.read_bytes(), b"protected image")
        valid.write_text("wrong_header\n100\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "長さCSV"):
            self.execute([valid])
        self.assertEqual(output.read_bytes(), b"previous graph")


if __name__ == "__main__":
    unittest.main()
