"""3本のGUIで使う画面の枠・ファイル選択・グラフの差し替え。"""

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from measurement_csv import read_lengths


def create_layout(root: tk.Tk) -> tuple[ttk.Frame, ttk.Frame, ttk.Frame]:
    header = ttk.Frame(root, padding=12)
    header.pack(fill="x")
    body = ttk.Frame(root, padding=(12, 0, 12, 12))
    body.pack(fill="both", expand=True)
    body.columnconfigure(0, minsize=220)
    body.columnconfigure(1, weight=1)
    body.rowconfigure(0, weight=1)
    sidebar = ttk.Frame(body)
    sidebar.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
    content = ttk.Frame(body)
    content.grid(row=0, column=1, sticky="nsew")
    return header, sidebar, content


def choose_csv_paths(
    root: tk.Tk, directory: Path, existing_paths: list[Path]
) -> list[Path]:
    selected = filedialog.askopenfilenames(
        parent=root,
        title="長さCSVを比較したい順に追加",
        initialdir=directory,
        filetypes=[("CSV", "*.csv")],
    )
    new_paths = []
    for filename in selected:
        path = Path(filename).resolve()
        if path in existing_paths or path in new_paths:
            continue
        read_lengths(path)
        new_paths.append(path)
    return new_paths


def choose_png_path(
    root: tk.Tk, directory: Path, filename: str, *, title: str = "グラフを保存"
) -> Path | None:
    selected = filedialog.asksaveasfilename(
        parent=root,
        title=title,
        initialdir=directory,
        initialfile=filename,
        defaultextension=".png",
        filetypes=[("PNG画像", "*.png")],
        confirmoverwrite=True,
    )
    if not selected:
        return None
    return Path(selected).resolve()


def replace_graph(
    frame: ttk.Frame, canvas: FigureCanvasTkAgg | None, figure: Figure | None
) -> FigureCanvasTkAgg | None:
    if canvas is not None:
        canvas.get_tk_widget().destroy()
        canvas.figure.clear()
    if figure is None:
        return None
    canvas = FigureCanvasTkAgg(figure, master=frame)
    canvas.get_tk_widget().pack(fill="both", expand=True)
    canvas.draw()
    return canvas
