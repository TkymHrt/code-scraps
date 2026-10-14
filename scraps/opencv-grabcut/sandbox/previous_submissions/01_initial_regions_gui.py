"""01のGUI版。矩形で初期指定を作り、元画像へ重ねて確認・保存する."""

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

import cv2 as cv
import numpy as np

type Rect = tuple[float, float, float, float]

# 01と同じBGRの色と重ねる順序。未指定部分は背景候補（灰）。
PALETTE = np.array(
    [(255, 80, 0), (0, 255, 0), (64, 64, 64), (0, 165, 255)], dtype=np.uint8
)
REGION_NAMES = {
    cv.GC_PR_FGD: "前景候補（橙）",
    cv.GC_BGD: "確実な背景（青）",
    cv.GC_FGD: "確実な前景（緑）",
}


def initial_overlay(image: np.ndarray, regions: dict[int, list[Rect]]) -> np.ndarray:
    height, width = image.shape[:2]
    labels = np.full((height, width), cv.GC_PR_BGD, np.uint8)
    for label in REGION_NAMES:
        for left, top, right, bottom in regions[label]:
            if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
                raise ValueError("矩形は0〜1の範囲で、左 < 右、上 < 下にしてください")
            x0, y0 = int(width * left), int(height * top)
            x1, y1 = int(width * right), int(height * bottom)
            if x0 == x1 or y0 == y1:
                raise ValueError("矩形が1画素未満です。指定範囲を広げてください")
            labels[y0:y1, x0:x1] = label
    return cv.addWeighted(image, 0.65, PALETTE[labels], 0.35, 0)


def main() -> None:
    directory = Path(__file__).resolve().parent
    root = tk.Tk()
    input_path: Path | None = None
    image: np.ndarray | None = None
    height = width = 1
    regions: dict[int, list[Rect]] = {label: [] for label in REGION_NAMES}
    region_rows: list[tuple[int, int]] = []
    photo: tk.PhotoImage | None = None
    display_bounds = (0, 0, 1, 1)
    drag_start: tuple[float, float] | None = None

    root.title("01 — 初期指定の作成・確認")
    root.geometry("1000x700")
    root.minsize(900, 648)
    mode = tk.IntVar(value=cv.GC_PR_FGD)
    view = tk.StringVar(value="initial")
    status = tk.StringVar()
    file_text = tk.StringVar(value="未読込")

    file_toolbar = ttk.Frame(root, padding=12)
    file_toolbar.pack(fill="x")
    ttk.Button(
        file_toolbar,
        text="画像を読み込む",
        padding=(12, 8),
        command=lambda: load_image(),
    ).pack(side="left")
    ttk.Label(file_toolbar, textvariable=file_text).pack(side="left", padx=8)
    body = ttk.Frame(root, padding=(12, 0, 12, 0))
    body.pack(fill="both", expand=True)
    sidebar = ttk.Frame(body)
    sidebar.pack(side="left", fill="y", padx=(0, 16))
    preview = ttk.Frame(body)
    preview.pack(side="left", fill="both", expand=True)
    view_toolbar = ttk.Frame(preview)
    view_toolbar.pack(fill="x", pady=(0, 8))
    for value, name in (("initial", "初期指定"), ("original", "元画像")):
        ttk.Radiobutton(
            view_toolbar,
            text=name,
            variable=view,
            value=value,
            padding=4,
            command=lambda: render(),
        ).pack(side="left", padx=(0, 8))
    canvas = tk.Canvas(preview, background="#242424", highlightthickness=0)
    canvas.pack(fill="both", expand=True)

    ttk.Label(sidebar, text="矩形の種類").pack(anchor="w", pady=(0, 4))
    # 色見本は同じBGRパレットから作り、表示中の参照を残す。
    swatches: list[tk.PhotoImage] = []
    for label, name in REGION_NAMES.items():
        blue, green, red = PALETTE[label]
        swatch = tk.PhotoImage(master=root, width=16, height=16)
        swatch.put(f"#{red:02x}{green:02x}{blue:02x}", to=(0, 0, 16, 16))
        swatches.append(swatch)
        ttk.Radiobutton(
            sidebar,
            text=name,
            image=swatch,
            compound="left",
            variable=mode,
            value=label,
            padding=4,
            command=lambda: show_initial(),
        ).pack(anchor="w", pady=4)
    region_list = tk.Listbox(sidebar, width=32, height=7, exportselection=False)
    region_list.pack(fill="x", pady=(8, 12))
    for name, action in (
        ("選択した矩形を削除", lambda: delete_region()),
        ("矩形をすべて削除", lambda: clear_regions()),
        ("確認画像を保存", lambda: save_image()),
        ("初期指定の設定をコピー", lambda: copy_settings()),
    ):
        ttk.Button(sidebar, text=name, padding=(12, 8), command=action).pack(
            fill="x", pady=4
        )
    ttk.Label(root, textvariable=status, padding=12, wraplength=876).pack(fill="x")

    def load_image() -> None:
        nonlocal image, input_path, height, width
        selected = filedialog.askopenfilename(
            parent=root,
            title="入力画像を選ぶ",
            initialdir=directory,
            filetypes=[
                ("画像", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff"),
                ("すべて", "*.*"),
            ],
        )
        if not selected:
            return
        # 日本語のパスにも対応するため、画像のバイト列を読み込む。
        loaded = cv.imdecode(np.fromfile(selected, np.uint8), cv.IMREAD_COLOR)
        if loaded is None:
            status.set("画像を読み込めません。別の画像を選んでください")
            return
        image = loaded
        input_path = Path(selected).resolve()
        height, width = image.shape[:2]
        file_text.set(f"{input_path.name}  ({width} × {height} px)")
        clear_regions()

    def refresh_regions() -> None:
        region_rows.clear()
        region_list.delete(0, tk.END)
        for label, name in REGION_NAMES.items():
            for index in range(len(regions[label])):
                region_rows.append((label, index))
                region_list.insert(tk.END, f"{name} {index + 1}")
        show_initial()
        status.set("")

    def clear_regions() -> None:
        for rectangles in regions.values():
            rectangles.clear()
        refresh_regions()

    def show_initial() -> None:
        view.set("initial")
        render()

    def render() -> None:
        nonlocal photo, display_bounds, drag_start
        drag_start = None
        canvas.delete("all")
        if image is None:
            return
        shown = initial_overlay(image, regions) if view.get() == "initial" else image
        scale = min(canvas.winfo_width() / width, canvas.winfo_height() / height, 1)
        display_width = max(1, int(width * scale))
        display_height = max(1, int(height * scale))
        small = cv.resize(
            shown, (display_width, display_height), interpolation=cv.INTER_NEAREST
        )
        _, encoded = cv.imencode(".png", small)
        photo = tk.PhotoImage(master=root, data=encoded.tobytes(), format="PNG")
        x = (canvas.winfo_width() - display_width) // 2
        y = (canvas.winfo_height() - display_height) // 2
        display_bounds = (x, y, x + display_width, y + display_height)
        canvas.create_image(x, y, image=photo, anchor="nw")
        selection = region_list.curselection()
        if view.get() == "initial" and selection:
            label, index = region_rows[selection[0]]
            left, top, right, bottom = regions[label][index]
            canvas.create_rectangle(
                x + left * display_width,
                y + top * display_height,
                x + right * display_width,
                y + bottom * display_height,
                outline="yellow",
                width=2,
            )

    def image_point(event: tk.Event) -> tuple[float, float]:
        x0, y0, x1, y1 = display_bounds
        return (
            min(1.0, max(0.0, (event.x - x0) / (x1 - x0))),
            min(1.0, max(0.0, (event.y - y0) / (y1 - y0))),
        )

    def start_draw(event: tk.Event) -> None:
        nonlocal drag_start
        if image is None or view.get() != "initial":
            return
        x0, y0, x1, y1 = display_bounds
        if x0 <= event.x <= x1 and y0 <= event.y <= y1:
            drag_start = image_point(event)

    def drag_draw(event: tk.Event) -> None:
        if drag_start is None:
            return
        x0, y0, x1, y1 = display_bounds
        x, y = image_point(event)
        canvas.delete("drag")
        canvas.create_rectangle(
            x0 + drag_start[0] * (x1 - x0),
            y0 + drag_start[1] * (y1 - y0),
            x0 + x * (x1 - x0),
            y0 + y * (y1 - y0),
            outline="white",
            width=2,
            dash=(5, 3),
            tags="drag",
        )

    def end_draw(event: tk.Event) -> None:
        nonlocal drag_start
        if drag_start is None:
            return
        x, y = image_point(event)
        left, right = sorted((drag_start[0], x))
        top, bottom = sorted((drag_start[1], y))
        drag_start = None
        canvas.delete("drag")
        if int(width * left) >= int(width * right) or int(height * top) >= int(
            height * bottom
        ):
            status.set("矩形が1画素未満です。指定範囲を広げてください。")
            return
        rect = (left, top, right, bottom)
        label = mode.get()
        if label == cv.GC_PR_FGD:
            regions[label] = [rect]
        else:
            regions[label].append(rect)
        refresh_regions()

    def delete_region() -> None:
        selection = region_list.curselection()
        if selection:
            label, index = region_rows[selection[0]]
            del regions[label][index]
            refresh_regions()

    def save_image() -> None:
        if image is None or input_path is None:
            status.set("画像を読み込んでください")
            return
        selected = filedialog.asksaveasfilename(
            parent=root,
            title="確認画像の保存先を選ぶ",
            initialdir=input_path.parent,
            initialfile=f"{input_path.stem}_initial_regions.png",
            defaultextension=".png",
            filetypes=[("PNG画像", "*.png")],
            confirmoverwrite=True,
        )
        if not selected:
            return
        output_path = Path(selected).resolve()
        if output_path == input_path:
            status.set("保存先を入力画像とは別のパスにしてください")
            return
        if output_path.suffix.lower() != ".png":
            status.set("保存先の拡張子は .png にしてください")
            return
        success, encoded = cv.imencode(".png", initial_overlay(image, regions))
        if not success:
            raise OSError("PNG画像を作成できません")
        encoded.tofile(output_path)
        status.set(f"保存しました: {output_path.name}")

    def copy_settings() -> None:
        if len(regions[cv.GC_PR_FGD]) != 1:
            status.set("前景候補の矩形を1つ描いてください")
            return
        # 丸めずにコピーし、提出版でも同じ画素を指定する。
        text = (
            f"CANDIDATE_RECT = {regions[cv.GC_PR_FGD][0]!r}\n"
            f"BACKGROUND_RECTS = {tuple(regions[cv.GC_BGD])!r}\n"
            f"FOREGROUND_RECTS = {tuple(regions[cv.GC_FGD])!r}\n"
        )
        root.clipboard_clear()
        root.clipboard_append(text)
        status.set("矩形の設定をコピーしました")

    canvas.bind("<Configure>", lambda event: render())
    canvas.bind("<ButtonPress-1>", start_draw)
    canvas.bind("<B1-Motion>", drag_draw)
    canvas.bind("<ButtonRelease-1>", end_draw)
    region_list.bind("<<ListboxSelect>>", lambda event: show_initial())
    refresh_regions()
    root.mainloop()


if __name__ == "__main__":
    main()
