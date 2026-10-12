# opencv-grabcut

試料の抽出・輪郭確認・左右側辺の計測を、実践用と比較試験用に分けています。
作成日：2026-10-08。依存関係はこのフォルダの `pyproject.toml` と `uv.lock` で管理します。

| フォルダ | 用途 | 手順 |
| --- | --- | --- |
| `practical/` | 元の解像度で抽出し、輪郭・側辺・長さを確認する | [実践用ガイド](practical/GUIDE.md) |
| `practical/quantitative/` | 一括計測、基準との差分、測定間隔への感度、幅の比較 | [定量比較の手順](practical/quantitative/README.md) |
| `experiments/` | 旧縮小版、マスク調整、AI画像による反射除去の比較 | [比較試験の一覧](experiments/README.md) |
| `tests/` | 独立実行・既知の形状・CSVの計算結果を確認する | 下の「チェック」 |

```text
opencv-grabcut/
  practical/
    outline.py                 外側の輪郭
    side_edges.py              左右の端
    side_lengths.py            左右側辺の長さ、画像・CSV
    GUIDE.md
    quantitative/              一括計測と3種類の比較
    input.png / results/       実画像と結果（Git管理対象外）
  experiments/
    ex03〜ex10                  旧方式と独立した比較試験
    verify_quantitative.py     合成画像で定量比較を実行
    input_ai.png               AI生成の確認用画像
    reference/                 以前の半分縮小の計測CSV
    README.md / GUIDE.md
    input.png / results/       ローカルの旧入力と比較結果
  tests/
    test_practical.py
    test_quantitative.py
  pyproject.toml / uv.lock
```

## 実践用を動かす

Python 3.14以降、NumPy、OpenCVを使います。**このフォルダから**実行します。

```powershell
uv sync
uv run practical/outline.py
uv run practical/side_edges.py
uv run practical/side_lengths.py
```

画像を `practical/input.png` に置き、使うスクリプトの冒頭で入力・保存先・初期指定を調整します。
相対パスはスクリプトがあるフォルダが基準です。
3本とも同じ初期指定・GrabCut反復回数・乱数シードで、縮小せずに抽出します。
比較する場合は変更後も設定を揃えてください。

各ファイルに設定から保存までを書き、1本を別フォルダへコピーしても実行できます。
出力は従来どおり `result_03`（輪郭）、`result_04`（左右端）、`result_05`（長さ）を使います。
初期指定画像・マスク・実行条件JSONも保存します。まず画像を確認してから計測値を使ってください。

複数画像を計測する場合は [quantitative/の手順](practical/quantitative/README.md) に従います。
1本で一括計測し、残り3本は保存済みCSVを読み、それぞれの比較と保存を完結させます。

## 比較試験を動かす

```powershell
uv run experiments/ex06_mask.py
uv run experiments/ex07_baseline.py
uv run experiments/ex08_seeded_mask.py
uv run experiments/ex09_vertical_open.py
uv run experiments/ex10_reflection_refine.py
uv run experiments/verify_quantitative.py
```

試験用の入力は `experiments/`、出力は `experiments/results/` が基準です。
AI画像や合成画像の確認は、実試料での抽出精度を保証するものではありません。

## チェック

```powershell
uv run python -m unittest discover -s tests
uv run ruff check .
uv run ruff format --check .
uv run ty check .
```

自動試験は、1本だけでの実行、3本の抽出条件とマスクの一致、上下辺を含めない長さ、
細い突起の保持、基準・左右差・mm換算・測定間隔・幅の補間など13件です。
Ruffは構文・未使用名・インポート順だけをチェックします。
計測条件は実画像に合わせて設定し、入力・保存先と生成物の更新を運用で確認します。

2026-10-12の構成変更後に上記の自動試験、Lint・format、型チェックと合成画像の定量比較を再確認しました。
実試料での抽出精度は、この検証の対象に含みません。
