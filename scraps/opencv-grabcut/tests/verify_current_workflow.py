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
from tkinter import filedialog, ttk
from unittest.mock import patch

import cv2 as cv
import numpy as np
from test_camera_conversion import calibration_photos, rendered_scene
from test_current_workflow import copy_current
from verify_adjacent_board import distort, save_image
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


def measure_with_gui(directory, image_path, offset, original_size, screenshots):
    script = copy_current("01_initial_regions_gui.py", directory)
    gui = runpy.run_path(str(script))
    root = tk.Tk()
    root.attributes("-alpha", 0)
    errors = []
    csv_path = directory / "lengths.csv"
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
        set_field(root, start, round(80 + offset[1]))
        set_field(root, end, round(1000 + offset[1]))
        image = cv.imdecode(np.frombuffer(image_bytes, np.uint8), cv.IMREAD_COLOR)
        assert image is not None
        height, width = image.shape[:2]
        original_width, _ = original_size

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

        left = (0.3052208835 * original_width + offset[0]) / width
        right = (0.697456493 * original_width + offset[0]) / width
        draw("前景候補（橙）", left, 0, right, 1)
        draw(
            "確実な背景（青）",
            0,
            0,
            (0.3012048193 * original_width + offset[0]) / width,
            1,
        )
        draw(
            "確実な背景（青）",
            (0.702811245 * original_width + offset[0]) / width,
            0,
            1,
            1,
        )
        draw(
            "確実な前景（緑）",
            (0.400267738 * original_width + offset[0]) / width,
            (80 + offset[1]) / height,
            (0.60107095 * original_width + offset[0]) / width,
            (1000 + offset[1]) / height,
        )
        invoke("長さを計測")
        assert "計測しました" in status(), status()
        assert buttons["長さCSVを保存"].instate(["!disabled"])
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
        if screenshots:
            capture(root, directory / "01_gui.png")
        for name, path in (
            ("長さCSVを保存", csv_path),
            ("確認画像を保存", directory / "measurement.png"),
        ):
            with patch.object(filedialog, "asksaveasfilename", return_value=str(path)):
                invoke(name)
            assert path.exists(), status()
        with patch.object(
            filedialog, "asksaveasfilename", return_value=str(image_path)
        ):
            invoke("確認画像を保存")
        assert "別のパス" in status()
        before = csv_path.read_bytes()
        set_field(root, start, -1)
        assert buttons["長さCSVを保存"].instate(["disabled"])
        invoke("長さを計測")
        assert "計測区間" in status()
        assert csv_path.read_bytes() == before
        assert image_path.read_bytes() == image_bytes
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
    gui = runpy.run_path(str(copy_current("length_comparison_gui.py", directory)))
    root = tk.Tk()
    root.attributes("-alpha", 0)
    errors = []

    def exercise():
        root.update()
        widgets = descendants(root)
        buttons = {str(w.cget("text")): w for w in widgets if isinstance(w, ttk.Button)}
        tables = [w for w in widgets if isinstance(w, ttk.Treeview)]
        input_table, length_table = tables[:2]
        set_field(root, field(root, widgets, "初期区間長 (mm)"), 230)
        set_field(root, field(root, widgets, "初期厚さ (mm)"), 10)
        with patch.object(
            filedialog,
            "askopenfilenames",
            return_value=tuple(str(path) for path in csv_paths),
        ):
            buttons["CSVを追加"].invoke()
        root.update()
        assert len(input_table.get_children()) == 3
        thickness = field(root, widgets, "撮影時の厚さ (mm)")
        for index in range(3):
            input_table.selection_set(str(index))
            input_table.event_generate("<<TreeviewSelect>>")
            root.update()
            set_field(root, thickness, 10)
            buttons["撮影名・厚さを適用"].invoke()
            root.update()
        buttons["比較する"].invoke()
        root.update()
        assert len(length_table.get_children()) == 3
        for name, suffix in (("比較CSVを保存", ".csv"), ("推移グラフを保存", ".png")):
            with patch.object(
                filedialog,
                "asksaveasfilename",
                return_value=str(directory / f"comparison{suffix}"),
            ):
                buttons[name].invoke()
            root.update()
            assert (directory / f"comparison{suffix}").exists()
        if screenshots:
            capture(root, directory / "comparison_gui.png")
        input_table.selection_set("2")
        buttons["上へ"].invoke()
        root.update()
        assert not length_table.get_children()
        buttons["比較する"].invoke()
        root.update()
        assert len(length_table.get_children()) == 3
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
    log = execute("camera_calibration.py", camera_folder, INPUT_DIRECTORY=str(photos))
    block = log[log.index("CALIBRATION_SIZE =") :]
    settings = {}
    for node in ast.parse(block).body:
        if isinstance(node, ast.Assign):
            settings[node.targets[0].id] = ast.literal_eval(node.value)
    save_image(
        camera_folder / "input.png",
        rendered_scene((0.12, -0.22, 0.03), (-170, -65, 600)),
    )
    execute(
        "rectify_image.py",
        camera_folder,
        INPUT_PATH="input.png",
        OUTPUT_IMAGE_PATH="rectified.png",
        **settings,
    )

    input_path = project / "submissions/input/赤茶色の床と剥離した金属帯.png"
    original_bytes = input_path.read_bytes()
    image = cv.imdecode(np.frombuffer(original_bytes, np.uint8), cv.IMREAD_COLOR)
    assert image is not None
    height, width = image.shape[:2]
    board_folder = output / "board"
    board_folder.mkdir()
    execute("generate_charuco_board.py", board_folder, PIXELS_PER_MM=4)
    board_image = cv.imdecode(
        np.frombuffer(
            (board_folder / "results/charuco_board.png").read_bytes(), np.uint8
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
    matrix = np.array([[1800.0, 0, width / 2], [0, 1800.0, height / 2], [0, 0, 1]])
    coefficients = np.array([-0.12, 0.025, 0.0005, -0.0008, 0.0])
    dictionary = cv.aruco.getPredefinedDictionary(cv.aruco.DICT_4X4_50)
    board = cv.aruco.CharucoBoard((7, 5), 30.0, 18.0, dictionary)
    detector = cv.aruco.CharucoDetector(board)
    rows = []
    paths = []
    for name, scene, distortion in (
        ("front", composite, np.zeros(5)),
        ("perspective", tilted, np.zeros(5)),
        ("lens", distort(tilted, matrix, coefficients, background), coefficients),
    ):
        folder = output / name
        folder.mkdir()
        source_path = folder / "input.png"
        corrected_path = folder / "rectified.png"
        save_image(source_path, scene)
        execute(
            "rectify_image.py",
            folder,
            INPUT_PATH=str(source_path),
            OUTPUT_IMAGE_PATH=str(corrected_path),
            CALIBRATION_SIZE=(output_width, height),
            CAMERA_MATRIX=matrix.tolist(),
            DIST_COEFFS=distortion.tolist(),
        )
        assert not list(folder.glob("*.csv"))
        corrected = cv.imdecode(
            np.frombuffer(corrected_path.read_bytes(), np.uint8), cv.IMREAD_COLOR
        )
        assert corrected is not None
        corners, ids, _, _ = detector.detectBoard(corrected)
        assert ids is not None and corners is not None
        board_indices = ids.astype(np.int32).ravel()
        world_points = np.array(board.getChessboardCorners())[board_indices, :2]
        origin = np.mean(corners.reshape(-1, 2) - world_points * 4, axis=0)
        offset = origin - np.array([board_left + 40, board_top + 40])
        row = measure_with_gui(
            folder,
            corrected_path,
            offset,
            (width, height),
            not arguments.no_screenshots,
        )
        rows.append(dict(row, case=name))
        paths.append(folder / "lengths.csv")
        print(f"{name}: left={row['left_mm']} right={row['right_mm']} mm", flush=True)
    compare_with_gui(output, paths, not arguments.no_screenshots)
    assert input_path.read_bytes() == original_bytes
    report = {
        "input_kind": "generated_test_image_not_production",
        "original_sha256": hashlib.sha256(original_bytes).hexdigest(),
        "camera_calibration": "12 synthetic photos, parameters copied to standalone rectifier",
        "adjacent_board_assumptions": "4px/mm, same plane, hypothetical camera coefficients",
        "analysis_assumptions": "same unrolled sample, initial interval 230mm, all thicknesses 10mm",
        "measurements": rows,
    }
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"5本の単発スクリプト・実Tk操作・3CSV比較・入力保護を確認: {output}")


if __name__ == "__main__":
    main()
