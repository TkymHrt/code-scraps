"""実Tkで厚さ入力の自動反映、軸・換算切替、PNG保存と不正入力を確認する。"""

import argparse
import runpy
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from unittest.mock import patch

import numpy as np
from test_current_workflow import copy_current
from test_length_comparison_local_gui import sample_csv
from verify_parameter_guis import capture, descendants


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out", type=Path, default=Path("tests/results/thickness_comparison_poc")
    )
    parser.add_argument("--no-screenshots", action="store_true")
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    output = (project / args.out).resolve()
    if not output.is_relative_to(project / "tests/results") or output.exists():
        raise ValueError("tests/results内の新しい保存先を指定してください")
    output.mkdir(parents=True)
    paths = [
        sample_csv(output, "p00_a", 100, 104, 102),
        sample_csv(output, "p01_a", 200, 208, 204),
        sample_csv(output, "p01_b", 100, 108, 106),
        sample_csv(output, "p02_a", 100, 110, 108),
    ]
    originals = [path.read_bytes() for path in paths]
    gui = runpy.run_path(
        str(copy_current("03_compare_edge_lengths_with_thickness_gui.py", output))
    )
    root = tk.Tk()
    root.attributes("-alpha", 0)
    errors = []
    figures = []
    create_graph = gui["create_graph"]

    def record_graph(rows, normalized=False, reduction_axis=False, **graph_options):
        figure = create_graph(rows, normalized, reduction_axis, **graph_options)
        figures.append(figure)
        return figure

    def exercise():
        root.update()
        widgets = descendants(root)
        buttons = {str(w.cget("text")): w for w in widgets if isinstance(w, ttk.Button)}
        radios = {
            str(w.cget("text")): w for w in widgets if isinstance(w, ttk.Radiobutton)
        }

        def invoke(label):
            buttons[label].invoke()
            root.update()

        def add(selected):
            with patch.object(
                filedialog, "askopenfilenames", return_value=tuple(map(str, selected))
            ):
                invoke("CSVを追加")

        def entries():
            return [w for w in descendants(root) if isinstance(w, ttk.Entry)]

        def set_entry(entry, value):
            root.setvar(str(entry.cget("textvariable")), str(value))
            root.update()

        assert set(buttons) == {"CSVを追加", "グラフを保存"}
        assert buttons["グラフを保存"].instate(["disabled"])
        add(paths)
        assert len(entries()) == 5
        assert buttons["グラフを保存"].instate(["disabled"])
        set_entry(entries()[0], 10)
        for entry, value in zip(entries()[1:], (10, 8, 8, 6)):
            set_entry(entry, value)
        assert buttons["グラフを保存"].instate(["!disabled"])
        np.testing.assert_allclose(
            figures[-1].axes[0].lines[0].get_ydata(), [104, 208, 108, 110]
        )
        add(paths)
        add([])
        assert len(entries()) == 5
        assert buttons["グラフを保存"].instate(["!disabled"])

        for x_label in ("撮影順", "累積圧下率"):
            for y_label in ("実測長", "100mm換算"):
                radios[x_label].invoke()
                radios[y_label].invoke()
                root.update()
                axis = figures[-1].axes[0]
                expected_x = (
                    [0, 20, 20, 40] if x_label == "累積圧下率" else [1, 2, 3, 4]
                )
                np.testing.assert_allclose(axis.lines[0].get_xdata(), expected_x)
                assert axis.lines[0].get_linestyle() == "-"
                assert axis.lines[1].get_linestyle() == "-"
                filename = f"{x_label}_{y_label}"
                if not args.no_screenshots:
                    capture(root, output / f"{filename}_gui.png")
                with patch.object(
                    filedialog,
                    "asksaveasfilename",
                    return_value=str(output / f"{filename}.png"),
                ):
                    invoke("グラフを保存")
                assert (output / f"{filename}.png").exists()
        set_entry(entries()[2], 7)
        assert buttons["グラフを保存"].instate(["!disabled"])
        np.testing.assert_allclose(
            figures[-1].axes[0].lines[0].get_xdata(), [0, 30, 20, 40]
        )
        set_entry(entries()[0], "")
        assert buttons["グラフを保存"].instate(["disabled"])
        set_entry(entries()[0], 10)
        assert buttons["グラフを保存"].instate(["!disabled"])
        paths[0].write_text("bad csv", encoding="utf-8")
        set_entry(entries()[0], 10)
        assert buttons["グラフを保存"].instate(["disabled"])
        paths[0].write_bytes(originals[0])
        set_entry(entries()[0], 10)
        assert buttons["グラフを保存"].instate(["!disabled"])
        delete_buttons = [
            w
            for w in descendants(root)
            if isinstance(w, ttk.Button) and str(w.cget("text")) == "削除"
        ]
        delete_buttons[0].invoke()
        root.update()
        assert len(entries()) == 4
        assert root.getvar(str(entries()[1].cget("textvariable"))) == "7"
        assert buttons["グラフを保存"].instate(["!disabled"])

        many = []
        for index in range(17):
            many.append(sample_csv(output, f"extra{index:02}"))
        add(many)
        assert len(entries()) == 21
        assert buttons["グラフを保存"].instate(["disabled"])
        for entry in entries()[4:]:
            set_entry(entry, 8)
        assert buttons["グラフを保存"].instate(["!disabled"])
        root.geometry("960x640")
        root.update()
        for widget in list(buttons.values()) + list(radios.values()):
            if str(widget.cget("text")) == "削除":
                continue
            assert widget.winfo_height() >= widget.winfo_reqheight()
            assert (
                widget.winfo_rootx() + widget.winfo_width()
                <= root.winfo_rootx() + root.winfo_width()
            )
        input_canvas = next(w for w in descendants(root) if isinstance(w, tk.Canvas))
        input_canvas.yview_moveto(1)
        if input_canvas.cget("xscrollcommand"):
            input_canvas.xview_moveto(1)
        root.update()
        assert input_canvas.yview()[1] == 1
        for widget in descendants(root):
            if isinstance(widget, ttk.Button) and str(widget.cget("text")) == "削除":
                assert widget.winfo_rootx() + widget.winfo_width() <= (
                    root.winfo_rootx() + root.winfo_width()
                )
        if not args.no_screenshots:
            capture(root, output / "20件_最小画面_gui.png")
        assert not errors, errors

    try:
        with (
            patch.object(tk, "Tk", return_value=root),
            patch.object(root, "mainloop", side_effect=exercise),
            patch.dict(gui["main"].__globals__, {"create_graph": record_graph}),
            patch.object(
                root,
                "report_callback_exception",
                side_effect=lambda kind, error, trace: errors.append(error),
            ),
        ):
            gui["main"]()
    finally:
        root.destroy()
    for path, original in zip(paths, originals):
        assert path.read_bytes() == original
    print(
        f"実Tkで厚さ入力・自動更新・累積圧下率・4表示・PNG保存・20件表示を確認: {output}"
    )


if __name__ == "__main__":
    main()
