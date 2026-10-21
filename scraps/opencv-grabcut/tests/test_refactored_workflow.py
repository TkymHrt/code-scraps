"""共通化した版と提出版の出力一致・入力保護・フォルダ移動を確認する。"""

import contextlib
import csv
import io
import os
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from tkinter import filedialog
from unittest.mock import Mock, patch

import cv2 as cv
import numpy as np
from fisheye_scene import calibration_photos, configure, rendered_scene
from test_current_workflow import copy_current
from test_length_comparison_local_gui import sample_csv

PROJECT = Path(__file__).resolve().parents[1]
REFACTORED = PROJECT / "src"
COMMON_MODULES = (
    "workflow_settings",
    "utils",
    "utils.file_io",
    "utils.measurement_csv",
    "utils.length_comparison",
    "utils.gui_parts",
)
ORIGINAL_RUN_PATH = runpy.run_path


def copy_refactored(filename, directory, **settings):
    shutil.copyfile(
        REFACTORED / "workflow_settings.py", directory / "workflow_settings.py"
    )
    shutil.copytree(REFACTORED / "utils", directory / "utils", dirs_exist_ok=True)
    path_names = {
        "00_2_calibrate_camera.py": {
            "INPUT_DIRECTORY": "CALIBRATION_DIRECTORY",
            "OUTPUT_DIRECTORY": "DETECTION_DIRECTORY",
        },
        "01_rectify_images.py": {
            "INPUT_DIRECTORY": "INPUT_DIRECTORY",
            "OUTPUT_DIRECTORY": "RECTIFIED_DIRECTORY",
        },
    }
    values = {}
    overrides = []
    for name, value in settings.items():
        if name in path_names.get(filename, {}):
            target = path_names[filename][name]
            path = (directory / value).resolve()
            overrides.append(f"{target} = Path({str(path)!r})\n")
        elif name == "RECTIFY_ROI":
            overrides.append(f"RECTIFY_ROI = {value!r}\n")
        else:
            values[name] = value
    script = copy_current(filename, directory, source_directory="src", **values)
    if overrides:
        source = script.read_text(encoding="utf-8")
        marker = 'if __name__ == "__main__":'
        source = source.replace(marker, "".join(overrides) + "\n" + marker)
        script.write_text(source, encoding="utf-8")
    return script


def run_refactored(path, **options):
    # コピー先の設定を読むため、自作モジュールだけを一時的に読み直す。
    cached = {}
    for name in COMMON_MODULES:
        if name in sys.modules:
            cached[name] = sys.modules.pop(name)
    try:
        folder = Path(path).parent
        if folder.name == "utils":
            folder = folder.parent
        with patch.object(sys, "path", [str(folder), *sys.path]):
            return ORIGINAL_RUN_PATH(str(path), **options)
    finally:
        for name in COMMON_MODULES:
            sys.modules.pop(name, None)
        sys.modules.update(cached)


def load_refactored(filename):
    path = REFACTORED / filename
    if not path.is_file():
        path = REFACTORED / "utils" / filename
    return run_refactored(path)


class RefactoredWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def test_shared_directories_follow_settings_in_a_copied_folder(self):
        for source in sorted(REFACTORED.glob("[0-9]*.py")):
            copy_refactored(source.name, self.directory)
        settings_path = self.directory / "workflow_settings.py"
        source = settings_path.read_text(encoding="utf-8")
        source = source.replace(
            'BASE_DIRECTORY / "input"', 'BASE_DIRECTORY / "入力写真"'
        )
        source = source.replace(
            'BASE_DIRECTORY / "output"', 'BASE_DIRECTORY / "別の出力"'
        )
        settings_path.write_text(source, encoding="utf-8")
        code = """
import runpy
import sys
from pathlib import Path
folder = Path(sys.argv[1])
sys.path.insert(0, str(folder))
board = runpy.run_path(str(folder / '00_1_generate_charuco_board.py'), run_name='__main__')
camera = runpy.run_path(str(folder / '00_2_calibrate_camera.py'))
rectifier = runpy.run_path(str(folder / '01_rectify_images.py'))
measurement = runpy.run_path(str(folder / '02_measure_edge_lengths_gui.py'))
assert camera['CALIBRATION_DIRECTORY'] == folder / '入力写真/camera_calibration'
assert camera['DETECTION_DIRECTORY'] == folder / '別の出力/camera_detection'
assert rectifier['INPUT_DIRECTORY'] == folder / '入力写真'
assert rectifier['RECTIFIED_DIRECTORY'] == measurement['RECTIFIED_DIRECTORY']
assert measurement['RECTIFIED_DIRECTORY'] == folder / '別の出力/rectified'
for name in ('03_compare_edge_lengths_gui.py', '03_compare_edge_lengths_with_thickness_gui.py'):
    gui = runpy.run_path(str(folder / name))
    assert gui['OUTPUT_DIRECTORY'] == measurement['OUTPUT_DIRECTORY']
"""
        result = subprocess.run(
            [sys.executable, "-c", code, str(self.directory)],
            cwd=PROJECT,
            capture_output=True,
            env=dict(os.environ, PYTHONIOENCODING="utf-8"),
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertTrue((self.directory / "別の出力/charuco_board.png").is_file())
        self.assertFalse((self.directory / "output").exists())

    def test_shared_file_selection_keeps_order_and_rejects_a_whole_bad_batch(self):
        common = load_refactored("gui_parts.py")
        existing = sample_csv(self.directory, "existing").resolve()
        second = sample_csv(self.directory, "second").resolve()
        third = sample_csv(self.directory, "third").resolve()
        paths = [existing]
        root = Mock()
        with patch.object(
            filedialog,
            "askopenfilenames",
            return_value=(str(third), str(existing), str(second), str(third)),
        ):
            added = common["choose_csv_paths"](root, self.directory, paths)
        self.assertEqual(added, [third, second])
        self.assertEqual(paths, [existing])
        bad = self.directory / "bad.csv"
        bad.write_text("invalid csv", encoding="utf-8")
        with patch.object(
            filedialog, "askopenfilenames", return_value=(str(second), str(bad))
        ):
            with self.assertRaises(ValueError):
                common["choose_csv_paths"](root, self.directory, paths)
        self.assertEqual(paths, [existing])
        with patch.object(filedialog, "askopenfilenames", return_value=()):
            self.assertEqual(
                common["choose_csv_paths"](root, self.directory, paths), []
            )
        with patch.object(filedialog, "asksaveasfilename", return_value=""):
            self.assertIsNone(
                common["choose_png_path"](root, self.directory, "graph.png")
            )

    def test_board_is_identical_and_copied_folder_uses_shared_settings(self):
        old = copy_current("00_1_generate_charuco_board.py", self.directory)
        with contextlib.redirect_stdout(io.StringIO()):
            runpy.run_path(str(old), run_name="__main__")
        folder = self.directory / "日本語 空白"
        folder.mkdir()
        script = copy_refactored(old.name, folder)
        run_refactored(script)
        self.assertFalse((folder / "output").exists())
        environment = dict(os.environ, PYTHONIOENCODING="utf-8")
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=self.directory,
            capture_output=True,
            env=environment,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(
            (folder / "output/charuco_board.png").read_bytes(),
            (self.directory / "output/charuco_board.png").read_bytes(),
        )
        copy_current(
            "workflow_settings.py",
            folder,
            source_directory="src",
            BOARD_SQUARES=(5, 4),
            MM_PER_PX=0.5,
        )
        for name in ("01_rectify_images.py", "02_measure_edge_lengths_gui.py"):
            shutil.copyfile(REFACTORED / name, folder / name)
        # 別プロセスで読み、既にimportした設定のキャッシュを使わない。
        code = """
import runpy
import sys
from pathlib import Path
folder = Path(sys.argv[1])
sys.path.insert(0, str(folder))
runpy.run_path(str(folder / '00_1_generate_charuco_board.py'), run_name='__main__')
for name in ('01_rectify_images.py', '02_measure_edge_lengths_gui.py'):
    module = runpy.run_path(str(folder / name))
    assert module['MM_PER_PX'] == 0.5
"""
        result = subprocess.run(
            [sys.executable, "-c", code, str(folder)],
            cwd=self.directory,
            capture_output=True,
            env=environment,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        image_files = load_refactored("file_io.py")
        image = image_files["read_image"](folder / "output/charuco_board.png")
        self.assertEqual(image.shape[:2], (1400, 1700))

    def test_image_files_handle_formats_unicode_and_failed_encoding(self):
        images = load_refactored("file_io.py")
        image = np.full((16, 20, 3), 80, np.uint8)
        for name in ("画像.png", "A.PNG", "b.jpg"):
            success, encoded = cv.imencode(Path(name).suffix, image)
            self.assertTrue(success)
            (self.directory / name).write_bytes(encoded.tobytes())
        (self.directory / "nested.png").mkdir()
        (self.directory / "memo.txt").write_text("skip", encoding="utf-8")
        paths = images["find_images"](self.directory)
        self.assertEqual([path.name for path in paths], ["A.PNG", "b.jpg", "画像.png"])
        with self.assertRaisesRegex(ValueError, "入力フォルダがありません"):
            images["find_images"](self.directory / "missing")
        empty_directory = self.directory / "empty"
        empty_directory.mkdir()
        with self.assertRaisesRegex(ValueError, "画像がありません"):
            images["find_images"](empty_directory)
        np.testing.assert_array_equal(images["read_image"](paths[0]), image)
        path = self.directory / "出力/画像.png"
        images["write_png"](path, image)
        before = path.read_bytes()
        with patch.object(cv, "imencode", return_value=(False, None)):
            with self.assertRaises(OSError):
                images["write_png"](path, image)
        self.assertEqual(path.read_bytes(), before)
        with self.assertRaises(ValueError):
            images["write_png"](self.directory / "wrong.jpg", image)
        for name, data in (("bad.png", b"not an image"), ("empty.png", b"")):
            bad = self.directory / name
            bad.write_bytes(data)
            with self.assertRaisesRegex(ValueError, f"画像を読み込めません: {name}"):
                images["read_image"](bad)
        with patch.object(cv, "imencode", side_effect=cv.error("encoder failed")):
            with self.assertRaisesRegex(OSError, "PNGを作成できません"):
                images["encode_png"](image)

    def test_calibration_values_and_detection_images_are_identical(self):
        old = runpy.run_path(str(PROJECT / "submissions/00_2_calibrate_camera.py"))
        new = load_refactored("00_2_calibrate_camera.py")
        paths = calibration_photos(self.directory)
        with contextlib.redirect_stdout(io.StringIO()):
            before = old["calibrate"](paths, self.directory / "old")
            after = new["calibrate"](paths, self.directory / "new")
        self.assertEqual(before[0], after[0])
        for old_value, new_value in zip(before[1:], after[1:]):
            np.testing.assert_array_equal(old_value, new_value)
        self.assertEqual(
            old["parameter_text"](*before[:3]), new["parameter_text"](*after[:3])
        )
        for path in paths:
            name = f"{path.name}_detected.png"
            self.assertEqual(
                (self.directory / "old" / name).read_bytes(),
                (self.directory / "new" / name).read_bytes(),
            )
        # 枚数は運用で決める。1枚でも枚数判定で止めず、校正計算へ渡す。
        with (
            contextlib.redirect_stdout(io.StringIO()),
            patch.object(
                cv.fisheye, "calibrate", side_effect=cv.error("cannot calibrate")
            ) as calibration,
            self.assertRaisesRegex(ValueError, "カメラ校正に失敗しました"),
        ):
            new["calibrate"](paths[:1], self.directory / "single")
        calibration.assert_called_once()
        self.assertTrue(
            (self.directory / "single" / f"{paths[0].name}_detected.png").exists()
        )
        output = io.StringIO()
        with (
            contextlib.redirect_stdout(output),
            patch.object(
                cv.fisheye,
                "calibrate",
                side_effect=cv.error("Ill-conditioned matrix for input array 0"),
            ) as calibration,
            self.assertRaisesRegex(ValueError, "校正に使える写真がありません"),
        ):
            new["calibrate"](paths[:1], self.directory / "condition")
        calibration.assert_called_once()
        self.assertIn(f"スキップ 1: {paths[0].name}", output.getvalue())
        self.assertIn("確認画像:", output.getvalue())

    def test_rectification_keeps_pixels_scale_orientation_and_batch_guards(self):
        old = runpy.run_path(str(PROJECT / "submissions/01_rectify_images.py"))
        new = load_refactored("01_rectify_images.py")
        for rectifier in (old, new):
            configure(rectifier)
        # 全体出力を指定した場合は、提出版と同じ座標・画素を保つ。
        new["rectify_image"].__globals__["RECTIFY_ROI"] = (0, 0, 1, 1)
        image = rendered_scene((0.12, -0.22, 0.03), (-170, -65, 400))
        for partial in (False, True):
            photo = rendered_scene((0.12, -0.22, 0.03), (-170, -65, 400), partial)
            before = old["rectify_image"](photo)
            after = new["rectify_image"](photo)
            np.testing.assert_array_equal(before.pop("image"), after.pop("image"))
            self.assertEqual(before, after)
        inputs = self.directory / "input"
        inputs.mkdir()
        images = load_refactored("file_io.py")
        images["write_png"](inputs / "撮影.png", image)
        settings = new["main"].__globals__
        settings["INPUT_DIRECTORY"] = str(inputs)
        settings["RECTIFIED_DIRECTORY"] = str(self.directory / "output")
        with contextlib.redirect_stdout(io.StringIO()):
            new["main"]()
        expected = new["rectify_image"](image)["image"]
        actual = images["read_image"](self.directory / "output/撮影.png")
        np.testing.assert_array_equal(actual, expected)
        (inputs / "撮影.jpg").write_bytes(b"collision")
        with self.assertRaisesRegex(ValueError, "出力名が重複"):
            new["main"]()
        settings["RECTIFIED_DIRECTORY"] = str(inputs)
        with self.assertRaisesRegex(ValueError, "別のフォルダ"):
            new["main"]()
        configure(new, distortion=np.zeros(5))
        with self.assertRaisesRegex(ValueError, "歪み係数4個"):
            new["rectify_image"](image)

    def test_measurement_csv_and_overlay_are_identical_and_protect_input(self):
        old = runpy.run_path(
            str(PROJECT / "submissions/02_measure_edge_lengths_gui.py")
        )
        new = load_refactored("02_measure_edge_lengths_gui.py")
        image = np.full((160, 140, 3), 35, np.uint8)
        image[20:141, 50:91] = 200
        regions = {
            cv.GC_PR_FGD: [(0.3, 0, 0.7, 1)],
            cv.GC_BGD: [(0, 0, 0.3, 1), (0.7, 0, 1, 1)],
            cv.GC_FGD: [(0.48, 0.4, 0.56, 0.6)],
        }
        source = self.directory / "入力.png"
        source.write_bytes(b"protected image")
        for notch in (False, True):
            if notch:
                image[60:71, 50:61] = 35
            before, before_overlay = old["measure_lengths"](image, regions, 20, 140)
            after, after_overlay = new["measure_lengths"](image, regions, 20, 140)
            before_initial = old["initial_overlay"](image, regions)
            after_initial = new["initial_overlay"](image, regions)
            self.assertEqual(before, after)
            # 追加した隅のDR・OP表示以外は、側辺と初期指定の画素を保つ。
            new["draw_edge_names"](before_overlay)
            new["draw_edge_names"](before_initial)
            np.testing.assert_array_equal(before_overlay, after_overlay)
            np.testing.assert_array_equal(before_initial, after_initial)
            old_path = self.directory / "old/lengths.csv"
            new_path = self.directory / "new/lengths.csv"
            old["write_measurement"](
                old_path, source, before, before_initial, before_overlay
            )
            new["write_measurement"](
                new_path, source, after, after_initial, after_overlay
            )
            self.assertEqual(old_path.read_bytes(), new_path.read_bytes())
            self.assertEqual(
                old_path.with_suffix(".png").read_bytes(),
                new_path.with_suffix(".png").read_bytes(),
            )
            self.assertEqual(
                (old_path.parent / "lengths_initial.png").read_bytes(),
                (new_path.parent / "lengths_initial.png").read_bytes(),
            )
        for gui, path in ((old, old_path), (new, new_path)):
            for protected in (
                source.with_suffix(".csv"),
                source,
                self.directory / "入力_initial.png",
            ):
                protected.write_bytes(b"protected image")
                with self.assertRaises(ValueError):
                    gui["write_measurement"](
                        source.with_suffix(".csv"),
                        protected,
                        after,
                        after_initial,
                        after_overlay,
                    )
                self.assertEqual(protected.read_bytes(), b"protected image")
            saved_paths = (
                path,
                path.with_suffix(".png"),
                path.parent / "lengths_initial.png",
            )
            saved_bytes = [output.read_bytes() for output in saved_paths]
            _, encoded = cv.imencode(".png", after_initial)
            # 1枚目と2枚目の、どちらのPNG変換で失敗しても既存の3ファイルを保つ。
            for results in ([(False, None)], [(True, encoded), (False, None)]):
                with patch.object(cv, "imencode", side_effect=results):
                    with self.assertRaises(OSError):
                        gui["write_measurement"](
                            path, source, after, after_initial, after_overlay
                        )
                self.assertEqual(
                    [output.read_bytes() for output in saved_paths], saved_bytes
                )
        self.assertEqual(source.read_bytes(), b"protected image")

    def test_both_comparisons_and_all_six_graph_modes_are_identical(self):
        paths = [
            sample_csv(self.directory, "p00", 100, 104, 102),
            sample_csv(self.directory, "p01", 200, 208, 204),
            sample_csv(self.directory, "p02", 100, 108, 106),
        ]
        samples = []
        for path, thickness in zip(paths, (10, 8, 8)):
            samples.append({"csv_path": path, "thickness_mm": thickness})
        for filename in (
            "03_compare_edge_lengths_gui.py",
            "03_compare_edge_lengths_with_thickness_gui.py",
        ):
            old = runpy.run_path(str(PROJECT / "submissions" / filename))
            new = load_refactored(filename)
            with_thickness = "with_thickness" in filename
            options = {}
            if with_thickness:
                before = old["compare_lengths"](samples, 10)
                after = new["compare_lengths_with_thickness"](samples, 10)
                options["initial_thickness_mm"] = 10
            else:
                before = old["compare_lengths"](paths)
                after = new["read_measurements"](paths)
            self.assertEqual(before, after)
            for normalized in (False, True):
                for reduction_axis in (False, True) if with_thickness else (False,):
                    arguments = [normalized]
                    if with_thickness:
                        arguments.append(reduction_axis)
                    old_path = self.directory / "old.png"
                    new_path = self.directory / "new.png"
                    old["write_graph"](old_path, before, *arguments)
                    new["write_graph"](new_path, after, *arguments, **options)
                    with self.subTest(filename=filename, modes=arguments):
                        expected = old["create_graph"](before, *arguments)
                        actual = new["create_graph"](after, *arguments, **options)
                        for previous_line, line in zip(
                            expected.axes[0].lines, actual.axes[0].lines
                        ):
                            np.testing.assert_array_equal(
                                previous_line.get_xydata(), line.get_xydata()
                            )
                        self.assertEqual(
                            [line.get_label() for line in actual.axes[0].lines[:2]],
                            ["DR側辺", "OP側辺"],
                        )
                        saved = cv.imdecode(
                            np.frombuffer(new_path.read_bytes(), np.uint8),
                            cv.IMREAD_COLOR,
                        )
                        assert saved is not None
                        self.assertEqual(saved.shape, (800, 1440, 3))

    def test_invalid_csv_and_graph_destinations_are_rejected(self):
        common = load_refactored("length_comparison.py")
        path = sample_csv(self.directory, "sample")
        rows = common["read_measurements"]([path])
        source_image = Path(rows[0]["image_path"])
        source_image.write_bytes(b"protected image")
        for destination in (path, source_image, self.directory / "bad.jpg"):
            with self.assertRaises(ValueError):
                common["write_graph"](destination, rows)
        self.assertEqual(source_image.read_bytes(), b"protected image")
        for paths in ([], [path, path]):
            with self.assertRaises(ValueError):
                common["read_measurements"](paths)
        with path.open(encoding="utf-8-sig", newline="") as source:
            original = list(csv.DictReader(source))[0]
        for column, value in (
            ("image_path", ""),
            ("mm_per_px", "nan"),
            ("start_y", "-1"),
            ("end_y", "20.5"),
            ("left_mm", "99"),
            ("right_mm", "inf"),
        ):
            bad = dict(original, **{column: value})
            with path.open("w", encoding="utf-8-sig", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=list(bad))
                writer.writeheader()
                writer.writerow(bad)
            with self.subTest(column=column), self.assertRaises(ValueError):
                common["read_lengths"](path)
        path = sample_csv(self.directory, "valid")
        thickness = load_refactored("03_compare_edge_lengths_with_thickness_gui.py")
        for value in (None, "", "abc", 0, -1, "nan", "inf"):
            with self.subTest(thickness=value), self.assertRaises(ValueError):
                thickness["compare_lengths_with_thickness"](
                    [{"csv_path": path, "thickness_mm": value}], 10
                )


if __name__ == "__main__":
    unittest.main()
