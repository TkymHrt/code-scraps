"""厚さから求める理想長との最小比較、単独実行、入出力を確認する."""

import csv
import runpy
import tempfile
import unittest
from pathlib import Path

from test_length_analysis_gui import write_sample

PROJECT = Path(__file__).resolve().parents[1]


class SimpleLengthComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.script = (
            PROJECT
            / "sandbox/previous_submissions/comparison_variants/length_comparison_simple_gui.py"
        )
        self.gui = runpy.run_path(str(self.script))

    def test_thickness_changes_ideal_with_independent_left_and_right_lengths(self):
        samples = []
        for name, interval, left, right, thickness in (
            ("初期", 100, 100, 100, 10),
            ("撮影1", 200, 210, 200, 5),
            ("撮影2", 400, 420, 390, 2.5),
        ):
            samples.append(
                write_sample(self.directory, name, interval, left, right, thickness)
            )
        rows = self.gui["compare_lengths"](samples, "100", "10")
        self.assertEqual([row["ideal_length_mm"] for row in rows], [100, 200, 400])
        self.assertEqual([row["delta_left_mm"] for row in rows], [0, 10, 20])
        self.assertEqual([row["delta_right_mm"] for row in rows], [0, 0, -10])
        figure = self.gui["create_graph"](rows)
        self.assertEqual(len(figure.axes), 1)
        axis = figure.axes[0]
        self.assertEqual(list(axis.lines[0].get_ydata()), [100, 210, 420])
        self.assertEqual(list(axis.lines[1].get_ydata()), [100, 200, 390])
        self.assertEqual(list(axis.lines[2].get_ydata()), [100, 200, 400])
        self.assertEqual(list(axis.lines[0].get_xdata()), [1, 2, 3])
        reversed_rows = self.gui["compare_lengths"](list(reversed(samples)), 100, 10)
        self.assertEqual(reversed_rows[0]["left_mm"], 420)
        self.assertEqual(reversed_rows[0]["ideal_length_mm"], 400)

    def test_single_and_twenty_csvs(self):
        samples = []
        for index in range(20):
            sample = write_sample(
                self.directory, f"撮影{index + 1}", 100, 100 + index, 100, 10
            )
            samples.append(sample)
        single = self.gui["compare_lengths"](samples[:1], 100, 10)
        self.assertEqual(single[0]["delta_left_mm"], 0)
        self.assertEqual(
            self.gui["create_graph"](single).axes[0].get_xlim(), (0.5, 1.5)
        )
        rows = self.gui["compare_lengths"](samples, 100, 10)
        self.assertEqual(len(rows), 20)
        self.assertEqual(rows[-1]["delta_left_mm"], 19)

    def test_standalone_saving_and_input_protection(self):
        copied = self.directory / self.script.name
        copied.write_bytes(self.script.read_bytes())
        gui = runpy.run_path(str(copied))
        sample = write_sample(self.directory, "入力 日本語", 100, 105.25, 101.5, 5)
        path = sample["csv_path"]
        before = path.read_bytes()
        image = self.directory / "入力 日本語.png"
        image.write_bytes(b"protected image")
        rows = gui["compare_lengths"]([sample], 50, 10)
        output = self.directory / "output/比較.csv"
        graph = self.directory / "output/比較.png"
        gui["write_csv"](output, rows)
        gui["write_graph"](graph, rows)
        with output.open(encoding="utf-8-sig", newline="") as source:
            saved = list(csv.DictReader(source))[0]
        self.assertEqual(saved["delta_left_mm"], "5.25")
        self.assertEqual(saved["delta_right_mm"], "1.5")
        self.assertEqual(saved["initial_length_mm"], "50")
        self.assertEqual(saved["initial_thickness_mm"], "10")
        self.assertEqual(saved["thickness_mm"], "5")
        self.assertEqual(saved["ideal_length_mm"], "100")
        self.assertEqual(rows[0]["image_path"], str(image.resolve()))
        self.assertTrue(output.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertEqual(graph.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        for function, protected in (("write_csv", path), ("write_graph", image)):
            with self.assertRaisesRegex(ValueError, "別の保存先"):
                gui[function](protected, rows)
        with self.assertRaises(ValueError):
            gui["write_csv"](output, [])
        with self.assertRaises(ValueError):
            gui["write_graph"](output, rows)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(image.read_bytes(), b"protected image")
        image.unlink()
        self.assertEqual(gui["compare_lengths"]([sample], 50, 10), rows)

    def test_invalid_conditions_and_csv_are_rejected(self):
        path = self.directory / "最小入力.csv"

        def write_rows(rows):
            with path.open("w", encoding="utf-8-sig", newline="") as output:
                writer = csv.writer(output)
                writer.writerow(("image_path", "left_mm", "right_mm"))
                writer.writerows(rows)

        write_rows([("image.png", 100, 110)])
        sample = {"csv_path": path, "thickness_mm": 10}
        self.assertEqual(
            self.gui["compare_lengths"]([sample], 100, 10)[0]["right_mm"], 110
        )
        for bad in ("", "text", 0, -1, float("nan"), float("inf")):
            for initial_length, initial_thickness in ((bad, 10), (100, bad)):
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    self.gui["compare_lengths"](
                        [sample], initial_length, initial_thickness
                    )
            with self.subTest(thickness=bad), self.assertRaises(ValueError):
                self.gui["compare_lengths"]([dict(sample, thickness_mm=bad)], 100, 10)
        for samples in ([], [sample, sample]):
            with self.assertRaises(ValueError):
                self.gui["compare_lengths"](samples, 100, 10)
        with self.assertRaises(ValueError):
            self.gui["compare_lengths"]([dict(sample, thickness_mm=5e-324)], 100, 10)
        for rows in (
            [],
            [("image.png", 100, 110), ("image.png", 100, 110)],
            [("", 100, 110)],
            [("image.png", "nan", 110)],
            [("image.png", 100, -1)],
            [("image.png", 100)],
        ):
            write_rows(rows)
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.gui["read_lengths"](path)
        path.write_text("wrong_header\n100\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "長さCSV"):
            self.gui["read_lengths"](path)


if __name__ == "__main__":
    unittest.main()
