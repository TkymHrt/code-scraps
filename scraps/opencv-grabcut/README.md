# opencv-grabcut

対応する同じ材料区間を複数撮影で計測し、撮影回ごとの長さの変化を比較します。
初期区間長・初期厚さと各回の厚さから、幅一定・体積一定の理想スラブを計算します。

実践用は `submissions/` の5本です。各ファイルに設定・入力・処理・保存を置き、
自作モジュールへ依存しない単発スクリプトを順番に使います。

| 順 | スクリプト | 役割 |
| --- | --- | --- |
| 1 | `generate_charuco_board.py` | ChArUco板のPNGを生成 |
| 2 | `camera_calibration.py` | 校正写真からカメラ係数を算出し、コピペ用に表示 |
| 3 | `rectify_image.py` | 指定フォルダを固定係数と板で一括補正し、PNGを出力 |
| 4 | `initial_regions_gui.py` | 初期指定・対応区間を操作し、長さCSVと確認画像を保存 |
| 5 | `length_comparison_gui.py` | 複数CSVと理想値を比較し、表・グラフ・CSVで確認 |

[実行順・設定・GUI操作・検証記録](submissions/README.md) に手順をまとめています。
板生成とカメラ校正は初回、画像補正と計測GUIは撮影ごと、比較は複数撮影のCSVを使います。
補正画像は固定のmm/pxへ揃え、同じ値を計測GUIのコード冒頭にも設定します。
カメラ係数はコードへ貼り付け、各工程を個別に実行します。

Python 3.14以降、NumPy、OpenCV、Matplotlib、GUIにはTkinterを使います。
依存関係はこのフォルダの `pyproject.toml` と `uv.lock` で管理します。

```powershell
# このフォルダから実行
uv sync
uv run submissions/generate_charuco_board.py
uv run submissions/camera_calibration.py
uv run submissions/rectify_image.py
uv run submissions/initial_regions_gui.py
uv run submissions/length_comparison_gui.py
```

カメラ係数は現在未設定です。本番カメラで校正してから補正コードへ貼り付けます。
`submissions/input/` の画像はテスト用の生成画像で、本番画像ではありません。

以前の輪郭・端線・幅・凹み候補・旧校正方式は `sandbox/` 側へ退避しました。
[旧提出版](sandbox/previous_submissions/README.md)、
[旧実践版](sandbox/previous_scripts/README.md)、
[試作・前処理比較](sandbox/README.md) を参照してください。
現行の標準出力先は `submissions/output/` です。補正画像は `output/rectified/`、計測CSV・比較結果・板のPNGは `output/` に保存します。過去の結果は従来の場所へ保管しています。

現在の実装範囲は [PLAN.md](PLAN.md)、作業履歴は [PROGRESS.md](PROGRESS.md)、
撮影条件は [CAPTURE.md](CAPTURE.md) にあります。

```powershell
uv run python -m unittest discover -s tests
uv run tests/verify_current_workflow.py --out tests/results/current_workflow_new
uv run ruff check .
uv run ruff format --check .
uv run ty check .
```

現行10件と旧版77件、合計87件の自動試験、生成画像を使った実Tk操作と複数CSV比較を確認しています。
実カメラの歪み補正精度、本番画像での抽出精度は未確認です。
