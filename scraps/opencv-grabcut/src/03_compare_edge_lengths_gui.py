"""局所区間の長さCSVを読み、DR・OP側辺長と100mm換算を表・グラフで比較する。"""

import tkinter as tk
from pathlib import Path
from tkinter import ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from utils.gui_parts import (
    choose_csv_paths,
    choose_png_path,
    create_layout,
    replace_graph,
)
from utils.length_comparison import create_graph, read_measurements, write_graph
from workflow_settings import OUTPUT_DIRECTORY


def main() -> None:
    output_directory = OUTPUT_DIRECTORY
    root = tk.Tk()
    root.title("局所区間のDR・OP長さ比較")
    root.geometry("1100x760")
    root.minsize(960, 640)
    paths: list[Path] = []
    rows: list[dict] = []
    graph_canvas: FigureCanvasTkAgg | None = None
    mode = tk.StringVar(master=root, value="実測長")
    status = tk.StringVar(master=root)
    file_text = tk.StringVar(master=root, value="0件")

    def draw_graph() -> None:
        nonlocal graph_canvas
        figure = None
        if rows:
            figure = create_graph(rows, mode.get() == "100mm換算")
        graph_canvas = replace_graph(graph_frame, graph_canvas, figure)

    def clear_results() -> None:
        rows.clear()
        table.delete(*table.get_children())
        save_graph_button.state(["disabled"])
        draw_graph()

    def update_comparison() -> None:
        clear_results()
        file_text.set(f"{len(paths)}件")
        for index, path in enumerate(paths):
            table.insert("", "end", iid=str(index), values=(path.name, "—", "—", "—"))
        if not paths:
            status.set("")
            return
        try:
            compared = read_measurements(paths)
        except ValueError as error:
            status.set(str(error))
            return
        rows.extend(compared)
        for index, row in enumerate(rows):
            values = [row["csv_name"]]
            for column in columns[1:]:
                values.append(f"{row[column]:.3f}")
            table.item(str(index), values=values)
        draw_graph()
        save_graph_button.state(["!disabled"])
        status.set("")

    def add_csvs() -> None:
        try:
            new_paths = choose_csv_paths(root, output_directory, paths)
        except ValueError as error:
            status.set(str(error))
            return
        if new_paths:
            paths.extend(new_paths)
            update_comparison()

    def remove_csvs() -> None:
        selected = table.selection()
        if not selected:
            status.set("表で削除するCSVを選んでください")
            return
        remaining = []
        for index, path in enumerate(paths):
            if str(index) not in selected:
                remaining.append(path)
        paths[:] = remaining
        update_comparison()

    def save_graph() -> None:
        stem = "length_comparison_local"
        if mode.get() == "100mm換算":
            stem += "_100mm"
        output_path = choose_png_path(root, output_directory, stem + ".png")
        if output_path is None:
            return
        try:
            write_graph(output_path, rows, mode.get() == "100mm換算")
        except ValueError as error:
            status.set(str(error))
            return
        except OSError:
            status.set(f"保存できません: {output_path.name}")
            return
        status.set(f"保存: {output_path.name}")

    header, sidebar, content = create_layout(root)
    ttk.Button(header, text="CSVを追加", command=add_csvs, padding=(12, 8)).pack(
        side="left"
    )
    ttk.Label(header, textvariable=file_text).pack(side="left", padx=8)
    ttk.Label(header, textvariable=status, wraplength=320).pack(side="right")
    ttk.Label(sidebar, text="グラフの表示").pack(anchor="w", pady=(0, 4))
    for label in ("実測長", "100mm換算"):
        ttk.Radiobutton(
            sidebar, text=label, value=label, variable=mode, command=draw_graph
        ).pack(anchor="w", pady=2)
    ttk.Button(
        sidebar, text="選択したCSVを削除", command=remove_csvs, padding=(12, 5)
    ).pack(fill="x", pady=(12, 3))
    save_graph_button = ttk.Button(
        sidebar, text="グラフを保存", command=save_graph, padding=(12, 8)
    )
    save_graph_button.pack(fill="x", pady=4)
    table_frame = ttk.LabelFrame(
        content, text="撮影ごとの計測値（CSV追加順）", padding=8
    )
    table_frame.pack(fill="x")
    columns = ("csv_name", "interval_length_mm", "left_mm", "right_mm")
    headings = ("撮影 / CSV", "区間長 (mm)", "DR側辺 (mm)", "OP側辺 (mm)")
    table = ttk.Treeview(table_frame, columns=columns, show="headings", height=6)
    for column, heading in zip(columns, headings):
        table.heading(column, text=heading)
        table.column(
            column,
            width=330 if column == "csv_name" else 150,
            anchor="w" if column == "csv_name" else "e",
        )
    table.grid(row=0, column=0, sticky="nsew")
    table_frame.columnconfigure(0, weight=1)
    vertical = ttk.Scrollbar(table_frame, orient="vertical", command=table.yview)
    vertical.grid(row=0, column=1, sticky="ns")
    horizontal = ttk.Scrollbar(table_frame, orient="horizontal", command=table.xview)
    horizontal.grid(row=1, column=0, sticky="ew")
    table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    graph_frame = ttk.Frame(content, padding=(0, 8, 0, 0))
    graph_frame.pack(fill="both", expand=True)
    save_graph_button.state(["disabled"])
    output_directory.mkdir(parents=True, exist_ok=True)
    root.mainloop()


if __name__ == "__main__":
    main()
