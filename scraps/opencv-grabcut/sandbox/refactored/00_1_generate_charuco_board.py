"""カメラ校正・画像換算に使うChArUco板だけをPNGに保存する."""

import cv2 as cv
from file_io import write_png
from workflow_settings import BOARD_SQUARES, MARKER_MM, OUTPUT_DIRECTORY, SQUARE_MM

PIXELS_PER_MM = 10
MARGIN_MM = 10


def main() -> None:
    dictionary = cv.aruco.getPredefinedDictionary(cv.aruco.DICT_4X4_50)
    board = cv.aruco.CharucoBoard(BOARD_SQUARES, SQUARE_MM, MARKER_MM, dictionary)
    board_width_mm = BOARD_SQUARES[0] * SQUARE_MM
    board_height_mm = BOARD_SQUARES[1] * SQUARE_MM
    board_width_px = int(board_width_mm * PIXELS_PER_MM)
    board_height_px = int(board_height_mm * PIXELS_PER_MM)
    board_image = board.generateImage((board_width_px, board_height_px))
    margin_px = int(MARGIN_MM * PIXELS_PER_MM)
    printable_image = cv.copyMakeBorder(
        board_image,
        margin_px,
        margin_px,
        margin_px,
        margin_px,
        cv.BORDER_CONSTANT,
        value=255,
    )

    output_path = OUTPUT_DIRECTORY / "charuco_board.png"
    write_png(output_path, printable_image)

    print(f"保存: {output_path}")
    print(
        f"黒白の板本体: {board_width_mm:g} × {board_height_mm:g}mm、1マス: {SQUARE_MM:g}mm"
    )
    print(
        f"PNG全体の印刷寸法: {board_width_mm + 2 * MARGIN_MM:g} × {board_height_mm + 2 * MARGIN_MM:g}mm"
    )
    print("印刷後に縦横・1マスの寸法を実測し、平らで硬い板へ貼ってください。")


if __name__ == "__main__":
    main()
