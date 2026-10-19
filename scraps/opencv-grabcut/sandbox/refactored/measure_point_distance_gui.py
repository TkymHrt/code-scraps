"""補正画像上の2点をクリックし、直線距離をmmで表示する。"""

import math
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import cv2 as cv
import numpy as np
from file_io import encode_png, read_image
from workflow_settings import MM_PER_PX, RECTIFIED_DIRECTORY


def main() -> None:
    if not math.isfinite(MM_PER_PX) or MM_PER_PX <= 0:
        raise ValueError("MM_PER_PXを正の数値にしてください")

    root = tk.Tk()
    root.title("2点間の距離")
    root.geometry("1000x760")
    root.minsize(640, 480)

    image: np.ndarray | None = None
    photo: tk.PhotoImage | None = None
    width = height = 1
    points: list[tuple[float, float]] = []
    scale = 1.0
    offset_x = offset_y = 0.0
    pan_start: tuple[int, int] | None = None
    distance_text = tk.StringVar(value="距離：—")

    def render(_event=None) -> None:
        nonlocal photo
        canvas.delete("all")
        if image is None:
            return
        canvas_width = max(1, canvas.winfo_width())
        canvas_height = max(1, canvas.winfo_height())
        transform = np.array([[scale, 0, offset_x], [0, scale, offset_y]])
        interpolation = cv.INTER_LINEAR
        if scale >= 1:
            interpolation = cv.INTER_NEAREST
        # 拡大後の画像全体ではなく、画面に見える範囲だけを作る。
        preview = cv.warpAffine(
            image,
            transform,
            (canvas_width, canvas_height),
            flags=interpolation,
            borderValue=(51, 51, 51),
        )
        photo = tk.PhotoImage(master=root, data=encode_png(preview), format="PNG")
        canvas.create_image(0, 0, image=photo, anchor="nw")

        display_points = []
        for image_x, image_y in points:
            display_x = offset_x + image_x * scale
            display_y = offset_y + image_y * scale
            display_points.append((display_x, display_y))
        if len(display_points) == 2:
            start_x, start_y = display_points[0]
            end_x, end_y = display_points[1]
            canvas.create_line(start_x, start_y, end_x, end_y, fill="yellow", width=2)
        for display_x, display_y in display_points:
            canvas.create_oval(
                display_x - 4,
                display_y - 4,
                display_x + 4,
                display_y + 4,
                fill="yellow",
                outline="black",
            )

    def fit_image() -> None:
        nonlocal scale, offset_x, offset_y, pan_start
        if image is None:
            return
        scale = min(canvas.winfo_width() / width, canvas.winfo_height() / height, 1)
        offset_x = (canvas.winfo_width() - width * scale) / 2
        offset_y = (canvas.winfo_height() - height * scale) / 2
        pan_start = None
        canvas.configure(cursor="crosshair")
        render()

    def load_image() -> None:
        nonlocal image, width, height
        selected = filedialog.askopenfilename(
            parent=root,
            title="補正画像を選ぶ",
            initialdir=RECTIFIED_DIRECTORY,
            filetypes=[("PNG画像", "*.png"), ("すべて", "*.*")],
        )
        if not selected:
            return
        path = Path(selected)
        try:
            loaded = read_image(path)
        except ValueError as error:
            messagebox.showerror("画像読込エラー", str(error), parent=root)
            return
        image = loaded
        height, width = image.shape[:2]
        points.clear()
        distance_text.set("距離：—")
        root.title(f"2点間の距離：{path.name}")
        fit_image()
        canvas.focus_set()

    def select_point(event: tk.Event) -> None:
        if image is None:
            return
        # 拡大率と移動量を戻し、元画像の座標で測る。
        image_x = (event.x - offset_x) / scale
        image_y = (event.y - offset_y) / scale
        if not (0 <= image_x < width and 0 <= image_y < height):
            return
        if len(points) == 2:
            points.clear()
        points.append((image_x, image_y))
        distance_text.set("距離：—")
        if len(points) == 2:
            start_x, start_y = points[0]
            end_x, end_y = points[1]
            distance_px = math.hypot(end_x - start_x, end_y - start_y)
            distance_mm = distance_px * MM_PER_PX
            distance_text.set(f"距離：{distance_mm:.2f} mm")
        render()

    def zoom(event: tk.Event) -> str:
        nonlocal scale, offset_x, offset_y
        if image is None or event.delta == 0:
            return "break"
        image_x = (event.x - offset_x) / scale
        image_y = (event.y - offset_y) / scale
        factor = 1.2 ** (event.delta / 120)
        scale = min(16.0, max(0.01, scale * factor))
        # カーソルが指していた場所を、拡大縮小後も同じ位置に保つ。
        offset_x = event.x - image_x * scale
        offset_y = event.y - image_y * scale
        render()
        return "break"

    def start_pan(event: tk.Event) -> None:
        nonlocal pan_start
        if image is not None:
            pan_start = (event.x, event.y)
            canvas.configure(cursor="fleur")

    def pan(event: tk.Event) -> None:
        nonlocal offset_x, offset_y, pan_start
        if pan_start is None:
            return
        offset_x += event.x - pan_start[0]
        offset_y += event.y - pan_start[1]
        pan_start = (event.x, event.y)
        render()

    def end_pan(_event: tk.Event) -> None:
        nonlocal pan_start
        pan_start = None
        canvas.configure(cursor="crosshair")

    def focus_canvas(_event: tk.Event) -> None:
        canvas.focus_set()

    header = ttk.Frame(root, padding=12)
    header.pack(fill="x")
    ttk.Button(header, text="補正画像を読み込む", command=load_image).pack(side="left")
    ttk.Button(header, text="全体表示", command=fit_image).pack(side="left", padx=8)
    ttk.Label(header, textvariable=distance_text).pack(side="right")
    ttk.Label(root, text="ホイール：拡大縮小　右ドラッグ：移動").pack(
        anchor="w", padx=12, pady=(0, 6)
    )
    canvas = tk.Canvas(
        root, background="#333333", highlightthickness=0, cursor="crosshair"
    )
    canvas.pack(fill="both", expand=True, padx=12, pady=(0, 12))
    canvas.bind("<Configure>", render)
    canvas.bind("<Button-1>", select_point)
    canvas.bind("<MouseWheel>", zoom)
    canvas.bind("<ButtonPress-3>", start_pan)
    canvas.bind("<B3-Motion>", pan)
    canvas.bind("<ButtonRelease-3>", end_pan)
    canvas.bind("<Enter>", focus_canvas)
    root.mainloop()


if __name__ == "__main__":
    main()
