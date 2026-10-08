# opencv-grabcut

- GrabCut で板の領域を推定する試し書き
- ruff / ty が単体で動く設定（`pyproject.toml` のみ）にして、通過確認する

## 動かし方

```sh
uv sync
uv run main.py
# input.png を読んで result_03.png を書く
```

## チェック（2026-10-08 時点で全部通過）

```sh
uvx ruff check .
uvx ruff format --check .
uvx ty check .
```

- `ruff 0.16.10`: lint 30カテゴリ以上 + format
- `ty 0.0.85`: `[tool.ty.rules] all = "error"`（全ルールをエラー扱い）
- 依存: `numpy 2.5.3`, `opencv-python 5.0.0.93`
- `uv sync` 不要でも `uvx` ならそのまま動く（ty は型解決のために `.venv` を使う）

## 元コードからの差分（通過のための修正3点）

1. `cv.grabCut(..., None, ...)` → `cv.grabCut(..., (0, 0, 1, 1), ...)`
   - `ty` の `no-matching-overload` で落ちる。型スタブ上 `rect` は必須
   - `GC_INIT_WITH_MASK` では `rect` は無視されるので動作は同等
   - これが唯一の実質的な修正
2. モジュール docstring を追加（ruff `D100`）
3. `raise FileNotFoundError("input.png")` → 変数に入れてから raise（ruff `EM101`）
