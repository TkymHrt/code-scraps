"""既存の工程・GUI操作検証を、共通モジュールを含むコピーで再実行する。"""

import argparse
import csv
import runpy
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from unittest.mock import Mock, patch

import cv2 as cv
import numpy as np
import verify_current_workflow
import verify_length_comparison_local_gui
import verify_length_comparison_thickness_gui
from test_length_comparison_local_gui import sample_csv
from test_refactored_workflow import copy_refactored, run_refactored
from verify_parameter_guis import capture, descendants


def copy_verification_script(filename, directory, **settings):
    # 既存の工程検証は画像端の板を再検出するので、全体出力で比較する。
    # 中央出力の寸法と画素数削減はtest_reference_frame_rectificationで確認する。
    if filename == "01_rectify_images.py":
        settings["RECTIFY_ROI"] = (0, 0, 1, 1)
    return copy_refactored(filename, directory, **settings)


def verify_layout(output, screenshots):
    output.mkdir()
    paths = [sample_csv(output, f"sample{index}") for index in range(4)]
    bad = output / "bad.csv"
    bad.write_text("bad csv", encoding="utf-8")
    for filename in (
        "02_measure_edge_lengths_gui.py",
        "03_compare_edge_lengths_gui.py",
        "03_compare_edge_lengths_with_thickness_gui.py",
    ):
        gui = run_refactored(copy_refactored(filename, output))
        root = tk.Tk()
        root.attributes("-alpha", 0)
        errors = []

        def exercise():
            root.update()
            header, body = root.winfo_children()
            sidebar, content = body.winfo_children()
            widgets = descendants(root)
            buttons = {
                str(w.cget("text")): w for w in widgets if isinstance(w, ttk.Button)
            }
            assert sidebar.winfo_rootx() < content.winfo_rootx()
            assert header.winfo_rooty() < body.winfo_rooty()
            status_label = header.winfo_children()[-1]

            def status():
                return root.getvar(str(status_label.cget("textvariable")))

            assert status() == ""
            if filename.startswith("02"):
                assert buttons["補正画像を読み込む"].master == header
                assert buttons["CSV・画像2枚を保存"].master == sidebar
                with patch.object(
                    filedialog, "askopenfilename", return_value=""
                ) as dialog:
                    buttons["補正画像を読み込む"].invoke()
                assert (
                    dialog.call_args.kwargs["initialdir"] == output / "output/rectified"
                )
                assert buttons["CSV・画像2枚を保存"].instate(["disabled"])
                empty_image = output / "empty.png"
                empty_image.write_bytes(b"")
                with patch.object(
                    filedialog, "askopenfilename", return_value=str(empty_image)
                ):
                    buttons["補正画像を読み込む"].invoke()
                assert status() == "画像を読み込めません: empty.png"
                image = np.full((160, 140, 3), 35, np.uint8)
                image[20:141, 50:91] = 200
                image_path = output / "measurement_input.png"
                image_path.write_bytes(gui["encode_png"](image))
                with patch.object(
                    filedialog, "askopenfilename", return_value=str(image_path)
                ):
                    buttons["補正画像を読み込む"].invoke()
                root.update()
                canvas = next(w for w in widgets if isinstance(w, tk.Canvas))
                x0, y0, x1, y1 = canvas.bbox(canvas.find_all()[0])

                def click(x, y):
                    canvas.event_generate(
                        "<ButtonPress-1>",
                        x=round(x0 + x * (x1 - x0) / 140),
                        y=round(y0 + y * (y1 - y0) / 160),
                    )

                for point in ((42, 8), (98, 8), (98, 152), (42, 152)):
                    click(*point)
                buttons["多角形を確定"].invoke()
                radios = {
                    str(w.cget("text")): w
                    for w in widgets
                    if isinstance(w, ttk.Radiobutton)
                }
                entry = next(w for w in widgets if isinstance(w, ttk.Entry))
                root.setvar(str(entry.cget("textvariable")), "25")
                radios["区間の中心"].invoke()
                click(70, 80)
                buttons["試料抽出・軸を自動推定"].invoke()
                root.update()
                buttons["長さを計測"].invoke()
                assert status() == "計測完了", status()
                with (
                    patch.object(
                        filedialog,
                        "asksaveasfilename",
                        return_value=str(output / "failed.csv"),
                    ),
                    patch.dict(
                        gui["main"].__globals__,
                        {
                            "write_measurement": Mock(
                                side_effect=OSError("technical details")
                            )
                        },
                    ),
                ):
                    buttons["CSV・画像2枚を保存"].invoke()
                assert status() == "保存失敗: CSV・PNGを確認してください"
                assert buttons["CSV・画像2枚を保存"].instate(["!disabled"])
                root.geometry("1000x760")
            else:
                assert buttons["CSVを追加"].master == header
                assert buttons["グラフを保存"].master == sidebar
                with patch.object(
                    filedialog,
                    "askopenfilenames",
                    return_value=tuple(map(str, paths[:3])),
                ) as dialog:
                    buttons["CSVを追加"].invoke()
                assert dialog.call_args.kwargs["initialdir"] == output / "output"
                entries = [w for w in descendants(root) if isinstance(w, ttk.Entry)]
                for entry in entries:
                    root.setvar(str(entry.cget("textvariable")), "10")
                root.update()
                assert buttons["グラフを保存"].instate(["!disabled"])
                assert status() == ""
                count_label = header.winfo_children()[1]
                assert root.getvar(str(count_label.cget("textvariable"))) == "3件"
                # 新しい選択を拒否したときは、現在の結果と保存可能状態を保つ。
                for selected in ((), (str(paths[3]), str(bad))):
                    with patch.object(
                        filedialog, "askopenfilenames", return_value=selected
                    ):
                        buttons["CSVを追加"].invoke()
                    root.update()
                    assert root.getvar(str(count_label.cget("textvariable"))) == "3件"
                    assert buttons["グラフを保存"].instate(["!disabled"])
                root.geometry("960x640")
            root.update()
            for button in buttons.values():
                assert button.winfo_height() >= button.winfo_reqheight()
            if screenshots:
                capture(root, output / f"{Path(filename).stem}_layout.png")
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
    print(f"3画面の配置・入出力開始先・取消と不正選択時の結果維持を確認: {output}")


def measure_with_axis_gui(directory, image_path, transform, original_size, screenshots):
    """旧検証の画像作成・比較を使い、src版だけ新しい計測操作へ置き換える。"""
    gui = run_refactored(copy_refactored("02_measure_edge_lengths_gui.py", directory))
    root = tk.Tk()
    root.attributes("-alpha", 0)
    errors = []
    image_bytes = image_path.read_bytes()
    image = cv.imdecode(np.frombuffer(image_bytes, np.uint8), cv.IMREAD_COLOR)
    assert image is not None
    height, width = image.shape[:2]
    original_width, original_height = original_size
    csv_path = directory / f"output/{directory.name}_lengths.csv"

    def exercise():
        root.update()
        widgets = descendants(root)
        buttons = {str(w.cget("text")): w for w in widgets if isinstance(w, ttk.Button)}
        radios = {
            str(w.cget("text")): w for w in widgets if isinstance(w, ttk.Radiobutton)
        }
        canvas = next(w for w in widgets if isinstance(w, tk.Canvas))
        status_label = root.winfo_children()[0].winfo_children()[-1]

        def invoke(name):
            buttons[name].invoke()
            root.update()

        with patch.object(filedialog, "askopenfilename", return_value=str(image_path)):
            invoke("補正画像を読み込む")
        x0, y0, x1, y1 = canvas.bbox(canvas.find_all()[0])

        def click(x, y):
            canvas.event_generate(
                "<ButtonPress-1>",
                x=round(x0 + x * (x1 - x0) / width),
                y=round(y0 + y * (y1 - y0) / height),
            )

        def transformed(points):
            points = np.array(points, dtype=np.float32).reshape(-1, 1, 2)
            return cv.perspectiveTransform(points, transform).reshape(-1, 2)

        def draw(kind, left, top, right, bottom):
            radios[kind].invoke()
            radios["多角形"].invoke()
            points = np.clip(
                [(left, top), (right, top), (right, bottom), (left, bottom)],
                (0, 0),
                (width - 1, height - 1),
            )
            for point in points:
                click(*point)
            invoke("多角形を確定")

        candidate = transformed(
            [
                (0.3052208835 * original_width, 0),
                (0.697456493 * original_width, 0),
                (0.697456493 * original_width, original_height),
                (0.3052208835 * original_width, original_height),
            ]
        )
        left, top = candidate.min(axis=0)
        right, bottom = candidate.max(axis=0)
        draw("前景候補（橙）", left, top, right, bottom)
        draw("確実な背景（青）", 0, 0, left - width * 0.005, height - 1)
        draw("確実な背景（青）", right + width * 0.005, 0, width - 1, height - 1)
        foreground = transformed(
            [
                (0.400267738 * original_width, 80),
                (0.60107095 * original_width, 80),
                (0.60107095 * original_width, 1000),
                (0.400267738 * original_width, 1000),
            ]
        )
        left, top = foreground.min(axis=0)
        right, bottom = foreground.max(axis=0)
        draw("確実な前景（緑）", left, top, right, bottom)
        entry = next(w for w in widgets if isinstance(w, ttk.Entry))
        # 折返しを含む検証素材は、両端が側辺を1回ずつ切る同じ225mmで比較する。
        root.setvar(str(entry.cget("textvariable")), "225")
        center = transformed([(original_width / 2, 540)])[0]
        radios["区間の中心"].invoke()
        click(*center)
        invoke("試料抽出・軸を自動推定")
        assert len(canvas.find_withtag("axis")) == 1, root.getvar(
            str(status_label.cget("textvariable"))
        )
        assert len(canvas.find_withtag("interval")) == 2
        invoke("長さを計測")
        status = root.getvar(str(status_label.cget("textvariable")))
        assert status == "計測完了", status
        assert buttons["CSV・画像2枚を保存"].instate(["!disabled"])
        if screenshots:
            capture(root, directory / "axis_measurement_gui.png")
        with patch.object(filedialog, "asksaveasfilename", return_value=str(csv_path)):
            invoke("CSV・画像2枚を保存")
        assert csv_path.is_file()
        assert csv_path.with_suffix(".png").is_file()
        assert csv_path.with_name(f"{csv_path.stem}_initial.png").is_file()
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
        row = next(csv.DictReader(source))
    assert "start_y" not in row and "end_y" not in row
    interval_mm = float(row["interval_length_mm"])
    assert np.isclose(interval_mm, 225)
    for edge in ("left", "right"):
        expected_percent = (float(row[f"{edge}_mm"]) / interval_mm - 1) * 100
        assert np.isclose(float(row[f"{edge}_excess_percent"]), expected_percent)
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--no-screenshots", action="store_true")
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    output = (project / args.out).resolve()
    if not output.is_relative_to(project / "tests/results") or output.exists():
        raise ValueError("tests/results内の新しい保存先を指定してください")
    output.mkdir(parents=True)
    verify_layout(output / "layout", not args.no_screenshots)
    for name, verification in (
        ("workflow", verify_current_workflow),
        ("local", verify_length_comparison_local_gui),
        ("thickness", verify_length_comparison_thickness_gui),
    ):
        arguments = [verification.__file__, "--out", str(output / name)]
        if args.no_screenshots:
            arguments.append("--no-screenshots")
        with (
            patch.object(sys, "argv", arguments),
            patch.object(runpy, "run_path", run_refactored),
            patch.object(verification, "copy_current", copy_verification_script),
            patch.object(
                verify_current_workflow, "measure_with_gui", measure_with_axis_gui
            ),
        ):
            verification.main()
    print(f"共通化した6本の校正・補正・計測・比較GUIを確認: {output}")


if __name__ == "__main__":
    main()
