# 比較試験用

旧方式、AI生成画像の反射対策、前処理の比較を行う独立スクリプトをまとめています。
実践用は [../GUIDE.md](../GUIDE.md) を使ってください。

| ファイル | 比較する内容 | 入力 |
| --- | --- | --- |
| `ex03_outline.py` | 元のフル解像度の外側輪郭 | `input.png` |
| `ex04_side_edges.py` | 元の半分縮小による左右端 | `input.png` |
| `ex05_side_lengths.py` | 元の半分縮小による長さ計測 | `input.png` |
| `ex06_mask.py` | 探索範囲と縮小倍率を変更するマスク試験 | `input.png` |
| `ex07_baseline.py` | AI画像で元方式の初期指定を再現 | `input_ai.png` |
| `ex08_seeded_mask.py` | 小さな前景とローラー背景の指定 | `input_ai.png` |
| `ex09_vertical_open.py` | 縦オープニングの追加 | `input_ai.png` |
| `ex10_reflection_refine.py` | 反射候補付近だけの再判定 | `input_ai.png` |
| [preprocess_comparison.py](preprocess_comparison.py) | 前処理の単独・組み合わせによる抽出と側辺長の比較 | `../submissions/input/` の画像 |

入力はこのフォルダ基準、出力は `results/` に保存します。
`input_ai.png` はユーザーが用意したAI生成画像です。
旧入力の `input.png` と既存の結果画像もこのフォルダへ移しました。
旧入力と生成された結果はGit管理対象外です。
以前の計測CSVは `reference/result_05_halfsize.csv` に保存しています。

`opencv-grabcut` フォルダから実行します。

```sh
uv run sandbox/ex06_mask.py
uv run sandbox/ex07_baseline.py
uv run sandbox/ex08_seeded_mask.py
uv run sandbox/ex09_vertical_open.py
uv run sandbox/ex10_reflection_refine.py
```

各コードの先頭で入力や初期指定などを変更できます。
ex07〜ex10は共通のフル解像度・初回GrabCut 5回・乱数シード0で比較します。
他のスクリプトやその結果を読み込まず、それぞれ単独で実行できます。
同じ出力名で実行すると結果を上書きするので、比較を残す場合は `OUTPUT_PREFIX` を変えてください。

処理の詳しい説明、確認画像の読み方、反射除去の調整手順は [GUIDE.md](GUIDE.md) にあります。
ローラーの反射除去を実践版に採用する前に、本物の突起も消えていないか確認してください。

## 前処理の比較

[preprocess_comparison.py](preprocess_comparison.py) は元画像から単独で動き、04と同じ方法で左右側辺長を測ります。
入力・矩形・反復回数・乱数シード・計測範囲は全ケースで同じにします。
04と比較するときは、これらの設定を04と比較用スクリプトで揃えてください。
入力は既定で `../submissions/input/` の画像を使い、結果はこのフォルダの `results/preprocess_comparison/` に保存します。
確実な前景の矩形には、試料外の床や影を含めないようにします。

```powershell
uv run sandbox/preprocess_comparison.py
```

冒頭の `CASES` に試す処理を書きます。タプルの左から順に適用し、組み合わせや順序違いを試せます。
無処理の基準となる `"original": ()` は残します。ケース名は保存先のフォルダ名にもなるため、フォルダ名1つで指定します。

```python
CASES = {
    "original": (),
    "blur": ("blur",),
    "clahe": ("clahe",),
    "gamma": ("gamma",),
    "sharp": ("sharp",),
    "blur_clahe": ("blur", "clahe"),
    "clahe_blur": ("clahe", "blur"),
}
```

| 処理名 | 処理と冒頭の設定 |
| --- | --- |
| `blur` | Gaussian blur。`BLUR_SIZE` は正の奇数の窓サイズ |
| `clahe` | Labの明るさ成分にCLAHE。`CLAHE_CLIP_LIMIT`・`CLAHE_GRID_SIZE` で調整 |
| `gamma` | `出力 = (入力 / 255) ** GAMMA * 255`。`GAMMA = 1` は無補正、1未満で暗部を明るくする |
| `sharp` | 元の画像とぼかした画像の差を強調。`SHARP_AMOUNT = 0` は無補正。窓サイズは `BLUR_SIZE` |

[Gaussian blurの仕様](https://docs.opencv.org/4.x/d4/d13/tutorial_py_filtering.html)、
[CLAHEの仕様](https://docs.opencv.org/4.x/d5/daf/tutorial_py_histogram_equalization.html)、
[gamma補正の式](https://docs.opencv.org/4.x/d3/dc1/tutorial_basic_linear_transform.html)に沿って処理します。
数値は最初に比較するための値です。影への改善効果を保証する設定ではありません。

`OUTPUT_DIRECTORY` の下に、各ケースの次の3枚と、全ケースの `comparison.csv` を保存します。

- `processed.png`: GrabCutへ渡した加工後の画像
- `mask.png`: GrabCut直後の2値マスク。最大領域の選択・穴埋め前の結果
- `overlay.png`: 04と同じ方法で取得した端線を、加工前の元画像に重ねた確認画像

表示・抽出・計測は元の解像度で行います。CSVには処理の順序、左・右・合計の長さ、無処理からの差、計測範囲を保存します。
差は `そのケース - original` で、丸める前に計算します。ケースの順序を変えても、初期マスク・モデル・シードは毎回戻します。
境界と切欠きが元画像に合っているかを `overlay.png` で確認します。長さの減少だけでは改善と判断しません。
計測できないケースは名前を示して停止し、比較CSVを更新しません。設定を直して再実行し、既存結果の保管は運用で扱います。

### 検証記録

2026-10-13に提出版05として作成したスクリプトを、比較用の試作としてこのフォルダへ移しました。自動検証は `tests/test_preprocess_comparison.py` にまとめました。

2026-10-13に前処理比較を追加しました。新しい5件と既存25件の合計30件、RuffのLint・format、tyの型チェックを確認しました。
比較スクリプトだけを日本語・空白を含むフォルダへコピーして7ケースを実行し、PNGと比較CSVを保存しました。
無処理の長さと端線が04に一致し、組み合わせの順序が画像とCSVへ反映されることを確認しました。
初期マスク・モデル・乱数シードのリセット、gamma=1・sharp=0の無補正、基準を最後に置いた場合の差も確認しています。
入力の上書き・ケース名の誤り・計測不成立は停止し、入力画像を変えないことを確認しました。
手元の入力画像でも7ケースを実行しました。結果は `tests/results/preprocess_20261013_85im34by/` に残しています（題材フォルダ基準、Git管理対象外）。
`comparison.csv` と各ケースの3枚の画像、実行したスクリプトのコピーがあります。`overview.png` は左から加工画像・抽出マスク・元画像上の端線を並べています。
同じ初期指定・計測範囲で次の差が出ました。境界の正しさを確認するための比較で、短いケースを最良とは判定していません。

| ケース | 合計px | 無処理との差px |
| --- | ---: | ---: |
| original | 2985.35 | 0.00 |
| blur | 2955.13 | -30.22 |
| clahe | 2986.78 | 1.43 |
| gamma | 2992.30 | 6.95 |
| sharp | 3013.03 | 27.68 |
| blur_clahe | 2981.93 | -3.42 |
| clahe_blur | 2958.24 | -27.11 |
