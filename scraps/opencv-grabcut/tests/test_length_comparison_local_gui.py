"""既存CSVの区間長・100mm換算、保存と入力保護を確認する。"""

import csv
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2 as cv
import numpy as np

PROJECT = Path(__file__).resolve().parents[1]


def sample_csv(directory, name, interval=100, left=104, right=102, scale=0.25):
    path = directory / f"{name}.csv"
    row = {
        "image_path": f"{name}.png",
        "image_width": 300,
        "image_height": int(interval / scale) + 40,
        "mm_per_px": scale,
        "start_y": 20,
        "end_y": 20 + int(interval / scale),
        "left_px": left / scale,
        "left_mm": left,
        "right_px": right / scale,
        "right_mm": right,
        "total_px": (left + right) / scale,
        "total_mm": left + right,
    }
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    return path


class LocalComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.script = PROJECT / "submissions/03_compare_edge_lengths_gui.py"
        self.gui = runpy.run_path(str(self.script))

    def test_different_intervals_have_the_same_normalized_lengths(self):
        paths = [
            sample_csv(self.directory, "p01_a"),
            sample_csv(self.directory, "p01_b", 200, 208, 204, scale=0.5),
        ]
        rows = self.gui["compare_lengths"](paths)
        self.assertEqual([row["interval_length_mm"] for row in rows], [100, 200])
        self.assertEqual([row["left_per_100mm"] for row in rows], [104, 104])
        self.assertEqual([row["right_per_100mm"] for row in rows], [102, 102])
        for normalized, expected in ((False, [104, 208]), (True, [104, 104])):
            figure = self.gui["create_graph"](rows, normalized)
            axis = figure.axes[0]
            np.testing.assert_allclose(axis.lines[0].get_ydata(), expected)
            self.assertEqual(len(axis.lines), 3)
            reference = axis.lines[2]
            expected_reference = [100, 100] if normalized else [100, 200]
            np.testing.assert_allclose(reference.get_ydata(), expected_reference)
            self.assertEqual(reference.get_linestyle(), "--")
            self.assertEqual(reference.get_label(), "基準（直線の目安）")
            self.assertEqual(
                [label.get_text() for label in axis.get_xticklabels()],
                ["p01_a", "p01_b"],
            )
            self.assertNotIn("パス", axis.get_xlabel())

    def test_standalone_copy_save_and_missing_images(self):
        copied = self.directory / self.script.name
        copied.write_bytes(self.script.read_bytes())
        gui = runpy.run_path(str(copied))
        path = sample_csv(self.directory, "入力 日本語")
        before = path.read_bytes()
        rows = gui["compare_lengths"]([path])
        self.assertEqual(rows[0]["image_path"], str(path.with_suffix(".png")))
        for normalized in (False, True):
            graph = self.directory / f"output/比較_{normalized}.png"
            gui["write_graph"](graph, rows, normalized)
            self.assertEqual(graph.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        with self.assertRaises(ValueError):
            gui["write_graph"](path, rows)
        with self.assertRaises(ValueError):
            gui["write_graph"](path.with_suffix(".png"), rows)
        with self.assertRaises(ValueError):
            gui["write_graph"](self.directory / "output/空.png", [])
        self.assertEqual(path.read_bytes(), before)

    def test_single_twenty_and_repeated_csv_keep_observation_order(self):
        paths = []
        for index in range(20):
            paths.append(sample_csv(self.directory, f"p{index // 2:02}_{index % 2}"))
        rows = self.gui["compare_lengths"](list(reversed(paths)))
        self.assertEqual([row["order"] for row in rows], list(range(1, 21)))
        self.assertEqual(rows[0]["csv_name"], paths[-1].name)
        single = self.gui["create_graph"](rows[:1])
        self.assertEqual(len(single.axes[0].lines[0].get_ydata()), 1)
        for invalid in ([], paths + [paths[0]]):
            with self.assertRaises(ValueError):
                self.gui["compare_lengths"](invalid)

    def test_invalid_values_and_incomplete_csv_are_rejected(self):
        path = sample_csv(self.directory, "入力")
        with path.open(encoding="utf-8-sig", newline="") as source:
            original = list(csv.DictReader(source))[0]
        for column, value in (
            ("image_path", ""),
            ("mm_per_px", "nan"),
            ("mm_per_px", "0"),
            ("start_y", "-1"),
            ("end_y", "20"),
            ("end_y", "21.5"),
            ("left_mm", "99"),
            ("right_mm", "inf"),
            ("left_mm", ""),
        ):
            bad = dict(original, **{column: value})
            with path.open("w", encoding="utf-8-sig", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=list(bad))
                writer.writeheader()
                writer.writerow(bad)
            with (
                self.subTest(column=column, value=value),
                self.assertRaises(ValueError),
            ):
                self.gui["read_lengths"](path)
        for text in (
            "left_mm,right_mm\n104,102\n",
            "image_path\n",
            "image_path\na\nb\n",
        ):
            path.write_text(text, encoding="utf-8")
            with self.assertRaises(ValueError):
                self.gui["read_lengths"](path)

    def test_measurement_pair_keeps_csv_schema_and_protects_source_image(self):
        measurement_gui = runpy.run_path(
            str(PROJECT / "submissions/02_measure_edge_lengths_gui.py")
        )
        image = np.full((160, 140, 3), 35, np.uint8)
        image[20:141, 50:91] = 200
        regions = {
            cv.GC_PR_FGD: [(0.3, 0, 0.7, 1)],
            cv.GC_BGD: [(0, 0, 0.3, 1), (0.7, 0, 1, 1)],
            cv.GC_FGD: [(0.48, 0.4, 0.56, 0.6)],
        }
        measurement, overlay = measurement_gui["measure_lengths"](
            image, regions, 20, 140
        )
        source = self.directory / "入力.png"
        source.write_bytes(b"protected input")
        output = self.directory / "output/p01_a.csv"
        png = measurement_gui["write_measurement"](output, source, measurement, overlay)
        self.assertEqual(png, output.with_suffix(".png"))
        decoded = cv.imdecode(
            np.frombuffer(png.read_bytes(), np.uint8), cv.IMREAD_COLOR
        )
        np.testing.assert_array_equal(decoded, overlay)
        self.assertEqual(self.gui["read_lengths"](output)["interval_length_mm"], 30)
        old_csv = self.directory / "旧保存.csv"
        measurement_gui["write_csv"](old_csv, source, measurement)
        self.assertEqual(output.read_bytes(), old_csv.read_bytes())
        with self.assertRaises(ValueError):
            measurement_gui["write_measurement"](
                source.with_suffix(".csv"), source, measurement, overlay
            )
        self.assertFalse(source.with_suffix(".csv").exists())
        before = output.read_bytes()
        with patch.object(cv, "imencode", return_value=(False, None)):
            with self.assertRaises(OSError):
                measurement_gui["write_measurement"](
                    output, source, measurement, overlay
                )
        self.assertEqual(output.read_bytes(), before)
        self.assertEqual(source.read_bytes(), b"protected input")


if __name__ == "__main__":
    unittest.main()
