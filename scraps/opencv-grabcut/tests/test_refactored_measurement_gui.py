"""多角形・固定区間・軸と、拡大・移動後の計測操作を実Tkで確認する。"""

import csv
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import filedialog, ttk
from unittest.mock import Mock, patch

import cv2 as cv
import numpy as np
from test_refactored_workflow import load_refactored
from test_video_frame_gui import find_widgets


class MeasurementRegionTests(unittest.TestCase):
    def setUp(self):
        self.script = load_refactored("02_measure_edge_lengths_gui.py")
        self.image = np.full((800, 1600, 3), 25, np.uint8)
        self.image[100:701, 700:901] = 210
        # 試料より大きな無関係の物体。処理範囲の外なので抽出に含めない。
        self.image[20:780, 30:600] = 210
        self.regions = {
            cv.GC_PR_FGD: [[(0.42, 0.1), (0.58, 0.1), (0.58, 0.9), (0.42, 0.9)]],
            cv.GC_BGD: [],
            cv.GC_FGD: [],
        }
        self.interval_points = np.array([[800, 120], [800, 680]])
        self.axis = self.script["manual_axis"](self.interval_points)

    def test_local_grabcut_keeps_full_image_coordinates_and_mm_per_pixel(self):
        original = self.image.copy()
        with patch.object(cv, "grabCut", wraps=cv.grabCut) as grabcut:
            row, overlay = self.script["measure_lengths"](
                self.image, self.regions, self.interval_points, self.axis
            )
        working = grabcut.call_args.args[0]
        self.assertLess(working.shape[0] * working.shape[1], 800 * 1600 // 4)
        self.assertEqual(row["image_width"], 1600)
        self.assertEqual(row["image_height"], 800)
        self.assertEqual(row["interval_length_mm"], 140)
        self.assertNotIn("start_y", row)
        self.assertNotIn("end_y", row)
        self.assertEqual(row["left_px"], 560)
        self.assertEqual(row["right_px"], 560)
        self.assertEqual(row["left_mm"], 140)
        self.assertEqual(row["right_mm"], 140)
        np.testing.assert_array_equal(overlay[400, 700], (0, 0, 255))
        np.testing.assert_array_equal(overlay[400, 900], (0, 0, 255))
        np.testing.assert_array_equal(original, self.image)

    def test_multiple_foreground_candidates_share_one_measurement(self):
        self.regions[cv.GC_PR_FGD] = [
            [(0.42, 0.1), (0.58, 0.1), (0.58, 0.52), (0.42, 0.52)],
            [(0.42, 0.48), (0.58, 0.48), (0.58, 0.9), (0.42, 0.9)],
        ]
        row, _ = self.script["measure_lengths"](
            self.image, self.regions, self.interval_points, self.axis
        )
        self.assertEqual(row["total_mm"], 280)

    def test_interval_outside_working_region_and_missing_edge_are_rejected(self):
        self.regions[cv.GC_PR_FGD] = [
            [(0.42, 0.3), (0.58, 0.3), (0.58, 0.7), (0.42, 0.7)]
        ]
        with self.assertRaisesRegex(ValueError, "断面.*側辺|計測区間全体"):
            self.script["measure_lengths"](
                self.image, self.regions, np.array([[800, 10], [800, 790]]), self.axis
            )
        self.image[100:701, 0:901] = 210
        self.regions[cv.GC_PR_FGD] = [[(0, 0.1), (0.58, 0.1), (0.58, 0.9), (0, 0.9)]]
        self.regions[cv.GC_FGD] = [[(0, 0.2), (0.5, 0.2), (0.5, 0.8), (0, 0.8)]]
        with self.assertRaisesRegex(ValueError, "端に接しています"):
            self.script["measure_lengths"](
                self.image, self.regions, np.array([[800, 200], [800, 600]]), self.axis
            )

    def test_polygon_mask_preserves_shape_and_multiple_region_types(self):
        image = np.zeros((101, 101, 3), np.uint8)
        regions = {
            cv.GC_PR_FGD: [[(0.1, 0.1), (0.9, 0.1), (0.5, 0.9)]],
            cv.GC_BGD: [[(0.4, 0.2), (0.6, 0.2), (0.5, 0.4)]],
            cv.GC_FGD: [
                [(0.45, 0.5), (0.55, 0.5), (0.5, 0.6)],
                [(0.45, 0.7), (0.55, 0.7), (0.5, 0.8)],
            ],
        }
        labels = self.script["initial_mask"](image, regions)
        self.assertEqual(labels[20, 20], cv.GC_PR_FGD)
        self.assertEqual(labels[80, 20], cv.GC_PR_BGD)
        self.assertEqual(labels[30, 50], cv.GC_BGD)
        self.assertEqual(labels[55, 50], cv.GC_FGD)
        self.assertEqual(labels[75, 50], cv.GC_FGD)


class MeasurementPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.path = self.directory / "試料.png"
        self.image = np.full((1600, 2400, 3), 25, np.uint8)
        self.image[300:1301, 1000:1401] = 210
        success, data = cv.imencode(".png", self.image)
        self.assertTrue(success)
        self.path.write_bytes(data.tobytes())
        self.script = load_refactored("02_measure_edge_lengths_gui.py")
        self.script["main"].__globals__["OUTPUT_DIRECTORY"] = self.directory

    def run_gui(self, actions):
        callback_errors = []

        def mainloop(root):
            root.report_callback_exception = lambda _kind, error, _tb: (
                callback_errors.append(error)
            )
            try:
                root.update()
                buttons = {}
                for button in find_widgets(root, ttk.Button):
                    buttons[button.cget("text")] = button
                canvas = find_widgets(root, tk.Canvas)[0]
                radios = {}
                for radio in find_widgets(root, ttk.Radiobutton):
                    radios[radio.cget("text")] = radio
                buttons["補正画像を読み込む"].invoke()
                root.update()
                actions(root, buttons, canvas, radios)
            finally:
                root.destroy()

        with (
            patch.object(tk.Tk, "mainloop", mainloop),
            patch.object(
                filedialog, "askopenfilename", return_value=str(self.path)
            ) as open_dialog,
            patch.object(filedialog, "asksaveasfilename") as save_dialog,
        ):
            self.open_dialog = open_dialog
            self.save_dialog = save_dialog
            self.script["main"]()
        self.assertFalse(callback_errors, callback_errors)

    def test_zoom_pan_polygons_axis_order_and_saved_measurement(self):
        def actions(root, buttons, canvas, radios):
            bounds = canvas.bbox(canvas.find_all()[0])
            x0, y0, x1, y1 = bounds
            scale = (x1 - x0) / 2400
            # カーソルの下の元画像座標を保って拡大する。
            cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
            canvas.event_generate("<MouseWheel>", x=cx, y=cy, delta=240)
            factor = 1.2**2
            x0 = cx - (cx - x0) * factor
            y0 = cy - (cy - y0) * factor
            scale *= factor
            canvas.event_generate("<ButtonPress-3>", x=cx, y=cy)
            canvas.event_generate("<B3-Motion>", x=cx + 37, y=cy - 21)
            canvas.event_generate("<ButtonRelease-3>", x=cx + 37, y=cy - 21)
            x0 += 37
            y0 -= 21

            def point(x, y):
                return round(x0 + x * scale), round(y0 + y * scale)

            def click(x, y):
                px, py = point(x, y)
                canvas.event_generate("<ButtonPress-1>", x=px, y=py)
                canvas.event_generate("<ButtonRelease-1>", x=px, y=py)

            for top, bottom in ((240, 820), (780, 1360)):
                for x, y in ((900, top), (1500, top), (1500, bottom), (900, bottom)):
                    click(x, y)
                buttons["多角形を確定"].invoke()
                root.update()
            region_list = find_widgets(root, tk.Listbox)[0]
            self.assertEqual(region_list.size(), 2)
            buttons["長さを計測"].invoke()
            self.assertTrue(buttons["CSV・画像2枚を保存"].instate(["disabled"]))
            self.assertNotIn("上側断面", radios)
            self.assertNotIn("下側断面", radios)
            entry = find_widgets(root, ttk.Entry)[0]
            root.setvar(str(entry.cget("textvariable")), "200")
            radios["区間の中心"].invoke()
            click(1200, 800)
            buttons["長さを計測"].invoke()
            self.assertTrue(buttons["CSV・画像2枚を保存"].instate(["disabled"]))
            buttons["試料抽出・軸を自動推定"].invoke()
            self.assertTrue(buttons["長さを計測"].instate(["!disabled"]))
            buttons["長さを計測"].invoke()
            root.update()
            self.assertTrue(buttons["CSV・画像2枚を保存"].instate(["!disabled"]))
            table = find_widgets(root, ttk.Treeview)[0]
            self.assertEqual(table.item("left", "values")[0], "DR")
            self.assertEqual(table.item("right", "values")[0], "OP")
            before = table.set("left", "length")
            buttons["全体表示"].invoke()
            root.geometry("1000x760")
            root.update()
            for control in (
                buttons["CSV・画像2枚を保存"],
                entry,
                radios["区間の中心"],
                radios["初期指定"],
                radios["元画像"],
                radios["計測結果"],
            ):
                self.assertGreaterEqual(control.winfo_rooty(), root.winfo_rooty())
                self.assertLessEqual(
                    control.winfo_rooty() + control.winfo_height(),
                    root.winfo_rooty() + root.winfo_height(),
                    str(control),
                )
            self.assertEqual(table.set("left", "length"), before)
            self.assertEqual(region_list.size(), 2)
            self.assertEqual(
                [canvas.itemcget(i, "text") for i in canvas.find_withtag("edge_name")],
                ["DR", "OP"],
            )
            self.save_dialog.return_value = str(self.directory / "計測.csv")
            buttons["CSV・画像2枚を保存"].invoke()
            with (self.directory / "計測.csv").open(
                encoding="utf-8-sig", newline=""
            ) as stream:
                row = next(csv.DictReader(stream))
            self.assertNotIn("start_y", row)
            self.assertNotIn("end_y", row)
            expected = float(row["interval_length_mm"])
            self.assertAlmostEqual(expected, 200, places=8)
            self.assertAlmostEqual(float(row["left_mm"]), expected)
            self.assertAlmostEqual(float(row["right_mm"]), expected)
            self.assertAlmostEqual(float(row["left_excess_percent"]), 0)
            self.assertAlmostEqual(float(row["right_excess_percent"]), 0)
            saved = cv.imdecode(
                np.frombuffer((self.directory / "計測.png").read_bytes(), np.uint8),
                cv.IMREAD_COLOR,
            )
            assert saved is not None
            self.assertEqual(saved.shape, self.image.shape)
            # 不正な読込と取消では計測と指定を保つ。
            for selected in ("", str(self.directory / "missing.png")):
                self.open_dialog.return_value = selected
                buttons["補正画像を読み込む"].invoke()
                self.assertEqual(region_list.size(), 2)
                self.assertEqual(table.set("left", "length"), before)
            radios["初期指定"].invoke()
            region_list.selection_set(0)
            buttons["選択した多角形を削除"].invoke()
            self.assertEqual(region_list.size(), 1)
            self.assertTrue(buttons["CSV・画像2枚を保存"].instate(["disabled"]))

        self.run_gui(actions)

    def test_manual_axis_and_interval_change_reestimate_and_invalidate_result(self):
        globals_ = self.script["main"].__globals__
        estimate = globals_["estimate_axis"]
        extract = globals_["extract_specimen"]

        def actions(root, buttons, canvas, radios):
            x0, y0, x1, _y1 = canvas.bbox(canvas.find_all()[0])
            scale = (x1 - x0) / self.image.shape[1]

            def click(x, y):
                px = round(x0 + x * scale)
                py = round(y0 + y * scale)
                canvas.event_generate("<ButtonPress-1>", x=px, y=py)
                canvas.event_generate("<ButtonRelease-1>", x=px, y=py)

            for x, y in ((900, 200), (1500, 200), (1500, 1400), (900, 1400)):
                click(x, y)
            buttons["多角形を確定"].invoke()
            entry = find_widgets(root, ttk.Entry)[0]
            root.setvar(str(entry.cget("textvariable")), "200")
            radios["区間の中心"].invoke()
            click(1200, 800)
            buttons["試料抽出・軸を自動推定"].invoke()
            buttons["長さを計測"].invoke()
            self.assertTrue(buttons["CSV・画像2枚を保存"].instate(["!disabled"]))
            radios["手動軸2点"].invoke()
            click(1160, 400)
            click(1240, 1200)
            self.assertTrue(buttons["CSV・画像2枚を保存"].instate(["disabled"]))
            self.assertTrue(buttons["長さを計測"].instate(["!disabled"]))
            buttons["長さを計測"].invoke()
            self.assertTrue(buttons["CSV・画像2枚を保存"].instate(["!disabled"]))
            self.save_dialog.return_value = str(self.directory / "傾けた手動軸.csv")
            buttons["CSV・画像2枚を保存"].invoke()
            with (self.directory / "傾けた手動軸.csv").open(
                encoding="utf-8-sig", newline=""
            ) as stream:
                row = next(csv.DictReader(stream))
            self.assertAlmostEqual(float(row["interval_length_mm"]), 200, places=8)
            self.assertGreater(float(row["left_mm"]), 200)
            # 手動軸を1点だけ指定した状態からも、自動推定へ戻って計測できる。
            click(1200, 500)
            self.assertTrue(buttons["CSV・画像2枚を保存"].instate(["disabled"]))
            buttons["試料抽出・軸を自動推定"].invoke()
            buttons["長さを計測"].invoke()
            self.assertTrue(buttons["CSV・画像2枚を保存"].instate(["!disabled"]))
            with patch.dict(
                globals_,
                estimate_axis=Mock(wraps=estimate),
                extract_specimen=Mock(wraps=extract),
            ):
                radios["区間の中心"].invoke()
                click(1200, 780)
                globals_["estimate_axis"].assert_called_once()
                self.assertTrue(buttons["CSV・画像2枚を保存"].instate(["disabled"]))
                buttons["長さを計測"].invoke()
                self.assertTrue(buttons["CSV・画像2枚を保存"].instate(["!disabled"]))
                root.setvar(str(entry.cget("textvariable")), "150")
                self.assertEqual(globals_["estimate_axis"].call_count, 2)
                globals_["extract_specimen"].assert_not_called()
            self.assertTrue(buttons["CSV・画像2枚を保存"].instate(["disabled"]))
            buttons["長さを計測"].invoke()
            self.save_dialog.return_value = str(self.directory / "短い区間.csv")
            buttons["CSV・画像2枚を保存"].invoke()
            with (self.directory / "短い区間.csv").open(
                encoding="utf-8-sig", newline=""
            ) as stream:
                row = next(csv.DictReader(stream))
            self.assertAlmostEqual(float(row["interval_length_mm"]), 150, places=8)
            self.assertAlmostEqual(float(row["left_excess_percent"]), 0)

        self.run_gui(actions)

    def test_failed_auto_axis_can_be_replaced_manually_and_saved(self):
        globals_ = self.script["main"].__globals__

        def actions(root, buttons, canvas, radios):
            x0, y0, x1, _y1 = canvas.bbox(canvas.find_all()[0])
            scale = (x1 - x0) / self.image.shape[1]

            def click(x, y):
                px = round(x0 + x * scale)
                py = round(y0 + y * scale)
                canvas.event_generate("<ButtonPress-1>", x=px, y=py)
                canvas.event_generate("<ButtonRelease-1>", x=px, y=py)

            for x, y in ((900, 200), (1500, 200), (1500, 1400), (900, 1400)):
                click(x, y)
            buttons["多角形を確定"].invoke()
            entry = find_widgets(root, ttk.Entry)[0]
            root.setvar(str(entry.cget("textvariable")), "200")
            radios["区間の中心"].invoke()
            click(1200, 800)
            with patch.dict(
                globals_, estimate_axis=Mock(side_effect=ValueError("軸の推定失敗"))
            ):
                buttons["試料抽出・軸を自動推定"].invoke()
                globals_["estimate_axis"].assert_called_once()
            self.assertTrue(buttons["CSV・画像2枚を保存"].instate(["disabled"]))
            radios["手動軸2点"].invoke()
            click(1200, 400)
            click(1200, 1200)
            buttons["長さを計測"].invoke()
            self.assertTrue(buttons["CSV・画像2枚を保存"].instate(["!disabled"]))
            self.save_dialog.return_value = str(self.directory / "手動軸.csv")
            buttons["CSV・画像2枚を保存"].invoke()
            with (self.directory / "手動軸.csv").open(
                encoding="utf-8-sig", newline=""
            ) as stream:
                row = next(csv.DictReader(stream))
            self.assertAlmostEqual(float(row["interval_length_mm"]), 200, places=8)
            self.assertAlmostEqual(float(row["left_excess_percent"]), 0)
            self.assertAlmostEqual(float(row["right_excess_percent"]), 0)
            self.assertNotIn("axis_mode", row)

        self.run_gui(actions)

    def test_invalid_fixed_length_and_outside_interval_cannot_be_saved(self):
        globals_ = self.script["main"].__globals__

        def actions(root, buttons, canvas, radios):
            entry = find_widgets(root, ttk.Entry)[0]
            length_variable = str(entry.cget("textvariable"))
            self.assertEqual(root.getvar(length_variable), "")
            x0, y0, x1, _y1 = canvas.bbox(canvas.find_all()[0])
            scale = (x1 - x0) / self.image.shape[1]

            def click(x, y):
                canvas.event_generate(
                    "<ButtonPress-1>",
                    x=round(x0 + x * scale),
                    y=round(y0 + y * scale),
                )

            for point in ((900, 200), (1500, 200), (1500, 1400), (900, 1400)):
                click(*point)
            buttons["多角形を確定"].invoke()
            radios["区間の中心"].invoke()
            click(1200, 800)
            root.setvar(length_variable, "200")
            buttons["試料抽出・軸を自動推定"].invoke()
            buttons["長さを計測"].invoke()
            self.assertTrue(buttons["CSV・画像2枚を保存"].instate(["!disabled"]))

            with patch.dict(globals_, extract_specimen=Mock()):
                for invalid in ("", "abc", "nan", "inf", "0", "-10"):
                    root.setvar(length_variable, invalid)
                    buttons["試料抽出・軸を自動推定"].invoke()
                    buttons["長さを計測"].invoke()
                    self.assertEqual(len(canvas.find_withtag("axis")), 0, invalid)
                    self.assertTrue(
                        buttons["CSV・画像2枚を保存"].instate(["disabled"]), invalid
                    )
                globals_["extract_specimen"].assert_not_called()

            # 試料端や画像端を越える指定は、測れる長さへ切り詰めない。
            for center, length in (((1200, 400), "200"), ((1200, 800), "1000")):
                root.setvar(length_variable, length)
                click(*center)
                buttons["試料抽出・軸を自動推定"].invoke()
                buttons["長さを計測"].invoke()
                self.assertTrue(buttons["CSV・画像2枚を保存"].instate(["disabled"]))
            self.save_dialog.assert_not_called()

        self.run_gui(actions)

    def test_new_image_keeps_fixed_length_and_resets_center_and_measurement(self):
        globals_ = self.script["main"].__globals__

        def actions(root, buttons, canvas, radios):
            entry = find_widgets(root, ttk.Entry)[0]
            length_variable = str(entry.cget("textvariable"))
            root.setvar(length_variable, "150")
            x0, y0, x1, _y1 = canvas.bbox(canvas.find_all()[0])
            scale = (x1 - x0) / self.image.shape[1]

            def click(x, y):
                canvas.event_generate(
                    "<ButtonPress-1>",
                    x=round(x0 + x * scale),
                    y=round(y0 + y * scale),
                )

            def polygon():
                radios["多角形"].invoke()
                for point in ((900, 200), (1500, 200), (1500, 1400), (900, 1400)):
                    click(*point)
                buttons["多角形を確定"].invoke()

            polygon()
            radios["区間の中心"].invoke()
            click(1200, 800)
            buttons["試料抽出・軸を自動推定"].invoke()
            buttons["長さを計測"].invoke()
            self.assertTrue(buttons["CSV・画像2枚を保存"].instate(["!disabled"]))
            second = self.directory / "次のパス.png"
            second.write_bytes(self.path.read_bytes())
            self.open_dialog.return_value = str(second)
            buttons["補正画像を読み込む"].invoke()
            root.update()
            self.assertEqual(root.getvar(length_variable), "150")
            self.assertEqual(find_widgets(root, tk.Listbox)[0].size(), 0)
            self.assertEqual(len(canvas.find_withtag("axis")), 0)
            self.assertTrue(buttons["CSV・画像2枚を保存"].instate(["disabled"]))
            table = find_widgets(root, ttk.Treeview)[0]
            for edge in ("left", "right"):
                self.assertEqual(table.set(edge, "length"), "—")
                self.assertEqual(table.set(edge, "excess"), "—")
            polygon()
            with patch.dict(globals_, extract_specimen=Mock()):
                buttons["試料抽出・軸を自動推定"].invoke()
                globals_["extract_specimen"].assert_not_called()
            self.assertTrue(buttons["CSV・画像2枚を保存"].instate(["disabled"]))

        self.run_gui(actions)

    def test_zoom_builds_only_visible_pixels_and_full_view_is_recoverable(self):
        def actions(root, buttons, canvas, _radios):
            original = cv.warpAffine
            with patch.object(cv, "warpAffine", wraps=original) as warp:
                canvas.event_generate("<MouseWheel>", x=400, y=300, delta=2400)
                self.assertTrue(warp.called)
                for call in warp.call_args_list:
                    width, height = call.args[2]
                    self.assertLessEqual(width, canvas.winfo_width())
                    self.assertLessEqual(height, canvas.winfo_height())
            canvas.event_generate("<ButtonPress-3>", x=200, y=200)
            canvas.event_generate("<B3-Motion>", x=10000, y=10000)
            canvas.event_generate("<ButtonRelease-3>", x=10000, y=10000)
            buttons["全体表示"].invoke()
            root.update()
            image_items = [i for i in canvas.find_all() if canvas.type(i) == "image"]
            self.assertEqual(len(image_items), 1)
            self.assertEqual(find_widgets(root, tk.Listbox)[0].size(), 0)

        self.run_gui(actions)

    def test_small_image_displays_at_one_to_one_scale(self):
        def actions(root, buttons, canvas, radios):
            small = np.full((160, 140, 3), 35, np.uint8)
            small[20:141, 50:91] = 200
            success, data = cv.imencode(".png", small)
            self.assertTrue(success)
            self.path.write_bytes(data.tobytes())
            buttons["補正画像を読み込む"].invoke()
            radios["元画像"].invoke()
            root.update()
            photo = canvas.itemcget(canvas.find_all()[0], "image")
            self.assertEqual(int(root.tk.call("image", "width", photo)), 140)
            self.assertEqual(int(root.tk.call("image", "height", photo)), 160)
            self.assertEqual(tuple(root.tk.call(photo, "get", 80, 80)), (200, 200, 200))

        self.run_gui(actions)


if __name__ == "__main__":
    unittest.main()
