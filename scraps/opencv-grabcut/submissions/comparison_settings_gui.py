"""比較用CSV・識別名・基準・保存先を選び、04・09の設定をコピーする."""

import csv
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

KINDS = {"長さ（04）": "04_compare_lengths", "候補（09）": "09_compare_candidates"}


def check_csv(path: Path, kind: str) -> None:
    required = {"edge", "length_px", "start_y", "end_y"}
    if kind == "候補（09）":
        required = {
            "edge",
            "candidate_count",
            "max_inward_px",
            "total_span_px",
            "boundary_candidate_count",
            "start_y",
            "end_y",
            "threshold_px",
            "min_rows",
            "left_reference_ranges",
            "right_reference_ranges",
        }
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if not required.issubset(reader.fieldnames or []):
            expected = (
                "08_candidate_summary.csv"
                if kind == "候補（09）"
                else "03_side_lengths.csv"
            )
            raise ValueError(f"{expected}の形式を選んでください: {path.name}")
        edges = []
        for row in reader:
            edges.append(row["edge"])
    if sorted(edges) != ["left", "right", "total"]:
        raise ValueError(f"左・右・合計の3行が必要です: {path.name}")


def settings_text(
    samples: list, baseline: str, output_csv: Path, output_image: Path, kind: str
) -> str:
    if len(samples) < 2:
        raise ValueError("比較するCSVを2枚以上追加してください")
    ids = []
    inputs = []
    for sample_id, path in samples:
        if not sample_id.strip() or sample_id in ids:
            raise ValueError("識別名は空欄にせず、重複しない名前にしてください")
        check_csv(path, kind)
        ids.append(sample_id)
        inputs.append((sample_id, str(path.resolve())))
    if baseline not in ids:
        raise ValueError("基準の識別名を選んでください")
    output_csv = output_csv.resolve()
    output_image = output_image.resolve()
    if output_csv.suffix.lower() != ".csv" or output_image.suffix.lower() != ".png":
        raise ValueError("比較CSVは .csv、グラフは .png を選んでください")
    if output_csv == output_image:
        raise ValueError("比較CSVとグラフは別々の保存先にしてください")
    for _, path in inputs:
        if Path(path) in (output_csv, output_image):
            raise ValueError("入力CSVと別の保存先を選んでください")
    return (
        f"INPUT_CSVS = {tuple(inputs)!r}\n"
        f"BASELINE_ID = {baseline!r}\n"
        f"OUTPUT_CSV_PATH = {str(output_csv)!r}\n"
        f"OUTPUT_IMAGE_PATH = {str(output_image)!r}\n"
    )


def main() -> None:
    directory = Path(__file__).resolve().parent
    root = tk.Tk()
    root.title("比較の設定 — CSV・識別名・基準・保存先")
    root.geometry("1000x620")
    root.minsize(880, 560)
    samples = []
    kind = tk.StringVar(value="長さ（04）")
    baseline = tk.StringVar()
    sample_id = tk.StringVar()
    selected_path = tk.StringVar()
    output_csv = tk.StringVar()
    output_image = tk.StringVar()
    status = tk.StringVar(value="種類を選び、比較するCSVを2枚以上追加してください")

    toolbar = ttk.Frame(root, padding=12)
    toolbar.pack(fill="x")
    ttk.Label(toolbar, text="比較の種類").pack(side="left", padx=(0, 8))
    kind_box = ttk.Combobox(
        toolbar, values=list(KINDS), textvariable=kind, state="readonly", width=16
    )
    kind_box.pack(side="left", padx=(0, 16))
    ttk.Button(
        toolbar, text="CSVを追加", padding=(12, 8), command=lambda: add_csvs()
    ).pack(side="left")
    ttk.Button(
        toolbar, text="選択を削除", padding=(12, 8), command=lambda: remove_sample()
    ).pack(side="left", padx=8)
    table_frame = ttk.Frame(root, padding=(12, 0))
    table_frame.pack(fill="both", expand=True)
    table = ttk.Treeview(
        table_frame,
        columns=("id", "path"),
        show="headings",
        selectmode="browse",
        height=8,
    )
    table.heading("id", text="画像の識別名")
    table.heading("path", text="入力CSV")
    table.column("id", width=160, stretch=False)
    table.column("path", width=600)
    table.pack(side="left", fill="both", expand=True)
    scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=table.yview)
    scrollbar.pack(side="right", fill="y")
    table.configure(yscrollcommand=scrollbar.set)
    path_row = ttk.Frame(root, padding=(12, 8, 12, 0))
    path_row.pack(fill="x")
    ttk.Label(path_row, text="選択中のCSV").pack(side="left", padx=(0, 8))
    ttk.Entry(path_row, textvariable=selected_path, state="readonly").pack(
        side="left", fill="x", expand=True
    )
    editor = ttk.Frame(root, padding=12)
    editor.pack(fill="x")
    ttk.Label(editor, text="選択行の識別名").pack(side="left", padx=(0, 8))
    ttk.Entry(editor, textvariable=sample_id, width=24).pack(side="left")
    ttk.Button(
        editor, text="識別名を変更", padding=(8, 4), command=lambda: rename_sample()
    ).pack(side="left", padx=8)
    ttk.Label(editor, text="基準").pack(side="left", padx=(16, 8))
    baseline_box = ttk.Combobox(
        editor, textvariable=baseline, state="readonly", width=24
    )
    baseline_box.pack(side="left")
    destinations = ttk.Frame(root, padding=(12, 0))
    destinations.pack(fill="x")
    destinations.columnconfigure(1, weight=1)
    for row, (label, variable, suffix) in enumerate(
        (
            ("比較CSV", output_csv, ".csv"),
            ("グラフPNG", output_image, ".png"),
        )
    ):
        ttk.Label(destinations, text=label).grid(
            row=row, column=0, sticky="w", padx=(0, 8), pady=4
        )
        ttk.Entry(destinations, textvariable=variable, state="readonly").grid(
            row=row, column=1, sticky="ew"
        )
        ttk.Button(
            destinations,
            text="保存先を選ぶ",
            command=lambda value=variable, extension=suffix: choose_output(
                value, extension
            ),
        ).grid(row=row, column=2, padx=(8, 0))
    ttk.Button(
        root,
        text="比較の設定をコピー",
        padding=(12, 8),
        command=lambda: copy_settings(),
    ).pack(anchor="w", padx=12, pady=12)
    ttk.Label(root, textvariable=status, padding=(12, 4, 12, 12), wraplength=856).pack(
        fill="x"
    )

    def refresh() -> None:
        table.delete(*table.get_children())
        for index, (name, path) in enumerate(samples):
            short_path = f"{path.parent.parent.name}/{path.parent.name}/{path.name}"
            table.insert("", "end", iid=str(index), values=(name, short_path))
        names = []
        for name, _ in samples:
            names.append(name)
        baseline_box.configure(values=names)
        if baseline.get() not in names:
            baseline.set(names[0] if names else "")
        sample_id.set("")
        selected_path.set("")

    def change_kind(event=None) -> None:
        samples.clear()
        refresh()
        stem = KINDS[kind.get()]
        output_csv.set(str(directory / "results" / f"{stem}.csv"))
        output_image.set(str(directory / "results" / f"{stem}.png"))
        status.set("比較するCSVを2枚以上追加してください")

    def add_csvs() -> None:
        selected = filedialog.askopenfilenames(
            parent=root,
            title="比較するCSVを選ぶ",
            initialdir=directory,
            filetypes=[("CSV", "*.csv")],
        )
        if not selected:
            return
        paths = []
        try:
            for filename in selected:
                path = Path(filename).resolve()
                check_csv(path, kind.get())
                paths.append(path)
        except (OSError, ValueError, csv.Error) as error:
            status.set(str(error))
            return
        for path in paths:
            existing_paths = []
            existing_ids = []
            for name, existing in samples:
                existing_paths.append(existing)
                existing_ids.append(name)
            if path in existing_paths:
                continue
            number = len(samples) + 1
            name = f"image_{number:02d}"
            while name in existing_ids:
                number += 1
                name = f"image_{number:02d}"
            samples.append((name, path))
        refresh()
        status.set(f"{len(samples)}枚を選択しました。識別名と基準を確認してください")

    def select_sample(event=None) -> None:
        selection = table.selection()
        if selection:
            name, path = samples[int(selection[0])]
            sample_id.set(name)
            selected_path.set(str(path))

    def remove_sample() -> None:
        selection = table.selection()
        if selection:
            del samples[int(selection[0])]
            refresh()
            status.set("選択したCSVを一覧から削除しました")

    def rename_sample() -> None:
        selection = table.selection()
        if not selection:
            status.set("識別名を変更する行を選んでください")
            return
        index = int(selection[0])
        name = sample_id.get().strip()
        if not name:
            status.set("識別名を入力してください")
            return
        for other_index, (other_name, _) in enumerate(samples):
            if other_index != index and other_name == name:
                status.set("識別名が重複しています")
                return
        old_name, path = samples[index]
        samples[index] = (name, path)
        if baseline.get() == old_name:
            baseline.set(name)
        refresh()
        table.selection_set(str(index))
        select_sample()
        status.set("識別名を変更しました")

    def choose_output(variable, suffix) -> None:
        current = Path(variable.get())
        selected = filedialog.asksaveasfilename(
            parent=root,
            title="出力先を選ぶ",
            initialdir=current.parent,
            initialfile=current.name,
            defaultextension=suffix,
            filetypes=[("出力ファイル", f"*{suffix}")],
            confirmoverwrite=False,
        )
        if selected:
            variable.set(str(Path(selected).resolve()))
            status.set("保存先を選びました")

    def copy_settings() -> None:
        try:
            text = settings_text(
                samples,
                baseline.get(),
                Path(output_csv.get()),
                Path(output_image.get()),
                kind.get(),
            )
        except (OSError, ValueError, csv.Error) as error:
            status.set(str(error))
            return
        root.clipboard_clear()
        root.clipboard_append(text)
        status.set(f"{KINDS[kind.get()]}.pyの設定をコピーしました")

    kind_box.bind("<<ComboboxSelected>>", change_kind)
    table.bind("<<TreeviewSelect>>", select_sample)
    change_kind()
    root.mainloop()


if __name__ == "__main__":
    main()
