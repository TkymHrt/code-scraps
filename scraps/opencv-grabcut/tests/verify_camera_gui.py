"""合成写真で、係数コピペ・換算GUI・03・mm CSVまで実際に動かす."""

import argparse
import contextlib
import io
import runpy
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from unittest.mock import patch

import cv2 as cv
import numpy as np
from test_camera_conversion import calibration_photos, configure, rendered_scene
from test_submissions import SubmissionTests
from verify_parameter_guis import capture, descendants


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, default=Path("tests/results/camera_gui_20261014")
    )
    parser.add_argument("--screenshots", action="store_true")
    arguments = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    output = (project / arguments.out).resolve()
    if (
        not output.is_relative_to((project / "tests/results").resolve())
        or output.exists()
    ):
        raise ValueError("tests/results内の、まだ存在しない検証先を指定してください")
    output.mkdir(parents=True)
    board_source = project / "submissions/generate_charuco_board.py"
    board_copy = output / board_source.name
    board_copy.write_bytes(board_source.read_bytes())
    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        runpy.run_path(str(board_copy))
    board_path = output / "results/charuco_board.png"
    board_contents = board_path.read_bytes()
    photos = output / "input/camera_calibration"
    photos.mkdir(parents=True)
    paths = calibration_photos(photos)
    camera_source = project / "submissions/camera_calibration.py"
    camera_copy = output / camera_source.name
    camera_copy.write_bytes(camera_source.read_bytes())
    with contextlib.redirect_stdout(log):
        runpy.run_path(str(camera_copy), run_name="__main__")
    assert board_path.read_bytes() == board_contents
    (output / "camera_calibration.txt").write_text(log.getvalue(), encoding="utf-8")
    assert "CALIBRATION_SIZE = (960, 720)" in log.getvalue()
    camera = runpy.run_path(str(camera_copy))
    _, matrix, distortion, rms, errors = camera["calibrate"](paths)
    gui_source = project / "submissions/rectify_image_gui.py"
    gui_copy = output / gui_source.name
    gui_copy.write_bytes(gui_source.read_bytes())
    gui = runpy.run_path(str(gui_copy))
    configure(gui, matrix, distortion)
    source = output / "撮影画像.png"
    image = rendered_scene((0.12, -0.22, 0.03), (-170, -65, 600))
    _, encoded = cv.imencode(".png", image)
    source.write_bytes(encoded.tobytes())
    original = source.read_bytes()
    corrected = output / "補正画像.png"
    source_csv = output / "03_side_lengths.csv"
    lengths_csv = output / "calibrated_lengths.csv"
    blank = output / "板のない画像.png"
    _, encoded = cv.imencode(".png", np.zeros_like(image))
    blank.write_bytes(encoded.tobytes())
    root = tk.Tk()
    root.withdraw()
    root.attributes("-alpha", 0)
    callback_errors = []

    def exercise():
        root.deiconify()
        root.update()
        widgets = descendants(root)
        buttons = {}
        labels = []
        for widget in widgets:
            if isinstance(widget, ttk.Button):
                buttons[str(widget.cget("text"))] = widget
            if isinstance(widget, ttk.Label) and str(widget.cget("textvariable")):
                labels.append(widget)
        assert not any(
            isinstance(widget, (ttk.Entry, ttk.Scale, ttk.Combobox))
            for widget in widgets
        )
        assert len(root.winfo_children()) == 2
        toolbar = root.winfo_children()[0]
        status_label = next(
            label
            for label in labels
            if label.master == toolbar and label.grid_info()["column"] == 2
        )
        canvas = next(widget for widget in widgets if isinstance(widget, tk.Canvas))
        table = next(widget for widget in widgets if isinstance(widget, ttk.Treeview))

        def status():
            return str(root.getvar(str(status_label.cget("textvariable"))))

        def invoke(name):
            buttons[name].invoke()
            root.update()

        assert buttons["補正後の03 CSVを読み込む"].instate(["disabled"])
        with patch.object(filedialog, "askopenfilename", return_value=str(source)):
            invoke("撮影画像を読み込む")
        assert "補正PNG" in status()
        if arguments.screenshots:
            capture(root, output / "rectification_gui.png")
        canvas.event_generate("<MouseWheel>", x=300, y=250, delta=60)
        canvas.event_generate("<ButtonPress-3>", x=300, y=250)
        canvas.event_generate("<B3-Motion>", x=330, y=280)
        canvas.event_generate("<ButtonRelease-3>", x=330, y=280)
        root.update()
        with patch.object(filedialog, "asksaveasfilename", return_value=""):
            invoke("補正PNGを保存")
        assert not corrected.exists()
        with patch.object(filedialog, "asksaveasfilename", return_value=str(source)):
            invoke("補正PNGを保存")
        assert "別のPNG" in status()
        assert source.read_bytes() == original
        with patch.object(filedialog, "asksaveasfilename", return_value=str(corrected)):
            invoke("補正PNGを保存")
        assert corrected.is_file()
        assert buttons["補正後の03 CSVを読み込む"].instate(["!disabled"])

        # 新しい画像の座標に合わせ、コピーした03だけの設定を変更する。
        normalized = cv.imdecode(
            np.frombuffer(corrected.read_bytes(), np.uint8), cv.IMREAD_COLOR
        )
        assert normalized is not None
        height, width = normalized.shape[:2]
        ys, xs = np.nonzero(cv.inRange(normalized, (20, 75, 145), (90, 145, 220)))
        x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
        candidate = (
            (x0 - 12) / width,
            (y0 - 12) / height,
            (x1 + 12) / width,
            (y1 + 12) / height,
        )
        foreground = (
            (x0 + 10) / width,
            (y0 + 10) / height,
            (x1 - 10) / width,
            (y1 - 10) / height,
        )
        settings = SubmissionTests().submission_source(
            "03_side_lengths.py",
            INPUT_PATH=str(corrected),
            OUTPUT_IMAGE_PATH=str(output / "03_side_lengths.png"),
            OUTPUT_CSV_PATH=str(source_csv),
            CANDIDATE_RECT=candidate,
            BACKGROUND_RECTS=(
                (0.0, 0.0, (x0 - 20) / width, 1.0),
                ((x1 + 20) / width, 0.0, 1.0, 1.0),
            ),
            FOREGROUND_RECTS=(foreground,),
            START_Y=y0,
            END_Y=y1,
        )
        measurement_copy = output / "03_side_lengths.py"
        measurement_copy.write_text(settings, encoding="utf-8")
        with contextlib.redirect_stdout(log):
            runpy.run_path(str(measurement_copy))
        with patch.object(filedialog, "askopenfilename", return_value=str(source_csv)):
            invoke("補正後の03 CSVを読み込む")
        assert len(table.get_children()) == 3
        if arguments.screenshots:
            capture(root, output / "conversion_gui.png")
        for path in (source, corrected, source_csv):
            before = path.read_bytes()
            with patch.object(filedialog, "asksaveasfilename", return_value=str(path)):
                invoke("mm換算CSVを保存")
            assert path.read_bytes() == before
        with patch.object(
            filedialog, "asksaveasfilename", return_value=str(lengths_csv)
        ):
            invoke("mm換算CSVを保存")
        comparison = runpy.run_path(
            str(project / "submissions/length_comparison_gui.py")
        )
        values = comparison["read_calibrated_lengths"](lengths_csv)
        assert values["mm_per_px"] == 0.25
        for edge in ("left", "right", "total"):
            assert values[f"{edge}_mm"] == values[f"{edge}_px"] * 0.25
        log.write(
            f"\nIndependent span: {(y1 - y0) * 0.25:.2f}mm; arc left: {values['left_mm']:.4f}mm; arc right: {values['right_mm']:.4f}mm\n"
        )
        with patch.object(filedialog, "askopenfilename", return_value=""):
            invoke("撮影画像を読み込む")
        assert len(table.get_children()) == 3
        # 保存時にも元CSVを読み直し、古いmm値を保存させない。
        contents = source_csv.read_bytes()
        source_csv.write_text("wrong,csv\n", encoding="utf-8")
        rejected = output / "stale.csv"
        with patch.object(filedialog, "asksaveasfilename", return_value=str(rejected)):
            invoke("mm換算CSVを保存")
        assert not rejected.exists()
        assert not table.get_children()
        source_csv.write_bytes(contents)
        with patch.object(filedialog, "askopenfilename", return_value=str(blank)):
            invoke("撮影画像を読み込む")
        assert "6点" in status()
        assert buttons["補正PNGを保存"].instate(["disabled"])
        assert buttons["mm換算CSVを保存"].instate(["disabled"])
        assert not table.get_children()
        if arguments.screenshots:
            capture(root, output / "no_board_error.png")
        assert source.read_bytes() == original
        assert not callback_errors, callback_errors

    try:
        with (
            patch.object(tk, "Tk", return_value=root),
            patch.object(root, "mainloop", side_effect=exercise),
            patch.object(
                root,
                "report_callback_exception",
                side_effect=lambda kind, error, trace: callback_errors.append(error),
            ),
        ):
            gui["main"]()
    finally:
        root.destroy()
    (output / "verification.txt").write_text(log.getvalue(), encoding="utf-8")
    print(f"カメラ校正12枚: RMS {rms:.4f}px、写真別最大 {max(errors):.4f}px")
    print(
        "換算GUI: ズーム・移動・補正PNG・03実行・mm保存・比較CSV読込・入力保護・キャンセル・失敗時解除を確認"
    )
    print(f"結果: {output}")


if __name__ == "__main__":
    main()
