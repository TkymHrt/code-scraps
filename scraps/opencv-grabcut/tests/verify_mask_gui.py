"""非表示のTkウィンドウで、01のGUI版の読み込み・矩形指定・保存を確認する."""

import runpy
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from unittest.mock import patch

import cv2 as cv
import numpy as np


def main() -> None:
    project = Path(__file__).resolve().parents[1]
    results = project / "tests/results"
    results.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=results) as temporary:
        directory = Path(temporary).resolve()
        if not directory.is_relative_to(results.resolve()):
            raise ValueError("検証用の一時領域が試験結果フォルダ外にあります")
        script = directory / "01_initial_regions_gui.py"
        source = (project / "submissions/01_initial_regions_gui.py").read_text(
            encoding="utf-8"
        )
        script.write_text(source, encoding="utf-8")
        gui = runpy.run_path(str(script))
        output_path = directory / "日本語の確認.png"
        expected = np.zeros((800, 700), np.uint8)
        expected[100:701, 250:451] = 255
        expected[250:325, 275:305] = 0
        expected[40:70, 250:285] = 255
        image = np.full((800, 700, 3), 35, np.uint8)
        image[expected > 0] = 200
        input_path = directory / "日本語の入力.png"
        success, encoded = cv.imencode(".png", image)
        if not success:
            raise OSError("検証用画像を作成できません")
        encoded.tofile(input_path)
        original_bytes = input_path.read_bytes()

        root = tk.Tk()
        root.withdraw()
        root.attributes("-alpha", 0)
        try:
            clipboard = root.clipboard_get()
        except tk.TclError:
            clipboard = None
        callback_errors = []

        def descendants(widget: tk.Misc) -> list[tk.Misc]:
            found: list[tk.Misc] = []
            for child in widget.winfo_children():
                found.append(child)
                found.extend(descendants(child))
            return found

        def exercise() -> None:
            root.deiconify()
            root.update()
            widgets = descendants(root)
            buttons = {
                str(widget.cget("text")): widget
                for widget in widgets
                if isinstance(widget, (ttk.Button, ttk.Radiobutton))
            }
            canvas = next(widget for widget in widgets if isinstance(widget, tk.Canvas))
            region_list = next(
                widget for widget in widgets if isinstance(widget, tk.Listbox)
            )
            assert not any(isinstance(widget, ttk.Entry) for widget in widgets)

            def invoke(name: str) -> None:
                buttons[name].invoke()
                root.update()

            open_dialog.assert_not_called()
            assert not canvas.find_all(), "起動時に画像が読み込まれています"
            assert region_list.size() == 0, "起動時に矩形が配置されています"
            invoke("確認画像を保存")
            save_dialog.assert_not_called()
            canvas.event_generate("<ButtonPress-1>", x=0, y=0)
            canvas.event_generate("<ButtonRelease-1>", x=1, y=1)
            root.update()
            assert region_list.size() == 0, "未読込の画面に矩形が追加されています"
            with patch.object(filedialog, "askopenfilename", return_value=""):
                invoke("画像を読み込む")
            assert root.winfo_exists() and not canvas.find_all()
            invoke("画像を読み込む")
            open_dialog.assert_called_once()
            assert region_list.size() == 0
            # 保存先の選択をキャンセルした場合はファイルを作らない。
            with patch.object(filedialog, "asksaveasfilename", return_value=""):
                invoke("確認画像を保存")
            assert not output_path.exists()
            invoke("初期指定の設定をコピー")
            assert len(callback_errors) == 1 and isinstance(
                callback_errors[0], ValueError
            )
            assert "前景候補" in str(callback_errors[0])
            assert canvas.find_all(), "プレビューを表示できません"
            root.geometry("900x650")
            root.update()
            for name, button in buttons.items():
                assert button.winfo_ismapped(), f"操作が隠れています: {name}"
                assert button.winfo_height() >= button.winfo_reqheight(), (
                    f"操作が隠れています: {name}"
                )
            invoke("確認画像を保存")
            overlay = cv.imdecode(np.fromfile(output_path, np.uint8), cv.IMREAD_COLOR)
            regions = {label: [] for label in gui["REGION_NAMES"]}
            expected_empty = cv.addWeighted(
                image, 0.65, np.full_like(image, (64, 64, 64)), 0.35, 0
            )
            np.testing.assert_array_equal(overlay, expected_empty)
            np.testing.assert_array_equal(
                overlay, gui["initial_overlay"](image, regions)
            )

            # 元画像の表示から種類を選ぶだけで編集に戻り、背景・前景を追加する。
            invoke("元画像")
            for name in ("確実な背景（青）", "確実な前景（緑）"):
                invoke(name)
                item = canvas.find_all()[0]
                x0, y0 = canvas.coords(item)
                photo_name = canvas.itemcget(item, "image")
                width = int(root.tk.call("image", "width", photo_name))
                height = int(root.tk.call("image", "height", photo_name))
                canvas.event_generate(
                    "<ButtonPress-1>",
                    x=int(x0 + width * 0.5),
                    y=int(y0 + height * 0.45),
                )
                canvas.event_generate(
                    "<ButtonRelease-1>",
                    x=int(x0 + width * 0.55),
                    y=int(y0 + height * 0.5),
                )
                root.update()
            assert region_list.size() == 2
            invoke("前景候補（橙）")

            # 縮小表示上で逆向きにドラッグし、コピーされた元画像の指定と照合する。
            invoke("初期指定")
            item = canvas.find_all()[0]
            x0, y0 = canvas.coords(item)
            photo_name = canvas.itemcget(item, "image")
            width = int(root.tk.call("image", "width", photo_name))
            height = int(root.tk.call("image", "height", photo_name))
            assert height < image.shape[0], "縮小表示の条件になっていません"
            start_x, start_y = int(x0 + width * 0.78), int(y0 + height * 0.94)
            end_x, end_y = int(x0 + width * 0.25), int(y0 + height * 0.08)
            canvas.event_generate("<ButtonPress-1>", x=start_x, y=start_y)
            canvas.event_generate("<B1-Motion>", x=end_x, y=end_y)
            canvas.event_generate("<ButtonRelease-1>", x=end_x, y=end_y)
            root.update()
            assert region_list.size() == 3
            # 前景候補は再び描いても増えず、置き換わる。
            canvas.event_generate("<ButtonPress-1>", x=start_x, y=start_y)
            canvas.event_generate("<ButtonRelease-1>", x=end_x, y=end_y)
            root.update()
            assert region_list.size() == 3
            invoke("初期指定の設定をコピー")
            copied = {}
            exec(root.clipboard_get(), copied)
            assert set(copied) - {"__builtins__"} == {
                "CANDIDATE_RECT",
                "BACKGROUND_RECTS",
                "FOREGROUND_RECTS",
            }
            assert copied["CANDIDATE_RECT"] == (
                (end_x - x0) / width,
                (end_y - y0) / height,
                (start_x - x0) / width,
                (start_y - y0) / height,
            )
            # 読み込みをキャンセルしても、現在の画像と矩形を保つ。
            with patch.object(filedialog, "askopenfilename", return_value=""):
                invoke("画像を読み込む")
            assert root.winfo_exists() and region_list.size() == 3
            # 編集直後に保存でき、保存画像はコピーした指定と一致する。
            invoke("確認画像を保存")
            edited = cv.imdecode(np.fromfile(output_path, np.uint8), cv.IMREAD_COLOR)
            edited_regions = {
                cv.GC_PR_FGD: [copied["CANDIDATE_RECT"]],
                cv.GC_BGD: list(copied["BACKGROUND_RECTS"]),
                cv.GC_FGD: list(copied["FOREGROUND_RECTS"]),
            }
            np.testing.assert_array_equal(
                edited, gui["initial_overlay"](image, edited_regions)
            )

            region_list.selection_set(1)
            region_list.event_generate("<<ListboxSelect>>")
            root.update()
            assert len(canvas.find_all()) == 2, "選択した矩形の枠がありません"
            invoke("選択した矩形を削除")
            assert region_list.size() == 2
            # 前景候補だけでもコピーでき、確実な背景・前景は空のタプルになる。
            region_list.selection_set(1)
            invoke("選択した矩形を削除")
            assert region_list.size() == 1
            invoke("初期指定の設定をコピー")
            candidate_only = {}
            exec(root.clipboard_get(), candidate_only)
            assert candidate_only["BACKGROUND_RECTS"] == ()
            assert candidate_only["FOREGROUND_RECTS"] == ()
            invoke("矩形をすべて削除")
            assert region_list.size() == 0
            # 保存先として入力画像を選んでも、元画像は上書きしない。
            with patch.object(
                filedialog, "asksaveasfilename", return_value=str(input_path)
            ):
                invoke("確認画像を保存")
            assert len(callback_errors) == 2 and "入力画像" in str(callback_errors[-1])
            assert input_path.read_bytes() == original_bytes
            invalid_path = directory / "確認.jpg"
            with patch.object(
                filedialog, "asksaveasfilename", return_value=str(invalid_path)
            ):
                invoke("確認画像を保存")
            assert not invalid_path.exists()
            assert len(callback_errors) == 3 and ".png" in str(callback_errors[-1])
            # 別の画像を読み込むと矩形を消し、新しい解像度で保存する。
            canvas.event_generate("<ButtonPress-1>", x=start_x, y=start_y)
            canvas.event_generate("<ButtonRelease-1>", x=end_x, y=end_y)
            root.update()
            assert region_list.size() == 1
            second_image = np.full((120, 200, 3), (40, 80, 160), np.uint8)
            second_path = directory / "別の入力.png"
            success, encoded = cv.imencode(".png", second_image)
            assert success
            encoded.tofile(second_path)
            with patch.object(
                filedialog, "askopenfilename", return_value=str(second_path)
            ):
                invoke("画像を読み込む")
            assert region_list.size() == 0
            invoke("確認画像を保存")
            reloaded = cv.imdecode(np.fromfile(output_path, np.uint8), cv.IMREAD_COLOR)
            np.testing.assert_array_equal(
                reloaded, gui["initial_overlay"](second_image, regions)
            )
            assert save_dialog.call_args.kwargs["initialfile"] == (
                "別の入力_initial_regions.png"
            )
            assert len(callback_errors) == 3, callback_errors
            print(
                "01 GUI smoke passed: load button, native file dialogs, cancellation, reload, empty start, manual rectangles, scaled drag, rectangle-only copy, delete, clear, save, input protection; no GrabCut"
            )

        try:
            with (
                patch.object(tk, "Tk", return_value=root),
                patch.object(root, "mainloop", side_effect=exercise),
                patch.object(
                    filedialog, "askopenfilename", return_value=str(input_path)
                ) as open_dialog,
                patch.object(
                    filedialog, "asksaveasfilename", return_value=str(output_path)
                ) as save_dialog,
                patch.object(
                    root,
                    "report_callback_exception",
                    side_effect=lambda kind, error, trace: callback_errors.append(
                        error
                    ),
                ),
                patch.object(
                    cv, "grabCut", side_effect=AssertionError("Unexpected GrabCut")
                ),
            ):
                gui["main"]()
        finally:
            root.clipboard_clear()
            if clipboard is not None:
                root.clipboard_append(clipboard)
            root.update()
            root.destroy()


if __name__ == "__main__":
    main()
