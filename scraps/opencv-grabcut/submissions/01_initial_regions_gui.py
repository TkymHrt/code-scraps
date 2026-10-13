"""01のGUI版。矩形で初期指定を作り、元画像へ重ねて確認・保存する."""

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import cv2 as cv
import numpy as np

# パスはこのスクリプトのフォルダが基準。01と同じ初期指定で始める。
INPUT_PATH = "input.png"
OUTPUT_PATH = "results/01_initial_regions_gui.png"
CANDIDATE_RECT = (0.34, 0.0, 0.705, 1.0)
BACKGROUND_RECTS = ((0.0, 0.0, 0.33, 1.0), (0.72, 0.0, 1.0, 1.0))
FOREGROUND_RECTS = ((0.48, 0.4, 0.56, 0.6),)

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


def make_labels(image: np.ndarray, regions: dict[int, list[Rect]]) -> np.ndarray:
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
    return labels


def initial_overlay(image: np.ndarray, regions: dict[int, list[Rect]]) -> np.ndarray:
    return cv.addWeighted(image, 0.65, PALETTE[make_labels(image, regions)], 0.35, 0)


def settings_text(input_path: Path, regions: dict[int, list[Rect]]) -> str:
    if len(regions[cv.GC_PR_FGD]) != 1:
        raise ValueError("設定をコピーするには、前景候補の矩形を1つ描いてください")
    # 丸めずにコピーし、提出版でも同じ画素を指定する。
    return (
        f"INPUT_PATH = {input_path.as_posix()!r}\n"
        f"CANDIDATE_RECT = {regions[cv.GC_PR_FGD][0]!r}\n"
        f"BACKGROUND_RECTS = {tuple(regions[cv.GC_BGD])!r}\n"
        f"FOREGROUND_RECTS = {tuple(regions[cv.GC_FGD])!r}\n"
    )


def main() -> None:
    directory = Path(__file__).resolve().parent
    input_path = (directory / INPUT_PATH).resolve()
    image: np.ndarray | None = None
    regions: dict[int, list[Rect]] = {}
    region_rows: list[tuple[int, int]] = []
    photo: tk.PhotoImage | None = None
    display_bounds = (0, 0, 1, 1)
    drag_start: tuple[float, float] | None = None

    root = tk.Tk()
    root.title("01 — 初期指定の作成・確認")
    root.geometry("1000x700")
    root.minsize(900, 650)
    mode = tk.IntVar(value=cv.GC_PR_FGD)
    view = tk.StringVar(value="initial")
    path_text = tk.StringVar(value="画像を開いてください")
    status = tk.StringVar(value="種類を選び、画像上をドラッグして矩形を指定します。")

    toolbar = ttk.Frame(root, padding=8)
    toolbar.pack(fill="x")
    ttk.Button(toolbar, text="画像を開く", command=lambda: open_image()).pack(
        side="left"
    )
    ttk.Label(toolbar, textvariable=path_text, wraplength=720).pack(
        side="left", padx=12
    )
    body = ttk.Frame(root, padding=(8, 0, 8, 8))
    body.pack(fill="both", expand=True)
    sidebar = ttk.Frame(body)
    sidebar.pack(side="left", fill="y", padx=(0, 10))
    preview = ttk.Frame(body)
    preview.pack(side="left", fill="both", expand=True)
    view_toolbar = ttk.Frame(preview)
    view_toolbar.pack(fill="x", pady=(0, 5))
    for value, name in (("initial", "初期指定"), ("original", "元画像")):
        ttk.Radiobutton(
            view_toolbar,
            text=name,
            variable=view,
            value=value,
            command=lambda: render(),
        ).pack(side="left", padx=(0, 8))
    canvas = tk.Canvas(preview, background="#242424", highlightthickness=0)
    canvas.pack(fill="both", expand=True)

    ttk.Label(sidebar, text="矩形の種類").pack(anchor="w")
    edit_widgets: list[ttk.Widget | tk.Listbox] = []
    for label, name in REGION_NAMES.items():
        radio = ttk.Radiobutton(
            sidebar,
            text=name,
            variable=mode,
            value=label,
            command=lambda: show_initial(),
        )
        radio.pack(anchor="w", pady=3)
        edit_widgets.append(radio)
    ttk.Label(
        sidebar,
        text="前景候補は描き直すと置き換わります。\n背景・前景は複数追加できます。\n灰色は未指定の背景候補です。\n重なると橙 → 青 → 緑の順に優先。",
    ).pack(anchor="w", pady=8)
    region_list = tk.Listbox(sidebar, width=32, height=7, exportselection=False)
    region_list.pack(fill="x")
    edit_widgets.append(region_list)
    for name, action in (
        ("選択した矩形を削除", lambda: delete_region()),
        ("既定の矩形に戻す", lambda: reset_regions()),
        ("確認画像を保存", lambda: save_image()),
        ("初期指定の設定をコピー", lambda: copy_settings()),
    ):
        button = ttk.Button(sidebar, text=name, command=action)
        button.pack(fill="x", pady=4)
        edit_widgets.append(button)
    ttk.Label(
        sidebar, text="表示だけ縮小し、確認画像は\n元の解像度で保存します。"
    ).pack(anchor="w", pady=8)
    ttk.Label(root, textvariable=status, padding=8, wraplength=850).pack(fill="x")

    def update_controls() -> None:
        for widget in edit_widgets:
            widget.configure({"state": "normal" if image is not None else "disabled"})

    def refresh_regions() -> None:
        region_rows.clear()
        # 無効状態のListboxは内容も変更できないため、更新中は有効にする。
        region_list.configure(state="normal")
        region_list.delete(0, tk.END)
        for label, name in REGION_NAMES.items():
            for index in range(len(regions[label])):
                region_rows.append((label, index))
                region_list.insert(tk.END, f"{name} {index + 1}")
        update_controls()
        show_initial()
        status.set(
            "初期指定を変更しました。元画像と照合して確認画像を保存してください。"
        )

    def reset_regions() -> None:
        regions[cv.GC_PR_FGD] = [CANDIDATE_RECT]
        regions[cv.GC_BGD] = list(BACKGROUND_RECTS)
        regions[cv.GC_FGD] = list(FOREGROUND_RECTS)
        refresh_regions()

    def show_initial() -> None:
        view.set("initial")
        render()

    def open_image(path: Path | None = None) -> None:
        nonlocal image, input_path
        if path is None:
            selected = filedialog.askopenfilename(
                parent=root,
                title="元画像を選ぶ",
                initialdir=input_path.parent,
                filetypes=[
                    ("画像", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff"),
                    ("すべて", "*.*"),
                ],
            )
            if not selected:
                return
            path = Path(selected)
        try:
            # 日本語のパスにも対応するため、画像のバイト列を読み込む。
            loaded = cv.imdecode(np.fromfile(path, np.uint8), cv.IMREAD_COLOR)
            if loaded is None:
                raise ValueError(f"入力画像を読み込めません: {path}")
        except (OSError, ValueError, cv.error) as error:
            messagebox.showerror("画像を開けません", str(error), parent=root)
            return
        image = loaded
        input_path = path.resolve()
        height, width = image.shape[:2]
        path_text.set(f"{input_path}  ({width} × {height} px)")
        reset_regions()

    def render() -> None:
        nonlocal photo, display_bounds, drag_start
        drag_start = None
        canvas.delete("all")
        if image is None:
            canvas.create_text(
                canvas.winfo_width() // 2,
                canvas.winfo_height() // 2,
                text="「画像を開く」から元画像を選んでください",
                fill="white",
            )
            return
        shown = image
        if view.get() == "initial":
            try:
                shown = initial_overlay(image, regions)
            except ValueError as error:
                status.set(str(error))
        height, width = shown.shape[:2]
        scale = min(canvas.winfo_width() / width, canvas.winfo_height() / height, 1)
        display_width = max(1, int(width * scale))
        display_height = max(1, int(height * scale))
        small = cv.resize(
            shown, (display_width, display_height), interpolation=cv.INTER_NEAREST
        )
        rgb = cv.cvtColor(small, cv.COLOR_BGR2RGB)
        header = f"P6\n{display_width} {display_height}\n255\n".encode("ascii")
        photo = tk.PhotoImage(master=root, data=header + rgb.tobytes(), format="PPM")
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
        if drag_start is None or image is None:
            return
        x, y = image_point(event)
        left, right = sorted((drag_start[0], x))
        top, bottom = sorted((drag_start[1], y))
        drag_start = None
        canvas.delete("drag")
        height, width = image.shape[:2]
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
        if image is None:
            return
        try:
            output = initial_overlay(image, regions)
            default_path = directory / OUTPUT_PATH
            selected = filedialog.asksaveasfilename(
                parent=root,
                title="確認画像の保存先を選ぶ",
                initialdir=default_path.parent
                if default_path.parent.exists()
                else directory,
                initialfile=default_path.name,
                defaultextension=".png",
                filetypes=[("PNG画像", "*.png")],
                confirmoverwrite=True,
            )
            if not selected:
                return
            output_path = Path(selected).resolve()
            if output_path == input_path:
                raise ValueError("保存先を入力画像とは別のパスにしてください")
            if output_path.suffix.lower() != ".png":
                raise ValueError("保存先の拡張子は .png にしてください")
            success, encoded = cv.imencode(".png", output)
            if not success:
                raise OSError("PNG画像を作成できません")
            encoded.tofile(output_path)
        except (OSError, ValueError, cv.error) as error:
            messagebox.showerror("保存できません", str(error), parent=root)
            return
        status.set(f"確認画像を保存しました: {output_path}")

    def copy_settings() -> None:
        if image is None:
            return
        try:
            make_labels(image, regions)
            text = settings_text(input_path, regions)
        except ValueError as error:
            messagebox.showerror("設定をコピーできません", str(error), parent=root)
            return
        root.clipboard_clear()
        root.clipboard_append(text)
        status.set(
            "初期指定をコピーしました。提出版の同名の4項目へ貼り付けてください。"
        )

    canvas.bind("<Configure>", lambda event: render())
    canvas.bind("<ButtonPress-1>", start_draw)
    canvas.bind("<B1-Motion>", drag_draw)
    canvas.bind("<ButtonRelease-1>", end_draw)
    region_list.bind("<<ListboxSelect>>", lambda event: show_initial())
    update_controls()
    if input_path.is_file():
        root.after(0, lambda: open_image(input_path))
    root.mainloop()


if __name__ == "__main__":
    main()
