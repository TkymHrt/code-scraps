"""実際のTkで新規分析GUIの操作・保存・画面配置を確認する."""

import argparse
import csv
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
    parser.add_argument("--out", default="tests/results/length_analysis_20261015")
    arguments = parser.parse_args()
    directory = Path(arguments.out).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    samples = [
        write_sample(directory, "初期", 100, 100, 100, 10),
        write_sample(directory, "パス1", 200, 210, 200, 5),
        write_sample(directory, "パス2", 400, 420, 400, 2.5),
        write_sample(directory, "パス3", 420, 462, 441, 2.5),
    ]
    source_bytes = {}
    for sample in samples:
        path = sample["csv_path"]
        source_bytes[path] = path.read_bytes()
    gui = runpy.run_path(
        str(
            copy_current(
                "length_analysis_gui.py",
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
        table = next(widget for widget in widgets if isinstance(widget, ttk.Treeview))
        status_label = next(
            widget
            for widget in widgets
            if isinstance(widget, ttk.Label) and str(widget.cget("wraplength")) == "650"
        )

        def status():
            return str(root.getvar(str(status_label.cget("textvariable"))))

        def entries():
            return [
                widget for widget in descendants(root) if isinstance(widget, ttk.Entry)
            ]

        def set_value(entry, value):
            root.setvar(str(entry.cget("textvariable")), str(value))
            root.update()

        def invoke(name):
            buttons[name].invoke()
            root.update()

        def add(paths):
            with patch.object(
                filedialog,
                "askopenfilenames",
                return_value=tuple(str(path) for path in paths),
            ):
                invoke("CSVを追加")

        assert buttons["分析CSVを保存"].instate(["disabled"])
        invoke("分析する")
        assert "初期区間長" in status()
        set_value(entries()[0], 100)
        set_value(entries()[1], 10)
        invoke("分析する")
        assert "1枚以上" in status()
        add([sample["csv_path"] for sample in samples])
        invoke("分析する")
        assert "厚さ" in status() and not table.get_children()
        for entry, sample in zip(entries()[2:], samples):
            set_value(entry, sample["thickness_mm"])
        invoke("分析する")
        assert len(table.get_children()) == 4, status()
        last = table.get_children()[-1]
        assert table.set(last, "interval_length_mm") == "420.000"
        assert table.set(last, "stretch_pct") == "+5.000"
        assert table.set(last, "left_shape_pct") == "10.000"
        assert table.set(last, "right_shape_pct") == "5.000"
        capture(root, directory / "analysis_gui.png")
        root.geometry("1100x840")
        root.update()
        for button in buttons.values():
            assert button.winfo_height() >= button.winfo_reqheight()
            assert (
                button.winfo_rooty() + button.winfo_height()
                <= root.winfo_rooty() + root.winfo_height()
            )
        capture(root, directory / "analysis_gui_minimum.png")
        root.geometry("1320x920")
        root.update()
        for name, suffix in (("分析CSVを保存", ".csv"), ("分析グラフを保存", ".png")):
            path = directory / f"output/analysis{suffix}"
            with patch.object(filedialog, "asksaveasfilename", return_value=str(path)):
                invoke(name)
            assert path.exists(), status()
        with (directory / "output/analysis.csv").open(
            encoding="utf-8-sig", newline=""
        ) as source:
            saved = list(csv.DictReader(source))
        assert saved[0]["previous_delta_stretch_pp"] == ""
        assert saved[2]["previous_delta_left_shape_pp"] == "0"
        assert saved[3]["previous_delta_left_shape_pp"] == "5"
        with patch.object(
            filedialog, "asksaveasfilename", return_value=str(samples[0]["csv_path"])
        ):
            invoke("分析CSVを保存")
        assert "別の保存先" in status()
        add([samples[0]["csv_path"]])
        assert len(entries()) == 6 and len(table.get_children()) == 4
        set_value(entries()[2], 5)
        assert not table.get_children()
        assert buttons["分析グラフを保存"].instate(["disabled"])
        invoke("分析する")
        assert table.set(table.get_children()[0], "stretch_pct") == "-50.000"
        set_value(entries()[2], 10)
        set_value(entries()[0], 200)
        assert not table.get_children()
        invoke("分析する")
        assert table.set(table.get_children()[0], "ideal_length_mm") == "200.000"
        set_value(entries()[0], 100)
        set_value(entries()[3], "invalid")
        invoke("分析する")
        assert not table.get_children() and "厚さ" in status()
        set_value(entries()[3], 5)
        bad = directory / "不正.csv"
        bad.write_bytes(b"bad header\n")
        add([bad])
        assert "長さCSV" in status() and len(entries()) == 6
        extra = []
        for index in range(16):
            sample = write_sample(
                directory, f"追加{index + 1}", 100, 100 + index, 100, 10
            )
            extra.append(sample["csv_path"])
        add(extra)
        assert len(entries()) == 22
        for entry in entries()[6:]:
            set_value(entry, 10)
        invoke("分析する")
        assert len(table.get_children()) == 20, status()
        input_canvas = next(
            widget for widget in descendants(root) if isinstance(widget, tk.Canvas)
        )
        input_canvas.yview_moveto(1)
        table.yview_moveto(1)
        root.update()
        capture(root, directory / "analysis_gui_twenty.png")
        delete_buttons = [
            widget
            for widget in descendants(root)
            if isinstance(widget, ttk.Button) and str(widget.cget("text")) == "削除"
        ]
        delete_buttons[-1].invoke()
        root.update()
        assert len(entries()) == 21 and not table.get_children()
        assert buttons["分析CSVを保存"].instate(["disabled"])
        invoke("分析する")
        assert len(table.get_children()) == 19
        for path, before in source_bytes.items():
            assert path.read_bytes() == before
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
    print(f"実Tkの入力・再分析・CSV/PNG保存・20パス表示・削除を確認: {directory}")


if __name__ == "__main__":
    main()
