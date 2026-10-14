# 現行の実行順

2026-10-14整理。設定・入力・処理・保存を各ファイルに書いた、独立した5本です。
自作モジュールや一括実行スクリプトは使わず、画像とCSVで結果を渡します。

| 順 | スクリプト | 入力 → 出力 | 実行する時期 |
| --- | --- | --- | --- |
| 1 | [generate_charuco_board.py](generate_charuco_board.py) | 板の設定 → 印刷用PNG | 板を作るとき |
| 2 | [camera_calibration.py](camera_calibration.py) | 校正板の複数写真 → コピペするカメラ係数 | 撮影条件を決めたとき |
| 3 | [rectify_image.py](rectify_image.py) | 撮影画像 → 固定倍率の補正PNG | 各撮影 |
| 4 | [01_initial_regions_gui.py](01_initial_regions_gui.py) | 補正PNG・矩形・区間 → 長さCSV・確認PNG | 各撮影 |
| 5 | [length_comparison_gui.py](length_comparison_gui.py) | 複数の長さCSV・初期値・各回の厚さ → 比較CSV・グラフ | 撮影を比較するとき |

`opencv-grabcut` フォルダから実行します。各スクリプトの相対パスは、そのファイルがあるフォルダを基準にします。

```powershell
uv sync
uv run submissions/generate_charuco_board.py
uv run submissions/camera_calibration.py
uv run submissions/rectify_image.py
uv run submissions/01_initial_regions_gui.py
uv run submissions/length_comparison_gui.py
```

## 1. 板を作る

ChArUco板は横7・縦5マス、1マス30mm、マーカー18mm、辞書 `DICT_4X4_50` です。
`results/charuco_board.png` を保存します。板本体210×150mm、余白込み230×170mmです。

印刷時は自動縮小を避け、実物の1マスが30mmであることを測って確認します。
寸法を変える場合は、板生成・カメラ校正・画像補正の3本の設定を同じ仕様へ手で揃えます。

## 2. カメラ係数を求めて貼る

同じ撮影モード・画角・解像度で、板の位置・傾き・距離を変えた写真を10枚以上用意します。
既定の保存場所は `submissions/input/camera_calibration/` です。
板の角を縦横に6点以上読める写真を使います。

`camera_calibration.py` の表示から、次の3設定を `rectify_image.py` の冒頭へコピペします。

```python
CALIBRATION_SIZE = ...
CAMERA_MATRIX = ...
DIST_COEFFS = ...
```

設定ファイルの保存・自動読込はありません。
固定したカメラ・撮影条件で係数を使い続け、モード・画角・解像度・電子補正などを変えたら校正し直す運用です。
現在の係数は `None`。本番カメラの写真で求めるまで補正は実行できません。

## 3. 各写真を補正する

板を試料の計測面と同じ高さ・同じ平面に置き、**板の縦方向を圧延方向に揃えます**。
補正後のy方向は板の座標で決まります。板の位置は任意ですが、試料を隠さず、角を縦横に6点以上読めるようにします。

`rectify_image.py` の `INPUT_PATH` と `OUTPUT_IMAGE_PATH` を撮影ごとに変更して実行します。
固定係数でレンズ歪みを補正し、板から求める平面の遠近補正を行い、PNGを保存します。
板が読めない場合や補正の誤差・出力範囲が不適切な場合は保存を止めます。

補正画像は全撮影を `MM_PER_PX = 0.25`、つまり4px/mmへ揃えます。
01 GUIの冒頭にも**同じ `MM_PER_PX`** を置きます。
換算係数CSVや別のCSV換算スクリプトは使いません。
補正画像と倍率の対応、写真ごとの保存先は運用で確認します。

この平面補正では、試料の反りや板との高さの違いは補正できません。
通常のカメラモデルを使い、魚眼モデルの切り替えは実装していません。

## 4. 01 GUIで長さCSVを作る

上部から**補正済みPNG**を読み込み、左サイドバーと右の画像で操作します。
ファイル名とサイズだけを表示し、エラー・ステータスは読み込みボタンの右端へ表示します。

1. 前景候補の矩形で試料を囲む。板・床・黒い余白は候補の外へ置く。
2. 必要なら確実な背景・確実な前景を矩形で指定する。確実な前景には床を含めない。
3. 印などで対応を確認できる同じ材料区間の開始y・終了yを入力する。両端の行を含む。
4. 「長さを計測」で抽出し、赤い左右側辺と黄色の区間を確認する。
5. 「長さCSVを保存」と「確認画像を保存」で、その撮影の結果を保存する。

区間の全行に試料が必要です。試料がない行を指定した場合は、区間か初期指定を直します。
矩形・区間・画像を変えたら結果を無効にし、計測し直してからCSVを保存します。
確認画像は計測後なら側辺と区間、計測前なら初期指定を保存します。

GrabCut 5回・乱数シード0で抽出し、最大の外側輪郭を塗りつぶします。
各y行の最左・最右を隣接行へつないで長さを求め、上下辺は加えません。
側辺の凹凸と画素の段差も長さへ入るため、直線の区間長と同じ値になるとは限りません。

CSVはUTF-8 BOM付き、1画像1行です。

```text
image_path,image_width,image_height,mm_per_px,start_y,end_y,
left_px,left_mm,right_px,right_mm,total_px,total_mm
```

実際のヘッダーは1行です。左右と合計のpx・mm値を保存し、比較側が読み込みます。
GUIで未補正画像や違う倍率の画像を判定する仕組みはありません。読み込む画像を確認してください。

## 5. 複数撮影を長さで比較する

比較GUIへ初期区間長と初期厚さを入力し、01で作った長さCSVを複数追加します。
各行を選んで撮影名・撮影時の厚さを適用し、上から撮影順に並べて比較します。

幅方向の変化を無視し、幅一定・体積一定の基準スラブを使います。

```text
理想の片側長 = 初期区間長 × 初期厚さ ÷ 各回の厚さ
理想の左右合計 = 理想の片側長 × 2
```

実寸・理想との差・差率・前回との差を表で確認し、比較CSVと推移グラフを保存します。
比較時は画像を読み直さず、保存済みCSVだけで計算します。
各画像のy座標を揃える必要はありませんが、**対応する同じ材料区間**を計測してください。
左右側辺の凹凸を含む長さを、滑らかな理想区間長と比較する値です。

## 退避したコード

幅・基準線・凹み候補・エッジ表示、旧手動校正、設定コピー用GUI、旧CSV換算は
[sandbox/previous_submissions](../sandbox/previous_submissions/README.md) へ移動しました。
変更した3本の旧版と、板生成・カメラ校正の旧時点のコピーも、過去の検証を再現するため同じ場所へ保存しています。
題材直下の旧計測・比較7本は [sandbox/previous_scripts](../sandbox/previous_scripts/README.md) へ移動しました。
元の `submissions/input/`・`submissions/results/` と、過去の検証結果は移動していません。

## 検証

```powershell
uv run python -m unittest discover -s tests
uv run tests/verify_current_workflow.py --out tests/results/current_workflow_new
uv run ruff check .
uv run ruff format --check .
uv run ty check .
```

現行7件と旧版77件、合計84件を確認しています。
実Tkでの矩形操作・区間変更・保存・3撮影の比較は `verify_current_workflow.py` で確認します。
12枚の合成写真からカメラ係数を算出し、独立した補正スクリプトへ貼る工程も含みます。

2026-10-14、元の生成画像に仮の板を隣接させ、正対・遠近・レンズ歪みの3条件を確認しました。
正対の仮算出は左314.873mm、右323.533mm、合計638.406mmです。
結果は `tests/results/current_workflow_20261014_complete/` に保存しています。
板4px/mm・同一平面・カメラ係数・理想区間230mm・全撮影厚さ10mmは仮定です。
同じ生成試料の撮影条件を変えた確認で、圧延前後の実測ではありません。
実カメラの校正精度と、本番試料での抽出精度は未確認です。
