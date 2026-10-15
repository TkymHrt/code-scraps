"""局所区間の左右側辺長を、実測厚さから求めた累積圧下率とともに比較する。"""

import math
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from gui_parts import choose_csv_paths, choose_png_path, create_layout, replace_graph
from length_comparison import create_graph, read_measurements, write_graph
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from measurement_csv import positive_value
from workflow_settings import OUTPUT_DIRECTORY


def compare_lengths_with_thickness(
    samples: list[dict], initial_thickness_mm: float | str | None
) -> list[dict]:
    initial_thickness_mm = positive_value(initial_thickness_mm, "初期厚さ")
    paths = []
    for sample in samples:
        paths.append(Path(sample["csv_path"]))
    rows = read_measurements(paths)
    for sample, row in zip(samples, rows):
        thickness_mm = positive_value(
            sample["thickness_mm"], f"厚さ: {row['csv_name']}"
        )
        reduction_pct = (
            (initial_thickness_mm - thickness_mm) / initial_thickness_mm * 100
        )
        if not math.isfinite(reduction_pct):
            raise ValueError(f"累積圧下率を計算できません: {row['csv_name']}")
        row["initial_thickness_mm"] = initial_thickness_mm
        row["thickness_mm"] = thickness_mm
        row["reduction_pct"] = reduction_pct
    return rows


def main() -> None:
    output_directory = OUTPUT_DIRECTORY
    root = tk.Tk()
    root.title("厚さ・累積圧下率と左右長さの比較")
    root.geometry("1100x760")
    root.minsize(960, 640)
    samples: list[dict] = []
    rows: list[dict] = []
    graph_canvas: FigureCanvasTkAgg | None = None
    initial_thickness_text = tk.StringVar(master=root)
    mode = tk.StringVar(master=root, value="実測長")
    horizontal_axis = tk.StringVar(master=root, value="撮影順")
    status = tk.StringVar(master=root)
    result_columns = ("interval_length_mm", "left_mm", "right_mm", "reduction_pct")
    file_text = tk.StringVar(master=root, value="0件")

    def draw_graph() -> None:
        nonlocal graph_canvas
        figure = None
        if rows:
            figure = create_graph(
                rows,
                mode.get() == "100mm換算",
                horizontal_axis.get() == "累積圧下率",
                initial_thickness_mm=rows[0]["initial_thickness_mm"],
            )
        graph_canvas = replace_graph(graph_frame, graph_canvas, figure)

    def clear_results() -> None:
        rows.clear()
        for sample in samples:
            for value in sample["result_text"].values():
                value.set("—")
        draw_graph()
        save_graph_button.state(["disabled"])

    def update_comparison(*_args) -> None:
        clear_results()
        file_text.set(f"{len(samples)}件")
        if not samples:
            status.set("")
            return
        if not initial_thickness_text.get().strip():
            status.set("初期厚さを入力してください")
            return
        conditions = []
        for sample in samples:
            thickness_text = sample["thickness_text"].get()
            if not thickness_text.strip():
                status.set(f"厚さを入力してください: {sample['csv_path'].name}")
                return
            conditions.append(
                {"csv_path": sample["csv_path"], "thickness_mm": thickness_text}
            )
        try:
            compared = compare_lengths_with_thickness(
                conditions, initial_thickness_text.get()
            )
        except ValueError as error:
            status.set(str(error))
            return
        rows.extend(compared)
        for sample, row in zip(samples, rows):
            for column in result_columns:
                sample["result_text"][column].set(f"{row[column]:.3f}")
        draw_graph()
        save_graph_button.state(["!disabled"])
        status.set("")

    def refresh_inputs() -> None:
        for widget in input_rows.winfo_children():
            widget.destroy()
        headings = (
            "撮影 / CSV",
            "厚さ (mm)",
            "区間長 (mm)",
            "左側辺 (mm)",
            "右側辺 (mm)",
            "累積圧下率 (%)",
            "",
        )
        for column, heading in enumerate(headings):
            width = 24 if column == 0 else 12
            if column == 5:
                width = 14
            if column == 6:
                width = 7
            ttk.Label(input_rows, text=heading, width=width, anchor="w").grid(
                row=0, column=column, sticky="ew", padx=4, pady=4
            )
        input_rows.columnconfigure(0, weight=1)
        for index, sample in enumerate(samples):
            row_number = index + 1
            ttk.Label(
                input_rows, text=sample["csv_path"].name, width=24, anchor="w"
            ).grid(row=row_number, column=0, sticky="ew", padx=4, pady=3)
            ttk.Entry(
                input_rows,
                textvariable=sample["thickness_text"],
                width=12,
                justify="right",
            ).grid(row=row_number, column=1, padx=4, pady=3)
            for column, name in enumerate(result_columns, start=2):
                ttk.Label(
                    input_rows,
                    textvariable=sample["result_text"][name],
                    width=12,
                    anchor="e",
                ).grid(row=row_number, column=column, sticky="ew", padx=4, pady=3)

            def remove_this(sample=sample) -> None:
                samples.remove(sample)
                refresh_inputs()
                update_comparison()

            ttk.Button(input_rows, text="削除", command=remove_this, width=7).grid(
                row=row_number, column=6, padx=4, pady=3
            )

    def add_csvs() -> None:
        existing_paths = []
        for sample in samples:
            existing_paths.append(sample["csv_path"])
        try:
            new_paths = choose_csv_paths(root, output_directory, existing_paths)
        except ValueError as error:
            status.set(str(error))
            return
        if not new_paths:
            return
        for path in new_paths:
            thickness_text = tk.StringVar(master=root)
            thickness_text.trace_add("write", update_comparison)
            result_text = {}
            for column in result_columns:
                result_text[column] = tk.StringVar(master=root, value="—")
            samples.append(
                {
                    "csv_path": path,
                    "thickness_text": thickness_text,
                    "result_text": result_text,
                }
            )
        refresh_inputs()
        update_comparison()

    def save_graph() -> None:
        stem = "length_comparison_thickness"
        if horizontal_axis.get() == "累積圧下率":
            stem += "_reduction"
        if mode.get() == "100mm換算":
            stem += "_100mm"
        output_path = choose_png_path(root, output_directory, stem + ".png")
        if output_path is None:
            return
        try:
            write_graph(
                output_path,
                rows,
                mode.get() == "100mm換算",
                horizontal_axis.get() == "累積圧下率",
                initial_thickness_mm=rows[0]["initial_thickness_mm"],
            )
        except ValueError as error:
            status.set(str(error))
            return
        except OSError:
            status.set(f"保存できません: {output_path.name}")
            return
        status.set(f"保存: {output_path.name}")

    def update_scroll(_event=None) -> None:
        width = max(input_canvas.winfo_width(), input_rows.winfo_reqwidth())
        input_canvas.itemconfigure(input_item, width=width)
        input_canvas.configure(scrollregion=input_canvas.bbox("all"))

    header, sidebar, content = create_layout(root)
    ttk.Button(header, text="CSVを追加", command=add_csvs, padding=(12, 8)).pack(
        side="left"
    )
    ttk.Label(header, textvariable=file_text).pack(side="left", padx=8)
    ttk.Label(header, textvariable=status, wraplength=320).pack(side="right")
    ttk.Label(sidebar, text="初期厚さ (mm)").pack(anchor="w", pady=(0, 4))
    ttk.Entry(
        sidebar, textvariable=initial_thickness_text, width=12, justify="right"
    ).pack(fill="x")
    ttk.Label(
        sidebar,
        text="累積圧下率 = (初期厚さ − 現在の厚さ) ÷ 初期厚さ × 100",
        wraplength=195,
    ).pack(anchor="w", pady=(4, 12))
    ttk.Label(sidebar, text="グラフの表示").pack(anchor="w", pady=(0, 4))
    for label in ("実測長", "100mm換算"):
        ttk.Radiobutton(
            sidebar, text=label, value=label, variable=mode, command=draw_graph
        ).pack(anchor="w", pady=2)
    ttk.Label(sidebar, text="横軸").pack(anchor="w", pady=(12, 4))
    for label in ("撮影順", "累積圧下率"):
        ttk.Radiobutton(
            sidebar,
            text=label,
            value=label,
            variable=horizontal_axis,
            command=draw_graph,
        ).pack(anchor="w", pady=2)
    save_graph_button = ttk.Button(
        sidebar, text="グラフを保存", command=save_graph, padding=(12, 8)
    )
    save_graph_button.pack(fill="x", pady=(12, 4))
    input_frame = ttk.LabelFrame(
        content, text="撮影ごとの厚さと計測値（CSV追加順）", padding=8
    )
    input_frame.pack(fill="x")
    input_frame.columnconfigure(0, weight=1)
    input_canvas = tk.Canvas(input_frame, width=1, height=175, highlightthickness=0)
    input_canvas.grid(row=0, column=0, sticky="nsew")
    vertical = ttk.Scrollbar(input_frame, orient="vertical", command=input_canvas.yview)
    vertical.grid(row=0, column=1, sticky="ns")
    horizontal = ttk.Scrollbar(
        input_frame, orient="horizontal", command=input_canvas.xview
    )
    horizontal.grid(row=1, column=0, sticky="ew")
    input_canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    input_rows = ttk.Frame(input_canvas)
    input_item = input_canvas.create_window(0, 0, window=input_rows, anchor="nw")
    input_canvas.bind("<Configure>", update_scroll)
    input_rows.bind("<Configure>", update_scroll)
    graph_frame = ttk.Frame(content, padding=(0, 8, 0, 0))
    graph_frame.pack(fill="both", expand=True)
    initial_thickness_text.trace_add("write", update_comparison)
    refresh_inputs()
    save_graph_button.state(["disabled"])
    output_directory.mkdir(parents=True, exist_ok=True)
    root.mainloop()


if __name__ == "__main__":
    main()
