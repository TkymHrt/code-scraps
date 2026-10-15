"""計測済みの長さCSVと撮影時の厚さから、複数撮影を理想スラブと比較する."""

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
    required = (
        "image_path",
        "mm_per_px",
        "image_width",
        "image_height",
        "start_y",
        "end_y",
        "left_px",
        "left_mm",
        "right_px",
        "right_mm",
        "total_px",
        "total_mm",
    )
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if not set(required).issubset(reader.fieldnames or []):
            raise ValueError(f"計測GUIで保存した長さCSVを選んでください: {path.name}")
        saved_rows = list(reader)
    if len(saved_rows) != 1:
        raise ValueError(f"長さCSVは1画像につき1行が必要です: {path.name}")
    saved = saved_rows[0]
    row: dict = {}
    for column in required:
        value = saved[column]
        if value is None or not value.strip():
            raise ValueError(f"空欄のある項目を確認してください: {column}: {path.name}")
        row[column] = value
    for column in (
        "mm_per_px",
        "left_px",
        "left_mm",
        "right_px",
        "right_mm",
        "total_px",
        "total_mm",
    ):
        row[column] = positive_value(row[column], f"{column}: {path.name}")
    try:
        for column in ("image_width", "image_height", "start_y", "end_y"):
            row[column] = int(row[column])
    except ValueError as error:
        raise ValueError(
            f"画像サイズ・計測範囲の数値を確認してください: {path.name}"
        ) from error
    if (
        row["image_width"] < 2
        or row["image_height"] < 2
        or not 0 <= row["start_y"] < row["end_y"] < row["image_height"]
    ):
        raise ValueError(
            f"長さCSVの画像サイズ・計測範囲を確認してください: {path.name}"
        )
    for edge in ("left", "right", "total"):
        if not math.isclose(
            row[f"{edge}_mm"],
            row[f"{edge}_px"] * row["mm_per_px"],
            rel_tol=1e-10,
            abs_tol=1e-10,
        ):
            raise ValueError(f"長さCSVのpx値・mm値・倍率が一致しません: {path.name}")
    if not math.isclose(
        row["left_mm"] + row["right_mm"], row["total_mm"], rel_tol=1e-10, abs_tol=1e-10
    ):
        raise ValueError(f"左右の実寸と合計が一致しません: {path.name}")
    image_path = Path(row["image_path"])
    if not image_path.is_absolute():
        image_path = path.parent / image_path
    row["image_path"] = str(image_path.resolve())
    return row


def compare_lengths(
    samples: list[dict],
    initial_length_mm: float | str | None,
    initial_thickness_mm: float | str | None,
) -> list[dict]:
    initial_length_mm = positive_value(initial_length_mm, "初期区間長 (mm)")
    initial_thickness_mm = positive_value(initial_thickness_mm, "初期厚さ (mm)")
    if not samples:
        raise ValueError("計測GUIで保存した長さCSVを1枚以上追加してください")
    names = []
    paths = []
    rows = []
    previous = None
    for sample in samples:
        name = sample["sample_id"].strip()
        if not name or name in names:
            raise ValueError("撮影名は空欄にせず、重複しない名前にしてください")
        path = Path(sample["csv_path"]).resolve()
        if path in paths:
            raise ValueError("同じCSVを重複して指定しないでください")
        names.append(name)
        paths.append(path)
        thickness = positive_value(sample["thickness_mm"], f"{name}の厚さ (mm)")
        measurement = read_lengths(path)
        elongation = positive_value(
            initial_thickness_mm / thickness, f"{name}の伸び倍率"
        )
        ideal_length = positive_value(
            initial_length_mm * elongation, f"{name}の理想区間長"
        )
        row = {
            "sample_id": name,
            "measurement_csv": str(path),
        }
        row.update(measurement)
        row["initial_length_mm"] = initial_length_mm
        row["initial_thickness_mm"] = initial_thickness_mm
        row["thickness_mm"] = thickness
        row["elongation"] = elongation
        row["ideal_length_mm"] = ideal_length
        row["previous_id"] = previous["sample_id"] if previous is not None else ""
        for edge in ("left", "right", "total"):
            measured = measurement[f"{edge}_mm"]
            ideal = ideal_length * 2 if edge == "total" else ideal_length
            ideal = positive_value(ideal, f"{name}の理想側辺長")
            difference = measured - ideal
            ratio = difference / ideal * 100
            if not math.isfinite(ratio):
                raise ValueError(f"{name}: 理想長との差率を計算できません")
            previous_difference = None
            if previous is not None:
                previous_difference = measured - previous[f"{edge}_mm"]
            row[f"{edge}_mm"] = measured
            row[f"delta_{edge}_mm"] = difference
            row[f"delta_{edge}_pct"] = ratio
            row[f"previous_delta_{edge}_mm"] = previous_difference
        rows.append(row)
        previous = row
    return rows


def check_output(path: Path, rows: list[dict], suffix: str) -> Path:
    if not rows:
        raise ValueError("比較してから保存してください")
    path = path.resolve()
    if path.suffix.lower() != suffix:
        raise ValueError(f"保存先の拡張子は {suffix} にしてください")
    for row in rows:
        if path in (
            Path(row["measurement_csv"]),
            Path(row["image_path"]),
        ):
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
                if value is None:
                    saved[column] = ""
                elif isinstance(value, float):
                    saved[column] = f"{value:.12g}"
            writer.writerow(saved)


def create_graph(rows: list[dict]) -> Figure:
    rcParams["font.sans-serif"] = ["Meiryo", "DejaVu Sans"]
    figure = Figure(figsize=(max(8, len(rows) * 0.9), 9), layout="constrained")
    axes = figure.subplots(3, 1, sharex=True)
    positions = list(range(len(rows)))
    names = []
    ideal_lengths = []
    for row in rows:
        names.append(row["sample_id"])
        ideal_lengths.append(row["ideal_length_mm"])
    for axis, prefix, suffix, title in (
        (axes[0], "", "mm", "実寸側辺長と理想区間長"),
        (axes[1], "delta_", "pct", "理想長との差率"),
        (axes[2], "previous_delta_", "mm", "前回からの実寸側辺長の変化"),
    ):
        for edge, label in (("left", "左"), ("right", "右"), ("total", "左右合計")):
            if not prefix and edge == "total":
                continue
            values = []
            for row in rows:
                value = row[f"{prefix}{edge}_{suffix}"]
                values.append(math.nan if value is None else value)
            axis.plot(positions, values, marker="o", label=label)
        if not prefix:
            axis.plot(
                positions,
                ideal_lengths,
                linestyle="--",
                color="black",
                marker="s",
                label="理想区間長",
            )
            axis.set_ylim(bottom=0)
            axis.set_ylabel("長さ (mm)")
        else:
            axis.axhline(0, color="gray", linewidth=1)
            axis.set_ylabel("差率 (%)" if suffix == "pct" else "差 (mm)")
        axis.set_title(title)
        axis.grid(alpha=0.3)
        axis.legend()
    axes[2].set_xticks(
        positions,
        names,
        rotation=45 if len(rows) > 4 else 0,
        ha="right" if len(rows) > 4 else "center",
    )
    axes[2].set_xlabel("撮影順（対応する同じ材料区間）")
    figure.suptitle(
        f"幅一定・体積一定の基準スラブ | 初期区間長 {rows[0]['initial_length_mm']:g}mm / "
        f"初期厚さ {rows[0]['initial_thickness_mm']:g}mm"
    )
    return figure


def write_graph(path: Path, rows: list[dict]) -> None:
    path = check_output(path, rows, ".png")
    figure = create_graph(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=160)


def main() -> None:
    directory = Path(__file__).resolve().parent
    output_directory = directory / "output"
    root = tk.Tk()
    root.title("長さと理想スラブの比較")
    root.geometry("1120x800")
    root.minsize(1000, 760)
    samples = []
    rows = []
    graph_canvas: FigureCanvasTkAgg | None = None
    initial_length = tk.StringVar(master=root)
    initial_thickness = tk.StringVar(master=root)
    count_text = tk.StringVar(master=root, value="0撮影")
    status = tk.StringVar(
        master=root, value="CSVを追加し、初期条件と各撮影の厚さを入力してください"
    )

    def invalidate(*_args) -> None:
        nonlocal graph_canvas
        rows.clear()
        for table in result_tables.values():
            table.delete(*table.get_children())
        if graph_canvas is not None:
            graph_canvas.get_tk_widget().destroy()
            graph_canvas.figure.clear()
            graph_canvas = None
        csv_button.state(["disabled"])
        graph_button.state(["disabled"])
        status.set("条件を変更しました。比較し直してください")

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
                wraplength=360,
            ).grid(row=0, column=0, sticky="w", padx=(0, 12))
            ttk.Entry(
                row_frame,
                textvariable=sample["thickness_text"],
                width=10,
                justify="right",
            ).grid(row=0, column=1, padx=(0, 6))
            ttk.Label(row_frame, text="mm").grid(row=0, column=2, padx=(0, 12))

            # 各ボタンが自分の行を覚えるよう、既定引数にそのサンプルを渡す。
            def remove_this(sample=sample) -> None:
                samples.remove(sample)
                refresh_inputs()
                invalidate()
                status.set(f"除外しました: {sample['csv_path'].name}")

            ttk.Button(row_frame, text="削除", command=remove_this).grid(
                row=0, column=3
            )
        count_text.set(f"{len(samples)}撮影")

    def add_csvs() -> None:
        selected = filedialog.askopenfilenames(
            parent=root,
            title="対応する材料区間の長さCSVを追加",
            initialdir=output_directory,
            filetypes=[("CSV", "*.csv")],
        )
        if not selected:
            return
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
            status.set("同じCSVは重複して追加しません")
            return
        for path in new_paths:
            thickness_text = tk.StringVar(master=root)
            thickness_text.trace_add("write", invalidate)
            samples.append({"csv_path": path, "thickness_text": thickness_text})
        refresh_inputs()
        invalidate()
        status.set("各CSVの厚さを入力して比較してください。表示順で比較します")

    def compare() -> None:
        nonlocal rows, graph_canvas
        invalidate()
        conditions = []
        for index, sample in enumerate(samples):
            conditions.append(
                {
                    "sample_id": f"{index + 1}. {sample['csv_path'].name}",
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
            for key, table in result_tables.items():
                values = [row["sample_id"]]
                if key == "length":
                    values.append(f"{row['ideal_length_mm']:.3f}")
                    prefix, suffix = "", "mm"
                elif key == "ideal":
                    prefix, suffix = "delta_", "mm"
                elif key == "ratio":
                    prefix, suffix = "delta_", "pct"
                else:
                    prefix, suffix = "previous_delta_", "mm"
                for edge in ("left", "right", "total"):
                    value = row[f"{prefix}{edge}_{suffix}"]
                    if value is None:
                        text = "—"
                    elif prefix:
                        text = f"{value:+.3f}"
                    else:
                        text = f"{value:.3f}"
                    values.append(text)
                table.insert("", "end", values=values)
        graph_canvas = FigureCanvasTkAgg(create_graph(rows), master=graph_frame)
        graph_canvas.get_tk_widget().pack(fill="both", expand=True)
        graph_canvas.draw()
        csv_button.state(["!disabled"])
        graph_button.state(["!disabled"])
        status.set("比較しました。差は実寸−理想、前回差は実寸−前回です")

    def save(suffix: str) -> None:
        if not rows:
            return
        selected = filedialog.asksaveasfilename(
            parent=root,
            title="比較結果を保存",
            initialdir=output_directory,
            initialfile=f"length_comparison{suffix}",
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

    toolbar = ttk.Frame(root, padding=12)
    toolbar.pack(fill="x")
    ttk.Button(toolbar, text="CSVを追加", command=add_csvs, padding=(12, 8)).pack(
        side="left"
    )
    ttk.Label(toolbar, textvariable=count_text).pack(side="left", padx=12)
    ttk.Label(toolbar, textvariable=status, wraplength=540).pack(side="right")
    body = ttk.Frame(root, padding=(12, 0, 12, 12))
    body.pack(fill="both", expand=True)
    sidebar = ttk.Frame(body, width=220)
    sidebar.pack(side="left", fill="y", padx=(0, 16))
    preview = ttk.Frame(body)
    preview.pack(side="left", fill="both", expand=True)

    ttk.Label(sidebar, text="基準スラブ").pack(anchor="w", pady=(0, 8))
    for label, variable in (
        ("初期区間長 (mm)", initial_length),
        ("初期厚さ (mm)", initial_thickness),
    ):
        ttk.Label(sidebar, text=label).pack(anchor="w", pady=(4, 2))
        ttk.Entry(sidebar, textvariable=variable, width=22).pack(fill="x", pady=(0, 8))
    ttk.Label(
        sidebar, text="幅一定・体積一定\n理想長 = 初期区間長 × 初期厚さ\n÷ 各撮影の厚さ"
    ).pack(anchor="w", pady=8)
    ttk.Button(sidebar, text="比較する", command=compare, padding=(12, 8)).pack(
        fill="x", pady=(8, 4)
    )
    csv_button = ttk.Button(
        sidebar, text="比較CSVを保存", command=save_csv, padding=(12, 8)
    )
    csv_button.pack(fill="x", pady=4)
    graph_button = ttk.Button(
        sidebar, text="推移グラフを保存", command=save_graph, padding=(12, 8)
    )
    graph_button.pack(fill="x", pady=4)

    input_frame = ttk.LabelFrame(
        preview, text="撮影（追加順・各行に厚さを入力）", padding=8
    )
    input_frame.pack(fill="x", pady=(0, 12))
    input_canvas = tk.Canvas(input_frame, height=160, highlightthickness=0)
    input_canvas.pack(side="left", fill="both", expand=True)
    input_scroll = ttk.Scrollbar(
        input_frame, orient="vertical", command=input_canvas.yview
    )
    input_scroll.pack(side="right", fill="y")
    input_canvas.configure(yscrollcommand=input_scroll.set)
    input_rows = ttk.Frame(input_canvas)
    input_item = input_canvas.create_window(0, 0, window=input_rows, anchor="nw")
    input_rows.bind("<Configure>", update_scroll)
    input_canvas.bind("<Configure>", resize_inputs)

    notebook = ttk.Notebook(preview)
    notebook.pack(fill="both", expand=True)
    result_tables = {}
    for key, title, unit in (
        ("length", "実寸", "mm"),
        ("ideal", "理想との差", "mm"),
        ("ratio", "差率", "%"),
        ("previous", "前回との差", "mm"),
    ):
        frame = ttk.Frame(notebook)
        notebook.add(frame, text=title)
        columns = ["name"]
        if key == "length":
            columns.append("ideal")
        columns.extend(("left", "right", "total"))
        table = ttk.Treeview(frame, columns=columns, show="headings", height=5)
        for column in columns:
            if column == "name":
                label = "撮影"
            elif column == "ideal":
                label = "理想片側長 (mm)"
            else:
                labels = {"left": "左", "right": "右", "total": "左右合計"}
                label = f"{labels[column]} ({unit})"
            table.heading(column, text=label)
            table.column(
                column,
                width=180 if column == "name" else 120,
                anchor="w" if column == "name" else "e",
            )
        table.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=table.yview)
        scrollbar.pack(side="right", fill="y")
        table.configure(yscrollcommand=scrollbar.set)
        result_tables[key] = table
    graph_frame = ttk.Frame(notebook)
    notebook.add(graph_frame, text="推移グラフ")

    initial_length.trace_add("write", invalidate)
    initial_thickness.trace_add("write", invalidate)
    csv_button.state(["disabled"])
    graph_button.state(["disabled"])
    output_directory.mkdir(parents=True, exist_ok=True)
    root.mainloop()


if __name__ == "__main__":
    main()
