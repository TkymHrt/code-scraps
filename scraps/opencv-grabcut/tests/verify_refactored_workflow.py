"""既存の工程・GUI操作検証を、共通モジュールを含むコピーで再実行する。"""

import argparse
import runpy
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from unittest.mock import Mock, patch

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
                entries = [w for w in widgets if isinstance(w, ttk.Entry)]
                for entry, value in zip(entries, ("20", "140")):
                    root.setvar(str(entry.cget("textvariable")), value)
                root.update()
                canvas = next(w for w in widgets if isinstance(w, tk.Canvas))
                x0, y0, x1, y1 = canvas.bbox(canvas.find_all()[0])
                canvas.event_generate(
                    "<ButtonPress-1>", x=round(x0 + (x1 - x0) * 0.3), y=y0
                )
                canvas.event_generate(
                    "<B1-Motion>", x=round(x0 + (x1 - x0) * 0.7), y=y1
                )
                canvas.event_generate(
                    "<ButtonRelease-1>", x=round(x0 + (x1 - x0) * 0.7), y=y1
                )
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
        ):
            verification.main()
    print(f"共通化した6本の校正・補正・計測・比較GUIを確認: {output}")


if __name__ == "__main__":
    main()
