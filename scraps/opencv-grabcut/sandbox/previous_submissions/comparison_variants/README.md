# PoCで使わない比較・分析の保管

2026-10-16、局所区間を比較するPoCの実行先を6本へ整理し、以下の5本を移動しました。
現在の手順は [実践用README](../../../submissions/README.md) を参照してください。
この親フォルダにある同名の `length_comparison_gui.py` は、さらに古い校正済みCSV用の版です。
別の版として上書きせず保持しています。

| スクリプト | 用途 |
| --- | --- |
| [length_comparison_gui.py](length_comparison_gui.py) | 同じ材料区間と厚さから理想長を求める従来の比較GUI |
| [length_analysis_gui.py](length_analysis_gui.py) | 区間の伸びと側辺形状を分ける分析GUI |
| [length_comparison_simple_gui.py](length_comparison_simple_gui.py) | 理想長と左右長さを表と1枚のグラフで比較するGUI |
| [length_comparison_simple.py](length_comparison_simple.py) | 厚さから理想長を求めるGUIなしのグラフ保存 |
| [length_comparison_no_thickness.py](length_comparison_no_thickness.py) | 厚さを使わず左右実測長だけをPNGにするGUIなし版 |

移動時はスクリプトの内容を変更せず、SHA-256で一致を確認しました。
相対パスは各スクリプトのある場所を基準にするため、再利用する場合は入力・出力の設定を確認してください。
従来の入出力は `submissions/input/`・`submissions/output/` に残しています。
自動試験・操作検証は題材の `tests/` から保管先を参照します。
以下のコマンドは `opencv-grabcut` フォルダから実行します。

## 厚さと理想長を使う従来の比較

`length_comparison_gui.py` は、対応する同じ材料区間と厚さを使う別案として残しています。

「CSVを追加」で計測GUIの長さCSVを複数追加し、各行へ撮影時の厚さを直接入力します。
左サイドバーに初期区間長・初期厚さを入力し、「比較する」を押します。
行の選択や適用ボタンは使いません。間違えたCSVは、その行の「削除」で除外できます。

**追加した順が撮影順**です。複数選択では選択ダイアログが返した順になります。
順番を明確に指定するときは、CSVを1つずつ追加します。
撮影名は番号とファイル名で表示し、並べ替え・名前編集・フルパス表示は置きません。

幅方向の変化を無視し、幅一定・体積一定の基準スラブを使います。

```text
理想の片側長 = 初期区間長 × 初期厚さ ÷ 各回の厚さ
理想の左右合計 = 理想の片側長 × 2
```

実寸・理想との差・差率・前回との差を表のタブで確認します。
「推移グラフ」タブも同じ画面内にあります。比較CSVとPNGグラフの保存先は既定で `output` です。
条件やCSVを変えたら結果を無効にし、比較し直してから保存します。
比較時は画像を読み直さず、保存済みCSVだけで計算します。
各画像のy座標を揃える必要はありませんが、**対応する同じ材料区間**を計測してください。
左右側辺の凹凸を含む長さを、滑らかな理想区間長と比較する値です。

## GUIなしでシンプルグラフを保存

`length_comparison_simple.py` は、現行の長さCSVから左側辺・右側辺・理想片側長の3本線を描き、1枚のPNGに保存する単独スクリプトです。
ファイル選択ダイアログやグラフのウィンドウは開きません。既存のMatplotlibだけで描画し、自作モジュールへ依存しません。

コード冒頭の初期区間長・初期厚さ・入力CSVと各撮影の厚さを、実際の値へ置き換えます。初期値とファイル名は記入例です。

```python
INITIAL_LENGTH_MM = 100.0
INITIAL_THICKNESS_MM = 10.0
INPUT_CSVS = [
    ("output/shot1_lengths.csv", 10.0),
    ("output/shot2_lengths.csv", 5.0),
]
OUTPUT_PATH = "output/length_comparison_simple.png"
```

```powershell
# opencv-grabcutフォルダから実行
uv run sandbox/previous_submissions/comparison_variants/length_comparison_simple.py
```

`INPUT_CSVS` に書いた順が撮影順です。相対パスはスクリプトのある `submissions/` を基準にします。
計測GUIの1画像1行のCSVから `image_path`・`left_mm`・`right_mm` を読み、画像自体は読み直しません。
理想片側長は幅一定・体積一定として、`初期区間長 × 初期厚さ ÷ 撮影時の厚さ` で求めます。
横軸は撮影順、縦軸は長さ(mm)です。CSVと厚さ・左右・理想の対応はターミナルにも表示します。
保存するのはPNGだけです。同じ保存先は再実行時に上書きし、入力CSV・元画像への上書きは止めます。
入力・値に問題があればエラーで止まるので、コードの設定またはCSVを直して再実行します。

旧版のGUIなし棒グラフは `sandbox/previous_submissions/04_compare_lengths.py` にあります。こちらは旧3行形式のpx CSVと基準との差分を扱います。

2026-10-15、既知の3撮影で左・右・理想の値、1撮影と20撮影の順序、不正値・入力保護を含む3件の自動試験を確認しました。
Tkinterを使えない状態で単独コピーを別プロセスから実行し、PNG保存を確認しています。Ruff・format・tyも通過しました。
生成した確認用グラフは `tests/results/headless_graph_20261015/output/length_comparison_simple.png` です。実測データの比較は未確認です。

## 厚さなしで左右の長さをグラフに保存

`length_comparison_no_thickness.py` は、現行の長さCSVから左右側辺長の2本線をPNGへ保存するGUIなしの単独スクリプトです。
厚さや初期値の設定は不要で、理想長は計算しません。

コード冒頭のCSVを実際のファイル名へ置き換え、撮影順に並べます。

```python
INPUT_CSVS = [
    "output/shot1_lengths.csv",
    "output/shot2_lengths.csv",
]
OUTPUT_PATH = "output/length_comparison_no_thickness.png"
```

```powershell
# opencv-grabcutフォルダから実行
uv run sandbox/previous_submissions/comparison_variants/length_comparison_no_thickness.py
```

横軸は指定した撮影順、縦軸はCSVに保存された側辺長(mm)です。CSV名と左右の値をターミナルにも表示します。
相対パスは `submissions/` を基準にします。計測GUIの1画像1行のCSVから `image_path`・`left_mm`・`right_mm` を読み、元画像は不要です。
PNGは再実行時に上書きします。入力CSV・元画像への上書きや不正値は止めるので、設定やCSVを直して再実行します。

2026-10-15、厚さ列を持たない既知の数値CSVで左右の値、1撮影・20撮影の指定順、不正値と入力保護を確認しました。
Tkinterを使えない状態で単独コピーを実行し、PNG保存も確認しています。比較関連の自動試験19件とRuff・format・tyが通過しました。
確認用PNGは `tests/results/no_thickness_graph_20261015/output/length_comparison_no_thickness.png` です。実測データでの比較は未確認です。

## 最小比較GUI：厚さから理想長を計算

`length_comparison_simple_gui.py` は、初期区間長・初期厚さと各撮影の厚さから理想片側長を求め、
CSVの左右側辺長と比較する独立スクリプトです。数値表と1枚の推移グラフに絞っています。

```powershell
# opencv-grabcutフォルダから実行
uv run sandbox/previous_submissions/comparison_variants/length_comparison_simple_gui.py
```

1. 「初期区間長 (mm)」「初期厚さ (mm)」を入力する。
2. 「CSVを追加」で、計測GUIの長さCSVを撮影順に追加する。
3. 各CSVの行に、撮影時の厚さをmmで入力する。
4. 「比較する」を押す。数値表には撮影ごとの理想長・左右側辺長・理想との差、グラフには左・右・理想長の3本を表示する。
5. 必要に応じて「比較CSVを保存」「グラフを保存」を使う。

幅一定・体積一定を仮定して計算します。

```text
理想片側長 = 初期区間長 × 初期厚さ ÷ 撮影時の厚さ
左右の理想差 = それぞれの側辺長 − その撮影の理想片側長
```

例えば初期区間長100mm・初期厚さ10mmの場合、厚さ5mmでの理想片側長は200mmです。
すべての長さ・厚さ・差の単位はmmです。
撮影順はCSV追加順で、複数選択ではダイアログが返した順になります。
順番を確実に指定するときは1枚ずつ追加します。不要なCSVはその行の「削除」を押します。
初期条件・厚さ・CSVを変更すると結果を消し、再比較するまで保存を無効にします。

読み込むのは1画像1行の長さCSVです。`image_path`・`left_mm`・`right_mm` を使い、
左右合計、差率、前回差、区間長や形状指標は計算しません。画像の読み直しや新しい依存関係もありません。
理想片側長は撮影ごとの厚さで変わり、その撮影の左右で共通です。
既定の保存先は `output`、名前は `length_comparison_simple.csv` と `length_comparison_simple.png` です。
比較CSVには撮影名・入力CSV・画像パス・初期区間長・初期厚さ・撮影時の厚さ・左右側辺長・理想片側長・左右の理想差を保存します。
入力CSV・補正画像への上書きは止めます。

```powershell
uv run python -m unittest discover -s tests -p test_length_comparison_simple_gui.py
uv run tests/verify_length_comparison_simple_gui.py
```

2026-10-15、既知の数値CSVによる4件の自動試験で、厚さから求める理想長との比較、左右と理想長の推移、
1画像と20画像、不正な初期条件・厚さ、単独コピー実行、CSV/PNG保存と入力保護を確認しました。
実Tkで初期条件・各行の厚さ入力、変更後の再比較、保存、削除、20撮影表示と、1060×720・最小960×640の画面を確認しました。
Ruffの検査・整形確認とtyの型検査も通過しています。
確認画像と保存結果は `tests/results/length_comparison_simple_thickness_20261015/` にあります。
本番試料を使った比較は未確認です。

## 長さ分析の別案：伸びと側辺形状を分ける

`length_analysis_gui.py` は既存の比較GUIとは別の独立スクリプトです。
`02_measure_edge_lengths_gui.py` の長さCSVを使い、理想長・区間長・左右側辺長の数値表、
伸びと左右側辺形状の推移、直前パスからの指標の変化を一画面に表示します。
新しい依存関係や他の自作モジュールは使いません。

```powershell
# opencv-grabcutフォルダから実行
uv run sandbox/previous_submissions/comparison_variants/length_analysis_gui.py
```

1. 「CSVを追加」で、対応する同じ材料区間の長さCSVを圧延パス順に追加する。
2. 初期区間長・初期厚さと、各行の撮影時の厚さをmmで入力する。
3. 「分析する」を押し、上の数値表と下の4枚のグラフを確認する。
4. 「分析CSVを保存」「分析グラフを保存」で結果を残す。

追加順が横軸のパス番号です。初期状態のCSVも追加すれば、実測した初期形状からの推移を確認できます。
複数選択時はダイアログの返した順になるため、順番を確実に指定するときは1枚ずつ追加します。
厚さ・初期条件・CSVを変更すると数値表とグラフを消し、再分析するまで保存を無効にします。
入力行と数値表にはスクロールがあり、多数のパスも同じ画面で扱います。

区間長は圧延方向（補正画像のy方向）に投影した、開始・終了の画素中心間の距離です。
CSVの両端の行を含めて計測していても、行数の `+1` は加えません。

```text
理想長 L* = 初期区間長 × 初期厚さ ÷ 各パスの厚さ
区間長 D = (end_y − start_y) × mm_per_px
伸びの差率 (%) = (D − L*) ÷ L* × 100
側辺の余分な経路長 (mm) = 側辺長 S − D
左右の側辺形状 (%) = (S − D) ÷ D × 100
直前パスからの変化 (ポイント) = 今回の指標 (%) − 前回の指標 (%)
```

例えば理想長200mm・区間長210mm・左側辺210mmなら、伸び差率は+5%、左形状は0%です。
理想長200mm・区間長200mm・左側辺210mmなら、伸び差率は0%、左形状は5%です。
区間の伸びと、側辺が直線より長い経路になった分を分けて読みます。
側辺形状には曲がりや凹凸が入り、クラック数や損傷率を表す指標ではありません。

グラフの上段は伸び差率と左右の側辺形状、下段はそれぞれの直前パスからの変化です。
5%から10%への変化は+5ポイントとなり、1回目は前回がないため棒を表示しません。
実寸が倍になっても側辺形状の割合が同じなら、その指標の前回変化は0です。

分析CSVは入力の長さ・倍率・区間に加えて、以下を保存します。

| 列 | 内容・単位 |
| --- | --- |
| `pass_number`, `sample_id` | 追加順の番号、番号とCSV名 |
| `initial_length_mm`, `initial_thickness_mm`, `thickness_mm` | 初期条件・各パスの厚さ (mm) |
| `ideal_length_mm`, `interval_length_mm` | 理想長・区間長 (mm) |
| `stretch_delta_mm`, `stretch_pct` | 区間長−理想長 (mm)、伸び差率 (%) |
| `left_excess_mm`, `right_excess_mm` | 左右の側辺長−区間長 (mm) |
| `left_shape_pct`, `right_shape_pct` | 左右の側辺形状 (%) |
| `previous_id` | 直前のCSVの識別名。1回目は空欄 |
| `previous_delta_stretch_pp` | 伸び差率の前回変化 (ポイント) |
| `previous_delta_left_shape_pp`, `previous_delta_right_shape_pp` | 左右形状の前回変化 (ポイント) |

前回変化の1回目はCSVでも空欄です。既定の保存先は `output`、名前は `length_analysis.csv` と
`length_analysis.png` です。入力CSV・補正画像への上書きは止めます。
分析時に画像は読み直さず、CSVの開始・終了yと倍率から区間長を求めます。
幅一定・体積一定を仮定し、区間の対応と輪郭が正しく与えられるレベル1の分析です。
幅・中心線・局所的な凹みの解析や、区間選択・撮影・抽出の誤差評価は含めません。

### 新規分析GUIの検証

```powershell
uv run python -m unittest discover -s tests -p test_length_analysis_gui.py
uv run tests/verify_length_analysis_gui.py
```

2026-10-15、既知の寸法による6件の自動試験で、伸びと側辺形状の分離、区間長の端点間隔、
割合の前回差、1パスと20パス、入力の不整合、単独コピー実行、CSV/PNG保存、入力保護を確認しました。
実Tkで初期条件・厚さの入力、再分析、保存、20パス表示、削除を確認しました。
1320×920と最小1100×840の画面も確認し、結果と画面画像は `tests/results/length_analysis_20261015/` に保存しています。
既存分を含む全93件の自動試験、Ruffの検査と整形確認、tyの型検査も通過しました。
これらは既知の数値CSVによる確認であり、本番試料の圧延前後の計測精度は未確認です。
