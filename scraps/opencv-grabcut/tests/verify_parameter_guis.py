"""設定・校正・長さ比較GUIの選択・計算・表示・保存を、実際のTkで確認する."""

import argparse
import ast
import csv
import hashlib
import runpy
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from unittest.mock import patch

import cv2 as cv
import numpy as np
from PIL import ImageGrab


def descendants(widget):
    found = []
    for child in widget.winfo_children():
        found.append(child)
        found.extend(descendants(child))
    return found


def literal_values(text):
    values = {}
    for node in ast.parse(text).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            values[node.targets[0].id] = ast.literal_eval(node.value)
    return values


def capture(root, path):
    root.attributes("-alpha", 1)
    root.lift()
    root.update()
    # Windows側の描画が反映されてからウィンドウを撮る。
    painted = tk.BooleanVar(master=root, value=False)
    root.after(100, painted.set, True)
    root.wait_variable(painted)
    root.update()
    # 表示倍率による論理座標と画素座標のずれを避け、ウィンドウを直接撮る。
    ImageGrab.grab(window=root.winfo_id()).save(path)
    root.attributes("-alpha", 0)
    root.update()


def exercise_measurement(project, output, root, screenshots):
    gui = runpy.run_path(str(project / "submissions/measurement_settings_gui.py"))
    errors = []

    def exercise():
        root.deiconify()
        root.update()
        widgets = descendants(root)
        buttons = {
            str(w.cget("text")): w
            for w in widgets
            if isinstance(w, (ttk.Button, ttk.Radiobutton))
        }
        canvas = next(w for w in widgets if isinstance(w, tk.Canvas))
        ranges = next(w for w in widgets if isinstance(w, tk.Listbox))
        target = next(w for w in widgets if isinstance(w, ttk.Combobox))
        notebook = next(w for w in widgets if isinstance(w, ttk.Notebook))
        root_labels = [w for w in root.winfo_children() if isinstance(w, ttk.Label)]
        summary_label, status_label = root_labels

        def text(label):
            return str(root.getvar(str(label.cget("textvariable"))))

        def invoke(name):
            buttons[name].invoke()
            root.update()

        def field(label):
            caption = next(
                w
                for w in widgets
                if isinstance(w, ttk.Label) and str(w.cget("text")) == label
            )
            return caption.master.grid_slaves(row=caption.grid_info()["row"], column=1)[
                0
            ]

        assert not canvas.find_all() and ranges.size() == 0
        invoke("計算して確認")
        assert "画像を読み込んで" in text(status_label)
        invoke("確認画像を保存")
        save_dialog.assert_not_called()
        root.clipboard_clear()
        root.clipboard_append("before")
        invoke("設定をコピー")
        assert root.clipboard_get() == "before"
        source = project / "submissions/08_candidate_sizes.py"
        with patch.object(filedialog, "askopenfilename", return_value=str(source)):
            invoke("スクリプトから設定を読む")
        assert ranges.size() == 4
        invoke("設定をコピー")
        copied = literal_values(root.clipboard_get())
        assert len(copied) == 12 and copied["START_Y"] == 80 and copied["END_Y"] == 1000
        initial = "\n".join(
            f"{name} = {copied[name]!r}"
            for name in ("CANDIDATE_RECT", "BACKGROUND_RECTS", "FOREGROUND_RECTS")
        )
        root.clipboard_clear()
        root.clipboard_append(initial)
        invoke("01の初期指定を貼り付け")
        invoke("計算して確認")
        assert "左2 / 右7" in text(summary_label), text(summary_label)
        assert "476.84" in text(summary_label)
        assert grabcut.call_count == 1
        if screenshots:
            capture(root, output / "measurement.png")
            notebook.select(1)
            root.update()
            capture(root, output / "measurement_conditions.png")
            notebook.select(0)
            root.update()
        root.geometry("1040x720")
        root.update()
        for name, button in buttons.items():
            assert button.winfo_ismapped(), f"操作が隠れています: {name}"
            assert button.winfo_height() >= button.winfo_reqheight(), (
                f"操作が切れています: {name}"
            )
            assert button.winfo_width() >= button.winfo_reqwidth(), (
                f"横幅が不足しています: {name}"
            )
        invoke("確認画像を保存")
        saved = output / "計測 確認.png"
        actual = cv.imdecode(
            np.frombuffer(saved.read_bytes(), np.uint8), cv.IMREAD_COLOR
        )
        assert actual is not None and actual.shape[:2] == (1086, 1448)
        saved_bytes = saved.read_bytes()
        with patch.object(
            filedialog, "asksaveasfilename", return_value=copied["INPUT_PATH"]
        ):
            invoke("確認画像を保存")
        assert "入力画像" in text(status_label)
        with patch.object(filedialog, "asksaveasfilename", return_value=""):
            invoke("確認画像を保存")
        inward = field("内向き偏差（px以上）")
        root.setvar(str(inward.cget("textvariable")), "10")
        root.update()
        assert "未計算" in text(summary_label)
        previous_saves = save_dialog.call_count
        invoke("確認画像を保存")
        assert (
            save_dialog.call_count == previous_saves
            and saved.read_bytes() == saved_bytes
        )
        invoke("計算して確認")
        assert grabcut.call_count == 1, "しきい値変更だけでGrabCutを再実行しました"
        invoke("設定をコピー")
        assert literal_values(root.clipboard_get())["MIN_INWARD_PX"] == 10
        seed = field("乱数シード")
        root.setvar(str(seed.cget("textvariable")), "1")
        root.update()
        invoke("計算して確認")
        assert grabcut.call_count == 2, "抽出条件の変更でマスクが更新されません"
        for name, count in (
            ("計測（03・05）", 8),
            ("基準線（06）", 10),
            ("候補（07・08）", 12),
        ):
            target.set(name)
            target.event_generate("<<ComboboxSelected>>")
            root.update()
            invoke("設定をコピー")
            assert len(literal_values(root.clipboard_get())) == count
        invoke("元画像＋範囲")
        invoke("すべて削除")

        def drag(first, last):
            item = next(
                item for item in canvas.find_all() if canvas.type(item) == "image"
            )
            x0, y0 = canvas.coords(item)
            photo = canvas.itemcget(item, "image")
            dw = int(root.tk.call("image", "width", photo))
            dh = int(root.tk.call("image", "height", photo))
            assert dh < 1086, "縮小表示になっていません"
            canvas.event_generate(
                "<ButtonPress-1>", x=int(x0 + dw / 2), y=int(y0 + dh * first)
            )
            canvas.event_generate(
                "<B1-Motion>", x=int(x0 + dw / 2), y=int(y0 + dh * last)
            )
            canvas.event_generate(
                "<ButtonRelease-1>", x=int(x0 + dw / 2), y=int(y0 + dh * last)
            )
            root.update()

        invoke("計測範囲（黄）")
        drag(0.9, 0.1)
        target.set("計測（03・05）")
        target.event_generate("<<ComboboxSelected>>")
        root.update()
        invoke("設定をコピー")
        bounds = literal_values(root.clipboard_get())
        assert 100 <= bounds["START_Y"] <= 110 and 970 <= bounds["END_Y"] <= 980
        for name in ("左の正常部分（緑）", "右の正常部分（水色）"):
            invoke(name)
            drag(0.3, 0.2)
        assert ranges.size() == 2
        target.set("候補（07・08）")
        target.event_generate("<<ComboboxSelected>>")
        root.update()
        invoke("設定をコピー")
        bands = literal_values(root.clipboard_get())
        assert (
            len(bands["LEFT_REFERENCE_RANGES"]) == 1
            and len(bands["RIGHT_REFERENCE_RANGES"]) == 1
        )
        ranges.selection_set(0)
        ranges.event_generate("<<ListboxSelect>>")
        root.update()
        assert any(
            float(canvas.itemcget(item, "width")) == 4
            for item in canvas.find_all()
            if canvas.type(item) == "rectangle"
        ), "選択した正常部分が強調されません"
        invoke("選択を削除")
        assert ranges.size() == 1
        old_clipboard = root.clipboard_get()
        invoke("設定をコピー")
        assert "2行以上" in text(status_label) and root.clipboard_get() == old_clipboard
        with patch.object(filedialog, "askopenfilename", return_value=""):
            invoke("画像を読み込む")
        assert ranges.size() == 1
        invalid = output / "invalid.py"
        invalid.write_text(
            "INPUT_PATH = 'anything.png'\nCANDIDATE_RECT = int('bad')\n",
            encoding="utf-8",
        )
        with patch.object(filedialog, "askopenfilename", return_value=str(invalid)):
            invoke("スクリプトから設定を読む")
        assert "読み込めません" in text(status_label) and ranges.size() == 1
        second = output / "別の画像.png"
        success, encoded = cv.imencode(".png", np.full((120, 200, 3), 100, np.uint8))
        assert success
        second.write_bytes(encoded.tobytes())
        with patch.object(filedialog, "askopenfilename", return_value=str(second)):
            invoke("画像を読み込む")
        assert ranges.size() == 0
        target.set("計測（03・05）")
        target.event_generate("<<ComboboxSelected>>")
        root.update()
        invoke("計算して確認")
        assert "初期指定" in text(status_label)
        assert not errors, errors
        print(
            "画像設定GUI: 読込・貼付・縮小ドラッグ・削除・再計算・キャッシュ・用途別コピー・保存・入力保護を確認"
        )

    with (
        patch.object(tk, "Tk", return_value=root),
        patch.object(root, "mainloop", side_effect=exercise),
        patch.object(
            root,
            "report_callback_exception",
            side_effect=lambda kind, error, trace: errors.append(error),
        ),
        patch.object(
            filedialog, "asksaveasfilename", return_value=str(output / "計測 確認.png")
        ) as save_dialog,
        patch.object(cv, "grabCut", wraps=cv.grabCut) as grabcut,
    ):
        gui["main"]()


def exercise_comparison(project, output, root, screenshots):
    gui = runpy.run_path(str(project / "submissions/comparison_settings_gui.py"))
    errors = []
    sources = project / "tests/results/shape_pipeline_20261013"
    paths = []
    summaries = []
    for case in ("original", "added_notch"):
        path = output / f"{case}_長さ.csv"
        path.write_bytes((sources / case / "results/03_side_lengths.csv").read_bytes())
        paths.append(str(path))
        summary = output / f"{case}_集計.csv"
        summary.write_bytes(
            (sources / case / "results/08_candidate_summary.csv").read_bytes()
        )
        summaries.append(str(summary))

    def exercise():
        root.deiconify()
        root.update()
        widgets = descendants(root)
        buttons = {str(w.cget("text")): w for w in widgets if isinstance(w, ttk.Button)}
        table = next(w for w in widgets if isinstance(w, ttk.Treeview))
        kind = next(
            w
            for w in widgets
            if isinstance(w, ttk.Combobox) and "長さ（04）" in w.cget("values")
        )
        baseline = next(
            w for w in widgets if isinstance(w, ttk.Combobox) and w is not kind
        )
        editor = next(
            w
            for w in widgets
            if isinstance(w, ttk.Entry) and str(w.cget("state")) == "normal"
        )
        destinations = []
        for name in ("比較CSV", "グラフPNG"):
            label = next(
                w
                for w in widgets
                if isinstance(w, ttk.Label) and str(w.cget("text")) == name
            )
            destinations.append(
                label.master.grid_slaves(row=label.grid_info()["row"], column=1)[0]
            )
        path_label = next(
            w
            for w in widgets
            if isinstance(w, ttk.Label) and str(w.cget("text")) == "選択中のCSV"
        )
        path_entry = next(
            w for w in path_label.master.winfo_children() if isinstance(w, ttk.Entry)
        )
        status_label = next(
            w for w in root.winfo_children() if isinstance(w, ttk.Label)
        )

        def status_text():
            return str(root.getvar(str(status_label.cget("textvariable"))))

        def invoke(name):
            buttons[name].invoke()
            root.update()

        root.clipboard_clear()
        root.clipboard_append("before")
        invoke("比較の設定をコピー")
        assert root.clipboard_get() == "before" and "2枚以上" in status_text()
        invoke("CSVを追加")
        assert len(table.get_children()) == 2
        invoke("CSVを追加")
        assert len(table.get_children()) == 2, "同じ入力が重複しました"
        table.selection_set("0")
        table.event_generate("<<TreeviewSelect>>")
        root.update()
        root.setvar(str(editor.cget("textvariable")), "基準画像")
        invoke("識別名を変更")
        assert baseline.get() == "基準画像"
        assert path_entry.get() == paths[0]
        baseline.set("image_02")
        invoke("比較の設定をコピー")
        values = literal_values(root.clipboard_get())
        assert (
            values["BASELINE_ID"] == "image_02"
            and values["INPUT_CSVS"][0][0] == "基準画像"
        )
        output_buttons = [
            w
            for w in widgets
            if isinstance(w, ttk.Button) and str(w.cget("text")) == "保存先を選ぶ"
        ]
        for button, suffix in zip(output_buttons, (".csv", ".png")):
            destination = output / f"比較結果{suffix}"
            with patch.object(
                filedialog, "asksaveasfilename", return_value=str(destination)
            ) as picker:
                button.invoke()
                root.update()
            assert picker.call_args.kwargs["defaultextension"] == suffix
            assert not destination.exists(), (
                "保存先の指定だけで出力ファイルが作られました"
            )
        invoke("比較の設定をコピー")
        values = literal_values(root.clipboard_get())
        assert values["OUTPUT_CSV_PATH"] == str(output / "比較結果.csv")
        assert values["OUTPUT_IMAGE_PATH"] == str(output / "比較結果.png")
        with patch.object(filedialog, "asksaveasfilename", return_value=""):
            output_buttons[0].invoke()
            root.update()
        assert destinations[0].get() == str(output / "比較結果.csv")
        if screenshots:
            capture(root, output / "comparison.png")
        root.geometry("880x560")
        root.update()
        for name, button in buttons.items():
            assert (
                button.winfo_ismapped()
                and button.winfo_height() >= button.winfo_reqheight()
            ), name
        root.setvar(str(destinations[0].cget("textvariable")), paths[0])
        before = root.clipboard_get()
        invoke("比較の設定をコピー")
        assert "別の保存先" in status_text() and root.clipboard_get() == before
        kind.set("候補（09）")
        kind.event_generate("<<ComboboxSelected>>")
        root.update()
        assert not table.get_children()
        invoke("CSVを追加")
        assert not table.get_children() and "08_candidate_summary" in status_text()
        with patch.object(
            filedialog, "askopenfilenames", return_value=tuple(summaries)
        ):
            invoke("CSVを追加")
        invoke("比較の設定をコピー")
        copied = literal_values(root.clipboard_get())
        assert copied["OUTPUT_CSV_PATH"].endswith("09_compare_candidates.csv")
        assert len(copied["INPUT_CSVS"]) == 2
        table.selection_set("1")
        invoke("選択を削除")
        before = root.clipboard_get()
        invoke("比較の設定をコピー")
        assert root.clipboard_get() == before and "2枚以上" in status_text()
        assert not errors, errors
        print(
            "比較設定GUI: 種類別CSV・重複防止・識別名・基準・コピー・削除・入力保護を確認"
        )

    with (
        patch.object(tk, "Tk", return_value=root),
        patch.object(root, "mainloop", side_effect=exercise),
        patch.object(
            root,
            "report_callback_exception",
            side_effect=lambda kind, error, trace: errors.append(error),
        ),
        patch.object(filedialog, "askopenfilenames", return_value=tuple(paths)),
    ):
        gui["main"]()


def exercise_length_calibration(project, output, root, screenshots):
    gui = runpy.run_path(str(project / "submissions/length_calibration_gui.py"))
    errors = []
    paths = []
    images = []
    reference_lengths = [100, 200, 100, 100, 100]
    cases = (
        (200, 200, 400),
        (400, 400, 800),
        (430, 410, 840),
        (440, 420, 860),
        (510, 500, 1010),
    )
    ranges = ((20, 220), (60, 460), (30, 430), (30, 430), (30, 530))
    for index, (lengths, y_range, reference_px) in enumerate(
        zip(cases, ranges, reference_lengths)
    ):
        path = output / "スラブ試験" / f"{index + 1:02d}" / "03_side_lengths.csv"
        path.parent.mkdir(parents=True)
        with path.open("w", encoding="utf-8-sig", newline="") as target:
            writer = csv.writer(target)
            writer.writerow(("edge", "length_px", "start_y", "end_y"))
            for edge, length in zip(("left", "right", "total"), lengths):
                writer.writerow((edge, f"{length:.2f}", *y_range))
        image_path = path.parent / "校正する 元画像.png"
        image = np.full((1080, 1920, 3), 245, np.uint8)
        cv.rectangle(image, (300, y_range[0]), (700, y_range[1]), (70, 80, 100), -1)
        cv.line(image, (1200, 400), (1200 + reference_px, 400), (0, 0, 0), 2)
        for x in (1200, 1200 + reference_px):
            cv.line(image, (x, 380), (x, 420), (0, 0, 0), 2)
        cv.putText(
            image, "50 mm", (1200, 370), cv.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2
        )
        success, encoded = cv.imencode(".png", image)
        assert success
        image_path.write_bytes(encoded.tobytes())
        paths.append(path)
        images.append(image_path)
    original = [
        (path.read_bytes(), image.read_bytes()) for path, image in zip(paths, images)
    ]

    def exercise():
        root.deiconify()
        root.update()
        widgets = descendants(root)
        buttons = {str(w.cget("text")): w for w in widgets if isinstance(w, ttk.Button)}
        choose_buttons = [
            w
            for w in widgets
            if isinstance(w, ttk.Button) and str(w.cget("text")) == "選ぶ"
        ]
        canvas = next(w for w in widgets if isinstance(w, tk.Canvas))
        slider = next(w for w in widgets if isinstance(w, ttk.Scale))
        caption = next(
            w
            for w in widgets
            if isinstance(w, ttk.Label) and str(w.cget("text")) == "基準物の実寸 (mm)"
        )
        siblings = caption.master.winfo_children()
        reference = siblings[siblings.index(caption) + 1]
        table = next(w for w in widgets if isinstance(w, ttk.Treeview))
        status_label = root.winfo_children()[-1]

        def status_text():
            return str(root.getvar(str(status_label.cget("textvariable"))))

        def invoke(name):
            buttons[name].invoke()
            root.update()

        def choose(button, path):
            with patch.object(filedialog, "askopenfilename", return_value=str(path)):
                button.invoke()
                root.update()

        def values():
            return tuple(
                tuple(table.item(item, "values")) for item in table.get_children()
            )

        def current_view():
            x0, y0, x1, y1 = canvas.coords("image_bounds")
            return x0, y0, (x1 - x0) / (1920 - 1)

        def click_image(x, y):
            offset_x, offset_y, scale = current_view()
            screen_x = round(offset_x + x * scale)
            screen_y = round(offset_y + y * scale)
            assert 0 <= screen_x < canvas.winfo_width()
            assert 0 <= screen_y < canvas.winfo_height()
            canvas.event_generate("<Button-1>", x=screen_x, y=screen_y)
            root.update()

        def drag(dx, dy):
            start_x = canvas.winfo_width() // 2
            start_y = canvas.winfo_height() // 2
            canvas.event_generate("<ButtonPress-3>", x=start_x, y=start_y)
            canvas.event_generate("<B3-Motion>", x=start_x + dx, y=start_y + dy)
            canvas.event_generate("<ButtonRelease-3>", x=start_x + dx, y=start_y + dy)
            root.update()

        def calibrate(index, capture_image=False):
            assert not any(isinstance(w, tk.Toplevel) for w in descendants(root))
            assert not any(isinstance(w, ttk.Combobox) for w in descendants(root))
            invoke("点を消す")
            invoke("全体表示")
            canvas.event_generate("<Button-1>", x=1, y=1)
            assert not canvas.find_withtag("reference")
            slider.set(173.25)
            root.update()
            offset_x, offset_y, scale = current_view()
            assert abs(scale - 1.7325) < 1e-10
            anchor_x = canvas.winfo_width() // 2 + 17
            anchor_y = canvas.winfo_height() // 2 - 11
            before_anchor = (
                (anchor_x - offset_x) / scale,
                (anchor_y - offset_y) / scale,
            )
            canvas.event_generate("<MouseWheel>", x=anchor_x, y=anchor_y, delta=60)
            root.update()
            next_x, next_y, next_scale = current_view()
            np.testing.assert_allclose(
                ((anchor_x - next_x) / next_scale, (anchor_y - next_y) / next_scale),
                before_anchor,
                atol=1e-9,
            )
            assert next_scale > scale
            canvas.event_generate("<MouseWheel>", x=anchor_x, y=anchor_y, delta=-60)
            root.update()
            np.testing.assert_allclose(
                current_view(), (offset_x, offset_y, scale), atol=1e-9
            )
            drag(-35, 26)
            np.testing.assert_allclose(
                current_view(), (offset_x - 35, offset_y + 26, scale), atol=1e-9
            )
            assert not canvas.find_withtag("reference"), (
                "右ドラッグが基準点を追加しました"
            )
            if index == 0:
                slider.set(1600)
                root.update()
                canvas.event_generate("<MouseWheel>", x=anchor_x, y=anchor_y, delta=120)
                root.update()
                assert current_view()[2] == 16
                photo = canvas.itemcget(canvas.find_withtag("source")[0], "image")
                assert (
                    int(root.tk.call("image", "width", photo)) == canvas.winfo_width()
                )
                assert (
                    int(root.tk.call("image", "height", photo)) == canvas.winfo_height()
                )
            invoke("100%")
            offset_x, offset_y, scale = current_view()
            assert scale == 1
            midpoint_x = offset_x + (1200 + reference_lengths[index] / 2) * scale
            midpoint_y = offset_y + 400 * scale
            drag(
                round(canvas.winfo_width() / 2 - midpoint_x),
                round(canvas.winfo_height() / 2 - midpoint_y),
            )
            slider.set(200)
            root.update()
            click_image(1200, 400)
            assert not table.get_children()
            click_image(1200 + reference_lengths[index], 400)
            root.setvar(str(reference.cget("textvariable")), "0")
            root.update()
            assert not table.get_children() and "有限値" in status_text()
            assert buttons["校正済みCSVを保存"].instate(["disabled"])
            root.setvar(str(reference.cget("textvariable")), "50")
            root.update()
            assert len(table.get_children()) == 3
            before = values()
            if capture_image and screenshots:
                capture(root, output / "length_calibration_zoom.png")
            slider.set(137.5)
            root.update()
            drag(30, -10)
            canvas.event_generate("<MouseWheel>", x=anchor_x, y=anchor_y, delta=120)
            root.update()
            root.geometry("1050x730")
            root.update()
            assert values() == before
            assert buttons["校正済みCSVを保存"].instate(["!disabled"])
            assert len(canvas.find_withtag("reference")) == 5
            invoke("全体表示")
            assert values() == before
            if capture_image and screenshots:
                capture(root, output / "length_calibration_points.png")

        invoke("点を消す")
        assert "CSVと元画像" in status_text()
        assert buttons["校正済みCSVを保存"].instate(["disabled"])
        for index in range(5):
            choose(choose_buttons[0], paths[index])
            assert not table.get_children()
            assert not canvas.find_all()
            assert not reference.get()
            assert buttons["校正済みCSVを保存"].instate(["disabled"])
            choose(choose_buttons[1], images[index])
            assert not table.get_children()
            assert buttons["校正済みCSVを保存"].instate(["disabled"])
            calibrate(index, capture_image=index == 0)
            factor = 50 / reference_lengths[index]
            expected = tuple(
                (label, f"{px:.3f}", f"{px * factor:.3f}")
                for label, px in zip(("左", "右", "左右合計"), cases[index])
            )
            assert values() == expected, values()
            before = values()
            for button in choose_buttons:
                choose(button, "")
                assert values() == before
            with patch.object(filedialog, "asksaveasfilename", return_value=""):
                invoke("校正済みCSVを保存")
            assert values() == before
            with patch.object(
                filedialog, "asksaveasfilename", return_value=str(paths[index])
            ):
                invoke("校正済みCSVを保存")
            assert "入力CSV" in status_text()
            destination = paths[index].parent / "calibrated_lengths.csv"
            with patch.object(
                filedialog, "asksaveasfilename", return_value=str(destination)
            ):
                invoke("校正済みCSVを保存")
            with destination.open(encoding="utf-8-sig", newline="") as source:
                row = next(csv.DictReader(source))
            assert float(row["mm_per_px"]) == factor
            assert abs(float(row["reference_x1"]) - 1200) <= 0.5
            assert abs(float(row["reference_y1"]) - 400) <= 0.5
            assert (
                abs(
                    float(row["reference_x2"])
                    - float(row["reference_x1"])
                    - reference_lengths[index]
                )
                < 1e-8
            )
            assert row["input_csv"] == str(paths[index])
            assert row["image_path"] == str(images[index])

        bad_csv = output / "候補形式.csv"
        bad_csv.write_text("edge,candidate_count\nleft,1\n", encoding="utf-8")
        before = values()
        choose(choose_buttons[0], bad_csv)
        assert "03_side_lengths" in status_text() and values() == before
        bad_image = output / "読めない画像.png"
        bad_image.write_bytes(b"not an image")
        choose(choose_buttons[1], bad_image)
        assert "画像を読み込めません" in status_text() and values() == before
        paths[4].write_text("edge,candidate_count\nleft,1\n", encoding="utf-8")
        with patch.object(
            filedialog, "asksaveasfilename", return_value=str(output / "stale.csv")
        ):
            invoke("校正済みCSVを保存")
        assert not (output / "stale.csv").exists() and not table.get_children()
        assert buttons["校正済みCSVを保存"].instate(["disabled"])
        paths[4].write_bytes(original[4][0])
        choose(choose_buttons[0], paths[4])
        assert len(table.get_children()) == 3
        if screenshots:
            capture(root, output / "length_calibrated_values.png")
        root.geometry("1000x700")
        root.update()
        for name, button in buttons.items():
            assert button.winfo_ismapped(), name
            assert button.winfo_height() >= button.winfo_reqheight(), name
            assert (
                button.winfo_rooty() + button.winfo_height()
                <= root.winfo_rooty() + root.winfo_height()
            )
        assert [
            (path.read_bytes(), image.read_bytes())
            for path, image in zip(paths, images)
        ] == original
        assert not errors, errors
        print(
            "校正GUI: 一画面・5画像・自由ズームとカーソル中心・右ドラッグ・座標保持・mm換算・CSV保存・キャンセル・入力保護を確認"
        )

    with (
        patch.object(tk, "Tk", return_value=root),
        patch.object(root, "mainloop", side_effect=exercise),
        patch.object(
            root,
            "report_callback_exception",
            side_effect=lambda kind, error, trace: errors.append(error),
        ),
    ):
        gui["main"]()


def exercise_length_comparison(project, output, root, screenshots):
    gui = runpy.run_path(str(project / "submissions/length_comparison_gui.py"))
    errors = []
    paths = []
    sources = []
    images = []
    thicknesses = [10, 10, 5, 5, 4]
    for index in range(5):
        directory = output / "スラブ試験" / f"{index + 1:02d}"
        paths.append(directory / "calibrated_lengths.csv")
        sources.append(directory / "03_side_lengths.csv")
        images.append(directory / "校正する 元画像.png")
    original = [
        (path.read_bytes(), source.read_bytes(), image.read_bytes())
        for path, source, image in zip(paths, sources, images)
    ]

    def exercise():
        root.deiconify()
        root.update()
        widgets = descendants(root)
        buttons = {str(w.cget("text")): w for w in widgets if isinstance(w, ttk.Button)}
        input_table, length_table, ideal_table, ratio_table, previous_table = [
            w for w in widgets if isinstance(w, ttk.Treeview)
        ]
        notebook = next(w for w in widgets if isinstance(w, ttk.Notebook))
        status_label = root.winfo_children()[-1]

        def status_text():
            return str(root.getvar(str(status_label.cget("textvariable"))))

        def invoke(name):
            buttons[name].invoke()
            root.update()

        def field(label):
            caption = next(
                w
                for w in widgets
                if isinstance(w, ttk.Label) and str(w.cget("text")) == label
            )
            siblings = caption.master.winfo_children()
            return siblings[siblings.index(caption) + 1]

        initial_length = field("初期区間長 (mm)")
        initial_thickness = field("初期厚さ (mm)")
        name_field = field("撮影名")
        thickness_field = field("撮影時の厚さ (mm)")

        def set_field(widget, value):
            root.setvar(str(widget.cget("textvariable")), str(value))
            root.update()

        def add(items):
            with patch.object(
                filedialog,
                "askopenfilenames",
                return_value=tuple(str(path) for path in items),
            ):
                invoke("CSVを追加")

        def select(*indices):
            input_table.selection_set(tuple(str(index) for index in indices))
            input_table.event_generate("<<TreeviewSelect>>")
            root.update()

        def values(table):
            return tuple(
                tuple(table.item(item, "values")) for item in table.get_children()
            )

        invoke("比較する")
        assert "初期区間長" in status_text()
        set_field(initial_length, 100)
        set_field(initial_thickness, 10)
        invoke("比較する")
        assert "1枚以上" in status_text()
        add(paths)
        add(paths)
        assert len(input_table.get_children()) == 5
        invoke("比較する")
        assert "厚さ" in status_text()
        for index, thickness in enumerate(thicknesses):
            select(index)
            set_field(thickness_field, thickness)
            invoke("撮影名・厚さを適用")
        assert [input_table.item(str(i), "values")[3] for i in range(5)] == [
            "0.5",
            "0.25",
            "0.5",
            "0.5",
            "0.5",
        ]
        invoke("比較する")
        assert values(length_table) == (
            ("撮影01", "100.000", "100.000", "100.000", "200.000"),
            ("撮影02", "100.000", "100.000", "100.000", "200.000"),
            ("撮影03", "200.000", "215.000", "205.000", "420.000"),
            ("撮影04", "200.000", "220.000", "210.000", "430.000"),
            ("撮影05", "250.000", "255.000", "250.000", "505.000"),
        ), values(length_table)
        assert values(ideal_table)[2] == ("撮影03", "+15.000", "+5.000", "+20.000")
        assert values(ratio_table)[2] == ("撮影03", "+7.500", "+2.500", "+5.000")
        assert values(previous_table)[0] == ("撮影01", "—", "—", "—")
        assert values(previous_table)[1] == ("撮影02", "+0.000", "+0.000", "+0.000")
        assert buttons["比較CSVを保存"].instate(["!disabled"])
        before = values(length_table)
        assert not any(isinstance(w, tk.Canvas) for w in widgets)
        assert "既知寸法から校正" not in buttons
        with patch.object(filedialog, "askopenfilenames", return_value=()):
            invoke("CSVを追加")
        assert values(length_table) == before
        select(2)
        set_field(name_field, "撮影02")
        invoke("撮影名・厚さを適用")
        assert "重複" in status_text() and values(length_table) == before
        select(2)
        set_field(name_field, "圧延後")
        invoke("撮影名・厚さを適用")
        assert not length_table.get_children()
        invoke("比較する")
        assert values(ideal_table)[2][0] == "圧延後"
        if screenshots:
            for index, filename in enumerate(
                (
                    "slab_lengths.png",
                    "slab_deviations.png",
                    "slab_rates.png",
                    "slab_previous.png",
                )
            ):
                notebook.select(index)
                root.update()
                capture(root, output / filename)
            notebook.select(0)
        root.geometry("1060x760")
        root.update()
        for name, button in buttons.items():
            assert button.winfo_ismapped(), name
            assert button.winfo_width() >= button.winfo_reqwidth(), name
            assert button.winfo_height() >= button.winfo_reqheight(), name
            assert (
                button.winfo_rooty() + button.winfo_height()
                <= root.winfo_rooty() + root.winfo_height()
            ), name
        for name, suffix in (("比較CSVを保存", ".csv"), ("推移グラフを保存", ".png")):
            path = output / f"スラブ実寸 比較{suffix}"
            with patch.object(filedialog, "asksaveasfilename", return_value=str(path)):
                invoke(name)
            assert path.is_file()
        with (output / "スラブ実寸 比較.csv").open(
            encoding="utf-8-sig", newline=""
        ) as saved:
            rows = list(csv.DictReader(saved))
        assert len(rows) == 5 and rows[1]["mm_per_px"] == "0.25"
        assert rows[2]["ideal_length_mm"] == "200" and rows[2]["delta_total_pct"] == "5"
        invoke("推移グラフを表示")
        preview = next(w for w in root.winfo_children() if isinstance(w, tk.Toplevel))
        assert (
            preview.winfo_rooty() + preview.winfo_height() <= root.winfo_screenheight()
        )
        if screenshots:
            capture(preview, output / "slab_graph_preview.png")
        invoke("推移グラフを表示")
        assert (
            len([w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]) == 1
        )
        for path in paths + sources:
            with patch.object(filedialog, "asksaveasfilename", return_value=str(path)):
                invoke("比較CSVを保存")
            assert "入力CSV" in status_text()
        for image in images:
            with patch.object(filedialog, "asksaveasfilename", return_value=str(image)):
                invoke("推移グラフを保存")
            assert "校正画像" in status_text()
        with patch.object(filedialog, "asksaveasfilename", return_value=""):
            invoke("比較CSVを保存")

        set_field(initial_length, 110)
        assert not preview.winfo_exists() and not length_table.get_children()
        assert buttons["比較CSVを保存"].instate(["disabled"])
        invoke("比較する")
        assert values(length_table)[0][1] == "110.000"
        set_field(initial_length, 100)
        invoke("比較する")
        select(4)
        invoke("上へ")
        assert not previous_table.get_children()
        invoke("比較する")
        assert values(length_table)[3][0] == "撮影05"
        assert values(previous_table)[3][1:] == ("+40.000", "+45.000", "+85.000")
        invoke("下へ")
        invoke("比較する")
        assert values(previous_table)[4][1:] == ("+35.000", "+40.000", "+75.000")
        select(4)
        set_field(thickness_field, 0)
        invoke("撮影名・厚さを適用")
        assert "厚さ" in status_text() and len(length_table.get_children()) == 5
        select(4)
        set_field(thickness_field, 5)
        invoke("撮影名・厚さを適用")
        assert not length_table.get_children()
        invoke("比較する")
        assert values(length_table)[4][1] == "200.000"
        select(4)
        set_field(thickness_field, 4)
        invoke("撮影名・厚さを適用")
        invoke("比較する")
        paths[4].write_text("edge,candidate_count\nleft,1\n", encoding="utf-8")
        invoke("比較する")
        assert (
            not length_table.get_children()
            and "calibrated_lengths.csv" in status_text()
        )
        assert buttons["推移グラフを表示"].instate(["disabled"])
        paths[4].write_bytes(original[4][0])
        invoke("比較する")
        select(1, 3)
        invoke("選択を削除")
        assert len(input_table.get_children()) == 3
        invoke("比較する")
        assert len(length_table.get_children()) == 3
        assert values(length_table)[1][0] == "圧延後"
        assert [
            (path.read_bytes(), source.read_bytes(), image.read_bytes())
            for path, source, image in zip(paths, sources, images)
        ] == original
        assert not errors, errors
        print(
            "スラブ比較GUI: 校正GUIを閉じた後の5CSV読込・初期区間と厚さ・mm/理想差/率/前回差・更新・並べ替え・保存・入力保護を確認"
        )

    with (
        patch.object(tk, "Tk", return_value=root),
        patch.object(root, "mainloop", side_effect=exercise),
        patch.object(
            root,
            "report_callback_exception",
            side_effect=lambda kind, error, trace: errors.append(error),
        ),
    ):
        gui["main"]()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, default=Path("tests/results/parameter_guis_20261014")
    )
    parser.add_argument("--screenshots", action="store_true")
    arguments = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    output = (project / arguments.out).resolve()
    if (
        not output.is_relative_to((project / "tests/results").resolve())
        or output.exists()
    ):
        raise ValueError("tests/results内で、まだ存在しない検証先を指定してください")
    output.mkdir(parents=True)
    input_path = project / "submissions/input/赤茶色の床と剥離した金属帯.png"
    original_hash = hashlib.sha256(input_path.read_bytes()).hexdigest()
    for exercise in (
        exercise_measurement,
        exercise_comparison,
        exercise_length_calibration,
        exercise_length_comparison,
    ):
        root = tk.Tk()
        root.withdraw()
        root.attributes("-alpha", 0)
        # コピーの内容を検証し、利用者のクリップボードには触れない。
        clipboard = {"text": ""}
        try:
            with (
                patch.object(
                    root, "clipboard_get", side_effect=lambda: clipboard["text"]
                ),
                patch.object(
                    root,
                    "clipboard_clear",
                    side_effect=lambda: clipboard.update(text=""),
                ),
                patch.object(
                    root,
                    "clipboard_append",
                    side_effect=lambda text: clipboard.update(
                        text=clipboard["text"] + text
                    ),
                ),
            ):
                exercise(project, output, root, arguments.screenshots)
        finally:
            root.update()
            root.destroy()
    assert hashlib.sha256(input_path.read_bytes()).hexdigest() == original_hash
    print(f"設定GUIの操作確認完了: {output}")


if __name__ == "__main__":
    main()
