# opencv-grabcut

対応する同じ材料区間を複数撮影で計測し、撮影回ごとの長さの変化を比較します。
初期区間長・初期厚さと各回の厚さから、幅一定・体積一定の理想スラブを計算します。

基本の実行順は `submissions/` の5本です。各ファイルに設定・入力・処理・保存を置き、
自作モジュールへ依存しない単発スクリプトを順番に使います。

| 順 | スクリプト | 役割 |
| --- | --- | --- |
| 1 | `generate_charuco_board.py` | ChArUco板のPNGを生成 |
| 2 | `camera_calibration.py` | 写真ごとの読取確認PNGを保存し、カメラ係数をコピペ用に表示 |
| 3 | `rectify_image.py` | 指定フォルダを固定係数と板で一括補正し、写真内の向きを保った補正PNGを出力 |
| 4 | `initial_regions_gui.py` | 初期指定・対応区間を操作し、長さCSVと確認画像を保存 |
| 5 | `length_comparison_gui.py` | 複数CSVと理想値を比較し、表・グラフ・CSVで確認 |

長さ分析の別案として `submissions/length_analysis_gui.py` も使えます。
同じ長さCSVから区間の伸びと左右側辺の形状を分け、数値表・推移・直前パスからの変化を一画面に表示します。
[操作と指標の定義](submissions/README.md#長さ分析の別案伸びと側辺形状を分ける) を参照してください。

最小比較には `submissions/length_comparison_simple_gui.py` を使えます。
初期区間長・初期厚さと各撮影の厚さから求めた理想片側長を、CSVの左右側辺長と数値表・1枚の推移グラフで比較します。
[最小比較GUIの操作](submissions/README.md#最小比較gui厚さから理想長を計算) を参照してください。

[実行順・設定・GUI操作・検証記録](submissions/README.md) に手順をまとめています。
板生成とカメラ校正は初回、画像補正と計測GUIは撮影ごと、比較は複数撮影のCSVを使います。
補正画像は固定のmm/pxへ揃え、同じ値を計測GUIのコード冒頭にも設定します。
カメラ係数はコードへ貼り付け、各工程を個別に実行します。
撮影は魚眼レンズを前提にし、校正・レンズ歪み補正にはOpenCVの魚眼モデルを使います。
歪み係数は `k1, k2, k3, k4` の4個です。通常モデルで求めた係数は使わず、校正し直します。

Python 3.14以降、NumPy、OpenCV 5以降、Matplotlib、GUIにはTkinterを使います。
依存関係はこのフォルダの `pyproject.toml` と `uv.lock` で管理します。

```powershell
# このフォルダから実行
uv sync
uv run submissions/generate_charuco_board.py
uv run submissions/camera_calibration.py
uv run submissions/rectify_image.py
uv run submissions/initial_regions_gui.py
uv run submissions/length_comparison_gui.py
# 長さ分析の別案
uv run submissions/length_analysis_gui.py
# 厚さから理想長を求める最小比較
uv run submissions/length_comparison_simple_gui.py
```

カメラ係数は現在未設定です。本番カメラで校正してから補正コードへ貼り付けます。
`submissions/input/` の画像はテスト用の生成画像で、本番画像ではありません。

以前の輪郭・端線・幅・凹み候補・旧校正方式は `sandbox/` 側へ退避しました。
[旧提出版](sandbox/previous_submissions/README.md)、
[旧実践版](sandbox/previous_scripts/README.md)、
[試作・前処理比較](sandbox/README.md) を参照してください。
現行の標準出力先は `submissions/output/` です。補正画像は `output/rectified/`、計測CSV・比較結果・板のPNGは `output/` に保存します。過去の結果は従来の場所へ保管しています。
読取確認画像はカメラ校正時に `output/camera_detection/` へ保存します。
`rectify_image.py` は補正PNGだけを保存し、写真で見えていた板の横軸の向きを保ちます。
計測する試料の長手方向は撮影時に縦へ揃えます。エラーで止まったら入力を直して再実行し、前回の出力との対応は運用で確認します。

現在の実装範囲は [PLAN.md](PLAN.md)、作業履歴は [PROGRESS.md](PROGRESS.md)、
撮影条件は [CAPTURE.md](CAPTURE.md) にあります。

```powershell
uv run python -m unittest discover -s tests
uv run tests/verify_current_workflow.py --out tests/results/current_workflow_new
uv run ruff check .
uv run ruff format --check .
uv run ty check .
```

読取確認PNGの追加時点では、現行工程12件・旧版77件・分析GUI6件・最小比較GUI4件、合計99件の自動試験を確認しています。
魚眼の合成写真12枚による校正・補正と、生成画像を使った実Tk操作・複数CSV比較も確認しています。
読取確認PNGの描画、NG画像の保存、失敗時の停止と入力修正後の再実行も確認しています。
その後の校正条件エラーへの対応では、停止した写真の名前・確認PNGの場所を出す処理を加え、関連13件とRuff・tyを確認しています。
補正側の確認PNG削除と向き保持への変更では、回転した板の5条件を含む関連14件とRuff・format・ty、生成画像での実Tkの計測・保存・比較を確認しました。
新規分析GUIは既知の数値CSVで、入力・再分析・保存と20パス表示も確認しています。
最小比較GUIは、追加の4件の自動試験と実Tkでの厚さ入力・再比較・保存・削除・20撮影表示を確認しています。
実カメラの歪み補正精度、本番画像での抽出精度は未確認です。
