# opencv-grabcut

試料を抽出し、輪郭・左右側辺の長さ・幅を確認するスクリプトです。
作成日：2026-10-08。依存関係はこのフォルダの `pyproject.toml` と `uv.lock` で管理します。

金属圧延の左右端クラックをパスごとに評価することを目指し、まず静止画像の輪郭抽出と形状の定量化から進めます。
撮影条件は単純背景、停止中のローラー上、稼働中の録画フレームの順で検証します。
形状指標と欠陥の個数・大きさの評価は段階を分け、人の初期指定あり・追加指定なしの成果も分けて確認します。

実際に使うコードはこのフォルダの直下、抽出方法の試作は `sandbox/`、自動検証は `tests/` にあります。

現在の成果・確認した要件と、静止画のパス間比較から録画処理・位置追跡・リアルタイム解析までの工程は
[PROGRESS.md](PROGRESS.md) にまとめています。
短いコードで段階ごとに提出する版は [submissions/README.md](submissions/README.md) にあります。
01の別バージョンとして、初期指定を画像上で作成・確認するGUIも、同じREADMEに操作手順をまとめています。
実画像の撮影条件、GoProの設定、画像ごとの調整・実行手順は [CAPTURE.md](CAPTURE.md) にまとめています。

| スクリプト | 用途 |
| --- | --- |
| `outline.py` | 元の解像度で外側の輪郭を描く |
| `side_edges.py` | 元の解像度で左右の端を描く |
| `side_lengths.py` | 左右側辺の長さを画像・CSVに保存する |
| `measure_batch.py` | 複数画像を同じ条件で計測する |
| `compare_lengths.py` | 計測済みの長さを基準と比較する |
| `compare_sampling.py` | 点を拾う間隔に対する長さの変化を比較する |
| `compare_widths.py` | 相対高さを揃えて幅を比較する |

各ファイルに設定から保存までを書き、1本を別フォルダへコピーしても実行できます。
詳しい設定は [GUIDE.md](GUIDE.md)、複数画像の計測・比較は [BATCH.md](BATCH.md) を参照してください。

## 動かす

Python 3.14以降、NumPy、OpenCVを使います。**このフォルダから**実行します。

```powershell
uv sync
uv run outline.py
uv run side_edges.py
uv run side_lengths.py
```

画像を `input.png` に置き、使うスクリプトの冒頭で入力・保存先・初期指定を調整します。
相対パスはスクリプトがあるフォルダが基準です。
輪郭・左右端・長さの3本は、同じ初期指定・反復回数・乱数シードで、縮小せずに抽出します。
比較する場合は変更後も設定を揃えてください。

結果は `results/` に保存します。出力名は `result_03`（輪郭）、`result_04`（左右端）、`result_05`（長さ）です。
初期指定画像・マスク・実行条件JSONも保存します。まず画像を確認してから計測値を使ってください。

一括計測では [samples.example.csv](samples.example.csv) を `samples.csv` にコピーして入力を指定します。
同じ `results/` に長さ一覧と点列を保存し、比較の3本が読み込みます。手順は [BATCH.md](BATCH.md) にあります。

## 試作・検証

旧縮小版や反射除去の試作は [sandbox/README.md](sandbox/README.md) にまとめています。

```powershell
uv run sandbox/ex06_mask.py
uv run sandbox/ex07_baseline.py
uv run sandbox/ex08_seeded_mask.py
uv run sandbox/ex09_vertical_open.py
uv run sandbox/ex10_reflection_refine.py
uv run sandbox/verify_quantitative.py
```

試作の入力は `sandbox/`、出力は `sandbox/results/` が基準です。
AI画像や合成画像の確認は、実試料での抽出精度を保証するものではありません。

```powershell
uv run python -m unittest discover -s tests
uv run tests/verify_stages.py --with-local-inputs --out tests/results/stages_new
uv run ruff check .
uv run ruff format --check .
uv run ty check .
```

自動試験は、独立実行、3本の抽出条件とマスクの一致、上下辺を含めない長さ、
細い突起の保持、基準・左右差・mm換算・測定間隔・幅の補間など13件です。
加えて、提出版の初期指定の一致・GrabCut直後のマスク・左右端の座標と表示・側辺長・計測範囲を確認する9件があります。
GUIの確認画像と01の一致、コピーした初期指定と02の入力の一致など3件を加え、合計25件です。
GUIの縮小表示上のドラッグ・保存などは `uv run tests/verify_mask_gui.py` で確認できます（Tkを起動できる環境で実行）。
Ruffは構文・未使用名・インポート順だけをチェックします。
計測条件は実画像に合わせて設定し、入力・保存先と生成物の更新を運用で確認します。

2026-10-12の配置変更後に、自動試験、Lint・format、型チェックと合成画像の定量比較を再確認しました。
実試料での抽出精度は、この検証の対象に含みません。
