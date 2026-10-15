"""実Tkで局所比較GUIの追加・削除・自動更新・換算切替・PNG保存を確認する。"""

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
    script = copy_current("03_compare_edge_lengths_gui.py", output)
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

        assert set(buttons) == {"CSVを追加", "選択したCSVを削除", "グラフを保存"}
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
        path = output / "comparison_100mm.png"
        with patch.object(
            filedialog, "asksaveasfilename", return_value=str(path)
        ) as dialog:
            invoke("グラフを保存")
        assert path.exists()
        assert dialog.call_args.kwargs["initialfile"].endswith("_100mm.png")
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

        # 外部でCSVを直した場合は、そのCSVを外して追加し直す。
        table.selection_set("0")
        invoke("選択したCSVを削除")
        assert len(table.get_children()) == 2
        paths[0].write_text("bad csv", encoding="utf-8")
        add([paths[0]])
        assert len(table.get_children()) == 2
        paths[0].write_bytes(originals[0])
        add([paths[0]])
        assert buttons["グラフを保存"].instate(["!disabled"])
        assert [table.item(i, "values")[0] for i in table.get_children()] == [
            "p01_a.csv",
            "p01_b.csv",
            "p00_a.csv",
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
    print(
        f"実Tkで局所比較・100mm換算・PNG保存・自動更新・削除・20件表示を確認: {output}"
    )


if __name__ == "__main__":
    main()
