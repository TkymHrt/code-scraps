"""カメラ校正・画像換算に使うChArUco板だけをPNGに保存する."""

from pathlib import Path

import cv2 as cv

OUTPUT_PATH = "results/charuco_board.png"

# camera_calibration.pyとrectify_image_gui.pyと同じ仕様にする。
BOARD_SQUARES = (7, 5)
SQUARE_MM = 30.0
MARKER_MM = 18.0
PIXELS_PER_MM = 10
MARGIN_MM = 10

dictionary = cv.aruco.getPredefinedDictionary(cv.aruco.DICT_4X4_50)
board = cv.aruco.CharucoBoard(BOARD_SQUARES, SQUARE_MM, MARKER_MM, dictionary)
board_width_mm = BOARD_SQUARES[0] * SQUARE_MM
board_height_mm = BOARD_SQUARES[1] * SQUARE_MM
board_width_px = int(board_width_mm * PIXELS_PER_MM)
board_height_px = int(board_height_mm * PIXELS_PER_MM)
board_image = board.generateImage((board_width_px, board_height_px))
margin_px = int(MARGIN_MM * PIXELS_PER_MM)
printable = cv.copyMakeBorder(
    board_image,
    margin_px,
    margin_px,
    margin_px,
    margin_px,
    cv.BORDER_CONSTANT,
    value=255,
)

output_path = Path(__file__).resolve().parent / OUTPUT_PATH
if output_path.suffix.lower() != ".png":
    raise ValueError("保存先の拡張子は .png にしてください")
success, encoded = cv.imencode(".png", printable)
if not success:
    raise OSError("校正板のPNGを作れません")
output_path.parent.mkdir(parents=True, exist_ok=True)
output_path.write_bytes(encoded.tobytes())

print(f"校正板: {output_path}")
print(
    f"黒白の板本体: {board_width_mm:g} × {board_height_mm:g}mm、1マス: {SQUARE_MM:g}mm"
)
print(
    f"PNG全体の印刷寸法: {board_width_mm + 2 * MARGIN_MM:g} × {board_height_mm + 2 * MARGIN_MM:g}mm"
)
print("印刷後に縦横・1マスの寸法を実測し、平らで硬い板へ貼ってください。")
