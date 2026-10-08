# opencv-grabcut

- GrabCut で板の領域を推定する試し書き
- ruff / ty が単体で動く設定（`pyproject.toml` のみ）にして、通過確認する
- 初心者向けの解説は `GUIDE.md` に分離。コード内に説明コメントは書かない

## バリエーション

| スクリプト | 出力 | 内容 |
| --- | --- | --- |
| `ex03_outline.py` | `result_03.png` | フル解像度で GrabCut、最大輪郭を赤縁で描く |
| `ex04_side_edges.py` | `result_04.png` | 半分縮小で GrabCut、左右端だけ赤線で描く |
| `ex05_side_lengths.py` | `result_05.png` / `result_05.csv` | 半分縮小で GrabCut、左右端の長さと合計を計測 |

元 `main.py` は `ex03_outline.py` にリネーム。番号と出力を一致させて比べやすくした。

## 動かし方

```sh
uv sync
uv run ex03_outline.py
uv run ex04_side_edges.py
uv run ex05_side_lengths.py
# input.png を読んで各番号の result_*.png を書く。ex05 は CSV も書く
```

`ex05` も単独で動き、他のスクリプトを読み込みません。左端はオレンジ、右端は水色で描き、
左・右・合計の長さを画像、CSV、ターミナルに出します。

長さは元画像の座標で、各行の左端・右端を結ぶ開いた線に沿って測ります。
左右を横につなぐ上辺・下辺は含めません。単位は **px** です。
mm に換算するには、元画像の `1 px あたり何 mm か` が別途必要です。
半分縮小による細部の省略や、マスクを拡大した際の階段状の境界が計測値に影響します。
折り返した裂け目など、同じ行に複数の境界がある部分は最外側の端で代表します。

## チェック（2026-10-09 時点で全部通過）

```sh
uvx ruff check .
uvx ruff format --check .
uvx ty check .
```

- `ruff 0.16.10`: lint 30カテゴリ以上 + format
- `ty 0.0.85`: `[tool.ty.rules] all = "error"`（全ルールをエラー扱い）
- 依存: `numpy 2.5.3`, `opencv-python 5.0.0.93`
- `uv sync` 不要でも `uvx` ならそのまま動く（ty は型解決のために `.venv` を使う）
- `ex05` は実画像で実行確認し、幅の違う長方形で上辺・下辺を含まないこと、斜めの側辺で斜めの距離を含むこと、CSVと表示の一致、板が見つからない場合のエラーを確認

## 元コードからの差分（通過のための修正）

1. `cv.grabCut(..., None, ...)` → `cv.grabCut(..., (0, 0, 1, 1), ...)`
   - `ty` の `no-matching-overload` で落ちる。型スタブ上 `rect` は必須
   - `GC_INIT_WITH_MASK` では `rect` は無視されるので動作は同等
2. モジュール docstring を追加（ruff `D100`）
3. `raise FileNotFoundError("input.png")` → 変数に入れてから raise（ruff `EM101`）
4. `cv.polylines(..., False, ...)` → `isClosed=False, color=..., thickness=...`（ruff `FBT003`）
   - boolean の位置引数渡しを禁止するルール。キーワード引数にする
5. `left_points: list[list[int]] = []` のように注釈追加
   - 空リストの型推論で `ty` が困らないようにする。`xs[0]` は `int(...)` で Python int 化
