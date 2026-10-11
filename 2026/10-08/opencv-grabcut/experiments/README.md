# 比較試験用

旧方式と、AI生成画像で反射の誤検知を調べる独立スクリプトをまとめています。
実践用は [../practical/GUIDE.md](../practical/GUIDE.md) を使ってください。

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

入力はこのフォルダ基準、出力は `results/` に保存します。
`input_ai.png` はユーザーが用意したAI生成画像です。
旧入力の `input.png` と既存の結果画像もこのフォルダへ移しました。
旧入力と生成された結果はGit管理対象外です。
以前の計測CSVは `reference/result_05_halfsize.csv` に保存しています。

`opencv-grabcut` フォルダから実行します。

```sh
uv run experiments/ex06_mask.py
uv run experiments/ex07_baseline.py
uv run experiments/ex08_seeded_mask.py
uv run experiments/ex09_vertical_open.py
uv run experiments/ex10_reflection_refine.py
```

各コードの先頭で入力や初期指定などを変更できます。
ex07〜ex10は共通のフル解像度・初回GrabCut 5回・乱数シード0で比較します。
他のスクリプトやその結果を読み込まず、それぞれ単独で実行できます。
同じ出力名で実行すると結果を上書きするので、比較を残す場合は `OUTPUT_PREFIX` を変えてください。

処理の詳しい説明、確認画像の読み方、反射除去の調整手順は [GUIDE.md](GUIDE.md) にあります。
ローラーの反射除去を実践版に採用する前に、本物の突起も消えていないか確認してください。
