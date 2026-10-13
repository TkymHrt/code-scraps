"""複数撮影の03の長さCSVを並べ、基準・前回からの変化を確認・保存する."""

import csv
import math
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from matplotlib import rcParams
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


def read_lengths(path: Path) -> tuple[dict[str, float], tuple[int, int]]:
    lengths = {}
    measurement_range = None
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        required = {"edge", "length_px", "start_y", "end_y"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"03_side_lengths.csvの形式を選んでください: {path}")
        for row in reader:
            for column in required:
                if row[column] is None or not row[column].strip():
                    raise ValueError(f"空欄のある行を確認してください: {path}")
            edge = row["edge"]
            if edge not in ("left", "right", "total") or edge in lengths:
                raise ValueError(f"左・右・合計を1行ずつ指定してください: {path}")
            try:
                length = float(row["length_px"])
                start_y = int(row["start_y"])
                end_y = int(row["end_y"])
            except ValueError as error:
                raise ValueError(
                    f"長さ・計測範囲の数値を確認してください: {path}"
                ) from error
            if not math.isfinite(length) or length <= 0:
                raise ValueError(f"長さは0より大きい有限値が必要です: {path}")
            if not 0 <= start_y < end_y:
                raise ValueError(f"長さを測れる計測範囲が必要です: {path}")
            row_range = (start_y, end_y)
            if measurement_range is not None and row_range != measurement_range:
                raise ValueError(f"CSV内の計測範囲が一致しません: {path}")
            measurement_range = row_range
            lengths[edge] = length
    if len(lengths) != 3 or measurement_range is None:
        raise ValueError(f"左・右・合計の3行が必要です: {path}")
    # 03は丸める前に合計を求めるため、左右の和と最大0.01pxずれる。
    if abs(lengths["left"] + lengths["right"] - lengths["total"]) > 0.011:
        raise ValueError(f"左右の長さと合計が一致しません: {path}")
    return lengths, measurement_range


def compare_lengths(samples: list[tuple[str, Path]], baseline_id: str) -> list[dict]:
    if len(samples) < 2:
        raise ValueError("03の長さCSVを2枚以上追加してください")
    sample_ids = []
    input_paths = []
    for sample_id, path in samples:
        sample_id = sample_id.strip()
        if not sample_id or sample_id in sample_ids:
            raise ValueError("撮影名は空欄にせず、重複しない名前にしてください")
        path = path.resolve()
        if path in input_paths:
            raise ValueError("同じCSVを重複して指定しないでください")
        sample_ids.append(sample_id)
        input_paths.append(path)
    baseline_id = baseline_id.strip()
    if baseline_id not in sample_ids:
        raise ValueError("一覧から基準にする撮影を選んでください")

    first_lengths, comparison_range = read_lengths(input_paths[0])
    measurements = [first_lengths]
    for path in input_paths[1:]:
        lengths, measurement_range = read_lengths(path)
        if measurement_range != comparison_range:
            raise ValueError(f"すべてのCSVの計測範囲を揃えてください: {path}")
        measurements.append(lengths)
    baseline_index = sample_ids.index(baseline_id)
    baseline = measurements[baseline_index]
    start_y, end_y = comparison_range

    # 一覧の順序を撮影順とする。最初の撮影には前回との差がない。
    rows = []
    for index, (sample_id, input_path, lengths) in enumerate(
        zip(sample_ids, input_paths, measurements)
    ):
        previous_id = sample_ids[index - 1] if index > 0 else ""
        row = {
            "sample_id": sample_id,
            "baseline_id": baseline_id,
            "input_csv": str(input_path),
            "baseline_csv": str(input_paths[baseline_index]),
            "previous_id": previous_id,
            "start_y": start_y,
            "end_y": end_y,
        }
        for edge in ("left", "right", "total"):
            length = lengths[edge]
            baseline_difference = length - baseline[edge]
            previous_difference = None
            if index > 0:
                previous_difference = length - measurements[index - 1][edge]
            row[f"{edge}_px"] = length
            row[f"delta_{edge}_px"] = baseline_difference
            row[f"previous_delta_{edge}_px"] = previous_difference
        rows.append(row)
    return rows


def check_output(path: Path, rows: list[dict], suffix: str) -> Path:
    if not rows:
        raise ValueError("比較してから保存してください")
    path = path.resolve()
    if path.suffix.lower() != suffix:
        raise ValueError(f"保存先の拡張子は {suffix} にしてください")
    for row in rows:
        if path == Path(row["input_csv"]):
            raise ValueError("入力CSVと別の保存先を選んでください")
    return path


def write_csv(path: Path, rows: list[dict]) -> None:
    path = check_output(path, rows, ".csv")
    columns = (
        "sample_id",
        "baseline_id",
        "left_px",
        "right_px",
        "total_px",
        "delta_left_px",
        "delta_right_px",
        "delta_total_px",
        "start_y",
        "end_y",
        "previous_id",
        "previous_delta_left_px",
        "previous_delta_right_px",
        "previous_delta_total_px",
        "input_csv",
        "baseline_csv",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            saved = row.copy()
            for edge in ("left", "right", "total"):
                for column in (
                    f"{edge}_px",
                    f"delta_{edge}_px",
                    f"previous_delta_{edge}_px",
                ):
                    value = row[column]
                    saved[column] = "" if value is None else f"{value:.2f}"
            writer.writerow(saved)


def create_graph(rows: list[dict]) -> Figure:
    rcParams["font.sans-serif"] = ["Meiryo", "DejaVu Sans"]
    figure = Figure(figsize=(max(8, len(rows) * 0.9), 9), layout="constrained")
    axes = figure.subplots(3, 1, sharex=True)
    positions = list(range(len(rows)))
    names = []
    baseline_index = 0
    for index, row in enumerate(rows):
        name = row["sample_id"]
        if name == row["baseline_id"]:
            baseline_index = index
            name += "（基準）"
        names.append(name)
    for axis, prefix, title in (
        (axes[0], "", "左右の長さ"),
        (axes[1], "delta_", "基準からの変化"),
        (axes[2], "previous_delta_", "前回からの変化"),
    ):
        for edge, label in (("left", "左"), ("right", "右"), ("total", "合計")):
            # 合計は左右の和。絶対長の図は左右だけにして変化の図と分ける。
            if not prefix and edge == "total":
                continue
            values = []
            for row in rows:
                value = row[f"{prefix}{edge}_px"]
                values.append(math.nan if value is None else value)
            axis.plot(positions, values, marker="o", label=label)
        axis.axvline(baseline_index, color="gray", linestyle="--", linewidth=1)
        if prefix:
            axis.axhline(0, color="gray", linewidth=1)
            axis.set_ylabel("差 (px)")
        else:
            axis.set_ylim(bottom=0)
            axis.set_ylabel("長さ (px)")
        axis.set_title(title)
        axis.grid(alpha=0.3)
        axis.legend()
    axes[2].set_xticks(
        positions,
        names,
        rotation=45 if len(rows) > 4 else 0,
        ha="right" if len(rows) > 4 else "center",
    )
    axes[2].set_xlabel("撮影順（一覧の上から順に）")
    figure.suptitle(
        f"撮影ごとの長さ比較 | 基準: {rows[0]['baseline_id']} | "
        f"y={rows[0]['start_y']}..{rows[0]['end_y']}"
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
    root.title("撮影ごとの長さ比較")
    root.geometry("1100x800")
    root.minsize(1000, 700)
    samples = []
    baseline_id = ""
    rows = []
    graph_window = None
    sample_name = tk.StringVar()
    selected_path = tk.StringVar()
    baseline_text = tk.StringVar(value="基準: 未選択")
    measurement_range = tk.StringVar(value="計測範囲: 未比較")
    status = tk.StringVar(
        value="03の長さCSVを2枚以上追加し、一覧を撮影順に並べてください"
    )

    def invalidate_result() -> None:
        nonlocal graph_window
        if graph_window is not None:
            graph_window.destroy()
            graph_window = None
        rows.clear()
        for table in result_tables.values():
            table.delete(*table.get_children())
        measurement_range.set("計測範囲: 未比較")
        csv_button.state(["disabled"])
        graph_button.state(["disabled"])
        preview_button.state(["disabled"])

    def refresh_inputs() -> None:
        input_table.delete(*input_table.get_children())
        for index, (name, path) in enumerate(samples):
            role = "基準" if name == baseline_id else ""
            short_path = f"{path.parent.parent.name}/{path.parent.name}/{path.name}"
            tags = ("baseline",) if role else ()
            input_table.insert(
                "",
                "end",
                iid=str(index),
                values=(index + 1, role, name, short_path),
                tags=tags,
            )
        sample_name.set("")
        selected_path.set("")
        baseline_text.set(f"基準: {baseline_id}" if baseline_id else "基準: 未選択")

    def select_sample(event=None) -> None:
        selection = input_table.selection()
        if len(selection) == 1:
            name, path = samples[int(selection[0])]
            sample_name.set(name)
            selected_path.set(str(path))
        else:
            sample_name.set("")
            selected_path.set("")

    def add_csvs() -> None:
        nonlocal baseline_id
        selected = filedialog.askopenfilenames(
            parent=root,
            title="撮影ごとの03の長さCSVを選ぶ",
            initialdir=directory,
            filetypes=[("CSV", "*.csv")],
        )
        if not selected:
            return
        existing_paths = []
        for _, path in samples:
            existing_paths.append(path)
        new_paths = []
        try:
            # 追加分を全部確認してから一覧を変更する。
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
        started_empty = not samples
        names = []
        for name, _ in samples:
            names.append(name)
        for path in new_paths:
            number = len(samples) + 1
            name = f"撮影{number:02d}"
            while name in names:
                number += 1
                name = f"撮影{number:02d}"
            samples.append((name, path))
            names.append(name)
        if started_empty:
            baseline_id = samples[0][0]
        refresh_inputs()
        invalidate_result()
        status.set(
            f"{len(samples)}枚を選択しました。撮影順と基準を確認して比較してください"
        )

    def remove_samples() -> None:
        nonlocal baseline_id
        selection = input_table.selection()
        if not selection:
            status.set("削除する行を選んでください")
            return
        indices = []
        for item in selection:
            indices.append(int(item))
        for index in sorted(indices, reverse=True):
            name, _ = samples[index]
            if name == baseline_id:
                baseline_id = ""
            del samples[index]
        refresh_inputs()
        invalidate_result()
        if not baseline_id and samples:
            status.set("基準を削除しました。一覧から基準にする行を選んでください")
        else:
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
        refresh_inputs()
        input_table.selection_set(str(new_index))
        input_table.see(str(new_index))
        select_sample()
        invalidate_result()
        status.set("撮影順を変更しました。比較し直してください")

    def move_up() -> None:
        move_sample(-1)

    def move_down() -> None:
        move_sample(1)

    def set_baseline() -> None:
        nonlocal baseline_id
        selection = input_table.selection()
        if len(selection) != 1:
            status.set("基準にする行を1つ選んでください")
            return
        index = int(selection[0])
        name, _ = samples[index]
        if name == baseline_id:
            return
        baseline_id = name
        refresh_inputs()
        input_table.selection_set(str(index))
        select_sample()
        invalidate_result()
        status.set("基準を変更しました。比較し直してください")

    def rename_sample() -> None:
        nonlocal baseline_id
        selection = input_table.selection()
        if len(selection) != 1:
            status.set("名前を変更する行を1つ選んでください")
            return
        index = int(selection[0])
        name = sample_name.get().strip()
        if not name:
            status.set("撮影名を入力してください")
            return
        for other_index, (other_name, _) in enumerate(samples):
            if other_index != index and other_name == name:
                status.set("撮影名が重複しています")
                return
        old_name, path = samples[index]
        if name == old_name:
            return
        samples[index] = (name, path)
        if baseline_id == old_name:
            baseline_id = name
        refresh_inputs()
        input_table.selection_set(str(index))
        select_sample()
        invalidate_result()
        status.set("撮影名を変更しました。比較し直してください")

    def compare() -> None:
        nonlocal rows
        invalidate_result()
        try:
            # 保存済みの値を使い直さず、比較時に全CSVを読み直す。
            rows = compare_lengths(samples, baseline_id)
        except (OSError, ValueError, csv.Error) as error:
            status.set(str(error))
            return
        for row in rows:
            name = row["sample_id"]
            tags = ("baseline",) if name == baseline_id else ()
            for prefix, table in result_tables.items():
                values = [name]
                for edge in ("left", "right", "total"):
                    value = row[f"{prefix}{edge}_px"]
                    if value is None:
                        text = "—"
                    elif prefix:
                        text = f"{value:+.2f}"
                    else:
                        text = f"{value:.2f}"
                    values.append(text)
                table.insert("", "end", values=values, tags=tags)
        measurement_range.set(
            f"計測範囲: y={rows[0]['start_y']}〜{rows[0]['end_y']}（両端を含む）"
        )
        csv_button.state(["!disabled"])
        graph_button.state(["!disabled"])
        preview_button.state(["!disabled"])
        status.set(
            "比較しました。差は「各撮影 − 基準」または「各撮影 − 前回」です。単位はpxです"
        )

    def save(suffix: str) -> None:
        if not rows:
            return
        selected = filedialog.asksaveasfilename(
            parent=root,
            title="比較結果を保存",
            initialdir=directory,
            initialfile=f"length_comparison{suffix}",
            defaultextension=suffix,
            filetypes=[("比較結果", f"*{suffix}")],
        )
        if not selected:
            return
        path = Path(selected)
        try:
            if suffix == ".csv":
                write_csv(path, rows)
            else:
                write_graph(path, rows)
        except (OSError, ValueError, csv.Error) as error:
            status.set(str(error))
            return
        status.set(f"保存しました: {path}")

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
        window.title("撮影ごとの長さ推移")
        # タイトルバーとタスクバーの余白を取り、下のラベルまで画面内に置く。
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

    toolbar = ttk.Frame(root, padding=12)
    toolbar.pack(fill="x")
    for label, command in (
        ("CSVを追加", add_csvs),
        ("選択を削除", remove_samples),
        ("上へ", move_up),
        ("下へ", move_down),
        ("選択を基準にする", set_baseline),
        ("比較する", compare),
    ):
        ttk.Button(toolbar, text=label, command=command, padding=(12, 8)).pack(
            side="left", padx=(0, 8)
        )
    ttk.Label(
        root,
        text="撮影順（上から順に。Ctrl・Shiftで複数行を選んで削除できます）",
        padding=(12, 0),
    ).pack(anchor="w")
    input_frame = ttk.Frame(root, padding=(12, 8))
    input_frame.pack(fill="both", expand=True)
    input_table = ttk.Treeview(
        input_frame,
        columns=("order", "role", "name", "path"),
        show="headings",
        selectmode="extended",
        height=5,
    )
    for column, label, width in (
        ("order", "順番", 60),
        ("role", "基準", 60),
        ("name", "撮影名", 180),
        ("path", "入力CSV", 600),
    ):
        input_table.heading(column, text=label)
        input_table.column(column, width=width, stretch=column == "path")
    input_table.tag_configure("baseline", background="#fff3cd")
    input_table.pack(side="left", fill="both", expand=True)
    input_scroll = ttk.Scrollbar(
        input_frame, orient="vertical", command=input_table.yview
    )
    input_scroll.pack(side="right", fill="y")
    input_table.configure(yscrollcommand=input_scroll.set)
    path_row = ttk.Frame(root, padding=(12, 0))
    path_row.pack(fill="x")
    ttk.Label(path_row, text="選択中のCSV").pack(side="left", padx=(0, 8))
    ttk.Entry(path_row, textvariable=selected_path, state="readonly").pack(
        side="left", fill="x", expand=True
    )
    editor = ttk.Frame(root, padding=12)
    editor.pack(fill="x")
    ttk.Label(editor, text="選択行の撮影名").pack(side="left", padx=(0, 8))
    ttk.Entry(editor, textvariable=sample_name, width=24).pack(side="left")
    ttk.Button(editor, text="撮影名を変更", command=rename_sample).pack(
        side="left", padx=8
    )
    ttk.Label(editor, textvariable=baseline_text).pack(side="left", padx=16)
    ttk.Label(root, textvariable=measurement_range, padding=(12, 4)).pack(anchor="w")
    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=12, pady=8)
    result_tables = {}
    for prefix, title in (
        ("", "長さ"),
        ("delta_", "基準との差"),
        ("previous_delta_", "前回との差"),
    ):
        frame = ttk.Frame(notebook)
        notebook.add(frame, text=title)
        table = ttk.Treeview(
            frame, columns=("name", "left", "right", "total"), show="headings", height=6
        )
        for column, label in (
            ("name", "撮影名"),
            ("left", "左 (px)"),
            ("right", "右 (px)"),
            ("total", "合計 (px)"),
        ):
            table.heading(column, text=label)
            table.column(column, width=220, anchor="w" if column == "name" else "e")
        table.tag_configure("baseline", background="#fff3cd")
        table.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=table.yview)
        scrollbar.pack(side="right", fill="y")
        table.configure(yscrollcommand=scrollbar.set)
        result_tables[prefix] = table
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
    ttk.Label(root, textvariable=status, padding=12, wraplength=940).pack(fill="x")
    input_table.bind("<<TreeviewSelect>>", select_sample)
    root.mainloop()


if __name__ == "__main__":
    main()
