"""厚さから求めた理想片側長とCSVの左右側辺長を、表と1枚のグラフで比較する."""

import csv
import math
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from matplotlib import rcParams
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


def positive_value(value: float | str | None, name: str) -> float:
    try:
        number = float(value) if value is not None else math.nan
    except ValueError as error:
        raise ValueError(f"{name}は0より大きい数値で入力してください") from error
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name}は0より大きい有限値が必要です")
    return number


def read_lengths(path: Path) -> dict:
    required = ("image_path", "left_mm", "right_mm")
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if not set(required).issubset(reader.fieldnames or []):
            raise ValueError(f"計測GUIで保存した長さCSVを選んでください: {path.name}")
        saved_rows = list(reader)
    if len(saved_rows) != 1:
        raise ValueError(f"長さCSVは1画像につき1行が必要です: {path.name}")
    saved = saved_rows[0]
    for column in required:
        value = saved[column]
        if value is None or not value.strip():
            raise ValueError(f"空欄を確認してください: {column}: {path.name}")
    image_path = Path(saved["image_path"])
    if not image_path.is_absolute():
        image_path = path.parent / image_path
    left_length = positive_value(saved["left_mm"], f"左側辺長: {path.name}")
    right_length = positive_value(saved["right_mm"], f"右側辺長: {path.name}")
    return {
        "image_path": str(image_path.resolve()),
        "left_mm": left_length,
        "right_mm": right_length,
    }


def compare_lengths(
    samples: list[dict],
    initial_length_mm: float | str | None,
    initial_thickness_mm: float | str | None,
) -> list[dict]:
    initial_length_mm = positive_value(initial_length_mm, "初期区間長 (mm)")
    initial_thickness_mm = positive_value(initial_thickness_mm, "初期厚さ (mm)")
    if not samples:
        raise ValueError("長さCSVを1枚以上追加してください")
    rows = []
    used_paths = []
    for index, sample in enumerate(samples):
        path = Path(sample["csv_path"]).resolve()
        if path in used_paths:
            raise ValueError("同じCSVを重複して指定しないでください")
        used_paths.append(path)
        measurement = read_lengths(path)
        thickness = positive_value(sample["thickness_mm"], f"{path.name}の厚さ (mm)")
        elongation = positive_value(initial_thickness_mm / thickness, "理想伸び倍率")
        ideal_length_mm = positive_value(initial_length_mm * elongation, "理想片側長")
        row = {
            "sample_id": f"{index + 1}. {path.name}",
            "measurement_csv": str(path),
        }
        row.update(measurement)
        row["initial_length_mm"] = initial_length_mm
        row["initial_thickness_mm"] = initial_thickness_mm
        row["thickness_mm"] = thickness
        row["ideal_length_mm"] = ideal_length_mm
        row["delta_left_mm"] = measurement["left_mm"] - ideal_length_mm
        row["delta_right_mm"] = measurement["right_mm"] - ideal_length_mm
        rows.append(row)
    return rows


def check_output(path: Path, rows: list[dict], suffix: str) -> Path:
    if not rows:
        raise ValueError("比較してから保存してください")
    path = path.resolve()
    if path.suffix.lower() != suffix:
        raise ValueError(f"保存先の拡張子は {suffix} にしてください")
    for row in rows:
        if path in (Path(row["measurement_csv"]), Path(row["image_path"])):
            raise ValueError("入力CSV・補正画像と別の保存先を選んでください")
    return path


def write_csv(path: Path, rows: list[dict]) -> None:
    path = check_output(path, rows, ".csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            saved = row.copy()
            for column, value in row.items():
                if isinstance(value, float):
                    saved[column] = f"{value:.12g}"
            writer.writerow(saved)


def create_graph(rows: list[dict]) -> Figure:
    rcParams["font.sans-serif"] = ["Meiryo", "DejaVu Sans"]
    figure = Figure(figsize=(8, 5), layout="constrained")
    axis = figure.subplots()
    positions = []
    left_values = []
    right_values = []
    ideal_values = []
    for index, row in enumerate(rows):
        positions.append(index + 1)
        left_values.append(row["left_mm"])
        right_values.append(row["right_mm"])
        ideal_values.append(row["ideal_length_mm"])
    axis.plot(positions, left_values, marker="o", label="左側辺", color="#d96c17")
    axis.plot(positions, right_values, marker="o", label="右側辺", color="#15927e")
    axis.plot(
        positions,
        ideal_values,
        linestyle="--",
        color="black",
        marker="s",
        label="理想片側長",
    )
    axis.set_xticks(positions)
    axis.set_xlim(0.5, len(rows) + 0.5)
    axis.set_xlabel("撮影順（CSV追加順）")
    axis.set_ylabel("側辺長 (mm)")
    axis.set_title("左右側辺長と厚さから求めた理想片側長")
    axis.grid(alpha=0.3)
    axis.legend()
    return figure


def write_graph(path: Path, rows: list[dict]) -> None:
    path = check_output(path, rows, ".png")
    figure = create_graph(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=160)


def main() -> None:
    output_directory = Path(__file__).resolve().parent / "output"
    root = tk.Tk()
    root.title("左右側辺長のシンプル比較")
    root.geometry("1060x720")
    root.minsize(960, 640)
    samples = []
    rows = []
    graph_canvas: FigureCanvasTkAgg | None = None
    initial_length = tk.StringVar(master=root)
    initial_thickness = tk.StringVar(master=root)
    status = tk.StringVar(
        master=root,
        value="CSVを撮影順に追加し、初期条件と各撮影の厚さを入力してください",
    )

    def invalidate(*_args) -> None:
        nonlocal graph_canvas
        rows.clear()
        table.delete(*table.get_children())
        if graph_canvas is not None:
            graph_canvas.get_tk_widget().destroy()
            graph_canvas.figure.clear()
            graph_canvas = None
        csv_button.state(["disabled"])
        graph_button.state(["disabled"])
        status.set("入力を変更しました。比較し直してください")

    def refresh_inputs() -> None:
        for widget in input_rows.winfo_children():
            widget.destroy()
        for index, sample in enumerate(samples):
            row_frame = ttk.Frame(input_rows, padding=(8, 4))
            row_frame.pack(fill="x")
            row_frame.columnconfigure(0, weight=1)
            ttk.Label(
                row_frame,
                text=f"{index + 1}. {sample['csv_path'].name}",
                wraplength=400,
            ).grid(row=0, column=0, sticky="w", padx=(0, 12))
            ttk.Entry(
                row_frame,
                textvariable=sample["thickness_text"],
                width=10,
                justify="right",
            ).grid(row=0, column=1, padx=(0, 6))
            ttk.Label(row_frame, text="mm").grid(row=0, column=2, padx=(0, 12))

            # 各ボタンが自分の行を覚えるよう、既定引数にサンプルを渡す。
            def remove_this(sample=sample) -> None:
                samples.remove(sample)
                refresh_inputs()
                invalidate()

            ttk.Button(row_frame, text="削除", command=remove_this).grid(
                row=0, column=3
            )

    def add_csvs() -> None:
        selected = filedialog.askopenfilenames(
            parent=root,
            title="長さCSVを撮影順に追加",
            initialdir=output_directory,
            filetypes=[("CSV", "*.csv")],
        )
        existing_paths = []
        for sample in samples:
            existing_paths.append(sample["csv_path"])
        new_paths = []
        try:
            for filename in selected:
                path = Path(filename).resolve()
                if path in existing_paths or path in new_paths:
                    continue
                read_lengths(path)
                new_paths.append(path)
        except (OSError, ValueError, csv.Error) as error:
            status.set(str(error))
            return
        if not new_paths:
            return
        for path in new_paths:
            thickness_text = tk.StringVar(master=root)
            thickness_text.trace_add("write", invalidate)
            samples.append({"csv_path": path, "thickness_text": thickness_text})
        refresh_inputs()
        invalidate()
        status.set(f"{len(samples)}撮影の厚さを入力してください。追加順で比較します")

    def compare() -> None:
        nonlocal rows, graph_canvas
        invalidate()
        conditions = []
        for sample in samples:
            conditions.append(
                {
                    "csv_path": sample["csv_path"],
                    "thickness_mm": sample["thickness_text"].get(),
                }
            )
        try:
            rows = compare_lengths(
                conditions, initial_length.get(), initial_thickness.get()
            )
        except (OSError, ValueError, csv.Error) as error:
            status.set(str(error))
            return
        for row in rows:
            values = [row["sample_id"]]
            for column in columns[1:]:
                value = row[column]
                if column.startswith("delta_"):
                    values.append(f"{value:+.3f}")
                else:
                    values.append(f"{value:.3f}")
            table.insert("", "end", values=values)
        graph_canvas = FigureCanvasTkAgg(create_graph(rows), master=graph_frame)
        graph_canvas.get_tk_widget().pack(fill="both", expand=True)
        graph_canvas.draw()
        csv_button.state(["!disabled"])
        graph_button.state(["!disabled"])
        status.set("比較しました。差は左右それぞれの側辺長 − 理想片側長です")

    def save(suffix: str) -> None:
        selected = filedialog.asksaveasfilename(
            parent=root,
            title="比較結果を保存",
            initialdir=output_directory,
            initialfile=f"length_comparison_simple{suffix}",
            defaultextension=suffix,
            filetypes=[("比較結果", f"*{suffix}")],
            confirmoverwrite=True,
        )
        if not selected:
            return
        try:
            if suffix == ".csv":
                write_csv(Path(selected), rows)
            else:
                write_graph(Path(selected), rows)
        except (OSError, ValueError, csv.Error) as error:
            status.set(str(error))
            return
        status.set(f"保存しました: {Path(selected).name}")

    def save_csv() -> None:
        save(".csv")

    def save_graph() -> None:
        save(".png")

    def update_scroll(_event=None) -> None:
        input_canvas.configure(scrollregion=input_canvas.bbox("all"))

    def resize_inputs(event) -> None:
        input_canvas.itemconfigure(input_item, width=event.width)

    ttk.Label(root, textvariable=status, padding=12, wraplength=900).pack(fill="x")
    body = ttk.Frame(root, padding=(12, 0, 12, 12))
    body.pack(fill="both", expand=True)
    sidebar = ttk.Frame(body)
    sidebar.pack(side="left", fill="y", padx=(0, 16))
    preview = ttk.Frame(body)
    preview.pack(side="left", fill="both", expand=True)
    for label, variable in (
        ("初期区間長 (mm)", initial_length),
        ("初期厚さ (mm)", initial_thickness),
    ):
        ttk.Label(sidebar, text=label).pack(anchor="w", pady=(0, 4))
        ttk.Entry(sidebar, textvariable=variable, width=23).pack(fill="x", pady=(0, 8))
    ttk.Label(
        sidebar,
        text="幅一定・体積一定\n理想長 = 初期区間長\n× 初期厚さ ÷ 撮影時の厚さ",
        wraplength=200,
    ).pack(anchor="w", pady=8)
    ttk.Button(sidebar, text="比較する", command=compare, padding=(12, 8)).pack(
        fill="x", pady=8
    )
    ttk.Button(sidebar, text="CSVを追加", command=add_csvs, padding=(12, 8)).pack(
        fill="x", pady=(8, 4)
    )
    csv_button = ttk.Button(
        sidebar, text="比較CSVを保存", command=save_csv, padding=(12, 8)
    )
    csv_button.pack(fill="x", pady=(16, 4))
    graph_button = ttk.Button(
        sidebar, text="グラフを保存", command=save_graph, padding=(12, 8)
    )
    graph_button.pack(fill="x", pady=4)
    input_frame = ttk.LabelFrame(
        preview, text="撮影（CSV追加順・各行に厚さを入力）", padding=8
    )
    input_frame.pack(fill="x", pady=(0, 8))
    input_canvas = tk.Canvas(input_frame, height=100, highlightthickness=0)
    input_canvas.pack(side="left", fill="both", expand=True)
    input_scroll = ttk.Scrollbar(
        input_frame, orient="vertical", command=input_canvas.yview
    )
    input_scroll.pack(side="right", fill="y")
    input_canvas.configure(yscrollcommand=input_scroll.set)
    input_rows = ttk.Frame(input_canvas)
    input_item = input_canvas.create_window(0, 0, window=input_rows, anchor="nw")
    input_canvas.bind("<Configure>", resize_inputs)
    input_rows.bind("<Configure>", update_scroll)
    table_frame = ttk.Frame(preview)
    table_frame.pack(fill="x", pady=(0, 8))
    columns = (
        "sample_id",
        "ideal_length_mm",
        "left_mm",
        "right_mm",
        "delta_left_mm",
        "delta_right_mm",
    )
    headings = (
        "撮影 / CSV",
        "理想長 (mm)",
        "左側辺 (mm)",
        "右側辺 (mm)",
        "左−理想 (mm)",
        "右−理想 (mm)",
    )
    table = ttk.Treeview(table_frame, columns=columns, show="headings", height=4)
    for column, heading in zip(columns, headings):
        table.heading(column, text=heading)
        table.column(
            column,
            width=150 if column == "sample_id" else 100,
            anchor="w" if column == "sample_id" else "e",
        )
    table.grid(row=0, column=0, sticky="nsew")
    table_frame.columnconfigure(0, weight=1)
    vertical_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=table.yview)
    vertical_scroll.grid(row=0, column=1, sticky="ns")
    horizontal_scroll = ttk.Scrollbar(
        table_frame, orient="horizontal", command=table.xview
    )
    horizontal_scroll.grid(row=1, column=0, sticky="ew")
    table.configure(
        yscrollcommand=vertical_scroll.set, xscrollcommand=horizontal_scroll.set
    )
    graph_frame = ttk.Frame(preview)
    graph_frame.pack(fill="both", expand=True)
    initial_length.trace_add("write", invalidate)
    initial_thickness.trace_add("write", invalidate)
    csv_button.state(["disabled"])
    graph_button.state(["disabled"])
    root.mainloop()


if __name__ == "__main__":
    main()
