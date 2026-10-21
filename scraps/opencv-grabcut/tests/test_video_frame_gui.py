"""合成動画を実Tkで操作し、表示したフレームと保存PNGを照合する。"""

import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from unittest.mock import patch

import cv2 as cv
import numpy as np
from test_refactored_workflow import load_refactored


def find_widgets(parent, widget_type):
    found = []
    for child in parent.winfo_children():
        if isinstance(child, widget_type):
            found.append(child)
        found.extend(find_widgets(child, widget_type))
    return found


class VideoFrameGuiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.video = self.directory / "撮影 動画.avi"
        self.expected = self.make_video(self.video, 6)
        self.gui = load_refactored("video_frame_gui.py")
        # 入出力は一時領域だけに置き、実際の入力フォルダを作らない。
        self.gui["main"].__globals__["FRAMES_DIRECTORY"] = self.directory / "frames"

    def make_video(self, path, count):
        writer = cv.VideoWriter(
            str(path), cv.VideoWriter.fourcc(*"MJPG"), 15, (1280, 720)
        )
        self.assertTrue(writer.isOpened())
        try:
            for index in range(count):
                image = np.full((720, 1280, 3), (20 + index * 30, 80, 190), np.uint8)
                cv.putText(
                    image,
                    str(index),
                    (500, 400),
                    cv.FONT_HERSHEY_SIMPLEX,
                    4,
                    (0, 0, 0),
                    8,
                )
                writer.write(image)
        finally:
            writer.release()
        reference = cv.VideoCapture(str(path))
        frames = []
        try:
            while True:
                success, frame = reference.read()
                if not success:
                    break
                frames.append(frame)
        finally:
            reference.release()
        self.assertEqual(len(frames), count)
        return frames

    def run_gui(self, actions):
        captures = []
        callback_errors = []
        original_capture = cv.VideoCapture

        def track_capture(*args):
            capture = original_capture(*args)
            captures.append(capture)
            return capture

        def report_error(_kind, error, _traceback):
            callback_errors.append(error)

        def mainloop(root):
            root.report_callback_exception = report_error
            try:
                root.update()
                buttons = {}
                for button in find_widgets(root, ttk.Button):
                    buttons[button.cget("text")] = button
                position = find_widgets(root, tk.Scale)[0]
                actions(root, buttons, position)
            finally:
                root.tk.call(root.protocol("WM_DELETE_WINDOW"))

        with (
            patch.object(tk.Tk, "mainloop", mainloop),
            patch.object(cv, "VideoCapture", side_effect=track_capture),
            patch.object(
                filedialog, "askopenfilename", return_value=str(self.video)
            ) as open_dialog,
            patch.object(filedialog, "asksaveasfilename") as save_dialog,
            patch.object(messagebox, "showerror") as errors,
        ):
            self.open_dialog = open_dialog
            self.save_dialog = save_dialog
            self.errors = errors
            self.gui["main"]()
        self.assertFalse(callback_errors, callback_errors)
        self.assertTrue(captures)
        for capture in captures:
            self.assertFalse(capture.isOpened())

    def assert_saved_frame(self, buttons, index):
        path = self.directory / f"保存 日本語/frame_{index}.png"
        self.save_dialog.return_value = str(path)
        buttons["フレームを保存"].invoke()
        decoded = cv.imdecode(
            np.frombuffer(path.read_bytes(), np.uint8), cv.IMREAD_COLOR
        )
        np.testing.assert_array_equal(decoded, self.expected[index])
        self.assertEqual(
            self.save_dialog.call_args.kwargs["initialfile"],
            f"撮影 動画_frame_{index:06d}.png",
        )
        self.assertTrue(self.save_dialog.call_args.kwargs["confirmoverwrite"])

    def wait_for(self, root, condition):
        deadline = time.monotonic() + 5
        while not condition() and time.monotonic() < deadline:
            root.update()
            time.sleep(0.005)
        self.assertTrue(condition())

    def test_selection_resize_and_original_pixels(self):
        def actions(root, buttons, position):
            self.assertTrue(buttons["フレームを保存"].instate(["disabled"]))
            buttons["動画を開く"].invoke()
            root.update()
            self.assertIn(self.video.name, root.title())
            self.assert_saved_frame(buttons, 0)
            buttons["1コマ戻る"].invoke()
            buttons["1コマ進む"].invoke()
            self.assert_saved_frame(buttons, 1)
            position.set(4)
            root.update()
            buttons["1コマ戻る"].invoke()
            root.update()
            self.assert_saved_frame(buttons, 3)
            position.set(5)
            root.update()
            buttons["1コマ進む"].invoke()
            self.assert_saved_frame(buttons, 5)
            root.geometry("640x480")
            root.update()
            canvas = find_widgets(root, tk.Canvas)[0]
            photo = canvas.itemcget(canvas.find_all()[0], "image")
            self.assertLess(int(root.tk.call("image", "width", photo)), 1280)
            self.assertLess(int(root.tk.call("image", "height", photo)), 720)
            rgb = tuple(root.tk.call(photo, "get", 10, 10))
            self.assertEqual(rgb, tuple(int(c) for c in self.expected[5][10, 10, ::-1]))
            self.assert_saved_frame(buttons, 5)
            self.errors.assert_not_called()

        self.run_gui(actions)

    def test_playback_pause_end_replay_and_save_cancel(self):
        def actions(root, buttons, position):
            buttons["動画を開く"].invoke()
            root.update()
            buttons["再生"].invoke()
            self.wait_for(root, lambda: position.get() >= 1)
            buttons["再生"].invoke()
            paused_index = position.get()
            root.update()
            self.assert_saved_frame(buttons, paused_index)
            buttons["再生"].invoke()
            self.wait_for(root, lambda: buttons["再生"].cget("text") == "再生")
            self.assertEqual(position.get(), 5)
            self.assert_saved_frame(buttons, 5)
            buttons["再生"].invoke()
            self.assertEqual(position.get(), 0)
            self.assertEqual(buttons["再生"].cget("text"), "一時停止")
            position.event_generate("<ButtonPress-1>", x=20, y=10)
            root.update()
            self.assertEqual(buttons["再生"].cget("text"), "再生")
            self.assertEqual(root.after_info(), ())
            buttons["再生"].invoke()
            self.save_dialog.return_value = ""
            buttons["フレームを保存"].invoke()
            self.assertEqual(buttons["再生"].cget("text"), "再生")
            self.assertEqual(root.after_info(), ())
            buttons["再生"].invoke()
            position.set(3)
            root.update()
            self.assertEqual(buttons["再生"].cget("text"), "再生")
            self.assert_saved_frame(buttons, 3)
            self.errors.assert_not_called()

        self.run_gui(actions)

    def test_failed_load_and_save_keep_current_frame_and_existing_file(self):
        def actions(root, buttons, position):
            buttons["動画を開く"].invoke()
            position.set(2)
            root.update()
            self.open_dialog.return_value = ""
            buttons["動画を開く"].invoke()
            self.open_dialog.return_value = str(self.directory / "missing.mp4")
            buttons["動画を開く"].invoke()
            self.errors.assert_called_once()
            self.assert_saved_frame(buttons, 2)
            self.save_dialog.return_value = str(self.video)
            before = self.video.read_bytes()
            buttons["フレームを保存"].invoke()
            self.assertEqual(self.video.read_bytes(), before)
            self.assertEqual(self.errors.call_count, 2)
            output = self.directory / "existing.png"
            output.write_bytes(b"keep existing file")
            self.save_dialog.return_value = str(output)
            with patch.object(cv, "imencode", return_value=(False, None)):
                buttons["フレームを保存"].invoke()
            self.assertEqual(output.read_bytes(), b"keep existing file")
            self.assertEqual(self.errors.call_count, 3)
            self.assert_saved_frame(buttons, 2)
            self.open_dialog.return_value = str(self.video)
            buttons["再生"].invoke()
            buttons["動画を開く"].invoke()
            root.update()
            self.assertEqual(position.get(), 0)
            self.assertEqual(root.after_info(), ())
            self.assert_saved_frame(buttons, 0)

        self.run_gui(actions)

    def test_single_frame_video_can_be_saved(self):
        self.video = self.directory / "single.avi"
        self.expected = self.make_video(self.video, 1)

        def actions(root, buttons, position):
            buttons["動画を開く"].invoke()
            buttons["再生"].invoke()
            buttons["1コマ戻る"].invoke()
            buttons["1コマ進む"].invoke()
            root.update()
            self.assertEqual(position.get(), 0)
            self.assertEqual(root.after_info(), ())
            self.save_dialog.return_value = str(self.directory / "single.png")
            buttons["フレームを保存"].invoke()
            decoded = cv.imdecode(
                np.frombuffer((self.directory / "single.png").read_bytes(), np.uint8),
                cv.IMREAD_COLOR,
            )
            np.testing.assert_array_equal(decoded, self.expected[0])
            self.errors.assert_not_called()

        self.run_gui(actions)


if __name__ == "__main__":
    unittest.main()
