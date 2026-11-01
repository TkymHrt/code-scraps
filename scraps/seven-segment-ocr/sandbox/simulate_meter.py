"""カメラがない場所でも試せる、反射した赤色7セグ計器の動画を作る。"""

import argparse
import csv
import json
from pathlib import Path

import cv2
import numpy as np

DISPLAY_WIDTH = 720
DISPLAY_HEIGHT = 200
FRAME_WIDTH = 960
FRAME_HEIGHT = 360
DISPLAY_CORNERS = [[110, 92], [846, 61], [866, 289], [91, 309]]

# 描画側はOCR側の定義を読み込まず、別の形状からテスト画像を作る。
LIT_SEGMENTS = {
    "0": "abcdef",
    "1": "bc",
    "2": "abdeg",
    "3": "abcdg",
    "4": "bcfg",
    "5": "acdfg",
    "6": "acdefg",
    "7": "abc",
    "8": "abcdefg",
    "9": "abcdfg",
    " ": "",
    "?": "ag",
}


def draw_display(display, brightness=230):
    """6文字の表示を描く。空白は消灯、?は数字にならない点灯。"""
    if len(display) != 6:
        raise ValueError("display は空白も含めて6文字で指定してください。")

    image = np.full((DISPLAY_HEIGHT, DISPLAY_WIDTH, 3), 8, dtype=np.uint8)
    segment_shapes = {
        "a": [[27, 20], [34, 13], [86, 13], [93, 20], [86, 27], [34, 27]],
        "b": [[99, 27], [106, 34], [106, 82], [99, 89], [92, 82], [92, 34]],
        "c": [[99, 111], [106, 118], [106, 166], [99, 173], [92, 166], [92, 118]],
        "d": [[27, 180], [34, 173], [86, 173], [93, 180], [86, 187], [34, 187]],
        "e": [[21, 111], [28, 118], [28, 166], [21, 173], [14, 166], [14, 118]],
        "f": [[21, 27], [28, 34], [28, 82], [21, 89], [14, 82], [14, 34]],
        "g": [[27, 100], [34, 93], [86, 93], [93, 100], [86, 107], [34, 107]],
    }

    for digit_index, symbol in enumerate(display):
        if symbol not in LIT_SEGMENTS:
            raise ValueError("描画できない文字です: " + symbol)
        lit_segments = LIT_SEGMENTS[symbol]
        for name, points in segment_shapes.items():
            polygon = np.array(points, dtype=np.int32)
            polygon[:, 0] += digit_index * 120
            color = (8, 8, 14)
            if name in lit_segments:
                color = (12, 17, brightness)
            cv2.fillConvexPoly(image, polygon, color, lineType=cv2.LINE_AA)
    return image


def make_frame(
    display,
    reflection="horizontal",
    brightness=230,
    blur_sigma=0.8,
    noise_sigma=2.5,
    seed=0,
):
    """透視変換、反射、背景の映り込み、ぼけ、雑音を加える。"""
    image = np.full((FRAME_HEIGHT, FRAME_WIDTH, 3), (29, 31, 32), dtype=np.uint8)
    cv2.line(image, (0, 10), (959, 100), (53, 53, 53), 38)
    cv2.line(image, (0, 280), (959, 345), (45, 45, 45), 26)
    # ROI外の赤い物体を、桁と取り違えないことも確認する。
    cv2.circle(image, (42, 180), 17, (12, 20, 225), -1)
    cv2.rectangle(image, (885, 110), (937, 127), (8, 14, 205), -1)

    display_image = draw_display(display, brightness)
    source_corners = np.float32([[0, 0], [719, 0], [719, 199], [0, 199]])
    destination_corners = np.float32(DISPLAY_CORNERS)
    transform = cv2.getPerspectiveTransform(source_corners, destination_corners)
    projected_display = cv2.warpPerspective(
        display_image, transform, (FRAME_WIDTH, FRAME_HEIGHT)
    )
    display_mask = np.full((DISPLAY_HEIGHT, DISPLAY_WIDTH), 255, dtype=np.uint8)
    projected_mask = cv2.warpPerspective(
        display_mask, transform, (FRAME_WIDTH, FRAME_HEIGHT)
    )
    image[projected_mask > 0] = projected_display[projected_mask > 0]

    # ハーフミラーに映った白っぽい筋を弱く重ねる。
    reflection_layer = np.zeros_like(image)
    cv2.line(reflection_layer, (90, 245), (860, 150), (15, 15, 15), 35)
    image = cv2.add(image, reflection_layer)
    if blur_sigma > 0:
        image = cv2.GaussianBlur(image, (0, 0), blur_sigma)
    if noise_sigma > 0:
        random = np.random.default_rng(seed)
        noise = random.normal(0, noise_sigma, image.shape)
        noisy_image = image.astype(np.float32) + noise
        image = np.clip(noisy_image, 0, 255).astype(np.uint8)
    if reflection == "horizontal":
        image = cv2.flip(image, 1)
    elif reflection == "vertical":
        image = cv2.flip(image, 0)
    elif reflection == "both":
        image = cv2.flip(image, -1)
    elif reflection != "none":
        raise ValueError("reflection は horizontal / vertical / both / none です。")
    return image


def make_scenarios():
    scenarios = []
    values = ["0.000", "0.001", "1.234", "12.345", "123.456", "789.012", "999.999"]
    for value in values:
        digits = value.replace(".", "")
        display = digits.rjust(6)
        scenarios.append((display, value, "normal", 230, 0.8, 2.5))

    scenarios.extend(
        [
            ("456789", "456.789", "dim", 100, 1.0, 3.0),
            (" 27364", "27.364", "blur_noise", 210, 1.8, 5.0),
            (" 10101", "10.101", "alternating", 230, 0.8, 2.5),
            ("      ", "", "all_blank", 230, 0.8, 2.5),
            ("12 456", "", "interior_blank", 230, 0.8, 2.5),
            ("123?56", "", "unknown_segments", 230, 0.8, 2.5),
            ("  1234", "1.234", "recovery", 230, 0.8, 2.5),
        ]
    )
    return scenarios


def make_config(reflection):
    """生成した映像に対応する設定。実機では四隅を選び直す。"""
    digit_boxes = []
    for digit_index in range(6):
        left = 120 * digit_index
        digit_boxes.append([left + 14, 13, left + 106, 187])
    return {
        "frame_size": [FRAME_WIDTH, FRAME_HEIGHT],
        "display_corners": DISPLAY_CORNERS,
        "reflection": reflection,
        "digit_boxes": digit_boxes,
        "red_min": 70,
        "red_margin": 40,
        "off_fraction": 0.15,
        "on_fraction": 0.65,
        "stable_frames": 3,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/simulation"))
    parser.add_argument("--frames-per-value", type=int, default=12)
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument(
        "--reflection",
        choices=["horizontal", "vertical", "both", "none"],
        default="horizontal",
    )
    args = parser.parse_args()
    if args.frames_per_value < 1 or not np.isfinite(args.fps) or args.fps <= 0:
        parser.error("frames-per-value と fps は正の値で指定してください。")

    video_path = args.output_dir / "meter.avi"
    truth_path = args.output_dir / "truth.csv"
    config_path = args.output_dir / "meter_config.json"
    preview_path = args.output_dir / "preview.png"
    for output_path in [video_path, truth_path, config_path, preview_path]:
        if output_path.exists():
            parser.error(
                f"既存ファイルは上書きしません: {output_path}。別の --output-dir を指定してください。"
            )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(video_path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        args.fps,
        (FRAME_WIDTH, FRAME_HEIGHT),
    )
    if not writer.isOpened():
        raise RuntimeError("動画の保存先を開けません: " + str(video_path))

    frame_index = 0
    try:
        with truth_path.open("w", encoding="utf-8", newline="") as truth_file:
            truth_writer = csv.writer(truth_file)
            truth_writer.writerow(
                ["frame_index", "time_seconds", "display", "value", "scenario"]
            )
            for (
                display,
                value,
                scenario,
                brightness,
                blur_sigma,
                noise_sigma,
            ) in make_scenarios():
                for repeat in range(args.frames_per_value):
                    frame = make_frame(
                        display,
                        args.reflection,
                        brightness,
                        blur_sigma,
                        noise_sigma,
                        seed=frame_index,
                    )
                    writer.write(frame)
                    truth_writer.writerow(
                        [
                            frame_index,
                            f"{frame_index / args.fps:.6f}",
                            display,
                            value,
                            scenario,
                        ]
                    )
                    if frame_index == 4 * args.frames_per_value:
                        if not cv2.imwrite(str(preview_path), frame):
                            raise RuntimeError("プレビュー画像を保存できません。")
                    frame_index += 1
    finally:
        writer.release()

    config_path.write_text(
        json.dumps(make_config(args.reflection), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"動画: {video_path} ({frame_index} frames, {args.fps:g} fps)")
    print(f"正解: {truth_path}")
    print(f"設定: {config_path}")
    print(f"画像: {preview_path}")


if __name__ == "__main__":
    main()
