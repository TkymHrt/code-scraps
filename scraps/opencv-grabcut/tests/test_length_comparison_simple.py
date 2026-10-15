"""GUIなしの単独実行、既知のグラフ数値、入力保護を確認する。"""

import contextlib
import io
import os
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_current_workflow import copy_current
from test_length_analysis_gui import write_sample


class HeadlessGraphTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def execute(self, samples, **settings):
        inputs = [(str(row["csv_path"]), row["thickness_mm"]) for row in samples]
        script = copy_current(
            "length_comparison_simple.py",
            self.directory,
            INPUT_CSVS=inputs,
            **settings,
        )
        with contextlib.redirect_stdout(io.StringIO()):
            return runpy.run_path(str(script), run_name="__main__")

    def test_known_values_and_standalone_execution_without_tkinter(self):
        samples = []
        for name, interval, left, right, thickness in (
            ("初期", 100, 100, 100, 10),
            ("撮影1", 200, 210, 200, 5),
            ("撮影2", 400, 420, 390, 2.5),
        ):
            samples.append(
                write_sample(self.directory, name, interval, left, right, thickness)
            )
        original = [row["csv_path"].read_bytes() for row in samples]
        result = self.execute(samples)
        lines = result["axis"].lines
        self.assertEqual(list(lines[0].get_ydata()), [100, 210, 420])
        self.assertEqual(list(lines[1].get_ydata()), [100, 200, 390])
        self.assertEqual(list(lines[2].get_ydata()), [100, 200, 400])
        self.assertEqual(list(lines[0].get_xdata()), [1, 2, 3])
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "utf-8"
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "import runpy,sys; sys.modules['tkinter']=None; runpy.run_path(sys.argv[1],run_name='__main__')",
                str(self.directory / "length_comparison_simple.py"),
            ],
            cwd=self.directory,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        image = self.directory / "output/length_comparison_simple.png"
        self.assertEqual(image.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(original, [row["csv_path"].read_bytes() for row in samples])

    def test_single_and_twenty_csvs_follow_configuration_order(self):
        samples = []
        for index in range(20):
            samples.append(
                write_sample(
                    self.directory, f"撮影{index + 1}", 100, 100 + index, 100, 10
                )
            )
        single = self.execute(samples[:1])
        self.assertEqual(single["axis"].get_xlim(), (0.5, 1.5))
        result = self.execute(list(reversed(samples)))
        self.assertEqual(result["left_values"], list(range(119, 99, -1)))
        self.assertEqual(result["ideal_values"], [100] * 20)

    def test_invalid_inputs_keep_existing_results_and_source_image(self):
        sample = write_sample(self.directory, "入力", 100, 100, 110, 10)
        output = self.directory / "output/length_comparison_simple.png"
        output.parent.mkdir()
        output.write_bytes(b"previous graph")
        for thickness in (0, -1, "nan", "inf", "", 5e-324):
            with self.subTest(thickness=thickness), self.assertRaises(ValueError):
                self.execute([dict(sample, thickness_mm=thickness)])
            self.assertEqual(output.read_bytes(), b"previous graph")
        for samples in ([], [sample, sample]):
            with self.assertRaises(ValueError):
                self.execute(samples)
        for settings in ({"INITIAL_LENGTH_MM": 0}, {"INITIAL_THICKNESS_MM": "nan"}):
            with self.assertRaises(ValueError):
                self.execute([sample], **settings)
        image_path = self.directory / "入力.png"
        image_path.write_bytes(b"protected image")
        with self.assertRaisesRegex(ValueError, "別の保存先"):
            self.execute([sample], OUTPUT_PATH=str(image_path))
        self.assertEqual(image_path.read_bytes(), b"protected image")
        sample["csv_path"].write_text("wrong_header\n100\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "長さCSV"):
            self.execute([sample])
        self.assertEqual(output.read_bytes(), b"previous graph")


if __name__ == "__main__":
    unittest.main()
