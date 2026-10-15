"""実Tkで局所比較GUIの追加・削除・換算切替・保存・再読込を確認する。"""

import argparse
import csv
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
        "--out", type=Path, default=Path("tests/results/local_comparison_poc")
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
    ]
    originals = [path.read_bytes() for path in paths]
    script = copy_current("length_comparison_local_gui.py", output)
    gui = runpy.run_path(str(script))
    root = tk.Tk()
    root.attributes("-alpha", 0)
    errors = []
    figures = []
    create_graph = gui["create_graph"]

    def record_graph(rows, normalized=False):
        figure = create_graph(rows, normalized)
        figures.append(figure)
        return figure

    def exercise():
        root.update()
        widgets = descendants(root)
        buttons = {str(w.cget("text")): w for w in widgets if isinstance(w, ttk.Button)}
        radios = {
            str(w.cget("text")): w for w in widgets if isinstance(w, ttk.Radiobutton)
        }
        table = next(w for w in widgets if isinstance(w, ttk.Treeview))

        def invoke(name):
            buttons[name].invoke()
            root.update()

        def add(selected):
            with patch.object(
                filedialog, "askopenfilenames", return_value=tuple(map(str, selected))
            ):
                invoke("CSVを追加")

        assert buttons["比較CSVを保存"].instate(["disabled"])
        assert buttons["グラフを保存"].instate(["disabled"])
        assert not any(isinstance(w, ttk.Entry) for w in widgets)
        add(paths)
        assert len(table.get_children()) == 3
        assert table.item("1", "values") == (
            "p01_a.csv",
            "200.000",
            "208.000",
            "204.000",
        )
        np.testing.assert_allclose(
            figures[-1].axes[0].lines[0].get_ydata(), [104, 208, 108]
        )
        add(paths)
        add([])
        assert len(table.get_children()) == 3
        radios["100mm換算"].invoke()
        root.update()
        np.testing.assert_allclose(
            figures[-1].axes[0].lines[0].get_ydata(), [104, 104, 108]
        )
        assert table.item("1", "values")[2] == "208.000"
        if not args.no_screenshots:
            capture(root, output / "comparison_100mm_gui.png")
        for label, filename in (
            ("比較CSVを保存", "comparison.csv"),
            ("グラフを保存", "comparison_100mm.png"),
        ):
            path = output / filename
            with patch.object(
                filedialog, "asksaveasfilename", return_value=str(path)
            ) as dialog:
                invoke(label)
            assert path.exists()
            if path.suffix == ".png":
                assert dialog.call_args.kwargs["initialfile"].endswith("_100mm.png")
        with (output / "comparison.csv").open(encoding="utf-8-sig", newline="") as file:
            saved = list(csv.DictReader(file))
        assert saved[1]["left_per_100mm"] == "104"
        assert saved[1]["left_mm"] == "208"
        radios["実測長"].invoke()
        root.update()
        with patch.object(
            filedialog,
            "asksaveasfilename",
            return_value=str(output / "comparison_raw.png"),
        ):
            invoke("グラフを保存")
        if not args.no_screenshots:
            capture(root, output / "comparison_raw_gui.png")

        # 外部でCSVを直した場合は、再比較で読み直す。失敗時は古い値を保存させない。
        paths[0].write_text("bad csv", encoding="utf-8")
        invoke("比較し直す")
        assert table.item("0", "values")[1] == "—"
        assert buttons["比較CSVを保存"].instate(["disabled"])
        paths[0].write_bytes(originals[0])
        invoke("比較し直す")
        assert buttons["比較CSVを保存"].instate(["!disabled"])
        table.selection_set("1")
        invoke("選択したCSVを削除")
        assert [table.item(i, "values")[0] for i in table.get_children()] == [
            "p00_a.csv",
            "p01_b.csv",
        ]
        table.selection_set(*table.get_children())
        invoke("選択したCSVを削除")
        assert not table.get_children()
        assert buttons["グラフを保存"].instate(["disabled"])
        many = []
        for index in range(20):
            many.append(sample_csv(output, f"p{index // 2:02}_{index % 2}"))
        add(many)
        assert len(table.get_children()) == 20
        root.geometry("960x640")
        root.update()
        for widget in list(buttons.values()) + list(radios.values()):
            assert widget.winfo_ismapped()
            assert widget.winfo_height() >= widget.winfo_reqheight()
            assert widget.winfo_rootx() + widget.winfo_width() <= (
                root.winfo_rootx() + root.winfo_width()
            )
        table.yview_moveto(1)
        root.update()
        assert table.yview()[1] == 1
        if not args.no_screenshots:
            capture(root, output / "comparison_20_minimum_gui.png")
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
    print(f"実Tkで局所比較・100mm換算・保存・再読込・削除・20件表示を確認: {output}")


if __name__ == "__main__":
    main()
