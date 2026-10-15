"""局所区間の左右側辺長を、実測厚さから求めた累積圧下率とともに比較する。"""

import csv
import math
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from matplotlib import rcParams
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

OUTPUT_DIRECTORY = "output"


def positive_value(value: float | str | None, name: str) -> float:
    try:
        number = float(value) if value is not None else math.nan
    except ValueError as error:
        raise ValueError(f"{name}は正の数値にしてください") from error
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name}は正の数値にしてください")
    return number


def read_lengths(path: Path) -> dict:
    required_columns = (
        "image_path",
        "mm_per_px",
        "start_y",
        "end_y",
        "left_mm",
        "right_mm",
    )
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if not set(required_columns).issubset(reader.fieldnames or []):
            raise ValueError(f"計測GUIの長さCSVを選んでください: {path.name}")
        saved_rows = list(reader)
    if len(saved_rows) != 1:
        raise ValueError(f"1回の計測を1行に保存したCSVが必要です: {path.name}")
    saved = saved_rows[0]
    for column in required_columns:
        value = saved[column]
        if value is None or not value.strip():
            raise ValueError(f"空欄を確認してください: {column}: {path.name}")
    mm_per_px = positive_value(saved["mm_per_px"], f"mm_per_px: {path.name}")
    try:
        start_y = int(saved["start_y"])
        end_y = int(saved["end_y"])
    except ValueError as error:
        raise ValueError(f"開始y・終了yは整数にしてください: {path.name}") from error
    if not 0 <= start_y < end_y:
        raise ValueError(f"0 ≤ 開始y < 終了yにしてください: {path.name}")
    # 両端の画素中心の間隔なので、行数の「+1」は加えない。
    interval_mm = (end_y - start_y) * mm_per_px
    if not math.isfinite(interval_mm):
        raise ValueError(f"区間長を計算できません: {path.name}")
    image_path = (path.parent / saved["image_path"]).resolve()
    row = {
        "image_path": str(image_path),
        "mm_per_px": mm_per_px,
        "start_y": start_y,
        "end_y": end_y,
        "interval_length_mm": interval_mm,
    }
    for edge in ("left", "right"):
        length_mm = positive_value(saved[f"{edge}_mm"], f"{edge}_mm: {path.name}")
        if length_mm < interval_mm and not math.isclose(
            length_mm, interval_mm, rel_tol=1e-10, abs_tol=1e-10
        ):
            raise ValueError(f"側辺長が区間長より短くなっています: {path.name}")
        per_100mm = length_mm / interval_mm * 100
        if not math.isfinite(per_100mm):
            raise ValueError(f"100mm換算を計算できません: {path.name}")
        row[f"{edge}_mm"] = length_mm
        row[f"{edge}_per_100mm"] = per_100mm
    return row


def compare_lengths(
    samples: list[dict], initial_thickness_mm: float | str | None
) -> list[dict]:
    initial_thickness_mm = positive_value(initial_thickness_mm, "初期厚さ")
    if not samples:
        raise ValueError("長さCSVを1つ以上追加してください")
    used_csv_paths = []
    rows = []
    for index, sample in enumerate(samples):
        path = Path(sample["csv_path"]).resolve()
        if path in used_csv_paths:
            raise ValueError(f"同じCSVを重複して指定しないでください: {path.name}")
        used_csv_paths.append(path)
        row = {
            "order": index + 1,
            "csv_name": path.name,
            "measurement_csv": str(path),
        }
        row.update(read_lengths(path))
        thickness_mm = positive_value(sample["thickness_mm"], f"厚さ: {path.name}")
        reduction_pct = (
            (initial_thickness_mm - thickness_mm) / initial_thickness_mm * 100
        )
        if not math.isfinite(reduction_pct):
            raise ValueError(f"累積圧下率を計算できません: {path.name}")
        row["initial_thickness_mm"] = initial_thickness_mm
        row["thickness_mm"] = thickness_mm
        row["reduction_pct"] = reduction_pct
        rows.append(row)
    return rows


def create_graph(
    rows: list[dict], normalized: bool = False, reduction_axis: bool = False
) -> Figure:
    rcParams["font.sans-serif"] = ["Meiryo", "DejaVu Sans"]
    figure = Figure(figsize=(9, 5), layout="constrained")
    axis = figure.subplots()
    positions = []
    labels = []
    left_values = []
    right_values = []
    interval_values = []
    for row in rows:
        if reduction_axis:
            positions.append(row["reduction_pct"])
        else:
            positions.append(row["order"])
        labels.append(Path(row["csv_name"]).stem)
        interval_values.append(row["interval_length_mm"])
        if normalized:
            left_values.append(row["left_per_100mm"])
            right_values.append(row["right_per_100mm"])
        else:
            left_values.append(row["left_mm"])
            right_values.append(row["right_mm"])
    axis.plot(positions, left_values, marker="o", label="左側辺", color="#d96c17")
    axis.plot(positions, right_values, marker="o", label="右側辺", color="#15927e")
    if normalized:
        axis.axhline(100, linestyle="--", color="gray", label="基準（直線の目安）")
    else:
        axis.plot(
            positions,
            interval_values,
            marker="s",
            linestyle="--",
            color="gray",
            label="基準（直線の目安）",
        )
    if reduction_axis:
        axis.set_xlabel("累積圧下率 (%)")
        axis.margins(x=0.1)
    else:
        axis.set_xticks(positions, labels, rotation=25, ha="right", fontsize=9)
        axis.set_xlim(0.5, len(rows) + 0.5)
        axis.set_xlabel("撮影 / CSV（追加順）")
    if normalized:
        axis.set_ylabel("100mmあたりの側辺長 (mm)")
        axis.set_title("左右側辺長の比較（100mm換算）")
    else:
        axis.set_ylabel("側辺長 (mm)")
        axis.set_title("左右側辺長の比較（実測長）")
    axis.grid(alpha=0.3)
    axis.legend()
    figure.suptitle(f"初期厚さ：{rows[0]['initial_thickness_mm']:g} mm")
    return figure


def write_graph(
    path: Path, rows: list[dict], normalized: bool = False, reduction_axis: bool = False
) -> None:
    if not rows:
        raise ValueError("比較してから保存してください")
    path = path.resolve()
    if path.suffix.lower() != ".png":
        raise ValueError("保存先の拡張子は .png にしてください")
    for row in rows:
        if path in (Path(row["measurement_csv"]), Path(row["image_path"])):
            raise ValueError("入力CSV・補正画像と別の保存先を選んでください")
    figure = create_graph(rows, normalized, reduction_axis)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=160)


def main() -> None:
    script_directory = Path(__file__).resolve().parent
    output_directory = script_directory / OUTPUT_DIRECTORY
    root = tk.Tk()
    root.title("厚さ・累積圧下率と左右長さの比較")
    root.geometry("1100x760")
    root.minsize(960, 640)
    samples: list[dict] = []
    rows: list[dict] = []
    graph_canvas: FigureCanvasTkAgg | None = None
    initial_thickness_text = tk.StringVar(master=root)
    length_mode = tk.StringVar(master=root, value="実測長")
    axis_mode = tk.StringVar(master=root, value="撮影順")
    status = tk.StringVar(master=root, value="CSVを追加してください")
    result_columns = ("interval_length_mm", "left_mm", "right_mm", "reduction_pct")

    def draw_graph() -> None:
        nonlocal graph_canvas
        if graph_canvas is not None:
            graph_canvas.get_tk_widget().destroy()
            graph_canvas.figure.clear()
            graph_canvas = None
        if rows:
            figure = create_graph(
                rows, length_mode.get() == "100mm換算", axis_mode.get() == "累積圧下率"
            )
            graph_canvas = FigureCanvasTkAgg(figure, master=graph_frame)
            graph_canvas.get_tk_widget().pack(fill="both", expand=True)
            graph_canvas.draw()

    def update_comparison(*_args) -> None:
        rows.clear()
        for sample in samples:
            for value in sample["result_text"].values():
                value.set("—")
        draw_graph()
        graph_button.state(["disabled"])
        if not samples:
            status.set("CSVを追加してください")
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
            compared = compare_lengths(conditions, initial_thickness_text.get())
        except (OSError, ValueError, csv.Error) as error:
            status.set(str(error))
            return
        rows.extend(compared)
        for sample, row in zip(samples, rows):
            for column in result_columns:
                sample["result_text"][column].set(f"{row[column]:.3f}")
        draw_graph()
        graph_button.state(["!disabled"])
        status.set(f"比較: {len(rows)}件")

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
            width = 28 if column == 0 else 12
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
                input_rows, text=sample["csv_path"].name, width=28, anchor="w"
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
        selected = filedialog.askopenfilenames(
            parent=root,
            title="長さCSVを比較したい順に追加",
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
        if axis_mode.get() == "累積圧下率":
            stem += "_reduction"
        if length_mode.get() == "100mm換算":
            stem += "_100mm"
        selected = filedialog.asksaveasfilename(
            parent=root,
            title="グラフを保存",
            initialdir=output_directory,
            initialfile=stem + ".png",
            defaultextension=".png",
            filetypes=[("PNG画像", "*.png")],
            confirmoverwrite=True,
        )
        if not selected:
            return
        try:
            write_graph(
                Path(selected),
                rows,
                length_mode.get() == "100mm換算",
                axis_mode.get() == "累積圧下率",
            )
        except (OSError, ValueError) as error:
            status.set(str(error))
            return
        status.set(f"保存: {Path(selected).name}")

    def update_scroll(_event=None) -> None:
        input_canvas.configure(scrollregion=input_canvas.bbox("all"))

    def resize_inputs(event) -> None:
        input_canvas.itemconfigure(input_item, width=event.width)

    toolbar = ttk.Frame(root, padding=12)
    toolbar.pack(fill="x")
    ttk.Button(toolbar, text="CSVを追加", command=add_csvs, padding=(10, 6)).pack(
        side="left", padx=(0, 8)
    )
    graph_button = ttk.Button(toolbar, text="グラフを保存", command=save_graph)
    graph_button.pack(side="left")
    conditions_frame = ttk.Frame(root, padding=(12, 0, 12, 8))
    conditions_frame.pack(fill="x")
    ttk.Label(conditions_frame, text="初期厚さ (mm)").pack(side="left", padx=(0, 8))
    ttk.Entry(
        conditions_frame, textvariable=initial_thickness_text, width=12, justify="right"
    ).pack(side="left")
    ttk.Label(
        conditions_frame,
        text="累積圧下率 = (初期厚さ − 現在の厚さ) ÷ 初期厚さ × 100",
    ).pack(side="left", padx=16)
    options = ttk.Frame(root, padding=(12, 0, 12, 8))
    options.pack(fill="x")
    ttk.Label(options, text="グラフ：").pack(side="left")
    for label in ("実測長", "100mm換算"):
        ttk.Radiobutton(
            options, text=label, value=label, variable=length_mode, command=draw_graph
        ).pack(side="left", padx=(0, 12))
    ttk.Label(options, text="横軸：").pack(side="left", padx=(16, 0))
    for label in ("撮影順", "累積圧下率"):
        ttk.Radiobutton(
            options,
            text=label,
            value=label,
            variable=axis_mode,
            command=draw_graph,
        ).pack(side="left", padx=(0, 12))
    input_frame = ttk.LabelFrame(
        root, text="撮影ごとの厚さと計測値（CSV追加順）", padding=8
    )
    input_frame.pack(fill="x", padx=12, pady=(0, 8))
    input_canvas = tk.Canvas(input_frame, height=175, highlightthickness=0)
    input_canvas.pack(side="left", fill="both", expand=True)
    vertical = ttk.Scrollbar(input_frame, orient="vertical", command=input_canvas.yview)
    vertical.pack(side="right", fill="y")
    input_canvas.configure(yscrollcommand=vertical.set)
    input_rows = ttk.Frame(input_canvas)
    input_item = input_canvas.create_window(0, 0, window=input_rows, anchor="nw")
    input_canvas.bind("<Configure>", resize_inputs)
    input_rows.bind("<Configure>", update_scroll)
    ttk.Label(root, textvariable=status, padding=(12, 0, 12, 8), wraplength=900).pack(
        fill="x"
    )
    graph_frame = ttk.Frame(root, padding=(12, 0, 12, 12))
    graph_frame.pack(fill="both", expand=True)
    initial_thickness_text.trace_add("write", update_comparison)
    refresh_inputs()
    graph_button.state(["disabled"])
    root.mainloop()


if __name__ == "__main__":
    main()
