# opencv-grabcut

圧延パスごとのエッジクラック定量評価を目標に、画像の準備・補正から局所側辺の計測・記録・比較までを行うPoCです。
現在の計測対象は、試料の外周に現れるDR・OP側辺の形状です。クラックの本数や大きさを直接検出する段階とは区別します。

成果物は `src/` 内のスクリプト一式です。
[設定・実行順・GUI操作・検証記録](src/README.md) と、
[発表原稿・PythonとExcelでのグラフ作成手順](PRESENTATION.md) を参照してください。
撮影の準備は [撮影手順](sandbox/CAPTURE.md) にあります。

## スクリプトの役割

| スクリプト | 役割 |
| --- | --- |
| `00_1_generate_charuco_board.py` | 印刷するChArUco板のPNGを作る |
| `00_2_calibrate_camera.py` | 校正写真から魚眼カメラ係数と読取確認PNGを出す |
| `video_frame_gui.py` | 動画から選んだフレームを元解像度のPNGで保存する |
| `01_rectify_images.py` | 画像ごとにレンズ歪み・遠近を補正し、一定のmm/pxへ揃える |
| `01_rectify_frames_from_reference.py` | 固定カメラの基準画像から求めた補正を、ボードなしフレームへ適用する |
| `measure_point_distance_gui.py` | 補正画像上の2点間距離をmmで確認する |
| `02_measure_edge_lengths_gui.py` | 多角形で試料を抽出し、長手軸に直角な固定長区間の側辺長・超過率をCSVと確認PNGへ保存する |
| `03_compare_edge_lengths_gui.py` | 計測CSVからDR・OPの実測長・100mm換算を比較する |
| `03_compare_edge_lengths_with_thickness_gui.py` | 実測厚さを加え、撮影順／累積圧下率で側辺長を比較する |
| `04_plot_pass_metrics.py` | 計測CSVから、パス別の超過率・初回差・DR−OP差を各区間の点と平均・SDで3枚のPNGに保存する |
| `05_plot_experiment_comparison.py` | DR／OPを左右のパネルに分け、実験回を色・記号・線種で区別して3指標を比較する |

入出力先・倍率は `src/workflow_settings.py`、画像入出力・CSV・比較・GUIの共通処理は `src/utils/` にあります。
別の場所へ持ち出す場合は、実行するスクリプトと共通設定、`utils/` を一緒にコピーします。
画像補正の2本と比較GUIの2本は、それぞれ用途に応じて選びます。

## 実行する

Python 3.14以降、NumPy、OpenCV 5以降、Matplotlib、Tkinterを使います。
依存関係はこのフォルダの `pyproject.toml` と `uv.lock` で管理します。

```powershell
# opencv-grabcutフォルダから実行
uv sync
uv run src/00_1_generate_charuco_board.py
uv run src/00_2_calibrate_camera.py
uv run src/01_rectify_images.py
uv run src/02_measure_edge_lengths_gui.py
uv run src/03_compare_edge_lengths_gui.py
# 厚さとの関係も見る場合は、比較をこちらで行う
uv run src/03_compare_edge_lengths_with_thickness_gui.py
```

カメラ係数は現在未設定です。本番カメラで校正し、表示された設定を補正コードへ貼り付けます。
撮影モード・画角・解像度を揃え、板は試料の計測面と同じ高さに置きます。
倍率 `MM_PER_PX` の現在値は `0.25` です。倍率を変える場合は、補正画像も作り直します。
標準の入力先は `src/input/`、出力先は `src/output/`、補正画像はその中の `rectified/` です。

計測は、多角形指定→基準区間長と中心指定→試料抽出・自動軸→必要なら手動軸→計測→保存の順です。
比較する全パスで基準区間長・倍率・評価間隔・平滑化幅を揃えます。
1回の保存で1行のCSV、初期指定PNG、計測結果PNGを残します。
超過率は `(側辺長 / 基準区間長 - 1) * 100` で求めます。
比較・作図は現行の `02` が保存するCSVだけを対象にし、旧形式の読込・読み替えは行いません。

比較GUIはCSV追加順の側辺長を表示します。パス0・2・4・…を横軸にした3図は、`04` の冒頭を編集して一括作成できます。

```powershell
# 04のMEASUREMENTS（実験回・パス・区間ID・計測CSV）とGRAPH_DIRECTORYを編集してから実行
uv run src/04_plot_pass_metrics.py
```

測定値の転記や別の対応表CSVは不要です。計測CSVの相対パスは `src/` が基準です。
同じ画像の複数区間は、それぞれ別名のCSVへ保存し、区間IDを `a`・`b` などに分けて指定します。
図には各区間の点、実験回・パスごとの平均と区間間の標本SDを表示します。1区間の場合はSDを表示しません。
補助線なし・内向き目盛りの体裁で、各図を600dpiのPNGへ保存します。題目と説明は原稿側で図の下に記載し、計測条件・区間数も必要に応じて添えます。
[Pythonの詳しい使い方](src/README.md#スクリプト内の設定から3種類のグラフを一括作成する) と [Excelでの集計手順](PRESENTATION.md) を参照してください。

異なる実験回を並べて比較する場合は、追加の `05_plot_experiment_comparison.py` を使います。既存の `04` はそのまま使えます。
`05` 冒頭の `MEASUREMENTS` に比較する各回のCSVを指定し、`uv run src/05_plot_experiment_comparison.py` で実行します。
既定の保存先は `src/output/experiment_comparison/` で、`04` の出力先とは別です。
超過率と初回差はDR／OPの2パネル、DR−OP差は1パネルで、実験回同士を平均せずに表示します。
[実験回比較版の設定と使い方](src/README.md#異なる実験回を並べて比較する) を参照してください。

## 検証

今回の計測変更に関係するテストは、`tests/` から次のように実行します。

```powershell
uv run python -m unittest -v test_fixed_measurement_interval test_axis_measurement test_axis_measurement_csv test_refactored_measurement_gui test_reference_frame_rectification test_refactored_workflow.RefactoredWorkflowTests.test_polygon_measurement_csv_and_images_preserve_input_protection
# 作図とCSV読込の確認
uv run python -m unittest -v test_experiment_comparison test_pass_metrics test_axis_measurement_csv
```

一連の操作検証は題材フォルダから実行します。保存先には、まだ存在しないフォルダを指定します。

```powershell
uv run tests/verify_refactored_workflow.py --out tests/results/axis_workflow_new --no-screenshots
```

既知の直線・凹凸形状と合成画像で、傾きへの安定性、固定区間長、校正から補正・計測・比較までの動作を確認しています。
関連53件の結果と詳細は [srcの検証記録](src/README.md#検証) にあります。
旧版との比較を含む全試験には、移動前の `submissions/` 参照が残っています。全試験成功とは区別します。
実カメラの校正、本番の圧延画像での寸法・抽出精度、測定者間の再現性、最適な計測条件は未検証です。
`sandbox/submissions/input/` の素材は生成したテスト画像で、本番画像ではありません。

## 保管先

矩形・水平区間で測る旧版は [sandbox/submissions](sandbox/submissions/README.md) に保管しています。
さらに前の版は [旧提出版](sandbox/previous_submissions/README.md)、
[旧実践版](sandbox/previous_scripts/README.md)、[試作・前処理比較](sandbox/README.md) にあります。
以前の計画・経緯は [PLAN.md](sandbox/PLAN.md) と [PROGRESS.md](sandbox/PROGRESS.md) に残しています。
