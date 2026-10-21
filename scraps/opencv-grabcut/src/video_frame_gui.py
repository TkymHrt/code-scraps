"""動画を再生し、表示中のフレームを元の解像度でPNGへ保存する。"""

import math
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import cv2 as cv
import numpy as np

from utils.file_io import check_output_path, write_png
from workflow_settings import INPUT_DIRECTORY

FRAMES_DIRECTORY = INPUT_DIRECTORY / "video_frames"


def main() -> None:
    root = tk.Tk()
    root.title("動画からフレームを保存")
    root.geometry("1000x760")
    root.minsize(640, 480)

    capture: cv.VideoCapture | None = None
    video_path: Path | None = None
    frame: np.ndarray | None = None
    photo: tk.PhotoImage | None = None
    frame_index = 0
    frame_count = 0
    fps = 0.0
    timer_id: str | None = None
    position_text = tk.StringVar(value="動画を選んでください")
    status_text = tk.StringVar()

    def render(_event=None) -> None:
        nonlocal photo
        if frame is None:
            return
        height, width = frame.shape[:2]
        canvas_width = max(1, canvas.winfo_width())
        canvas_height = max(1, canvas.winfo_height())
        scale = min(canvas_width / width, canvas_height / height, 1.0)
        preview = cv.resize(
            frame,
            (max(1, round(width * scale)), max(1, round(height * scale))),
            interpolation=cv.INTER_AREA,
        )
        # 表示用だけ縮小する。保存には元のframeを使う。
        rgb = cv.cvtColor(preview, cv.COLOR_BGR2RGB)
        preview_height, preview_width = rgb.shape[:2]
        header = f"P6\n{preview_width} {preview_height}\n255\n".encode("ascii")
        photo = tk.PhotoImage(master=root, data=header + rgb.tobytes(), format="PPM")
        canvas.delete("all")
        canvas.create_image(canvas_width / 2, canvas_height / 2, image=photo)

    def pause(_event=None) -> None:
        nonlocal timer_id
        if timer_id is not None:
            root.after_cancel(timer_id)
            timer_id = None
        play_button.configure(text="再生")

    def show_frame(index: int) -> bool:
        nonlocal frame, frame_index
        if capture is None:
            return False
        try:
            # 通常再生は順に読み、位置を移動したときだけシークする。
            if round(capture.get(cv.CAP_PROP_POS_FRAMES)) != index:
                if not capture.set(cv.CAP_PROP_POS_FRAMES, index):
                    raise ValueError("この動画では位置を移動できません")
            success, loaded = capture.read()
            if not success:
                raise ValueError(f"フレーム {index} を読み込めません")
        except (ValueError, cv.error) as error:
            pause()
            status_text.set("フレーム読込失敗")
            messagebox.showerror("動画読込エラー", str(error), parent=root)
            return False
        frame = loaded
        frame_index = index
        position.set(frame_index)
        position_text.set(
            f"フレーム {frame_index} / {frame_count - 1}"
            f"　{frame_index / fps:.3f} 秒　{fps:g} fps"
        )
        status_text.set("")
        render()
        return True

    def load_video() -> None:
        nonlocal capture, video_path, frame_count, fps, frame, frame_index
        pause()
        selected = filedialog.askopenfilename(
            parent=root,
            title="動画を選ぶ",
            initialdir=INPUT_DIRECTORY,
            filetypes=[
                ("動画", "*.mp4 *.mov *.avi *.mkv *.m4v"),
                ("すべて", "*.*"),
            ],
        )
        if not selected:
            return
        path = Path(selected).resolve()
        loaded_capture = cv.VideoCapture()
        try:
            if not loaded_capture.open(str(path)):
                raise ValueError(f"動画を開けません: {path.name}")
            # 校正画像と画素の向きを揃えるため、自動回転を無効にする。
            loaded_capture.set(cv.CAP_PROP_ORIENTATION_AUTO, 0)
            count = loaded_capture.get(cv.CAP_PROP_FRAME_COUNT)
            rate = loaded_capture.get(cv.CAP_PROP_FPS)
            if not math.isfinite(count) or count < 1:
                raise ValueError("フレーム数を取得できない動画です")
            if not math.isfinite(rate) or rate <= 0:
                raise ValueError("FPSを取得できない動画です")
            success, first_frame = loaded_capture.read()
            if not success:
                raise ValueError(f"先頭フレームを読み込めません: {path.name}")
        except (ValueError, cv.error) as error:
            loaded_capture.release()
            messagebox.showerror("動画読込エラー", str(error), parent=root)
            return
        if capture is not None:
            capture.release()
        capture = loaded_capture
        video_path = path
        frame_count = int(count)
        fps = rate
        position.configure(to=frame_count - 1, state="normal")
        for button in (play_button, previous_button, next_button, save_button):
            button.configure(state="normal")
        root.title(f"動画からフレームを保存：{path.name}")
        # 読込確認済みの先頭フレームを表示し、再生はボタンで開始する。
        frame = first_frame
        frame_index = 0
        position.set(0)
        position_text.set(f"フレーム 0 / {frame_count - 1}　0.000 秒　{fps:g} fps")
        status_text.set("")
        render()

    def seek(value) -> None:
        if capture is None:
            return
        index = min(frame_count - 1, max(0, round(float(value))))
        # 再生中にスライダーを表示更新した場合は読み直さない。
        if index == frame_index:
            return
        pause()
        if not show_frame(index):
            position.set(frame_index)

    def previous_frame() -> None:
        pause()
        seek(frame_index - 1)

    def next_frame() -> None:
        pause()
        seek(frame_index + 1)

    def play_next_frame() -> None:
        nonlocal timer_id
        timer_id = None
        started = time.perf_counter()
        if not show_frame(frame_index + 1):
            return
        if frame_index == frame_count - 1:
            pause()
            status_text.set("動画の末尾です")
            return
        elapsed_ms = (time.perf_counter() - started) * 1000
        delay_ms = max(1, round(1000 / fps - elapsed_ms))
        timer_id = root.after(delay_ms, play_next_frame)

    def toggle_playback() -> None:
        nonlocal timer_id
        if capture is None:
            return
        if timer_id is not None:
            pause()
            return
        if frame_count == 1:
            status_text.set("動画の末尾です")
            return
        if frame_index == frame_count - 1:
            if not show_frame(0):
                return
        play_button.configure(text="一時停止")
        timer_id = root.after(max(1, round(1000 / fps)), play_next_frame)

    def save_frame() -> None:
        if frame is None or video_path is None:
            return
        pause()
        try:
            FRAMES_DIRECTORY.mkdir(parents=True, exist_ok=True)
            selected = filedialog.asksaveasfilename(
                parent=root,
                title="表示中のフレームを保存",
                initialdir=FRAMES_DIRECTORY,
                initialfile=f"{video_path.stem}_frame_{frame_index:06d}.png",
                defaultextension=".png",
                filetypes=[("PNG画像", "*.png")],
                confirmoverwrite=True,
            )
            if not selected:
                return
            path = check_output_path(Path(selected), ".png", [video_path])
            write_png(path, frame)
        except (ValueError, OSError) as error:
            messagebox.showerror("フレーム保存エラー", str(error), parent=root)
            return
        status_text.set(f"保存: {path}")

    def close() -> None:
        pause()
        root.destroy()

    header = ttk.Frame(root, padding=12)
    header.pack(fill="x")
    ttk.Button(header, text="動画を開く", command=load_video).pack(side="left")
    play_button = ttk.Button(
        header, text="再生", command=toggle_playback, state="disabled"
    )
    play_button.pack(side="left", padx=(8, 0))
    previous_button = ttk.Button(
        header, text="1コマ戻る", command=previous_frame, state="disabled"
    )
    previous_button.pack(side="left", padx=(8, 0))
    next_button = ttk.Button(
        header, text="1コマ進む", command=next_frame, state="disabled"
    )
    next_button.pack(side="left", padx=(8, 0))
    save_button = ttk.Button(
        header, text="フレームを保存", command=save_frame, state="disabled"
    )
    save_button.pack(side="right")
    ttk.Label(root, textvariable=position_text).pack(anchor="w", padx=12)
    position = tk.Scale(
        root,
        from_=0,
        to=0,
        orient="horizontal",
        showvalue=False,
        resolution=1,
        command=seek,
        state="disabled",
    )
    position.pack(fill="x", padx=12)
    position.bind("<ButtonPress-1>", pause)
    canvas = tk.Canvas(root, background="#333333", highlightthickness=0)
    canvas.pack(fill="both", expand=True, padx=12, pady=6)
    canvas.bind("<Configure>", render)
    ttk.Label(root, textvariable=status_text, wraplength=600).pack(
        anchor="w", padx=12, pady=(0, 12)
    )
    root.protocol("WM_DELETE_WINDOW", close)
    try:
        root.mainloop()
    finally:
        if capture is not None:
            capture.release()


if __name__ == "__main__":
    main()
