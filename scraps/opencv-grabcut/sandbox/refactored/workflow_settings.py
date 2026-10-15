"""工程間で揃える入出力先・板・倍率の設定。"""

from pathlib import Path

BASE_DIRECTORY = Path(__file__).resolve().parent
INPUT_DIRECTORY = BASE_DIRECTORY / "input"
OUTPUT_DIRECTORY = BASE_DIRECTORY / "output"
CALIBRATION_DIRECTORY = INPUT_DIRECTORY / "camera_calibration"
DETECTION_DIRECTORY = OUTPUT_DIRECTORY / "camera_detection"
RECTIFIED_DIRECTORY = OUTPUT_DIRECTORY / "rectified"

# 板の寸法を変えたら、印刷とカメラ校正もやり直す。
BOARD_SQUARES = (7, 5)
SQUARE_MM = 30.0
MARKER_MM = 18.0

# 画像補正と計測の倍率。変更後は補正画像も作り直す。
MM_PER_PX = 0.25
