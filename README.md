# code-scraps

その場限りで書いたコードの保管庫。
動けばOK、きれいじゃなくてOK、後で消してもOK。

## 構成

日付ベース。1ネタ = 1フォルダ。

```text
2026/
  10-08/
    python-hello/
      README.md
      main.py
    typescript-fizzbuzz/
      README.md
      main.ts
_template/
  README.md
scripts/
  New-Scrap.ps1
```

ルールはこれだけ:

- `YYYY/MM-DD/<slug>/` に作る
- `<slug>` は `言語-ネタ` のように付ける（例: `python-hello`, `rust-cli-memo`）
- 同じ日に複数作ってOK、フォルダを分けるだけ
- 各フォルダに最低限の `README.md` を置く（何を試したか、動かし方）

## 作り方

PowerShell で:

```powershell
./scripts/New-Scrap.ps1 python-hello
# -> 2026/10-08/python-hello/ ができる
```

手動で作る場合も `_template/README.md` をコピーして使う。

## 運用

- 1 scrap = 1 commit 目安、`scrap: YYYY-MM-DD slug` のように書く
- `main` に直接 commit・push でOK、PR は不要
- 動かない途中経過も置いてOK
- 整理したくなったら消す・まとめるだけ、履歴は気にしない

## 注意（public リポジトリ）

- APIキー、トークン、個人情報は絶対に入れない
- `.env` や認証情報ファイルは置かない（`.gitignore` で除外済み）
- 誤って入れたらすぐ削除 + キーの無効化をする
