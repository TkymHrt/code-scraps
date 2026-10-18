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
    display_bounds = (0, 0, 1, 1)
    distance_text = tk.StringVar(value="距離：—")

    def render(_event=None) -> None:
        nonlocal photo, display_bounds
        canvas.delete("all")
        if image is None:
            return
        scale = min(canvas.winfo_width() / width, canvas.winfo_height() / height, 1)
        display_width = max(1, int(width * scale))
        display_height = max(1, int(height * scale))
        preview = cv.resize(
            image, (display_width, display_height), interpolation=cv.INTER_AREA
        )
        photo = tk.PhotoImage(master=root, data=encode_png(preview), format="PNG")
        display_left = (canvas.winfo_width() - display_width) // 2
        display_top = (canvas.winfo_height() - display_height) // 2
        display_bounds = (
            display_left,
            display_top,
            display_left + display_width,
            display_top + display_height,
        )
        canvas.create_image(display_left, display_top, image=photo, anchor="nw")

        display_points = []
        for image_x, image_y in points:
            display_x = display_left + image_x * display_width / width
            display_y = display_top + image_y * display_height / height
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
        render()

    def select_point(event: tk.Event) -> None:
        if image is None:
            return
        display_left, display_top, display_right, display_bottom = display_bounds
        if not (
            display_left <= event.x < display_right
            and display_top <= event.y < display_bottom
        ):
            return
        display_width = display_right - display_left
        display_height = display_bottom - display_top
        # 縮小表示の距離ではなく、元画像上の距離を測る。
        image_x = (event.x - display_left) * width / display_width
        image_y = (event.y - display_top) * height / display_height
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

    header = ttk.Frame(root, padding=12)
    header.pack(fill="x")
    ttk.Button(header, text="補正画像を読み込む", command=load_image).pack(side="left")
    ttk.Label(header, textvariable=distance_text).pack(side="right")
    canvas = tk.Canvas(
        root, background="#333333", highlightthickness=0, cursor="crosshair"
    )
    canvas.pack(fill="both", expand=True, padx=12, pady=(0, 12))
    canvas.bind("<Configure>", render)
    canvas.bind("<Button-1>", select_point)
    root.mainloop()


if __name__ == "__main__":
    main()
