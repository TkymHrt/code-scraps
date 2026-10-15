"""局所区間の長さCSVを読み、左右側辺長と100mm換算を表・グラフで比較する。"""

import csv
import math
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from matplotlib import rcParams
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


def positive_value(value: str | None, name: str) -> float:
    try:
        number = float(value) if value is not None else math.nan
    except ValueError as error:
        raise ValueError(f"{name}は正の数値にしてください") from error
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name}は正の有限値にしてください")
    return number


def read_lengths(path: Path) -> dict:
    required = (
        "image_path",
        "mm_per_px",
        "start_y",
        "end_y",
        "left_mm",
        "right_mm",
    )
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if not set(required).issubset(reader.fieldnames or []):
            raise ValueError(f"計測GUIの長さCSVを選んでください: {path.name}")
        saved_rows = list(reader)
    if len(saved_rows) != 1:
        raise ValueError(f"1回の計測を1行に保存したCSVが必要です: {path.name}")
    saved = saved_rows[0]
    for column in required:
        value = saved[column]
        if value is None or not value.strip():
            raise ValueError(f"空欄を確認してください: {column}: {path.name}")
    scale = positive_value(saved["mm_per_px"], f"mm_per_px: {path.name}")
    try:
        start_y = int(saved["start_y"])
        end_y = int(saved["end_y"])
    except ValueError as error:
        raise ValueError(f"開始y・終了yは整数にしてください: {path.name}") from error
    if not 0 <= start_y < end_y:
        raise ValueError(f"0 ≤ 開始y < 終了yにしてください: {path.name}")
    # 両端の画素中心の間隔なので、行数の「+1」は加えない。
    interval_mm = (end_y - start_y) * scale
    if not math.isfinite(interval_mm):
        raise ValueError(f"区間長を計算できません: {path.name}")
    image_path = (path.parent / saved["image_path"]).resolve()
    row = {
        "image_path": str(image_path),
        "mm_per_px": scale,
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


def compare_lengths(paths: list[Path]) -> list[dict]:
    if not paths:
        raise ValueError("長さCSVを1つ以上追加してください")
    used_paths = []
    rows = []
    for index, path in enumerate(paths):
        path = path.resolve()
        if path in used_paths:
            raise ValueError(f"同じCSVを重複して指定しないでください: {path.name}")
        used_paths.append(path)
        row = {
            "order": index + 1,
            "csv_name": path.name,
            "measurement_csv": str(path),
        }
        row.update(read_lengths(path))
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


def create_graph(rows: list[dict], normalized: bool = False) -> Figure:
    rcParams["font.sans-serif"] = ["Meiryo", "DejaVu Sans"]
    figure = Figure(figsize=(9, 5), layout="constrained")
    axis = figure.subplots()
    positions = []
    labels = []
    left_values = []
    right_values = []
    interval_values = []
    for row in rows:
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
    return figure


def write_graph(path: Path, rows: list[dict], normalized: bool = False) -> None:
    path = check_output(path, rows, ".png")
    figure = create_graph(rows, normalized)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=160)


def main() -> None:
    output_directory = Path(__file__).resolve().parent / "output"
    root = tk.Tk()
    root.title("局所区間の左右長さ比較")
    root.geometry("1100x760")
    root.minsize(960, 640)
    paths: list[Path] = []
    rows: list[dict] = []
    graph_canvas: FigureCanvasTkAgg | None = None
    mode = tk.StringVar(master=root, value="実測長")
    status = tk.StringVar(master=root, value="長さCSVを比較したい順に追加してください")

    def draw_graph() -> None:
        nonlocal graph_canvas
        if graph_canvas is not None:
            graph_canvas.get_tk_widget().destroy()
            graph_canvas.figure.clear()
            graph_canvas = None
        if rows:
            figure = create_graph(rows, mode.get() == "100mm換算")
            graph_canvas = FigureCanvasTkAgg(figure, master=graph_frame)
            graph_canvas.get_tk_widget().pack(fill="both", expand=True)
            graph_canvas.draw()

    def compare() -> None:
        rows.clear()
        table.delete(*table.get_children())
        csv_button.state(["disabled"])
        graph_button.state(["disabled"])
        draw_graph()
        for index, path in enumerate(paths):
            table.insert("", "end", iid=str(index), values=(path.name, "—", "—", "—"))
        if not paths:
            status.set("長さCSVを比較したい順に追加してください")
            return
        try:
            compared = compare_lengths(paths)
        except (OSError, ValueError, csv.Error) as error:
            status.set(str(error))
            return
        rows.extend(compared)
        for index, row in enumerate(rows):
            values = [row["csv_name"]]
            for column in columns[1:]:
                values.append(f"{row[column]:.3f}")
            table.item(str(index), values=values)
        draw_graph()
        csv_button.state(["!disabled"])
        graph_button.state(["!disabled"])
        status.set(f"{len(rows)}件を比較しました。区間長は開始・終了yの間隔です")

    def add_csvs() -> None:
        selected = filedialog.askopenfilenames(
            parent=root,
            title="長さCSVを比較したい順に追加",
            initialdir=output_directory,
            filetypes=[("CSV", "*.csv")],
        )
        new_paths = []
        try:
            for filename in selected:
                path = Path(filename).resolve()
                if path in paths or path in new_paths:
                    continue
                read_lengths(path)
                new_paths.append(path)
        except (OSError, ValueError, csv.Error) as error:
            status.set(str(error))
            return
        if new_paths:
            paths.extend(new_paths)
            compare()

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
        compare()

    def save(suffix: str) -> None:
        stem = "length_comparison_local"
        if suffix == ".png" and mode.get() == "100mm換算":
            stem += "_100mm"
        selected = filedialog.asksaveasfilename(
            parent=root,
            title="比較結果を保存",
            initialdir=output_directory,
            initialfile=stem + suffix,
            defaultextension=suffix,
            filetypes=[("比較結果", "*" + suffix)],
            confirmoverwrite=True,
        )
        if not selected:
            return
        try:
            if suffix == ".csv":
                write_csv(Path(selected), rows)
            else:
                write_graph(Path(selected), rows, mode.get() == "100mm換算")
        except (OSError, ValueError, csv.Error) as error:
            status.set(str(error))
            return
        status.set(f"保存しました: {Path(selected).name}")

    def save_csv() -> None:
        save(".csv")

    def save_graph() -> None:
        save(".png")

    toolbar = ttk.Frame(root, padding=12)
    toolbar.pack(fill="x")
    for label, action in (
        ("CSVを追加", add_csvs),
        ("選択したCSVを削除", remove_csvs),
        ("比較し直す", compare),
    ):
        ttk.Button(toolbar, text=label, command=action, padding=(10, 6)).pack(
            side="left", padx=(0, 8)
        )
    csv_button = ttk.Button(toolbar, text="比較CSVを保存", command=save_csv)
    csv_button.pack(side="left", padx=(12, 8))
    graph_button = ttk.Button(toolbar, text="グラフを保存", command=save_graph)
    graph_button.pack(side="left")
    options = ttk.Frame(root, padding=(12, 0, 12, 8))
    options.pack(fill="x")
    ttk.Label(options, text="グラフ：").pack(side="left")
    for label in ("実測長", "100mm換算"):
        ttk.Radiobutton(
            options, text=label, value=label, variable=mode, command=draw_graph
        ).pack(side="left", padx=(0, 12))
    table_frame = ttk.Frame(root, padding=(12, 0, 12, 8))
    table_frame.pack(fill="x")
    columns = ("csv_name", "interval_length_mm", "left_mm", "right_mm")
    headings = ("撮影 / CSV", "区間長 (mm)", "左側辺 (mm)", "右側辺 (mm)")
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
    ttk.Label(root, textvariable=status, padding=(12, 0, 12, 8), wraplength=900).pack(
        fill="x"
    )
    graph_frame = ttk.Frame(root, padding=(12, 0, 12, 12))
    graph_frame.pack(fill="both", expand=True)
    csv_button.state(["disabled"])
    graph_button.state(["disabled"])
    output_directory.mkdir(parents=True, exist_ok=True)
    root.mainloop()


if __name__ == "__main__":
    main()
