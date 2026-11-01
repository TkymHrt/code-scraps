"""赤い6桁7セグを読み、固定小数3桁の値をJSONLとCSVに出力する。"""

import argparse
import csv
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

DISPLAY_WIDTH = 720
DISPLAY_HEIGHT = 200

# 各桁の外接枠を幅・高さ1とした座標。順序は上、右上、右下、下、左下、左上、中央。
SEGMENT_REGIONS = [
    (0.30, 0.01, 0.70, 0.07),
    (0.88, 0.16, 0.98, 0.36),
    (0.88, 0.64, 0.98, 0.84),
    (0.30, 0.93, 0.70, 0.99),
    (0.02, 0.64, 0.12, 0.84),
    (0.02, 0.16, 0.12, 0.36),
    (0.30, 0.47, 0.70, 0.53),
]
PATTERN_TO_DIGIT = {
    "1111110": "0",
    "0110000": "1",
    "1101101": "2",
    "1111001": "3",
    "0110011": "4",
    "1011011": "5",
    "1011111": "6",
    "1110000": "7",
    "1111111": "8",
    "1111011": "9",
    "0000000": " ",
}


def validate_corners(points, width, height):
    corners = np.array(points, dtype=np.float32)
    if corners.shape != (4, 2) or not np.isfinite(corners).all():
        raise ValueError("display_corners は4個の有限な座標にしてください。")
    if (corners[:, 0] < 0).any() or (corners[:, 0] >= width).any():
        raise ValueError("四隅のx座標が撮影画像からはみ出しています。")
    if (corners[:, 1] < 0).any() or (corners[:, 1] >= height).any():
        raise ValueError("四隅のy座標が撮影画像からはみ出しています。")
    if (
        not cv2.isContourConvex(corners)
        or cv2.contourArea(corners, oriented=True) < 100
    ):
        raise ValueError("四隅を左上→右上→右下→左下の順に選び直してください。")


def validate_settings(settings):
    """誤った校正で別の位置を読まないよう、保存設定を確認する。"""
    width, height = settings["frame_size"]
    if (
        not isinstance(width, int)
        or not isinstance(height, int)
        or min(width, height) < 2
    ):
        raise ValueError("frame_size は正の整数の幅・高さで指定してください。")
    if settings["reflection"] not in ("none", "horizontal", "vertical", "both"):
        raise ValueError("reflection の指定が不正です。")
    validate_corners(settings["display_corners"], width, height)
    boxes = settings["digit_boxes"]
    if len(boxes) != 6:
        raise ValueError("digit_boxes は消灯桁も含め6個必要です。")
    previous_right = 0
    for left, top, right, bottom in boxes:
        for coordinate in (left, top, right, bottom):
            if not isinstance(coordinate, int):
                raise ValueError("桁の枠は整数座標にしてください。")
        if not (previous_right <= left < right <= DISPLAY_WIDTH):
            raise ValueError("桁の枠は左から順に、重ならないよう指定してください。")
        if not (0 <= top < bottom <= DISPLAY_HEIGHT):
            raise ValueError("桁の枠のy座標が補正画像からはみ出しています。")
        if right - left < 20 or bottom - top < 40:
            raise ValueError("桁の枠が小さすぎます。校正をやり直してください。")
        previous_right = right

    for name in ("red_min", "red_margin"):
        if not isinstance(settings[name], int) or not 1 <= settings[name] <= 255:
            raise ValueError(name + " は1〜255の整数にしてください。")
    off = settings["off_fraction"]
    on = settings["on_fraction"]
    if not 0 <= off < on <= 1:
        raise ValueError("0 <= off_fraction < on_fraction <= 1 が必要です。")
    count = settings["stable_frames"]
    if not isinstance(count, int) or count < 1:
        raise ValueError("stable_frames は1以上の整数にしてください。")


def correct_reflection(frame, reflection):
    if reflection == "horizontal":
        return cv2.flip(frame, 1)
    if reflection == "vertical":
        return cv2.flip(frame, 0)
    if reflection == "both":
        return cv2.flip(frame, -1)
    if reflection == "none":
        return frame
    raise ValueError("反射方向が不正です。")


def rectify_display(frame, settings):
    height, width = frame.shape[:2]
    if [width, height] != settings["frame_size"]:
        raise ValueError(
            "撮影解像度が校正時と異なります。現在の解像度で校正し直してください。"
        )
    corrected = correct_reflection(frame, settings["reflection"])
    source = np.float32(settings["display_corners"])
    destination = np.float32([[0, 0], [719, 0], [719, 199], [0, 199]])
    transform = cv2.getPerspectiveTransform(source, destination)
    return cv2.warpPerspective(corrected, transform, (DISPLAY_WIDTH, DISPLAY_HEIGHT))


def recognize_display(image, settings):
    # uint8のまま引くと負数が255付近に回り込むため、先に型を変える。
    blue = image[:, :, 0].astype(np.int16)
    green = image[:, :, 1].astype(np.int16)
    red = image[:, :, 2].astype(np.int16)
    red_excess = red - np.maximum(blue, green)
    red_pixels = (red >= settings["red_min"]) & (red_excess >= settings["red_margin"])
    mask = red_pixels.astype(np.uint8) * 255

    display = ""
    all_fractions = []
    for left, top, right, bottom in settings["digit_boxes"]:
        digit_mask = mask[top:bottom, left:right]
        digit_height, digit_width = digit_mask.shape
        pattern = ""
        fractions = []
        for x1, y1, x2, y2 in SEGMENT_REGIONS:
            region_left = round(x1 * digit_width)
            region_top = round(y1 * digit_height)
            region_right = round(x2 * digit_width)
            region_bottom = round(y2 * digit_height)
            region = digit_mask[region_top:region_bottom, region_left:region_right]
            fraction = cv2.countNonZero(region) / region.size
            fractions.append(fraction)
            if fraction >= settings["on_fraction"]:
                pattern += "1"
            elif fraction <= settings["off_fraction"]:
                pattern += "0"
            else:
                pattern += "?"
        display += PATTERN_TO_DIGIT.get(pattern, "?")
        all_fractions.append(fractions)

    raw_value = None
    reason = ""
    integer_part = display[:3].lstrip(" ")
    fraction_part = display[3:]
    if "?" in display:
        reason = "uncertain_segments"
    elif display == "      ":
        reason = "all_blank"
    elif not integer_part.isdigit() or not fraction_part.isdigit():
        reason = "misplaced_blank"
    else:
        # floatを介さず文字列で作り、0.001や末尾の0をそのまま保存する。
        raw_value = str(int(integer_part)) + "." + fraction_part
    reading = {
        "display": display,
        "raw_value": raw_value,
        "reason": reason,
        "fractions": all_fractions,
    }
    return reading, mask


def draw_preview(image, mask, settings, reading, status):
    annotated = image.copy()
    for digit_index, box in enumerate(settings["digit_boxes"]):
        left, top, right, bottom = box
        cv2.rectangle(annotated, (left, top), (right, bottom), (160, 160, 160), 1)
        for segment_index, region in enumerate(SEGMENT_REGIONS):
            x1, y1, x2, y2 = region
            start = (
                left + round(x1 * (right - left)),
                top + round(y1 * (bottom - top)),
            )
            end = (left + round(x2 * (right - left)), top + round(y2 * (bottom - top)))
            fraction = reading["fractions"][digit_index][segment_index]
            color = (0, 200, 0)
            if settings["off_fraction"] < fraction < settings["on_fraction"]:
                color = (0, 200, 255)
            cv2.rectangle(annotated, start, end, color, 1)
    mask_bgr = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
    panel = np.vstack([annotated, mask_bgr])
    label = f"{status}: [{reading['display']}] {reading['reason']}   Q: quit"
    cv2.putText(
        panel, label, (8, 218), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 1
    )
    return panel


def calibrate_meter(capture, first_frame, is_camera, reflection, config_path):
    """反射補正後の四隅を選び、補正画像で6桁の外接枠を選ぶ。"""
    window = "Calibration"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    frame_height, frame_width = first_frame.shape[:2]
    scale = min(1.0, 1280 / frame_width, 720 / frame_height)
    cv2.resizeWindow(window, round(frame_width * scale), round(frame_height * scale))
    frame = first_frame
    while True:
        corrected = correct_reflection(frame, reflection)
        preview = corrected.copy()
        cv2.putText(
            preview,
            "SPACE: freeze   N: next video frame   Q: cancel",
            (10, 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 255),
            2,
        )
        cv2.imshow(window, preview)
        delay = 0
        if is_camera:
            delay = 30
        key = cv2.waitKey(delay) & 0xFF
        if key in (27, ord("q")):
            return
        if key == ord(" "):
            break
        if not is_camera and key == ord("n"):
            success, next_frame = capture.read()
            if success:
                frame = next_frame
            else:
                print(
                    "動画の最後です。現在の画像で校正するかQで終了してください。",
                    file=sys.stderr,
                )
        if is_camera:
            success, frame = capture.read()
            if not success:
                raise RuntimeError("校正中にカメラ画像の取得に失敗しました。")

    points = []

    def remember_click(event, x, y, flags, parameter):
        if event == cv2.EVENT_LBUTTONDOWN and len(points) < 4:
            points.append([x, y])

    cv2.setMouseCallback(window, remember_click)
    while True:
        preview = corrected.copy()
        cv2.putText(
            preview,
            "Click TL, TR, BR, BL   ENTER: next   R: reset   Q: cancel",
            (10, 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 255, 255),
            1,
        )
        for index, point in enumerate(points):
            cv2.circle(preview, tuple(point), 4, (0, 255, 255), -1)
            cv2.putText(
                preview,
                str(index + 1),
                tuple(point),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 255),
                2,
            )
        cv2.imshow(window, preview)
        key = cv2.waitKey(30) & 0xFF
        if key in (27, ord("q")):
            return
        if key == ord("r"):
            points.clear()
        if key == 13 and len(points) == 4:
            try:
                validate_corners(points, frame.shape[1], frame.shape[0])
            except ValueError as error:
                print(str(error) + " Rで選び直せます。", file=sys.stderr)
                continue
            break

    settings = {
        "frame_size": [frame.shape[1], frame.shape[0]],
        "display_corners": points,
        "reflection": reflection,
        "digit_boxes": [],
        "red_min": 70,
        "red_margin": 40,
        "off_fraction": 0.15,
        "on_fraction": 0.65,
        "stable_frames": 3,
    }
    image = rectify_display(frame, settings)
    cv2.destroyWindow(window)
    for digit_index in range(6):
        preview = image.copy()
        for left, top, right, bottom in settings["digit_boxes"]:
            cv2.rectangle(preview, (left, top), (right, bottom), (0, 255, 255), 1)
        title = f"Digit {digit_index + 1}/6: box as if 8, ENTER confirm, C cancel"
        x, y, width, height = cv2.selectROI(title, preview, showCrosshair=True)
        cv2.destroyWindow(title)
        if width == 0 or height == 0:
            return
        settings["digit_boxes"].append([x, y, x + width, y + height])
    validate_settings(settings)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("x", encoding="utf-8") as file:
        json.dump(settings, file, ensure_ascii=False, indent=2)
        file.write("\n")
    print("校正を保存しました: " + str(config_path), file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("calibrate", "read"):
        command = commands.add_parser(name)
        source = command.add_mutually_exclusive_group(required=True)
        source.add_argument("--camera", type=int, help="カメラ番号。通常は0")
        source.add_argument("--video", type=Path, help="保存した動画")
        command.add_argument("--config", type=Path, required=True, help="校正JSON")
        if name == "calibrate":
            command.add_argument(
                "--reflection",
                choices=["none", "horizontal", "vertical", "both"],
                default="horizontal",
            )
        else:
            command.add_argument(
                "--csv", type=Path, required=True, help="新しいCSV保存先"
            )
            command.add_argument(
                "--headless", action="store_true", help="確認画面を表示しない"
            )
    args = parser.parse_args()
    settings = None
    if args.command == "calibrate":
        if args.config.exists():
            raise FileExistsError(
                "校正ファイルは上書きしません。別の--configを指定してください。"
            )
    else:
        settings = json.loads(args.config.read_text(encoding="utf-8-sig"))
        validate_settings(settings)
        if args.csv.exists():
            raise FileExistsError("CSVは上書きしません。別の--csvを指定してください。")

    is_camera = args.camera is not None
    if is_camera:
        source = args.camera
    else:
        source = str(args.video)
    capture = cv2.VideoCapture(source)
    csv_file = None
    try:
        if not capture.isOpened():
            raise RuntimeError("カメラまたは動画を開けません: " + str(source))
        # カメラが対応する場合、校正時の解像度を要求する。実際のサイズも毎フレーム照合する。
        if is_camera and settings is not None:
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, settings["frame_size"][0])
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, settings["frame_size"][1])
        success, frame = capture.read()
        if not success:
            raise RuntimeError("最初の画像を取得できません。")
        if args.command == "calibrate":
            calibrate_meter(capture, frame, is_camera, args.reflection, args.config)
            return

        fps = capture.get(cv2.CAP_PROP_FPS)
        if not is_camera and (not math.isfinite(fps) or fps <= 0):
            raise RuntimeError(
                "動画のfpsを取得できません。時刻を付けられないため停止します。"
            )
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        csv_file = args.csv.open("x", encoding="utf-8", newline="")
        fields = [
            "frame_index",
            "captured_at",
            "source_time_seconds",
            "status",
            "display",
            "raw_value",
            "value",
            "reason",
        ]
        writer = csv.DictWriter(csv_file, fieldnames=fields)
        writer.writeheader()
        previous_value = None
        consecutive_count = 0
        frame_index = 0
        start_time = time.monotonic()
        while True:
            captured_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
            if is_camera:
                source_time = time.monotonic() - start_time
            else:
                source_time = frame_index / fps
            image = rectify_display(frame, settings)
            reading, mask = recognize_display(image, settings)
            raw_value = reading["raw_value"]
            value = None
            if raw_value is None:
                previous_value = None
                consecutive_count = 0
                status = "invalid"
            else:
                if raw_value == previous_value:
                    consecutive_count += 1
                else:
                    previous_value = raw_value
                    consecutive_count = 1
                status = "warming_up"
                if consecutive_count >= settings["stable_frames"]:
                    status = "ok"
                    value = raw_value
            row = {
                "frame_index": frame_index,
                "captured_at": captured_at,
                "source_time_seconds": round(source_time, 6),
                "status": status,
                "display": reading["display"],
                "raw_value": raw_value,
                "value": value,
                "reason": reading["reason"],
            }
            writer.writerow(row)
            csv_file.flush()
            print(json.dumps(row, ensure_ascii=True), flush=True)
            if not args.headless:
                cv2.imshow(
                    "Seven segment OCR",
                    draw_preview(image, mask, settings, reading, status),
                )
                delay = 1
                if not is_camera:
                    delay = max(1, round(1000 / fps))
                key = cv2.waitKey(delay) & 0xFF
                if key in (27, ord("q")):
                    break
            success, frame = capture.read()
            if not success:
                if is_camera:
                    raise RuntimeError(
                        "カメラ画像の取得に失敗しました。収集を停止します。"
                    )
                break
            frame_index += 1
    finally:
        capture.release()
        if csv_file is not None:
            csv_file.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("収集を停止しました。", file=sys.stderr)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, cv2.error) as error:
        print("エラー: " + str(error), file=sys.stderr)
        sys.exit(1)
