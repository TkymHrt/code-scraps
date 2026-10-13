"""非表示のTkウィンドウで、01のGUI版の矩形指定・確認画像保存を確認する."""

import runpy
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import ttk
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
        source = source.replace(
            'INPUT_PATH = "input.png"', 'INPUT_PATH = "日本語の入力.png"'
        )
        source = source.replace(
            'OUTPUT_PATH = "results/01_initial_regions_gui.png"',
            'OUTPUT_PATH = "results/日本語の確認.png"',
        )
        script.write_text(source, encoding="utf-8")
        gui = runpy.run_path(str(script))
        output_path = directory / gui["OUTPUT_PATH"]
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

            assert region_list.size() == 4
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
            regions = {
                cv.GC_PR_FGD: [gui["CANDIDATE_RECT"]],
                cv.GC_BGD: list(gui["BACKGROUND_RECTS"]),
                cv.GC_FGD: list(gui["FOREGROUND_RECTS"]),
            }
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
            assert region_list.size() == 6
            invoke("既定の矩形に戻す")
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
            assert region_list.size() == 4
            invoke("初期指定の設定をコピー")
            copied = {}
            exec(root.clipboard_get(), copied)
            assert copied["INPUT_PATH"] == input_path.as_posix()
            assert set(copied) - {"__builtins__"} == {
                "INPUT_PATH",
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
            assert region_list.size() == 3
            invoke("既定の矩形に戻す")
            assert region_list.size() == 4
            # 入力画像と同じ保存先は、GUIを起動する前に拒否する。
            gui["main"].__globals__["OUTPUT_PATH"] = str(input_path)
            with patch.object(tk, "Tk", side_effect=AssertionError("Unexpected GUI")):
                try:
                    gui["main"]()
                except ValueError as error:
                    assert "入力画像" in str(error)
                else:
                    raise AssertionError("入力画像と同じ保存先を許可しました")
            assert input_path.read_bytes() == original_bytes
            print(
                "01 GUI smoke passed: preview, scaled drag, copy, delete, reset, save, input protection; no GrabCut"
            )

        try:
            with (
                patch.object(tk, "Tk", return_value=root),
                patch.object(root, "mainloop", side_effect=exercise),
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
