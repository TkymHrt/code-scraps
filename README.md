# code-scraps

小さな試作から、実際に使うスクリプトまでを置くリポジトリです。
試作は自由に、実践用は初学者や引き継ぐ人が読めるシンプルさを重視します。

## 構成

```text
projects/                     継続して使う題材（名前で探す）
  opencv-grabcut/
    practical/                実画像で使う独立スクリプト
      quantitative/           CSVを使う一括計測・比較
    experiments/              抽出方法の試作と比較
    tests/                    実践用の動作を確認するコード
    README.md
    pyproject.toml / uv.lock
  gopro-calibration/
    practical/                校正・補正のmain.pyと印刷用の盤
    tests/                    合成画像による検証と記録
    README.md
    requirements.txt
scraps/YYYY/MM-DD/<slug>/      単発の試作・学習（作成日で探す）
research/YYYY/MM-DD/<slug>/    調査メモ・出典・検討案
_template/README.md            試作のREADMEひな形
scripts/New-Scrap.ps1          試作フォルダを作る補助スクリプト
AGENTS.md                     エージェント向けの短い作業指針
```

| 題材 | 用途・動かし方 |
| --- | --- |
| [GrabCut](projects/opencv-grabcut/README.md) | 試料抽出、輪郭・左右側辺の計測、複数画像の比較 |
| [GoPro校正](projects/gopro-calibration/README.md) | 魚眼レンズの校正と写真の歪み補正 |
| [端割れの調査](research/2026/10-11/edge-crack/REPORT.md) | 代替手法、撮影・計測条件、比較実験の検討 |
| [Hello world](scraps/2026/10-08/python-hello/README.md) | 単発の構成サンプル |

依存関係と実行コマンドは各題材のREADMEで管理します。リポジトリ全体をパッケージにはしません。

## 実装の考え方

`scraps/` と `experiments/` は、動かない途中経過、複雑な比較、使い捨てのコードも置けます。
実践用の実装方針を試作へ強制しません。`tests/` は合成入力や自動検証の置き場所です。

`practical/` は、**1つの目的を1本のスクリプトで完結させる**ことを基本にします。
読み込みから処理、保存までを追えるようにし、設定は冒頭か必要最小限の引数にまとめます。
比較用のスクリプトが計測済みCSVを入力にすることは構いません。
「1本で完結」は、全工程を巨大な1本へ詰め込む意味ではなく、ほかの自作モジュールを配らずに使える意味です。

- 名前と処理の順序で分かるコードを優先し、コメントは目的・単位・判断理由を補います。
- 長い処理を読みやすくする小さな関数は使って構いません。関数も同じファイルに置きます。
- 共通化だけを目的にした別モジュール、クラス、設定階層、プラグイン構造は増やしません。
  短い処理の重複は許容し、同じ条件で比較するコードは検証で整合を確認します。
- YAGNI（今必要なものだけ作る）を基本に、将来の拡張点や使わないオプションは作りません。
- 入力違いによる誤計測・データ破壊を防ぐチェックは残します。
  全設定の検証、包括的な例外処理、自動リトライや復旧処理は必要が出てから考えます。
  標準の例外で原因が分かるところは、そのまま止めます。

運用では、実行前に入力・単位・保存先を確認し、実行後に画像やCSVを確認します。
同じ保存先を使うと上書きするため、必要な結果は試料・実行ごとに保存先を分けます。
失敗したら原因を直して再実行します。誤計測を黙って通す処理は簡素化に含めません。

`practical/` は実行するコードの分類です。実試料での精度や適用性が確認済みという意味ではありません。
試作から移す際は、必要な機能だけを残して1本で実行し、入力・出力・設定・確認方法をREADMEに記載します。
検証コードは `tests/` に置き、検証できた範囲と未確認の範囲を記録します。

## 試作を追加する

```powershell
./scripts/New-Scrap.ps1 python-hello
# -> scraps/YYYY/MM-DD/python-hello/ ができる（実行日の日本時間）
```

手動で作る場合も `_template/README.md` を使えます。
作成コマンドの `<slug>` は英小文字・数字をハイフンでつなぎます（例：`python-hello`）。
継続して扱う題材になったら `projects/<題材>/` へ移し、実践用と試作を分けます。
用途がない空フォルダや一律のひな形は作らず、必要な部分だけ用意します。

## Gitでの運用

- `main` に直接commit・pushでOK。PRは必須にしません。
- 機能追加と大きな整理は別のコミットにすると、移動と内容の変更を追いやすくなります。
- コミット前に差分を見て、変更した処理に関係する既存の検証を実行します。
  テストは計算結果や独立実行など、意味のある振る舞いに絞ります。
- 仮想環境、入力実画像、大きな生成結果、APIキー・認証情報・個人情報は公開しません。
  共有するサンプルや小さな検証記録は用途と来歴を明記します。

## 2026-10-12の整理

| 以前の場所 | 現在の場所 |
| --- | --- |
| `2026/10-08/opencv-grabcut/` | `projects/opencv-grabcut/` |
| `2026/10-09/python-gopro-calibration/` | `projects/gopro-calibration/` |
| `2026/10-08/python-hello/` | `scraps/2026/10-08/python-hello/` |
| `2026/10-11/edge-crack-research/` | `research/2026/10-11/edge-crack/` |

GrabCutの実践用は `ex03_outline.py` → `outline.py`、`ex04_side_edges.py` → `side_edges.py`、
`ex05_side_lengths.py` → `side_lengths.py` に変更しました。出力の `result_03`〜`result_05` は従来の名前を使います。
GrabCutの自動試験は `experiments/tests/` から `tests/` へ、GoProの `main.py` と盤画像は `practical/` へ移しました。
ローカルの入力・生成結果・仮想環境も題材と一緒に移動し、引き続きGitの対象外にしています。
