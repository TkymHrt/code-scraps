"""03の長さCSVを2枚選び、左右・合計と基準との差を確認・保存する."""

import csv
import math
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from matplotlib import pyplot as plt


def read_lengths(path: Path) -> tuple[dict[str, float], tuple[int, int]]:
    lengths = {}
    measurement_range = None
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        required = {"edge", "length_px", "start_y", "end_y"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"03_side_lengths.csvの形式を選んでください: {path.name}")
        for row in reader:
            for column in required:
                if row[column] is None or not row[column].strip():
                    raise ValueError(f"空欄のある行を確認してください: {path.name}")
            edge = row["edge"]
            if edge not in ("left", "right", "total") or edge in lengths:
                raise ValueError(f"左・右・合計を1行ずつ指定してください: {path.name}")
            length = float(row["length_px"])
            if not math.isfinite(length) or length <= 0:
                raise ValueError(f"長さは0より大きい有限値が必要です: {path.name}")
            start_y = int(row["start_y"])
            end_y = int(row["end_y"])
            if not 0 <= start_y < end_y:
                raise ValueError(f"長さを測れる計測範囲が必要です: {path.name}")
            row_range = (start_y, end_y)
            if measurement_range is not None and row_range != measurement_range:
                raise ValueError(f"CSV内の計測範囲が一致しません: {path.name}")
            measurement_range = row_range
            lengths[edge] = length
    if len(lengths) != 3 or measurement_range is None:
        raise ValueError(f"左・右・合計の3行が必要です: {path.name}")
    # 03は丸める前に合計を求めるため、左右の和と最大0.01pxずれる。
    if abs(lengths["left"] + lengths["right"] - lengths["total"]) > 0.011:
        raise ValueError(f"左右の長さと合計が一致しません: {path.name}")
    return lengths, measurement_range


def compare_lengths(baseline_path: Path, comparison_path: Path) -> list[dict]:
    baseline_path = baseline_path.resolve()
    comparison_path = comparison_path.resolve()
    if baseline_path == comparison_path:
        raise ValueError("基準と比較対象には別々のCSVを選んでください")
    baseline, baseline_range = read_lengths(baseline_path)
    comparison, comparison_range = read_lengths(comparison_path)
    if baseline_range != comparison_range:
        raise ValueError("基準と比較対象の計測範囲を揃えてください")
    start_y, end_y = baseline_range
    rows = []
    for edge in ("left", "right", "total"):
        rows.append(
            {
                "edge": edge,
                "baseline_csv": str(baseline_path),
                "comparison_csv": str(comparison_path),
                "baseline_px": baseline[edge],
                "comparison_px": comparison[edge],
                "delta_px": comparison[edge] - baseline[edge],
                "start_y": start_y,
                "end_y": end_y,
            }
        )
    return rows


def check_output(path: Path, rows: list[dict], suffix: str) -> Path:
    path = path.resolve()
    if path.suffix.lower() != suffix:
        raise ValueError(f"保存先の拡張子は {suffix} にしてください")
    if path in (Path(rows[0]["baseline_csv"]), Path(rows[0]["comparison_csv"])):
        raise ValueError("入力CSVと別の保存先を選んでください")
    return path


def write_csv(path: Path, rows: list[dict]) -> None:
    path = check_output(path, rows, ".csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(
            (
                "edge",
                "baseline_csv",
                "comparison_csv",
                "baseline_px",
                "comparison_px",
                "delta_px",
                "start_y",
                "end_y",
            )
        )
        for row in rows:
            writer.writerow(
                (
                    row["edge"],
                    row["baseline_csv"],
                    row["comparison_csv"],
                    f"{row['baseline_px']:.2f}",
                    f"{row['comparison_px']:.2f}",
                    f"{row['delta_px']:.2f}",
                    row["start_y"],
                    row["end_y"],
                )
            )


def write_graph(path: Path, rows: list[dict]) -> None:
    path = check_output(path, rows, ".png")
    plt.switch_backend("Agg")
    plt.rcParams["font.sans-serif"] = ["Meiryo", "DejaVu Sans"]
    figure, axes = plt.subplots(figsize=(7, 5), layout="constrained")
    baseline_lengths = [rows[0]["baseline_px"], rows[1]["baseline_px"]]
    comparison_lengths = [rows[0]["comparison_px"], rows[1]["comparison_px"]]
    baseline_bars = axes.bar([-0.2, 0.8], baseline_lengths, width=0.4, label="基準")
    comparison_bars = axes.bar(
        [0.2, 1.2], comparison_lengths, width=0.4, label="比較対象"
    )
    axes.bar_label(baseline_bars, fmt="%.2f", padding=3)
    axes.bar_label(comparison_bars, fmt="%.2f", padding=3)
    axes.set_xticks([0, 1], ["左", "右"])
    axes.set_ylim(0, max(baseline_lengths + comparison_lengths) * 1.2)
    axes.set_ylabel("側辺長 (px)")
    axes.set_title(f"長さの比較 | y={rows[0]['start_y']}..{rows[0]['end_y']}")
    axes.set_axisbelow(True)
    axes.grid(axis="y", alpha=0.3)
    axes.legend()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        figure.savefig(path, dpi=160)
    finally:
        plt.close(figure)


def main() -> None:
    directory = Path(__file__).resolve().parent
    root = tk.Tk()
    root.title("長さの比較 — 基準と比較対象の2枚")
    root.geometry("860x430")
    root.minsize(760, 430)
    baseline_path = tk.StringVar()
    comparison_path = tk.StringVar()
    measurement_range = tk.StringVar(value="計測範囲: 未比較")
    status = tk.StringVar(value="03の長さCSVを基準と比較対象に1枚ずつ選んでください")
    rows = []

    def choose_csv(variable: tk.StringVar) -> None:
        current = Path(variable.get()) if variable.get() else directory
        selected = filedialog.askopenfilename(
            parent=root,
            title="03の長さCSVを選ぶ",
            initialdir=current.parent if variable.get() else directory,
            filetypes=[("CSV", "*.csv")],
        )
        if not selected:
            return
        variable.set(str(Path(selected).resolve()))
        rows.clear()
        table.delete(*table.get_children())
        measurement_range.set("計測範囲: 未比較")
        csv_button.state(["disabled"])
        graph_button.state(["disabled"])
        status.set("CSVを選びました。「比較する」を押してください")

    def choose_baseline() -> None:
        choose_csv(baseline_path)

    def choose_comparison() -> None:
        choose_csv(comparison_path)

    def compare() -> None:
        nonlocal rows
        if not baseline_path.get() or not comparison_path.get():
            status.set("基準と比較対象のCSVを両方選んでください")
            return
        # 再比較に失敗した場合も、以前の結果を保存できないようにする。
        rows.clear()
        table.delete(*table.get_children())
        measurement_range.set("計測範囲: 未比較")
        csv_button.state(["disabled"])
        graph_button.state(["disabled"])
        try:
            rows = compare_lengths(
                Path(baseline_path.get()), Path(comparison_path.get())
            )
        except (OSError, ValueError, csv.Error) as error:
            status.set(str(error))
            return
        labels = {"left": "左", "right": "右", "total": "合計"}
        for row in rows:
            table.insert(
                "",
                "end",
                values=(
                    labels[row["edge"]],
                    f"{row['baseline_px']:.2f}",
                    f"{row['comparison_px']:.2f}",
                    f"{row['delta_px']:+.2f}",
                ),
            )
        measurement_range.set(
            f"計測範囲: y={rows[0]['start_y']}〜{rows[0]['end_y']}（両端を含む）"
        )
        csv_button.state(["!disabled"])
        graph_button.state(["!disabled"])
        status.set("比較しました。差は「比較対象 − 基準」です。単位はすべてpxです")

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

    inputs = ttk.Frame(root, padding=12)
    inputs.pack(fill="x")
    inputs.columnconfigure(1, weight=1)
    for index, (label, variable, command) in enumerate(
        (
            ("基準CSV", baseline_path, choose_baseline),
            ("比較対象CSV", comparison_path, choose_comparison),
        )
    ):
        ttk.Label(inputs, text=label).grid(row=index, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(inputs, textvariable=variable, state="readonly").grid(
            row=index, column=1, sticky="ew", pady=4
        )
        ttk.Button(inputs, text=f"{label}を選ぶ", command=command).grid(
            row=index, column=2, padx=(8, 0)
        )
    ttk.Button(root, text="比較する", padding=(12, 8), command=compare).pack(
        anchor="w", padx=12, pady=(0, 8)
    )
    ttk.Label(root, textvariable=measurement_range, padding=(12, 4)).pack(anchor="w")
    table = ttk.Treeview(
        root,
        columns=("edge", "baseline", "comparison", "delta"),
        show="headings",
        height=3,
    )
    for column, label in (
        ("edge", "項目"),
        ("baseline", "基準 (px)"),
        ("comparison", "比較対象 (px)"),
        ("delta", "差: 比較対象 − 基準 (px)"),
    ):
        table.heading(column, text=label)
        table.column(column, width=180, anchor="e" if column != "edge" else "w")
    table.pack(fill="x", padx=12, pady=8)
    actions = ttk.Frame(root, padding=(12, 8))
    actions.pack(fill="x")
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
        text="左右のグラフを保存",
        command=save_graph,
        state="disabled",
        padding=(12, 8),
    )
    graph_button.pack(side="left", padx=8)
    ttk.Label(root, textvariable=status, padding=12, wraplength=720).pack(fill="x")
    root.mainloop()


if __name__ == "__main__":
    main()
