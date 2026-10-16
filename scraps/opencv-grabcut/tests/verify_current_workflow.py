"""現行の単発CLIと実際のTkを使い、生成画像から複数長さCSVを比較する."""

import argparse
import ast
import csv
import hashlib
import json
import os
import runpy
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from unittest.mock import patch

import cv2 as cv
import numpy as np
from fisheye_scene import calibration_photos, distort, rendered_scene, specimen_size
from test_current_workflow import copy_current
from verify_adjacent_board import save_image
from verify_parameter_guis import capture, descendants


def execute(filename, directory, **settings):
    script = copy_current(filename, directory, **settings)
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=directory,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
    )
    # Windowsの標準出力も日本語を保存できるよう、親プロセスでUTF-8を指定する。
    (directory / f"{script.stem}.log").write_text(
        completed.stdout + completed.stderr, encoding="utf-8"
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr)
    return completed.stdout


def field(root, widgets, label):
    caption = next(
        w for w in widgets if isinstance(w, ttk.Label) and str(w.cget("text")) == label
    )
    siblings = caption.master.winfo_children()
    return siblings[siblings.index(caption) + 1]


def set_field(root, widget, value):
    root.setvar(str(widget.cget("textvariable")), str(value))
    root.update()


def measure_with_gui(directory, image_path, transform, original_size, screenshots):
    script = copy_current("02_measure_edge_lengths_gui.py", directory)
    gui = runpy.run_path(str(script))
    root = tk.Tk()
    root.attributes("-alpha", 0)
    errors = []
    csv_path = directory / f"output/{directory.name}_lengths.csv"
    image_bytes = image_path.read_bytes()

    def exercise():
        root.update()
        widgets = descendants(root)
        buttons = {str(w.cget("text")): w for w in widgets if isinstance(w, ttk.Button)}
        canvas = next(w for w in widgets if isinstance(w, tk.Canvas))
        radios = {
            str(w.cget("text")): w for w in widgets if isinstance(w, ttk.Radiobutton)
        }
        status_label = root.winfo_children()[0].winfo_children()[-1]

        def status():
            return str(root.getvar(str(status_label.cget("textvariable"))))

        def invoke(name):
            buttons[name].invoke()
            root.update()

        invoke("長さを計測")
        assert "読み込んで" in status()
        with patch.object(filedialog, "askopenfilename", return_value=str(image_path)):
            invoke("補正画像を読み込む")
        start = field(root, widgets, "開始y")
        end = field(root, widgets, "終了y")
        image = cv.imdecode(np.frombuffer(image_bytes, np.uint8), cv.IMREAD_COLOR)
        assert image is not None
        height, width = image.shape[:2]
        original_width, original_height = original_size
        interval = np.array(
            [[original_width / 2, 80], [original_width / 2, 1000]], dtype=np.float32
        )
        interval = cv.perspectiveTransform(interval.reshape(-1, 1, 2), transform)
        set_field(root, start, round(float(interval[0, 0, 1])))
        set_field(root, end, round(float(interval[1, 0, 1])))

        def draw(kind, left, top, right, bottom):
            radios[kind].invoke()
            root.update()
            image_item = canvas.find_withtag("all")[0]
            x0, y0, x1, y1 = canvas.bbox(image_item)
            # Tkの画像bboxは画素端までを含む。実際の表示サイズから座標を作る。
            display_width = x1 - x0
            display_height = y1 - y0
            x_start = round(x0 + left * display_width)
            y_start = round(y0 + top * display_height)
            x_end = round(x0 + right * display_width)
            y_end = round(y0 + bottom * display_height)
            canvas.event_generate("<ButtonPress-1>", x=x_start, y=y_start)
            canvas.event_generate("<B1-Motion>", x=x_end, y=y_end)
            canvas.event_generate("<ButtonRelease-1>", x=x_end, y=y_end)
            root.update()

        def bounds(left, top, right, bottom):
            points = np.array(
                [[left, top], [right, top], [right, bottom], [left, bottom]],
                dtype=np.float32,
            )
            points = cv.perspectiveTransform(points.reshape(-1, 1, 2), transform)
            normalized = points.reshape(-1, 2) / [width, height]
            minimum = np.clip(normalized.min(axis=0), 0, 1)
            maximum = np.clip(normalized.max(axis=0), 0, 1)
            return minimum[0], minimum[1], maximum[0], maximum[1]

        candidate = bounds(
            0.3052208835 * original_width,
            0,
            0.697456493 * original_width,
            original_height,
        )
        draw("前景候補（橙）", *candidate)
        draw("確実な背景（青）", 0, 0, max(0, candidate[0] - 0.005), 1)
        draw("確実な背景（青）", min(1, candidate[2] + 0.005), 0, 1, 1)
        foreground = bounds(
            0.400267738 * original_width,
            80,
            0.60107095 * original_width,
            1000,
        )
        draw("確実な前景（緑）", *foreground)

        interval_start = int(root.getvar(str(start.cget("textvariable"))))
        interval_end = int(root.getvar(str(end.cget("textvariable"))))

        def preview_lines():
            return [
                canvas.coords(item)
                for item in canvas.find_withtag("interval")
                if canvas.type(item) == "line"
            ]

        # 縮小表示と余白があっても、入力した画像内の位置へ横線が移動する。
        set_field(root, start, height // 4)
        set_field(root, end, height * 3 // 4)
        image_item = canvas.find_all()[0]
        x0, y0, x1, y1 = canvas.bbox(image_item)
        lines = preview_lines()
        assert len(lines) == 2
        for line, fraction in zip(lines, (0.25, 0.75)):
            assert line[0] == x0 and line[2] == x1
            assert abs(line[1] - (y0 + (y1 - y0) * fraction)) <= 1
        set_field(root, start, height // 2)
        moved_lines = preview_lines()
        assert moved_lines[0][1] > lines[0][1]
        assert moved_lines[1] == lines[1]
        assert any(
            canvas.itemcget(item, "text") == f"開始 y={height // 2}"
            for item in canvas.find_withtag("interval")
            if canvas.type(item) == "text"
        )
        for invalid in ("", "整数ではない値", -1, height):
            set_field(root, start, invalid)
            assert len(preview_lines()) == 1
            assert preview_lines()[0] == lines[1]
        set_field(root, start, interval_start)
        set_field(root, end, interval_end)
        interval_labels = []
        for widget in widgets:
            if isinstance(widget, ttk.Label) and widget.cget("textvariable"):
                value = str(root.getvar(str(widget.cget("textvariable"))))
                if value.startswith("区間長："):
                    interval_labels.append(widget)
        assert len(interval_labels) == 1
        interval_variable = str(interval_labels[0].cget("textvariable"))
        expected_interval = (interval_end - interval_start) * gui["MM_PER_PX"]
        assert root.getvar(interval_variable) == f"区間長：{expected_interval:.3f} mm"
        radios["元画像"].invoke()
        root.update()
        assert len(preview_lines()) == 2
        if screenshots:
            capture(root, directory / "interval_preview_gui.png")
        radios["初期指定"].invoke()
        initial_path = directory / "output/initial.png"
        with patch.object(
            filedialog, "asksaveasfilename", return_value=str(initial_path)
        ):
            invoke("確認画像を保存")
        initial_image = cv.imdecode(
            np.frombuffer(initial_path.read_bytes(), np.uint8), cv.IMREAD_COLOR
        )
        assert initial_image is not None
        center_x = int(width * (foreground[0] + foreground[2]) / 2)
        center_y = int(height * (foreground[1] + foreground[3]) / 2)
        source_pixel = image[center_y : center_y + 1, center_x : center_x + 1]
        green = np.full_like(source_pixel, (0, 255, 0))
        expected_pixel = cv.addWeighted(source_pixel, 0.65, green, 0.35, 0)
        np.testing.assert_array_equal(
            initial_image[center_y : center_y + 1, center_x : center_x + 1],
            expected_pixel,
        )
        invoke("長さを計測")
        assert status() == "計測完了", status()
        assert buttons["CSV・確認PNGを保存"].instate(["!disabled"])
        root.geometry("1000x760")
        root.update()
        for button in list(buttons.values()) + list(radios.values()):
            assert button.winfo_ismapped()
            assert button.winfo_height() >= button.winfo_reqheight(), button.cget(
                "text"
            )
            assert (
                button.winfo_rooty() + button.winfo_height()
                <= root.winfo_rooty() + root.winfo_height()
            )
        assert not any(isinstance(w, tk.Toplevel) for w in widgets)
        result_table = next(w for w in widgets if isinstance(w, ttk.Treeview))
        assert len(preview_lines()) == 2
        assert result_table.set("left", "length") != "—"
        assert not any(
            isinstance(w, ttk.Label) and "固定倍率" in str(w.cget("text"))
            for w in widgets
        )
        if screenshots:
            capture(root, directory / "initial_regions_gui.png")
        for name, path in (
            ("CSV・確認PNGを保存", csv_path),
            ("確認画像を保存", directory / "output/measurement.png"),
        ):
            with patch.object(
                filedialog, "asksaveasfilename", return_value=str(path)
            ) as dialog:
                invoke(name)
            assert dialog.call_args.kwargs["initialdir"] == directory / "output"
            assert path.exists(), status()
        paired_png = csv_path.with_suffix(".png")
        assert paired_png.exists()
        paired_before = (csv_path.read_bytes(), paired_png.read_bytes())
        result_image = cv.imdecode(
            np.frombuffer(paired_before[1], np.uint8), cv.IMREAD_COLOR
        )
        for view_name, expected_image in (
            ("初期指定", initial_image),
            ("元画像", image),
            ("計測結果", result_image),
        ):
            radios[view_name].invoke()
            saved_path = directory / f"output/{view_name}.png"
            with patch.object(
                filedialog, "asksaveasfilename", return_value=str(saved_path)
            ):
                invoke("確認画像を保存")
            saved_image = cv.imdecode(
                np.frombuffer(saved_path.read_bytes(), np.uint8), cv.IMREAD_COLOR
            )
            np.testing.assert_array_equal(saved_image, expected_image)

        # 表示を初期指定へ戻しても、一括保存するPNGは計測結果にする。
        radios["初期指定"].invoke()
        csv_path.write_bytes(b"old CSV")
        paired_png.write_bytes(b"old PNG")
        with (
            patch.object(
                filedialog, "asksaveasfilename", return_value=str(csv_path)
            ) as dialog,
            patch.object(
                messagebox,
                "askyesno",
                side_effect=AssertionError("上書き確認は不要です"),
            ) as confirm,
        ):
            invoke("CSV・確認PNGを保存")
        assert dialog.call_args.kwargs["confirmoverwrite"] is False
        confirm.assert_not_called()
        assert (csv_path.read_bytes(), paired_png.read_bytes()) == paired_before
        assert status() == f"保存: {csv_path.name} / {paired_png.name}"
        with patch.object(
            filedialog, "asksaveasfilename", return_value=str(image_path)
        ):
            invoke("確認画像を保存")
        assert "別の保存先" in status()
        before = csv_path.read_bytes()
        set_field(root, start, -1)
        assert root.getvar(interval_variable) == "区間長：—"
        assert buttons["CSV・確認PNGを保存"].instate(["disabled"])
        assert result_table.set("left", "length") == "—"
        invoke("長さを計測")
        assert "計測区間" in status()
        assert csv_path.read_bytes() == before
        assert image_path.read_bytes() == image_bytes

        set_field(root, start, interval_start)
        invoke("長さを計測")
        assert buttons["CSV・確認PNGを保存"].instate(["!disabled"])
        region_list = next(w for w in widgets if isinstance(w, tk.Listbox))
        region_count = region_list.size()
        region_list.selection_set(0)
        invoke("選択した矩形を削除")
        assert region_list.size() == region_count - 1
        assert buttons["CSV・確認PNGを保存"].instate(["disabled"])
        assert result_table.set("left", "length") == "—"
        invoke("矩形をすべて削除")
        assert region_list.size() == 0
        with patch.object(filedialog, "askopenfilename", return_value=str(image_path)):
            invoke("補正画像を読み込む")
        assert root.getvar(str(start.cget("textvariable"))) == "0"
        assert root.getvar(str(end.cget("textvariable"))) == str(height - 1)
        assert len(preview_lines()) == 2
        assert buttons["CSV・確認PNGを保存"].instate(["disabled"])
        assert not errors, errors

    try:
        with (
            patch.object(tk, "Tk", return_value=root),
            patch.object(root, "mainloop", side_effect=exercise),
            patch.object(
                root,
                "report_callback_exception",
                side_effect=lambda kind, error, trace: errors.append(error),
            ),
        ):
            gui["main"]()
    finally:
        root.destroy()
    with csv_path.open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))[0]


def compare_with_gui(directory, csv_paths, screenshots):
    gui = runpy.run_path(str(copy_current("03_compare_edge_lengths_gui.py", directory)))
    read_measurements = gui.get("read_measurements", gui.get("compare_lengths"))
    expected_rows = read_measurements(csv_paths)
    source_bytes = [path.read_bytes() for path in csv_paths]
    root = tk.Tk()
    root.attributes("-alpha", 0)
    errors = []

    def exercise():
        root.update()
        widgets = descendants(root)
        buttons = {str(w.cget("text")): w for w in widgets if isinstance(w, ttk.Button)}
        radios = {
            str(w.cget("text")): w for w in widgets if isinstance(w, ttk.Radiobutton)
        }
        table = next(w for w in widgets if isinstance(w, ttk.Treeview))
        assert set(buttons) == {"CSVを追加", "選択したCSVを削除", "グラフを保存"}
        assert buttons["グラフを保存"].instate(["disabled"])

        def add(paths):
            with patch.object(
                filedialog,
                "askopenfilenames",
                return_value=tuple(str(path) for path in paths),
            ):
                buttons["CSVを追加"].invoke()
            root.update()

        add(csv_paths)
        assert len(table.get_children()) == 3
        for item, expected in zip(table.get_children(), expected_rows):
            values = table.item(item, "values")
            assert values == (
                expected["csv_name"],
                f"{expected['interval_length_mm']:.3f}",
                f"{expected['left_mm']:.3f}",
                f"{expected['right_mm']:.3f}",
            )
        assert buttons["グラフを保存"].instate(["!disabled"])
        add(csv_paths)
        add([])
        assert len(table.get_children()) == 3
        root.geometry("960x640")
        root.update()
        for button in buttons.values():
            assert button.winfo_height() >= button.winfo_reqheight()
        for label, stem in (
            ("実測長", "comparison"),
            ("100mm換算", "comparison_100mm"),
        ):
            radios[label].invoke()
            root.update()
            path = directory / f"output/{stem}.png"
            with patch.object(
                filedialog, "asksaveasfilename", return_value=str(path)
            ) as dialog:
                buttons["グラフを保存"].invoke()
            root.update()
            assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
            assert dialog.call_args.kwargs["initialdir"] == directory / "output"
            if screenshots:
                capture(root, directory / f"{stem}_gui.png")

        extra_paths = []
        for index in range(17):
            path = directory / f"output/extra{index + 1:02}.csv"
            path.write_bytes(csv_paths[0].read_bytes())
            extra_paths.append(path)
        add(extra_paths)
        assert len(table.get_children()) == 20
        assert table.item(table.get_children()[-1], "values")[0] == "extra17.csv"
        table.yview_moveto(1)
        root.update()
        assert table.yview()[1] == 1
        if screenshots:
            capture(root, directory / "comparison_twenty.png")
        table.selection_set(table.get_children()[3])
        buttons["選択したCSVを削除"].invoke()
        root.update()
        assert len(table.get_children()) == 19
        assert buttons["グラフを保存"].instate(["!disabled"])
        table.selection_set(*table.get_children())
        buttons["選択したCSVを削除"].invoke()
        root.update()
        assert not table.get_children()
        assert buttons["グラフを保存"].instate(["disabled"])
        assert not errors, errors

    try:
        with (
            patch.object(tk, "Tk", return_value=root),
            patch.object(root, "mainloop", side_effect=exercise),
            patch.object(
                root,
                "report_callback_exception",
                side_effect=lambda kind, error, trace: errors.append(error),
            ),
        ):
            gui["main"]()
    finally:
        root.destroy()
    assert [path.read_bytes() for path in csv_paths] == source_bytes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, default=Path("tests/results/current_workflow_20261014")
    )
    parser.add_argument("--no-screenshots", action="store_true")
    arguments = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    output = (project / arguments.out).resolve()
    if not output.is_relative_to(project / "tests/results") or output.exists():
        raise ValueError("tests/results内の、まだ存在しない保存先を指定してください")
    output.mkdir(parents=True)

    camera_folder = output / "camera"
    camera_folder.mkdir()
    photos = camera_folder / "photos"
    photos.mkdir()
    calibration_photos(photos)
    log = execute(
        "00_2_calibrate_camera.py", camera_folder, INPUT_DIRECTORY=str(photos)
    )
    assert len(list((camera_folder / "output/camera_detection").glob("*.png"))) == 12
    block = log[log.index("CALIBRATION_SIZE =") :]
    settings = {}
    for node in ast.parse(block).body:
        if isinstance(node, ast.Assign):
            settings[node.targets[0].id] = ast.literal_eval(node.value)
    batch_input = camera_folder / "input"
    batch_input.mkdir()
    save_image(
        batch_input / "shot1.png",
        rendered_scene((0.12, -0.22, 0.03), (-170, -65, 400)),
    )
    save_image(
        batch_input / "shot2.png",
        rendered_scene((-0.20, 0.18, -0.10), (-150, -100, 450)),
    )
    execute(
        "01_rectify_images.py",
        camera_folder,
        INPUT_DIRECTORY="input",
        OUTPUT_DIRECTORY="output/rectified",
        **settings,
    )
    known_dimensions = []
    assert not (camera_folder / "output/rectified/detected").exists()
    for name in ("shot1", "shot2"):
        image_path = camera_folder / f"output/rectified/{name}.png"
        corrected = cv.imdecode(
            np.frombuffer(image_path.read_bytes(), np.uint8), cv.IMREAD_COLOR
        )
        length_mm, width_mm = specimen_size(corrected)
        assert abs(length_mm - 150) < 1
        assert abs(width_mm - 40) < 1
        known_dimensions.append(
            {"image": name, "length_mm": float(length_mm), "width_mm": float(width_mm)}
        )

    input_path = project / "submissions/input/赤茶色の床と剥離した金属帯.png"
    original_bytes = input_path.read_bytes()
    image = cv.imdecode(np.frombuffer(original_bytes, np.uint8), cv.IMREAD_COLOR)
    assert image is not None
    height, width = image.shape[:2]
    board_folder = output / "board"
    board_folder.mkdir()
    execute("00_1_generate_charuco_board.py", board_folder, PIXELS_PER_MM=4)
    board_image = cv.imdecode(
        np.frombuffer(
            (board_folder / "output/charuco_board.png").read_bytes(), np.uint8
        ),
        cv.IMREAD_COLOR,
    )
    assert board_image is not None
    board_left, board_top = 1046, (height - board_image.shape[0]) // 2
    output_width = board_left + board_image.shape[1] + 40
    background = tuple(int(v) for v in np.median(image[:, width - 150 :], axis=(0, 1)))
    composite = np.full((height, output_width, 3), background, np.uint8)
    composite[:, :width] = image
    composite[
        board_top : board_top + board_image.shape[0],
        board_left : board_left + board_image.shape[1],
    ] = board_image
    frame = np.array(
        [
            [0, 0],
            [output_width - 1, 0],
            [output_width - 1, height - 1],
            [0, height - 1],
        ],
        np.float32,
    )
    tilted_frame = np.array(
        [
            [80, 65],
            [output_width - 110, 20],
            [output_width - 35, height - 55],
            [25, height - 15],
        ],
        np.float32,
    )
    tilted = cv.warpPerspective(
        composite,
        cv.getPerspectiveTransform(frame, tilted_frame),
        (output_width, height),
        borderValue=background,
    )
    matrix = np.array(
        [[1800.0, 0, output_width / 2], [0, 1800.0, height / 2], [0, 0, 1]]
    )
    coefficients = np.array([-0.04, 0.005, -0.001, 0.0001])
    dictionary = cv.aruco.getPredefinedDictionary(cv.aruco.DICT_4X4_50)
    board = cv.aruco.CharucoBoard((7, 5), 30.0, 18.0, dictionary)
    detector = cv.aruco.CharucoDetector(board)
    rows = []
    paths = []
    for name, scene, distortion in (
        ("front", distort(composite, matrix, np.zeros(4), background), np.zeros(4)),
        ("perspective", distort(tilted, matrix, np.zeros(4), background), np.zeros(4)),
        ("lens", distort(tilted, matrix, coefficients, background), coefficients),
    ):
        folder = output / name
        folder.mkdir()
        input_directory = folder / "input"
        input_directory.mkdir()
        source_path = input_directory / f"{name}.png"
        corrected_path = folder / f"output/rectified/{name}.png"
        save_image(source_path, scene)
        execute(
            "01_rectify_images.py",
            folder,
            INPUT_DIRECTORY=str(input_directory),
            CALIBRATION_SIZE=(output_width, height),
            CAMERA_MATRIX=matrix.tolist(),
            DIST_COEFFS=distortion.tolist(),
        )
        assert not (folder / "output/rectified/detected").exists()
        assert not list(folder.glob("*.csv"))
        corrected = cv.imdecode(
            np.frombuffer(corrected_path.read_bytes(), np.uint8), cv.IMREAD_COLOR
        )
        assert corrected is not None
        corners, ids, _, _ = detector.detectBoard(corrected)
        assert ids is not None and corners is not None
        board_indices = ids.astype(np.int32).ravel()
        world_points = np.array(board.getChessboardCorners())[board_indices, :2]
        board_to_output, _ = cv.findHomography(world_points * 4, corners.reshape(-1, 2))
        source_to_board = np.array(
            [[1, 0, -board_left - 40], [0, 1, -board_top - 40], [0, 0, 1]],
            dtype=np.float64,
        )
        transform = board_to_output @ source_to_board
        row = measure_with_gui(
            folder,
            corrected_path,
            transform,
            (width, height),
            not arguments.no_screenshots,
        )
        rows.append(dict(row, case=name))
        paths.append(folder / f"output/{name}_lengths.csv")
        print(f"{name}: left={row['left_mm']} right={row['right_mm']} mm", flush=True)
    compare_with_gui(output, paths, not arguments.no_screenshots)
    assert input_path.read_bytes() == original_bytes
    report = {
        "input_kind": "generated_test_image_not_production",
        "original_sha256": hashlib.sha256(original_bytes).hexdigest(),
        "camera_model": "opencv_fisheye",
        "camera_calibration": "12 synthetic fisheye photos, parameters copied to standalone rectifier",
        "known_dimensions": known_dimensions,
        "detection_checks": "12 calibration photos only; rectification saves corrected PNGs only",
        "orientation": "preserves the board horizontal-axis direction in the undistorted photo",
        "adjacent_board_assumptions": "4px/mm, same plane, hypothetical camera coefficients",
        "comparison_basis": "local intervals in CSV addition order, raw and per-100mm lengths; no ideal stretch model",
        "measurements": rows,
    }
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"5本の単発スクリプト・実Tk操作・3CSV比較・入力保護を確認: {output}")


if __name__ == "__main__":
    main()
