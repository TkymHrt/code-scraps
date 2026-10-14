"""校正済みの長さCSVと撮影時の厚さから、複数撮影を理想スラブと比較する."""

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


def read_calibrated_lengths(path: Path) -> dict:
    required = (
        "input_csv",
        "image_path",
        "reference_mm",
        "reference_px",
        "mm_per_px",
        "reference_x1",
        "reference_y1",
        "reference_x2",
        "reference_y2",
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
            raise ValueError(
                f"校正GUIで保存したcalibrated_lengths.csvを選んでください: {path}"
            )
        saved_rows = list(reader)
    if len(saved_rows) != 1:
        raise ValueError(f"校正済みCSVは1画像につき1行が必要です: {path}")
    saved = saved_rows[0]
    row: dict = {}
    for column in required:
        value = saved[column]
        if value is None or not value.strip():
            raise ValueError(f"空欄のある項目を確認してください: {column}: {path}")
        row[column] = value
    for column in (
        "reference_mm",
        "reference_px",
        "mm_per_px",
        "left_px",
        "left_mm",
        "right_px",
        "right_mm",
        "total_px",
        "total_mm",
    ):
        row[column] = positive_value(row[column], f"{column}: {path}")
    try:
        for column in ("image_width", "image_height", "start_y", "end_y"):
            row[column] = int(row[column])
        for column in ("reference_x1", "reference_y1", "reference_x2", "reference_y2"):
            row[column] = float(row[column])
            if not math.isfinite(row[column]):
                raise ValueError("基準点の座標は有限値が必要です")
    except ValueError as error:
        raise ValueError(
            f"画像サイズ・計測範囲・基準点の数値を確認してください: {path}"
        ) from error
    if (
        row["image_width"] < 2
        or row["image_height"] < 2
        or not 0 <= row["start_y"] < row["end_y"] < row["image_height"]
    ):
        raise ValueError(f"校正済みCSVの画像サイズ・計測範囲を確認してください: {path}")
    for edge in ("left", "right", "total"):
        if not math.isclose(
            row[f"{edge}_mm"],
            row[f"{edge}_px"] * row["mm_per_px"],
            rel_tol=1e-10,
            abs_tol=1e-10,
        ):
            raise ValueError(f"校正済みCSVのpx値・mm値・倍率が一致しません: {path}")
    # 03の左右・合計には、丸めによる最大0.01pxの差がある。
    tolerance_mm = 0.011 * row["mm_per_px"] + 1e-10
    if abs(row["left_mm"] + row["right_mm"] - row["total_mm"]) > tolerance_mm:
        raise ValueError(f"左右の実寸と合計が一致しません: {path}")
    for column in ("input_csv", "image_path"):
        row[column] = str(Path(row[column]).resolve())
    return row


def compare_lengths(
    samples: list[dict],
    initial_length_mm: float | str | None,
    initial_thickness_mm: float | str | None,
) -> list[dict]:
    initial_length_mm = positive_value(initial_length_mm, "初期区間長 (mm)")
    initial_thickness_mm = positive_value(initial_thickness_mm, "初期厚さ (mm)")
    if not samples:
        raise ValueError("校正済みの長さCSVを1枚以上追加してください")
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
        measurement = read_calibrated_lengths(path)
        elongation = positive_value(
            initial_thickness_mm / thickness, f"{name}の伸び倍率"
        )
        ideal_length = positive_value(
            initial_length_mm * elongation, f"{name}の理想区間長"
        )
        row = {
            "sample_id": name,
            "calibrated_csv": str(path),
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
            Path(row["calibrated_csv"]),
            Path(row["input_csv"]),
            Path(row["image_path"]),
        ):
            raise ValueError("入力CSV・校正画像と別の保存先を選んでください")
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
    root = tk.Tk()
    root.title("校正済み長さと理想スラブの比較")
    root.geometry("1160x820")
    root.minsize(1060, 760)
    samples = []
    rows = []
    graph_window = None
    initial_length = tk.StringVar()
    initial_thickness = tk.StringVar()
    sample_name = tk.StringVar()
    sample_thickness = tk.StringVar()
    selected_csv = tk.StringVar()
    selected_image = tk.StringVar()
    status = tk.StringVar(
        value="初期区間長・初期厚さを入れ、対応する同じ材料区間の校正済みCSVを追加してください"
    )

    def invalidate_result() -> None:
        nonlocal graph_window
        if graph_window is not None:
            graph_window.destroy()
            graph_window = None
        rows.clear()
        for table in result_tables.values():
            table.delete(*table.get_children())
        for button in (preview_button, csv_button, graph_button):
            button.state(["disabled"])

    def model_changed(*args) -> None:
        invalidate_result()
        status.set("初期スラブの条件を変更しました。比較し直してください")

    def select_sample(event=None) -> None:
        selection = input_table.selection()
        if len(selection) == 1:
            sample = samples[int(selection[0])]
            sample_name.set(sample["sample_id"])
            thickness = sample["thickness_mm"]
            sample_thickness.set("" if thickness is None else f"{thickness:g}")
            selected_csv.set(str(sample["csv_path"]))
            selected_image.set(sample["measurement"]["image_path"])
        else:
            sample_name.set("")
            sample_thickness.set("")
            selected_csv.set("")
            selected_image.set("")

    def refresh_inputs(selection: int | None = None) -> None:
        input_table.delete(*input_table.get_children())
        for index, sample in enumerate(samples):
            path = sample["csv_path"]
            short_path = f"{path.parent.parent.name}/{path.parent.name}/{path.name}"
            thickness = sample["thickness_mm"]
            factor = f"{sample['measurement']['mm_per_px']:.8g}"
            input_table.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    index + 1,
                    sample["sample_id"],
                    "未入力" if thickness is None else f"{thickness:g}",
                    factor,
                    short_path,
                ),
            )
        if selection is not None:
            input_table.selection_set(str(selection))
            input_table.see(str(selection))
        select_sample()

    def add_csvs() -> None:
        selected = filedialog.askopenfilenames(
            parent=root,
            title="対応する同じ材料区間の校正済みCSVを選ぶ",
            initialdir=directory,
            filetypes=[("CSV", "*.csv")],
        )
        if not selected:
            return
        existing_paths = []
        names = []
        for sample in samples:
            existing_paths.append(sample["csv_path"])
            names.append(sample["sample_id"])
        new_paths = []
        measurements = []
        try:
            for filename in selected:
                path = Path(filename).resolve()
                if path in existing_paths or path in new_paths:
                    continue
                measurement = read_calibrated_lengths(path)
                new_paths.append(path)
                measurements.append(measurement)
        except (OSError, ValueError, csv.Error) as error:
            status.set(str(error))
            return
        if not new_paths:
            status.set("同じCSVは重複して追加しません")
            return
        for path, measurement in zip(new_paths, measurements):
            number = len(samples) + 1
            name = f"撮影{number:02d}"
            while name in names:
                number += 1
                name = f"撮影{number:02d}"
            samples.append(
                {
                    "sample_id": name,
                    "csv_path": path,
                    "thickness_mm": None,
                    "measurement": measurement,
                }
            )
            names.append(name)
        refresh_inputs()
        invalidate_result()
        status.set("各行を選び、撮影名と厚さを入力・適用して比較してください")

    def remove_samples() -> None:
        selection = input_table.selection()
        if not selection:
            status.set("削除する行を選んでください")
            return
        indices = []
        for item in selection:
            indices.append(int(item))
        for index in sorted(indices, reverse=True):
            del samples[index]
        refresh_inputs()
        invalidate_result()
        status.set(f"選択したCSVを削除しました。残り{len(samples)}枚です")

    def move_sample(direction: int) -> None:
        selection = input_table.selection()
        if len(selection) != 1:
            status.set("移動する行を1つ選んでください")
            return
        index = int(selection[0])
        new_index = index + direction
        if not 0 <= new_index < len(samples):
            return
        moved = samples[index]
        samples[index] = samples[new_index]
        samples[new_index] = moved
        refresh_inputs(new_index)
        invalidate_result()
        status.set("撮影順を変更しました。比較し直してください")

    def move_up() -> None:
        move_sample(-1)

    def move_down() -> None:
        move_sample(1)

    def apply_sample() -> None:
        selection = input_table.selection()
        if len(selection) != 1:
            status.set("条件を設定する行を1つ選んでください")
            return
        index = int(selection[0])
        name = sample_name.get().strip()
        if not name:
            status.set("撮影名を入力してください")
            return
        for other_index, sample in enumerate(samples):
            if other_index != index and sample["sample_id"] == name:
                status.set("撮影名が重複しています")
                return
        try:
            thickness = positive_value(sample_thickness.get(), "撮影時の厚さ (mm)")
        except ValueError as error:
            status.set(str(error))
            return
        if (
            samples[index]["sample_id"] == name
            and samples[index]["thickness_mm"] == thickness
        ):
            return
        samples[index]["sample_id"] = name
        samples[index]["thickness_mm"] = thickness
        refresh_inputs(index)
        invalidate_result()
        status.set("撮影名と厚さを設定しました。比較し直してください")

    def compare() -> None:
        nonlocal rows
        invalidate_result()
        try:
            rows = compare_lengths(
                samples, initial_length.get(), initial_thickness.get()
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
        for button in (preview_button, csv_button, graph_button):
            button.state(["!disabled"])
        status.set(
            "比較しました。理想との差は「実寸 − 理想」、前回差は「実寸 − 前回の実寸」です"
        )

    def save(suffix: str) -> None:
        if not rows:
            return
        selected = filedialog.asksaveasfilename(
            parent=root,
            title="スラブ基準の比較結果を保存",
            initialdir=directory,
            initialfile=f"slab_length_comparison{suffix}",
            defaultextension=suffix,
            filetypes=[("比較結果", f"*{suffix}")],
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
        status.set(f"保存しました: {selected}")

    def save_csv() -> None:
        save(".csv")

    def save_graph() -> None:
        save(".png")

    def show_graph() -> None:
        nonlocal graph_window
        if not rows:
            return
        if graph_window is not None:
            graph_window.lift()
            return
        window = tk.Toplevel(root)
        graph_window = window
        window.title("理想スラブと実寸の推移")
        width = min(1100, root.winfo_screenwidth() - 80)
        height = min(900, root.winfo_screenheight() - 120)
        left = max(0, (root.winfo_screenwidth() - width) // 2)
        window.geometry(f"{width}x{height}+{left}+20")
        window.minsize(800, 650)
        figure = create_graph(rows)
        canvas = FigureCanvasTkAgg(figure, master=window)
        canvas.get_tk_widget().pack(fill="both", expand=True)
        window.update_idletasks()
        canvas.draw()

        def close_graph() -> None:
            nonlocal graph_window
            window.destroy()
            graph_window = None

        window.protocol("WM_DELETE_WINDOW", close_graph)

    model = ttk.Frame(root, padding=12)
    model.pack(fill="x")
    ttk.Label(model, text="初期区間長 (mm)").pack(side="left", padx=(0, 8))
    ttk.Entry(model, textvariable=initial_length, width=16).pack(side="left")
    ttk.Label(model, text="初期厚さ (mm)").pack(side="left", padx=(24, 8))
    ttk.Entry(model, textvariable=initial_thickness, width=16).pack(side="left")
    ttk.Label(
        root,
        text="理想の片側長 = 初期区間長 × 初期厚さ ÷ 各回の厚さ（幅一定・体積一定）",
        padding=(12, 0),
    ).pack(anchor="w")
    toolbar = ttk.Frame(root, padding=(12, 8))
    toolbar.pack(fill="x")
    for label, command in (
        ("CSVを追加", add_csvs),
        ("選択を削除", remove_samples),
        ("上へ", move_up),
        ("下へ", move_down),
        ("比較する", compare),
    ):
        ttk.Button(toolbar, text=label, command=command, padding=(12, 8)).pack(
            side="left", padx=(0, 8)
        )
    ttk.Label(
        root,
        text="撮影順（上から順に。同じ材料区間を各画像で計測。Ctrl・Shiftで複数削除）",
        padding=(12, 0),
    ).pack(anchor="w")
    input_frame = ttk.Frame(root, padding=(12, 8))
    input_frame.pack(fill="both", expand=True)
    input_table = ttk.Treeview(
        input_frame,
        columns=("order", "name", "thickness", "scale", "path"),
        show="headings",
        selectmode="extended",
        height=4,
    )
    for column, label, width in (
        ("order", "順番", 50),
        ("name", "撮影名", 140),
        ("thickness", "厚さ (mm)", 100),
        ("scale", "mm/px", 130),
        ("path", "校正済みCSV", 620),
    ):
        input_table.heading(column, text=label)
        input_table.column(column, width=width, stretch=column == "path")
    input_table.pack(side="left", fill="both", expand=True)
    input_scroll = ttk.Scrollbar(
        input_frame, orient="vertical", command=input_table.yview
    )
    input_scroll.pack(side="right", fill="y")
    input_table.configure(yscrollcommand=input_scroll.set)
    for label, variable in (
        ("選択中のCSV", selected_csv),
        ("校正した元画像", selected_image),
    ):
        frame = ttk.Frame(root, padding=(12, 2))
        frame.pack(fill="x")
        ttk.Label(frame, text=label, width=14).pack(side="left", padx=(0, 8))
        ttk.Entry(frame, textvariable=variable, state="readonly").pack(
            side="left", fill="x", expand=True
        )
    editor = ttk.Frame(root, padding=(12, 8))
    editor.pack(fill="x")
    ttk.Label(editor, text="撮影名").pack(side="left", padx=(0, 8))
    ttk.Entry(editor, textvariable=sample_name, width=20).pack(side="left")
    ttk.Label(editor, text="撮影時の厚さ (mm)").pack(side="left", padx=(16, 8))
    ttk.Entry(editor, textvariable=sample_thickness, width=12).pack(side="left")
    ttk.Button(editor, text="撮影名・厚さを適用", command=apply_sample).pack(
        side="left", padx=8
    )
    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=12, pady=8)
    result_tables = {}
    for key, title, unit in (
        ("length", "実寸 (mm)", "mm"),
        ("ideal", "理想との差 (mm)", "mm"),
        ("ratio", "理想との差率 (%)", "%"),
        ("previous", "前回との差 (mm)", "mm"),
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
                label = "撮影名"
            elif column == "ideal":
                label = "理想片側長 (mm)"
            else:
                labels = {"left": "左", "right": "右", "total": "左右合計"}
                label = f"{labels[column]} ({unit})"
            table.heading(column, text=label)
            table.column(column, width=200, anchor="w" if column == "name" else "e")
        table.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=table.yview)
        scrollbar.pack(side="right", fill="y")
        table.configure(yscrollcommand=scrollbar.set)
        result_tables[key] = table
    actions = ttk.Frame(root, padding=(12, 8))
    actions.pack(fill="x")
    preview_button = ttk.Button(
        actions,
        text="推移グラフを表示",
        command=show_graph,
        state="disabled",
        padding=(12, 8),
    )
    preview_button.pack(side="left", padx=(0, 8))
    csv_button = ttk.Button(
        actions,
        text="比較CSVを保存",
        command=save_csv,
        state="disabled",
        padding=(12, 8),
    )
    csv_button.pack(side="left")
    graph_button = ttk.Button(
        actions,
        text="推移グラフを保存",
        command=save_graph,
        state="disabled",
        padding=(12, 8),
    )
    graph_button.pack(side="left", padx=8)
    ttk.Label(root, textvariable=status, padding=12, wraplength=1020).pack(fill="x")
    input_table.bind("<<TreeviewSelect>>", select_sample)
    initial_length.trace_add("write", model_changed)
    initial_thickness.trace_add("write", model_changed)
    root.mainloop()


if __name__ == "__main__":
    main()
