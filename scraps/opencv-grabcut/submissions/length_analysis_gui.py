"""同じ材料区間の伸び・左右側辺の形状・直前パスからの変化を分析する."""

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
        "image_width",
        "image_height",
        "mm_per_px",
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
            raise ValueError(f"空欄を確認してください: {column}: {path.name}")
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
        raise ValueError(f"画像サイズ・計測範囲を確認してください: {path.name}")
    for edge in ("left", "right", "total"):
        converted = row[f"{edge}_px"] * row["mm_per_px"]
        if not math.isclose(row[f"{edge}_mm"], converted, rel_tol=1e-10, abs_tol=1e-10):
            raise ValueError(f"px値・mm値・倍率が一致しません: {path.name}")
    if not math.isclose(
        row["left_mm"] + row["right_mm"], row["total_mm"], rel_tol=1e-10, abs_tol=1e-10
    ):
        raise ValueError(f"左右の実寸と合計が一致しません: {path.name}")
    interval_px = row["end_y"] - row["start_y"]
    for edge in ("left", "right"):
        side_px = row[f"{edge}_px"]
        if side_px < interval_px and not math.isclose(
            side_px, interval_px, rel_tol=1e-10, abs_tol=1e-10
        ):
            raise ValueError(
                f"側辺長が開始・終了yの間隔より短くなっています: {path.name}"
            )
    image_path = Path(row["image_path"])
    if not image_path.is_absolute():
        image_path = path.parent / image_path
    row["image_path"] = str(image_path.resolve())
    return row


def analyze_lengths(
    samples: list[dict],
    initial_length_mm: float | str | None,
    initial_thickness_mm: float | str | None,
) -> list[dict]:
    initial_length_mm = positive_value(initial_length_mm, "初期区間長 (mm)")
    initial_thickness_mm = positive_value(initial_thickness_mm, "初期厚さ (mm)")
    if not samples:
        raise ValueError("計測GUIで保存した長さCSVを1枚以上追加してください")
    paths = []
    rows = []
    previous = None
    for index, sample in enumerate(samples):
        path = Path(sample["csv_path"]).resolve()
        if path in paths:
            raise ValueError("同じCSVを重複して指定しないでください")
        paths.append(path)
        name = f"{index + 1}. {path.name}"
        thickness = positive_value(sample["thickness_mm"], f"{name}の厚さ (mm)")
        measurement = read_lengths(path)
        elongation = positive_value(initial_thickness_mm / thickness, "理想伸び倍率")
        ideal_length = positive_value(initial_length_mm * elongation, "理想区間長")
        # 両端の画素中心の間隔なので、含まれる行数の「+1」は加えない。
        interval_px = measurement["end_y"] - measurement["start_y"]
        interval_length = positive_value(
            interval_px * measurement["mm_per_px"], "区間長"
        )
        stretch_difference = interval_length - ideal_length
        stretch_pct = stretch_difference / ideal_length * 100
        row = {
            "pass_number": index + 1,
            "sample_id": name,
            "measurement_csv": str(path),
        }
        row.update(measurement)
        row["initial_length_mm"] = initial_length_mm
        row["initial_thickness_mm"] = initial_thickness_mm
        row["thickness_mm"] = thickness
        row["ideal_length_mm"] = ideal_length
        row["interval_length_mm"] = interval_length
        row["stretch_delta_mm"] = stretch_difference
        row["stretch_pct"] = stretch_pct
        for edge in ("left", "right"):
            side_length = measurement[f"{edge}_mm"]
            # CSV保存時の丸めで生じる微小な負値だけを0に揃える。
            excess_length = max(0.0, side_length - interval_length)
            shape_pct = excess_length / interval_length * 100
            row[f"{edge}_excess_mm"] = excess_length
            row[f"{edge}_shape_pct"] = shape_pct
        row["previous_id"] = "" if previous is None else previous["sample_id"]
        for indicator in ("stretch", "left_shape", "right_shape"):
            change = None
            if previous is not None:
                change = row[f"{indicator}_pct"] - previous[f"{indicator}_pct"]
            row[f"previous_delta_{indicator}_pp"] = change
        for column, value in row.items():
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(
                    f"{name}: {column}を計算できません。数値を確認してください"
                )
        rows.append(row)
        previous = row
    return rows


def check_output(path: Path, rows: list[dict], suffix: str) -> Path:
    if not rows:
        raise ValueError("分析してから保存してください")
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
                if value is None:
                    saved[column] = ""
                elif isinstance(value, float):
                    saved[column] = f"{value:.12g}"
            writer.writerow(saved)


def create_graph(rows: list[dict]) -> Figure:
    rcParams["font.sans-serif"] = ["Meiryo", "DejaVu Sans"]
    figure = Figure(figsize=(10, 7), layout="constrained")
    axes = figure.subplots(2, 2, sharex=True)
    positions = []
    stretch_values = []
    left_values = []
    right_values = []
    for row in rows:
        positions.append(row["pass_number"])
        stretch_values.append(row["stretch_pct"])
        left_values.append(row["left_shape_pct"])
        right_values.append(row["right_shape_pct"])
    axes[0, 0].plot(
        positions, stretch_values, marker="o", color="#2864b4", label="伸びの差率"
    )
    axes[0, 0].axhline(0, color="gray", linestyle="--", label="理想：0%")
    axes[0, 0].set_title("伸び方：区間長と理想長の差率")
    axes[0, 1].plot(positions, left_values, marker="o", color="#d96c17", label="左")
    axes[0, 1].plot(positions, right_values, marker="o", color="#15927e", label="右")
    axes[0, 1].axhline(0, color="gray", linestyle="--", label="直線：0%")
    axes[0, 1].set_title("側辺形状：区間長に対する余分な経路")
    for axis in axes[0]:
        axis.set_ylabel("割合 (%)")
        axis.legend(loc="best")
    axes[1, 0].set_title("直前パスからの変化：伸びの差率")
    axes[1, 1].set_title("直前パスからの変化：左右側辺の形状")
    change_positions = []
    stretch_changes = []
    left_positions = []
    right_positions = []
    left_changes = []
    right_changes = []
    for row in rows[1:]:
        position = row["pass_number"]
        change_positions.append(position)
        stretch_changes.append(row["previous_delta_stretch_pp"])
        left_positions.append(position - 0.18)
        right_positions.append(position + 0.18)
        left_changes.append(row["previous_delta_left_shape_pp"])
        right_changes.append(row["previous_delta_right_shape_pp"])
    axes[1, 0].bar(change_positions, stretch_changes, width=0.6, color="#2864b4")
    axes[1, 1].bar(
        left_positions, left_changes, width=0.36, color="#d96c17", label="左"
    )
    axes[1, 1].bar(
        right_positions, right_changes, width=0.36, color="#15927e", label="右"
    )
    axes[1, 1].legend(loc="best")
    for axis in axes[1]:
        axis.axhline(0, color="gray", linewidth=1)
        axis.set_ylabel("変化 (ポイント)")
        axis.set_xlabel("圧延パス（CSV追加順・1回目は前回なし）")
    for axis in axes.flat:
        axis.set_xticks(positions)
        axis.set_xlim(0.5, len(rows) + 0.5)
        axis.grid(axis="y", alpha=0.3)
    figure.suptitle(
        f"幅一定・体積一定 | 初期区間長 {rows[0]['initial_length_mm']:g}mm / "
        f"初期厚さ {rows[0]['initial_thickness_mm']:g}mm"
    )
    return figure


def write_graph(path: Path, rows: list[dict]) -> None:
    path = check_output(path, rows, ".png")
    figure = create_graph(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=160)


def main() -> None:
    output_directory = Path(__file__).resolve().parent / "output"
    root = tk.Tk()
    root.title("材料区間の伸びと側辺形状の分析")
    root.geometry("1320x920")
    root.minsize(1100, 840)
    samples = []
    rows = []
    graph_canvas: FigureCanvasTkAgg | None = None
    initial_length = tk.StringVar(master=root)
    initial_thickness = tk.StringVar(master=root)
    count_text = tk.StringVar(master=root, value="0パス")
    status = tk.StringVar(
        master=root, value="CSVを圧延パス順に追加し、初期条件と厚さを入力してください"
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
        status.set("条件を変更しました。分析し直してください")

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
                wraplength=450,
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
                status.set(f"除外しました: {sample['csv_path'].name}")

            ttk.Button(row_frame, text="削除", command=remove_this).grid(
                row=0, column=3
            )
        count_text.set(f"{len(samples)}パス")

    def add_csvs() -> None:
        selected = filedialog.askopenfilenames(
            parent=root,
            title="対応する材料区間の長さCSVをパス順に追加",
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
        status.set("各パスの厚さを入力してください。追加順で直前パスと比較します")

    def analyze() -> None:
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
            rows = analyze_lengths(
                conditions, initial_length.get(), initial_thickness.get()
            )
        except (OSError, ValueError, csv.Error) as error:
            status.set(str(error))
            return
        for row in rows:
            values = [row["sample_id"]]
            for column in columns[1:]:
                value = row[column]
                if column == "stretch_pct":
                    values.append(f"{value:+.3f}")
                else:
                    values.append(f"{value:.3f}")
            table.insert("", "end", values=values)
        graph_canvas = FigureCanvasTkAgg(create_graph(rows), master=graph_frame)
        graph_canvas.get_tk_widget().pack(fill="both", expand=True)
        graph_canvas.draw()
        csv_button.state(["!disabled"])
        graph_button.state(["!disabled"])
        status.set("分析しました。下段は割合の差（ポイント）です。1回目は前回なし")

    def save(suffix: str) -> None:
        selected = filedialog.asksaveasfilename(
            parent=root,
            title="分析結果を保存",
            initialdir=output_directory,
            initialfile=f"length_analysis{suffix}",
            defaultextension=suffix,
            filetypes=[("分析結果", f"*{suffix}")],
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
    ttk.Label(toolbar, textvariable=status, wraplength=650).pack(side="right")
    body = ttk.Frame(root, padding=(12, 0, 12, 12))
    body.pack(fill="both", expand=True)
    sidebar = ttk.Frame(body)
    sidebar.pack(side="left", fill="y", padx=(0, 16))
    preview = ttk.Frame(body)
    preview.pack(side="left", fill="both", expand=True)
    ttk.Label(sidebar, text="理想スラブの初期条件").pack(anchor="w", pady=(0, 8))
    for label, variable in (
        ("初期区間長 (mm)", initial_length),
        ("初期厚さ (mm)", initial_thickness),
    ):
        ttk.Label(sidebar, text=label).pack(anchor="w", pady=(4, 2))
        ttk.Entry(sidebar, textvariable=variable, width=23).pack(fill="x", pady=(0, 8))
    ttk.Label(
        sidebar,
        text="幅一定・体積一定\n理想長 = 初期区間長\n× 初期厚さ ÷ 各パスの厚さ\n\n区間長 = 開始・終了yの間隔\nをmmへ換算\n\n伸びの差率 (%)\n= (区間長 ÷ 理想長 − 1) × 100\n\n側辺形状 (%)\n= (側辺長 ÷ 区間長 − 1) × 100\n\n前回変化は割合の差\n単位：ポイント",
        wraplength=215,
        justify="left",
    ).pack(anchor="w", pady=8)
    ttk.Button(sidebar, text="分析する", command=analyze, padding=(12, 8)).pack(
        fill="x", pady=(8, 4)
    )
    csv_button = ttk.Button(
        sidebar, text="分析CSVを保存", command=save_csv, padding=(12, 8)
    )
    csv_button.pack(fill="x", pady=4)
    graph_button = ttk.Button(
        sidebar, text="分析グラフを保存", command=save_graph, padding=(12, 8)
    )
    graph_button.pack(fill="x", pady=4)
    input_frame = ttk.LabelFrame(
        preview, text="圧延パス（CSV追加順・各行に厚さを入力）", padding=8
    )
    input_frame.pack(fill="x", pady=(0, 8))
    input_canvas = tk.Canvas(input_frame, height=120, highlightthickness=0)
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
    table_frame = ttk.LabelFrame(preview, text="長さと分析指標", padding=8)
    table_frame.pack(fill="x", pady=(0, 8))
    columns = (
        "sample_id",
        "ideal_length_mm",
        "interval_length_mm",
        "left_mm",
        "right_mm",
        "stretch_pct",
        "left_shape_pct",
        "right_shape_pct",
    )
    headings = (
        "パス / CSV",
        "理想長 (mm)",
        "区間長 (mm)",
        "左側辺 (mm)",
        "右側辺 (mm)",
        "伸び差率 (%)",
        "左形状 (%)",
        "右形状 (%)",
    )
    table = ttk.Treeview(table_frame, columns=columns, show="headings", height=4)
    for column, heading in zip(columns, headings):
        table.heading(column, text=heading)
        table.column(
            column,
            width=180 if column == "sample_id" else 100,
            anchor="w" if column == "sample_id" else "e",
        )
    table.grid(row=0, column=0, sticky="nsew")
    table_frame.columnconfigure(0, weight=1)
    table_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=table.yview)
    table_scroll.grid(row=0, column=1, sticky="ns")
    horizontal_scroll = ttk.Scrollbar(
        table_frame, orient="horizontal", command=table.xview
    )
    horizontal_scroll.grid(row=1, column=0, sticky="ew")
    table.configure(
        yscrollcommand=table_scroll.set, xscrollcommand=horizontal_scroll.set
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
