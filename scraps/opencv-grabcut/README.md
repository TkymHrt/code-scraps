# opencv-grabcut

床置きで撮影した局所画像から左右側辺長を測り、各パスで採取した区間の形状の違いを見るPoCです。
確認画像と長さのグラフを見比べ、凹凸の違いが数値にも現れるかを試します。
比較する区間長を揃えるか、100mmあたりの側辺長へ換算します。同じ材料区間の追跡は必須にしません。

## PoCに使う6本

実行用は `submissions/` にある次の6本です。`00_1`・`00_2` は初回準備、`01`～`03` は撮影後の処理です。
比較の `03` は厚さの有無に合わせて選びます。
各ファイルに設定・入力・処理・保存を置き、自作モジュールへ依存しない単発スクリプトとして使います。

| 番号 | スクリプト | 役割 |
| --- | --- | --- |
| 00_1 | `00_1_generate_charuco_board.py` | 印刷するChArUco板のPNGを作る |
| 00_2 | `00_2_calibrate_camera.py` | 校正写真から魚眼カメラ係数を求め、読取確認PNGとコピペ用の係数を出す |
| 01 | `01_rectify_images.py` | 写真内の向きを保ち、固定mm/pxの補正PNGへ揃える |
| 02 | `02_measure_edge_lengths_gui.py` | 矩形と計測区間を指定し、左右側辺長のCSVと確認PNGを保存する |
| 03 | `03_compare_edge_lengths_gui.py` | 計測CSVから左右の実測長・100mm換算と基準線を比較する |
| 03（厚さあり） | `03_compare_edge_lengths_with_thickness_gui.py` | 同じ計測CSVと実測厚さから、撮影順／累積圧下率で比較する |

板作成とカメラ校正は撮影条件を決めたとき、補正と計測は各撮影、比較は複数撮影のCSVで行います。
`00_*` は毎回の実行は不要ですが、板の仕様や撮影モード・画角・解像度を変えた場合は準備し直します。
[設定・実行順・GUI操作](submissions/README.md) と [撮影手順](CAPTURE.md) を参照してください。

共通設定・画像入出力・CSV受渡し・GUIの枠を整理した比較用の版は
[sandbox/refactored](sandbox/refactored/README.md) にあります。
6本の役割と機能を保ち、GUIを計測版の配置へ揃えています。提出版を変更せずに、読み方と共通化の効果を比較できます。
固定カメラの動画から切り出したフレームには、同じフォルダの
[基準画像からの一括補正](sandbox/refactored/README.md#固定カメラの動画フレームを補正する)を使えます。
動作前のボード画像で補正を求め、ボードのない動作中フレームへ適用します。

## 実行する

Python 3.14以降、NumPy、OpenCV 5以降、Matplotlib、Tkinterを使います。
依存関係はこのフォルダの `pyproject.toml` と `uv.lock` で管理します。

```powershell
# opencv-grabcutフォルダから実行
uv sync
uv run submissions/00_1_generate_charuco_board.py
uv run submissions/00_2_calibrate_camera.py
uv run submissions/01_rectify_images.py
uv run submissions/02_measure_edge_lengths_gui.py
uv run submissions/03_compare_edge_lengths_gui.py
# 厚さとの関係も見る場合は、比較をこちらで行う
uv run submissions/03_compare_edge_lengths_with_thickness_gui.py
```

カメラ係数は現在未設定です。本番カメラで校正し、表示された3設定を補正コードへ貼り付けます。
撮影モード・画角・解像度を揃え、魚眼モデルの係数4個を使います。
板を試料の計測面と同じ高さに置き、試料の長手を画像の縦方向へ揃え、区間内の左右両側辺を写します。
補正と計測GUIの `MM_PER_PX` は同じ値にします。現在は `0.25` です。

標準出力先は `submissions/output/`、補正画像はその中の `rectified/` です。
計測CSVは1回につき1行です。CSV保存時に、同じ名前の計測結果PNGと、名前に `_initial` を付けた初期指定PNGも保存します。
区間長は比較側で `(end_y − start_y) × mm_per_px` として求めます。
比較GUIはCSVの追加・削除に合わせて自動更新し、厚さ版では厚さの入力も即時反映します。
点はCSV追加順に線で結び、表示中のグラフをPNGで保存します。比較CSVは出力しません。
同じパスの複数箇所は `p01_a`・`p01_b` などで区別します。
厚さの入力値は終了時に保存されないため、撮影記録にも残してください。

## 保管先

今回使わない理想長との比較・分析・GUIなし版の5本と説明は
[sandbox/previous_submissions/comparison_variants](sandbox/previous_submissions/comparison_variants/README.md) へ移動しました。
それ以前のコードは [旧提出版](sandbox/previous_submissions/README.md)、
[旧実践版](sandbox/previous_scripts/README.md)、[試作・前処理比較](sandbox/README.md) に保管しています。
入力・出力・過去の検証結果の場所は維持しています。

## 検証

```powershell
uv run python -m unittest discover -s tests
uv run tests/verify_current_workflow.py --out tests/results/poc_workflow_new
uv run tests/verify_length_comparison_local_gui.py --out tests/results/local_comparison_new
uv run tests/verify_length_comparison_thickness_gui.py --out tests/results/thickness_comparison_new
uv run ruff check .
uv run ruff format --check .
uv run ty check .
```

操作検証の保存先には `tests/results/` 内のまだ存在しないフォルダを指定します。
合成写真・生成画像・数値CSVで校正から計測・比較まで確認します。保管版の試験も移動先を参照します。
2026-10-16の整理後に全118件と、実Tkでの計測・局所比較・厚さ比較、Ruff・format・tyを確認しました。
`submissions/input/` は生成したテスト画像で、本番画像ではありません。
実カメラでの校正と、本番画像での寸法・抽出精度は未確認です。初回撮影で既知寸法と撮り直しを確認します。
現在の範囲は [PLAN.md](PLAN.md)、検証記録・作業履歴は [PROGRESS.md](PROGRESS.md) にあります。
