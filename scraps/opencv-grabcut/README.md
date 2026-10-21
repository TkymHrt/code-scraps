# opencv-grabcut

圧延パスごとのエッジクラック定量評価を目標に、画像の準備・補正から局所側辺の計測・記録・比較までを行うPoCです。
現在の計測対象は、試料の外周に現れるDR・OP側辺の形状です。クラックの本数や大きさを直接検出する段階とは区別します。

成果物は `src/` 内のスクリプト一式です。
[設定・実行順・GUI操作・検証記録](src/README.md) と、
[発表原稿・Excelでのグラフ作成手順](PRESENTATION.md) を参照してください。
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

比較GUIはCSV追加順の側辺長を表示します。パス0・2・4・…を横軸にした超過率グラフは、
[Excelでの集計手順](PRESENTATION.md) に従って作成します。

## 検証

今回の計測変更に関係するテストは、`tests/` から次のように実行します。

```powershell
uv run python -m unittest -v test_fixed_measurement_interval test_axis_measurement test_axis_measurement_csv test_refactored_measurement_gui test_reference_frame_rectification test_refactored_workflow.RefactoredWorkflowTests.test_polygon_measurement_csv_and_images_preserve_input_protection
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
