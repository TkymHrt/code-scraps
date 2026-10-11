# opencv-grabcut

試料の抽出・輪郭確認・左右側辺の計測を、実践用と比較試験用に分けています。

| フォルダ | 用途 | 手順 |
| --- | --- | --- |
| `practical/` | ex03〜05をフル解像度・同一抽出条件で使う | [実践用ガイド](practical/GUIDE.md) |
| `experiments/` | 旧縮小版、マスク調整、AI画像での反射除去を比較する | [比較試験の一覧](experiments/README.md) |

```text
opencv-grabcut/
├─ practical/
│  ├─ ex03_outline.py         外側の輪郭
│  ├─ ex04_side_edges.py      左右の端
│  ├─ ex05_side_lengths.py    左右側辺の長さ、画像・CSV
│  ├─ GUIDE.md
│  └─ results/                実画像での結果（実行時に作成）
├─ experiments/
│  ├─ ex03〜ex10              旧方式と独立した比較試験
│  ├─ input_ai.png            添付されたAI生成画像
│  ├─ input.png               旧検証画像（ローカルに保存）
│  ├─ results/                比較試験の結果
│  ├─ reference/              以前の半分縮小の計測CSV
│  ├─ tests/                  実践版の計測と条件を確認する自動試験
│  ├─ README.md
│  └─ GUIDE.md
├─ pyproject.toml
└─ uv.lock
```

## 実践用を動かす

このフォルダで `uv sync` を実行し、使いたい画像を `practical/input.png` に置きます。
使うスクリプトの冒頭で、入力・保存先・初期指定を調整してから実行してください。

```sh
uv run practical/ex03_outline.py
uv run practical/ex04_side_edges.py
uv run practical/ex05_side_lengths.py
```

3本とも縮小倍率1.0、同じ初期指定・GrabCut反復回数・乱数シードで抽出します。
元のex04・ex05にあった半分縮小とマスク拡大は、比較試験側に残しています。
実践版では結果画像、初期指定画像、マスク、実行条件JSONを保存し、ex05は長さのCSVも保存します。
初期値は元ex03の設定です。試料の幅・位置・背景に合わせて変更が必要です。
設定と読み込み・抽出・描画・保存の処理を、各スクリプト内にすべて書いています。
処理を上から順に読める構成で、段階ごとに短いコメントを付けています。
比較時は3本の設定値を揃えてください。独自のエラーチェックは画像の読み込みと領域未検出だけです。

試料と圧延回数ごとに保存先を分ける場合は、冒頭の設定を書き換えます。
相対パスはスクリプトのフォルダが基準です。

```python
INPUT_PATH = "../images/sample_A_pass00.png"
OUTPUT_DIRECTORY = "results/sample_A/pass00"
```

AI画像で実践コードを動かす場合も、試験結果を `experiments/` 側に保存できます。

```python
INPUT_PATH = "../experiments/input_ai.png"
OUTPUT_DIRECTORY = "../experiments/results/practical_fullsize"
```

## 比較試験を動かす

```sh
uv run experiments/ex06_mask.py
uv run experiments/ex07_baseline.py
uv run experiments/ex08_seeded_mask.py
uv run experiments/ex09_vertical_open.py
uv run experiments/ex10_reflection_refine.py
```

試験用コードはそれぞれ単独で動き、入力は `experiments/`、出力は `experiments/results/` が基準です。
AI生成画像での動作確認は、実画像での抽出精度を保証するものではありません。

## チェック

```sh
uv run ruff check .
uv run ruff format --check .
uv run ty check .
uv run python -m unittest discover -s experiments/tests
```

Python 3.14以降、NumPy、OpenCVを使います。環境と依存はルートの `pyproject.toml` と `uv.lock` で管理します。

2026-10-11に実践用3本と比較試験用8本を実行し、実践用の3本のマスクと保存条件が一致することを確認しました。
スクリプト1本だけでの実行、上下辺を含めない計測、斜めの距離、細い突起の保持、
CSVとの一致、画像を読めない場合のエラーなど5件の自動試験と、
ruffのlint・format、tyの型チェックも通過しています。
