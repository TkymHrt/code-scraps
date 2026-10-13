"""設定GUIと長さ専用GUIの選択・計算・表示・保存を、実際のTkで確認する."""

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


def exercise_length_comparison(project, output, root, screenshots):
    gui = runpy.run_path(str(project / "submissions/length_comparison_gui.py"))
    errors = []
    paths = []
    original_bytes = []
    for index, lengths in enumerate(
        (
            (120, 122, 242),
            (123, 121, 244),
            (121, 124, 245),
            (126, 125, 251),
            (125, 127, 252),
        )
    ):
        path = output / "撮影試験" / f"{index + 1:02d}" / "03_side_lengths.csv"
        path.parent.mkdir(parents=True)
        with path.open("w", encoding="utf-8-sig", newline="") as target:
            writer = csv.writer(target)
            writer.writerow(("edge", "length_px", "start_y", "end_y"))
            for edge, length in zip(("left", "right", "total"), lengths):
                writer.writerow((edge, f"{length:.2f}", 20, 140))
        paths.append(path)
        original_bytes.append(path.read_bytes())

    def exercise():
        root.deiconify()
        root.update()
        widgets = descendants(root)
        buttons = {str(w.cget("text")): w for w in widgets if isinstance(w, ttk.Button)}
        tables = [w for w in widgets if isinstance(w, ttk.Treeview)]
        input_table, lengths_table, delta_table, previous_table = tables
        notebook = next(w for w in widgets if isinstance(w, ttk.Notebook))
        editor = next(
            w
            for w in widgets
            if isinstance(w, ttk.Entry) and str(w.cget("state")) == "normal"
        )
        path_entry = next(
            w
            for w in widgets
            if isinstance(w, ttk.Entry) and str(w.cget("state")) == "readonly"
        )
        status_label = root.winfo_children()[-1]

        def status_text():
            return str(root.getvar(str(status_label.cget("textvariable"))))

        def invoke(name):
            buttons[name].invoke()
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

        assert buttons["比較CSVを保存"].instate(["disabled"])
        invoke("比較する")
        assert "2枚以上" in status_text()
        add(paths[:1])
        invoke("比較する")
        assert "2枚以上" in status_text()
        add(paths)
        assert len(input_table.get_children()) == 5
        invoke("比較する")
        assert values(lengths_table) == (
            ("撮影01", "120.00", "122.00", "242.00"),
            ("撮影02", "123.00", "121.00", "244.00"),
            ("撮影03", "121.00", "124.00", "245.00"),
            ("撮影04", "126.00", "125.00", "251.00"),
            ("撮影05", "125.00", "127.00", "252.00"),
        )
        assert values(previous_table)[0] == ("撮影01", "—", "—", "—")
        assert values(previous_table)[1] == ("撮影02", "+3.00", "-1.00", "+2.00")
        before = values(lengths_table)
        add(paths)
        add(())
        assert values(lengths_table) == before and len(input_table.get_children()) == 5
        assert buttons["比較CSVを保存"].instate(["!disabled"])

        select(2)
        assert path_entry.get() == str(paths[2])
        invoke("選択を基準にする")
        assert not lengths_table.get_children()
        assert input_table.item("2", "values")[1] == "基準"
        root.setvar(str(editor.cget("textvariable")), "中間撮影")
        invoke("撮影名を変更")
        assert input_table.item("2", "values")[2] == "中間撮影"
        invoke("比較する")
        assert values(delta_table) == (
            ("撮影01", "-1.00", "-2.00", "-3.00"),
            ("撮影02", "+2.00", "-3.00", "-1.00"),
            ("中間撮影", "+0.00", "+0.00", "+0.00"),
            ("撮影04", "+5.00", "+1.00", "+6.00"),
            ("撮影05", "+4.00", "+3.00", "+7.00"),
        )
        root.setvar(str(editor.cget("textvariable")), "撮影02")
        invoke("撮影名を変更")
        assert "重複" in status_text() and len(lengths_table.get_children()) == 5
        select(2)
        invoke("比較する")
        assert "baseline" in delta_table.item(delta_table.get_children()[2], "tags")
        if screenshots:
            for index, filename in enumerate(
                (
                    "length_comparison.png",
                    "length_baseline_delta.png",
                    "length_previous_delta.png",
                )
            ):
                notebook.select(index)
                root.update()
                capture(root, output / filename)
            notebook.select(0)
            root.update()
        root.geometry("1000x700")
        root.update()
        for name, button in buttons.items():
            assert button.winfo_ismapped(), name
            assert button.winfo_height() >= button.winfo_reqheight(), name
            assert button.winfo_width() >= button.winfo_reqwidth(), name
            assert (
                button.winfo_rooty() + button.winfo_height()
                <= root.winfo_rooty() + root.winfo_height()
            ), name

        for name, suffix in (("比較CSVを保存", ".csv"), ("推移グラフを保存", ".png")):
            path = output / f"撮影 推移{suffix}"
            with patch.object(filedialog, "asksaveasfilename", return_value=str(path)):
                invoke(name)
            assert path.is_file()
        with (output / "撮影 推移.csv").open(encoding="utf-8-sig", newline="") as saved:
            rows = list(csv.DictReader(saved))
        assert len(rows) == 5 and all(row["baseline_id"] == "中間撮影" for row in rows)
        assert rows[0]["previous_delta_total_px"] == ""
        assert (
            rows[-1]["delta_total_px"] == "7.00"
            and rows[-1]["previous_delta_total_px"] == "1.00"
        )
        invoke("推移グラフを表示")
        preview = next(w for w in root.winfo_children() if isinstance(w, tk.Toplevel))
        assert preview.winfo_ismapped()
        assert (
            preview.winfo_rooty() + preview.winfo_height() <= root.winfo_screenheight()
        )
        invoke("推移グラフを表示")
        assert (
            len([w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]) == 1
        )
        if screenshots:
            capture(preview, output / "length_graph_preview.png")
        close_command = preview.protocol("WM_DELETE_WINDOW")
        preview.tk.call(close_command)
        root.update()
        assert not preview.winfo_exists()
        invoke("推移グラフを表示")
        preview = next(w for w in root.winfo_children() if isinstance(w, tk.Toplevel))
        for path in paths:
            with patch.object(filedialog, "asksaveasfilename", return_value=str(path)):
                invoke("比較CSVを保存")
            assert "入力CSV" in status_text()
        with patch.object(filedialog, "asksaveasfilename", return_value=""):
            invoke("比較CSVを保存")
        assert len(lengths_table.get_children()) == 5

        select(4)
        invoke("上へ")
        assert not preview.winfo_exists(), "撮影順変更後も古いグラフが残っています"
        assert not previous_table.get_children() and buttons["比較CSVを保存"].instate(
            ["disabled"]
        )
        assert input_table.item("2", "values")[1] == "基準"
        invoke("比較する")
        assert values(previous_table)[3] == ("撮影05", "+4.00", "+3.00", "+7.00")
        assert values(previous_table)[4] == ("撮影04", "+1.00", "-2.00", "-1.00")
        invoke("下へ")
        invoke("比較する")
        assert values(previous_table)[4] == ("撮影05", "-1.00", "+2.00", "+1.00")

        bad = output / "不正.csv"
        bad.write_text("edge,candidate_count\nleft,1\n", encoding="utf-8")
        extra = output / "有効.csv"
        extra.write_bytes(original_bytes[0])
        add((extra, bad))
        assert (
            len(input_table.get_children()) == 5
            and len(lengths_table.get_children()) == 5
        )
        assert "03_side_lengths.csv" in status_text(), status_text()

        paths[4].write_text("edge,candidate_count\nleft,1\n", encoding="utf-8")
        invoke("比較する")
        assert (
            not lengths_table.get_children() and "03_side_lengths.csv" in status_text()
        )
        assert buttons["推移グラフを保存"].instate(["disabled"])
        with patch.object(filedialog, "asksaveasfilename") as picker:
            invoke("比較CSVを保存")
            picker.assert_not_called()
        paths[4].write_bytes(original_bytes[4])
        invoke("比較する")
        select(1, 3)
        invoke("選択を削除")
        assert len(input_table.get_children()) == 3
        invoke("比較する")
        assert [row[0] for row in values(lengths_table)] == [
            "撮影01",
            "中間撮影",
            "撮影05",
        ]
        select(1)
        invoke("選択を削除")
        invoke("比較する")
        assert "基準" in status_text() and not delta_table.get_children()
        select(0)
        invoke("選択を基準にする")
        invoke("比較する")
        assert len(delta_table.get_children()) == 2
        select(0, 1)
        invoke("選択を削除")
        assert not input_table.get_children() and buttons["比較CSVを保存"].instate(
            ["disabled"]
        )

        # 画面より多い撮影でも、一覧と結果の最後の行までたどれる。
        many_paths = []
        for index in range(12):
            path = output / f"追加撮影{index + 1:02d}.csv"
            path.write_bytes(original_bytes[0])
            many_paths.append(path)
        add(many_paths)
        invoke("比較する")
        assert len(lengths_table.get_children()) == 12
        for table in tables:
            last = table.get_children()[-1]
            if table is not input_table:
                notebook.select(table.master)
            root.update()
            table.see(last)
            root.update()
            assert table.bbox(last), f"最後の撮影までスクロールできません: {table}"
        assert [path.read_bytes() for path in paths] == original_bytes
        assert not errors, errors
        print(
            "長さ専用GUI: 複数追加・撮影順・基準変更・撮影名・3表・推移プレビュー・複数削除・結果更新・保存・入力保護を確認"
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
