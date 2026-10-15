"""実Tkで厚さ付き最小比較GUIの入力、再比較、保存、多数行、削除を確認する."""

import argparse
import runpy
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from unittest.mock import patch

from test_current_workflow import copy_current
from test_length_analysis_gui import write_sample
from verify_parameter_guis import capture, descendants


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out", default="tests/results/length_comparison_simple_thickness_20261015"
    )
    arguments = parser.parse_args()
    directory = Path(arguments.out).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    samples = []
    for name, interval, left, right, thickness in (
        ("初期", 100, 100, 100, 10),
        ("撮影1", 200, 210, 200, 5),
        ("撮影2", 400, 420, 390, 2.5),
    ):
        samples.append(write_sample(directory, name, interval, left, right, thickness))
    paths = [sample["csv_path"] for sample in samples]
    gui = runpy.run_path(
        str(
            copy_current(
                "length_comparison_simple_gui.py",
                directory,
                source_directory="sandbox/previous_submissions/comparison_variants",
            )
        )
    )
    root = tk.Tk()
    root.attributes("-alpha", 0)
    errors = []

    def exercise():
        root.update()
        widgets = descendants(root)
        buttons = {}
        for widget in widgets:
            if isinstance(widget, ttk.Button):
                buttons[str(widget.cget("text"))] = widget

        def entries():
            return [
                widget for widget in descendants(root) if isinstance(widget, ttk.Entry)
            ]

        assert len(entries()) == 2
        table = next(widget for widget in widgets if isinstance(widget, ttk.Treeview))
        status_label = next(
            widget for widget in root.winfo_children() if isinstance(widget, ttk.Label)
        )

        def status():
            return str(root.getvar(str(status_label.cget("textvariable"))))

        def invoke(name):
            buttons[name].invoke()
            root.update()

        def set_value(entry, value):
            root.setvar(str(entry.cget("textvariable")), str(value))
            root.update()

        assert buttons["比較CSVを保存"].instate(["disabled"])
        invoke("比較する")
        assert "初期区間長" in status()
        set_value(entries()[0], 100)
        set_value(entries()[1], 10)
        invoke("比較する")
        assert "1枚以上" in status()
        with patch.object(
            filedialog,
            "askopenfilenames",
            return_value=tuple(str(path) for path in paths),
        ):
            invoke("CSVを追加")
        invoke("比較する")
        assert "厚さ" in status() and not table.get_children()
        for entry, sample in zip(entries()[2:], samples):
            set_value(entry, sample["thickness_mm"])
        invoke("比較する")
        assert len(entries()) == 5 and len(table.get_children()) == 3
        second = table.get_children()[1]
        assert table.set(second, "left_mm") == "210.000"
        assert table.set(second, "ideal_length_mm") == "200.000"
        assert table.set(second, "delta_left_mm") == "+10.000"
        assert table.set(second, "delta_right_mm") == "+0.000"
        capture(root, directory / "simple_gui.png")
        root.geometry("960x640")
        root.update()
        for button in buttons.values():
            assert button.winfo_height() >= button.winfo_reqheight()
            assert (
                button.winfo_rooty() + button.winfo_height()
                <= root.winfo_rooty() + root.winfo_height()
            )
        capture(root, directory / "simple_gui_minimum.png")
        for name, suffix in (("比較CSVを保存", ".csv"), ("グラフを保存", ".png")):
            output = directory / f"output/comparison{suffix}"
            with patch.object(
                filedialog, "asksaveasfilename", return_value=str(output)
            ):
                invoke(name)
            assert output.is_file(), status()
        before = paths[0].read_bytes()
        with patch.object(filedialog, "asksaveasfilename", return_value=str(paths[0])):
            invoke("比較CSVを保存")
        assert "別の保存先" in status() and paths[0].read_bytes() == before
        with patch.object(
            filedialog, "askopenfilenames", return_value=(str(paths[0]),)
        ):
            invoke("CSVを追加")
        assert len(entries()) == 5 and len(table.get_children()) == 3
        set_value(entries()[3], 10)
        assert not table.get_children() and buttons["グラフを保存"].instate(
            ["disabled"]
        )
        invoke("比較する")
        assert table.set(table.get_children()[1], "ideal_length_mm") == "100.000"
        assert table.set(table.get_children()[1], "delta_left_mm") == "+110.000"
        set_value(entries()[3], 5)
        set_value(entries()[1], 20)
        assert not table.get_children()
        invoke("比較する")
        assert table.set(table.get_children()[1], "ideal_length_mm") == "400.000"
        set_value(entries()[1], 10)
        set_value(entries()[0], 200)
        invoke("比較する")
        assert table.set(table.get_children()[0], "ideal_length_mm") == "200.000"
        set_value(entries()[0], 100)
        set_value(entries()[3], "bad")
        invoke("比較する")
        assert "厚さ" in status() and not table.get_children()
        set_value(entries()[3], 5)
        extra_paths = []
        for index in range(17):
            sample = write_sample(
                directory, f"追加{index + 1}", 100, 100 + index, 100, 10
            )
            extra_paths.append(sample["csv_path"])
        with patch.object(
            filedialog,
            "askopenfilenames",
            return_value=tuple(str(path) for path in extra_paths),
        ):
            invoke("CSVを追加")
        for entry in entries()[5:]:
            set_value(entry, 10)
        invoke("比較する")
        assert len(table.get_children()) == 20
        input_canvas = next(
            widget for widget in descendants(root) if isinstance(widget, tk.Canvas)
        )
        input_canvas.yview_moveto(1)
        root.update()
        capture(root, directory / "simple_gui_twenty.png")
        delete_buttons = [
            widget
            for widget in descendants(root)
            if isinstance(widget, ttk.Button) and str(widget.cget("text")) == "削除"
        ]
        delete_buttons[1].invoke()
        root.update()
        assert len(entries()) == 21 and not table.get_children()
        invoke("比較する")
        assert len(table.get_children()) == 19
        assert table.set(table.get_children()[1], "right_mm") == "390.000"
        assert table.set(table.get_children()[1], "ideal_length_mm") == "400.000"
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
    print(f"Simple GUI input, compare, save and delete: OK ({directory})")


if __name__ == "__main__":
    main()
