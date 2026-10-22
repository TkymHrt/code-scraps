# 04_plot_pass_metrics.pyを、1計測ずつの値の動きから読む

[全体の入口](../IMPLEMENTATION_GUIDE.md) / [Pythonの基礎](python_basics.md) / [対象コード](../04_plot_pass_metrics.py)

## 1. 最初に：この章が説明するのは区間ごとの折れ線を描く版

解説作成時の作業フォルダにある `04_plot_pass_metrics.py` を対象とします。このファイルには作成開始前から変更があり、READMEに記録されている平均・標本SDを描く版とは異なります。

この章の版では、次の動作になります。

- 実験回・区間IDごとに線を分ける。DRとOPも別の線になる。
- 区間間の平均やSDを計算しない。誤差棒も描かない。
- 図は10×6インチ、保存解像度は180dpi。
- 図題・計測条件・日本語の軸ラベル・補助線・0の水平線を描く。
- PNG3枚を保存する。SVGやキャプション用テキストは出力しない。

手元のファイルに `summarize_measurements()` がある場合は、この章とは別の版です。ここで扱う版の関数は `read_pass_measurements()`、`create_graphs()`、`write_graphs()`、`main()` の4つです。

## 2. このスクリプトの目的・入力・出力

`02` で保存した1計測1行のCSVを複数読み、圧延パス数を横軸にして3種類の図を作ります。画像を読む処理、試料の抽出、長さの再計測は行いません。

| 入力 | 内容 |
| --- | --- |
| `MEASUREMENTS` | 実験回・パス番号・区間ID・計測CSVの場所を並べたリスト |
| 指定したCSV | 基準区間長、DR・OPの側辺長と超過率、倍率、評価間隔、平滑化幅など |
| 描画用設定 | 色、線種、マーカー、フォント、図の大きさ、軸範囲、保存先 |

| 出力ファイル | 縦軸にする値 | 単位 |
| --- | --- | --- |
| `excess.png` | DR・OPそれぞれの超過率 | % |
| `change_from_initial.png` | 同じ実験回・同じ区間・同じ側のパス0からの超過率の変化 | パーセントポイント |
| `dr_op_difference.png` | 同じ計測のDR超過率−OP超過率 | パーセントポイント |

保存先は既定で `src/output/pass_graphs/` です。同じ名前の出力PNGは上書きされます。

実行コマンドは題材フォルダから次です。引数はありません。冒頭のCSV名は例なので、実際に計測して保存したCSVへ書き換えます。

```powershell
uv run src/04_plot_pass_metrics.py
```

## 3. 数式を先に具体例で理解する

ここでの表は説明用です。実験値ではありません。同じ実験回 `run01`、同じ区間 `a`、基準区間長100mmの計測を考えます。

| パス | DR長さ | OP長さ | DR超過率 | OP超過率 |
| ---: | ---: | ---: | ---: | ---: |
| 0 | 101mm | 102mm | 1% | 2% |
| 2 | 103mm | 102mm | 3% | 2% |
| 4 | 105mm | 104mm | 5% | 4% |

超過率は `(側辺長 / 基準区間長 - 1) * 100` です。DRのパス2なら `(103 / 100 - 1) * 100 = 3` になります。

### 超過率の図

DRのy値は `[1, 3, 5]`、OPは `[2, 2, 4]` です。横軸はいずれも `[0, 2, 4]` です。

### 初回差の図

DRの基準は、同じ区間aのパス0の `1` です。各値から引くので `[0, 2, 4]` になります。OPの基準は `2` で、結果は `[0, 0, 2]` です。

1%から3%への変化は2パーセントポイントです。このコードは `(3 - 1) / 1 * 100 = 200%` という相対的な増加率は計算しません。

パス0の差が0になるのは、自分自身を引くからです。初回計測の誤差が0という意味ではありません。

### DR−OP差の図

同じパスの左右を引きます。結果は `[1 - 2, 3 - 2, 5 - 4]`、つまり `[-1, 1, 1]` です。正ならDR側の超過率が大きく、負ならOP側が大きいと読めます。

長さそのものの差 `103 - 102 = 1mm` を図にしているわけではありません。この例は基準長が100mmなので数値が偶然一致します。基準長200mmで側辺長206mm・204mmなら、長さの差は2mm、超過率の差は `3 - 2 = 1` ポイントです。

区間bも測った場合、bにはb自身のパス0を使います。区間aの初回値をbへ使ったり、実験回 `run02` へ使ったりしません。

## 4. ファイル先頭のimport

```python
import math
from pathlib import Path

from matplotlib import rcParams
from matplotlib.figure import Figure

from utils.file_io import check_output_path
from utils.measurement_csv import read_lengths
from workflow_settings import BASE_DIRECTORY, OUTPUT_DIRECTORY
```

- `math` は、条件の数値が十分近いかを `isclose()` で確認するために使います。
- `Path` は、CSVやPNGの場所を操作します。
- `rcParams` はMatplotlibの共通描画設定です。ここではフォントを設定します。
- `Figure` は図全体を表すオブジェクトです。
- `check_output_path()` は保存先の拡張子と入力への上書きを検査する自作関数です。
- `read_lengths()` はCSVを読み、値を検証して辞書へまとめる自作関数です。
- `BASE_DIRECTORY` は `workflow_settings.py` がある `src/`、`OUTPUT_DIRECTORY` は既定でその下の `output/` です。

このファイルにNumPyのimportはありません。数値計算の中心は、検証済みの超過率の引き算とリストの組み立てです。Matplotlibへ渡した後の描画はライブラリが担当します。

## 5. MEASUREMENTSを1文字ずつの役割まで読む

```python
MEASUREMENTS = [
    ("run01", 0, "a", "output/run01_pass00_a.csv"),
    ("run01", 2, "a", "output/run01_pass02_a.csv"),
    ("run01", 4, "a", "output/run01_pass04_a.csv"),
]
```

外側の `[]` はリストです。内側の `()` が1計測に対応する4要素のタプルです。1行の順番は次です。

1. `"run01"`：実験回を区別する文字列。
2. `0`：パス番号という整数。引用符を付けません。
3. `"a"`：測った区間を区別する文字列。
4. `"output/run01_pass00_a.csv"`：読むCSVの場所という文字列。

ファイル名からパス番号を自動推定しているわけではありません。番号とIDはこのリストの指定が使われます。名前が `pass04` のCSVにパス番号2を付けても、コードはファイル名の意味までは照合しません。設定時に人が対応を確認します。

1行を追加するときは、隣の行とのカンマを忘れないでください。文字列と整数の位置を入れ替えないでください。実装が想定する4要素と型に沿って編集します。

相対パスは `src/` が基準です。PowerShellを開いたフォルダが基準ではありません。絶対パスも渡せます。

```python
# 設定例：同じ実験回の区間aとbを、パス0・2で比較する
MEASUREMENTS = [
    ("run01", 0, "a", "output/run01_pass00_a.csv"),
    ("run01", 2, "a", "output/run01_pass02_a.csv"),
    ("run01", 0, "b", "output/run01_pass00_b.csv"),
    ("run01", 2, "b", "output/run01_pass02_b.csv"),
]
```

この設定で超過率図は、run01/aのDR・OPとrun01/bのDR・OPという4本の線になります。区間aとbを平均した2本の線にはなりません。

同じ画像の別区間を使うことはできますが、`02` で別々に測り、別名のCSVを用意します。CSV内の `image_path` が同じことは拒否しません。同じCSV自体の使い回しは拒否します。

## 6. 描画設定を読む

| 変数 | 現在値 | 意味 |
| --- | --- | --- |
| `GRAPH_DIRECTORY` | `OUTPUT_DIRECTORY / "pass_graphs"` | PNG3枚の保存先 |
| `FIGURE_SIZE` | `(10, 6)` | 横10・縦6インチ |
| `FONT_FAMILY` | `"Meiryo"` | 日本語を含む文字のフォント候補 |
| `FONT_SIZE` | `11` | 共通の文字サイズ |
| `SAVE_DPI` | `180` | 保存時の1インチあたりの画素数 |
| `DR_COLOR` | `"#d96c17"` | DRの色 |
| `OP_COLOR` | `"#15927e"` | OPの色 |
| `DIFFERENCE_COLOR` | `"#5964a6"` | 左右差の色 |
| `LINE_STYLES` | `("-", "--", "-.", ":")` | 実線、破線、一点鎖線、点線の巡回 |
| `MARKERS` | `("o", "s", "^", "D", "v", "P", "X")` | 丸・四角など点の記号の巡回 |
| `PASS_X_LIMITS` | `None` | 3図共通の横軸範囲。Noneなら自動 |
| `EXCESS_Y_LIMITS` | `None` | 超過率図の縦軸範囲 |
| `CHANGE_Y_LIMITS` | `None` | 初回差図の縦軸範囲 |
| `DIFFERENCE_Y_LIMITS` | `None` | 左右差図の縦軸範囲 |

10×6インチを180dpiで保存するので、通常は1800×1080pxになります。これはグラフ画像の解像度で、試料画像の `MM_PER_PX` とは無関係です。Figureのサイズはインチ、保存時の `dpi` はその画素化の細かさです。[MatplotlibのFigure](https://matplotlib.org/stable/api/_as_gen/matplotlib.figure.Figure.html)

`EXCESS_Y_LIMITS = (0, 10)` のようにすれば0〜10へ固定します。ただし、その範囲を外れる点は見えなくなります。`None` は、この実装ではMatplotlibの自動範囲を使います。0の水平線も描くため、初期の自動範囲には0も反映されます。手動範囲の指定後には、範囲外の0の線は見えない場合があります。

色・線種・マーカーの変数名を大文字で書くのは設定値という約束です。変更後はスクリプトを実行し直して反映します。

## 7. 全体の呼び出し順

```text
main()
  ├─ read_pass_measurements(MEASUREMENTS)
  │    ├─ 1指定ずつ内容・重複・パス番号を確認
  │    ├─ read_lengths(CSV) で数値と列を検証
  │    ├─ 全CSVの計測条件を比較
  │    └─ 実験回・区間・パス順の辞書リストを返す
  └─ write_graphs(GRAPH_DIRECTORY, rows)
       ├─ 保存先3つを検査
       ├─ create_graphs(rows)
       │    ├─ 3枚の図と座標軸を作る
       │    ├─ 実験回・区間ごとに値を並べる
       │    └─ 超過率・初回差・左右差の線を描く
       ├─ フォルダを作る
       └─ PNG3枚を順に保存
```

この順番により、不正なCSVが見つかった時点ではPNG保存へ進みません。ただし保存そのものが途中で失敗したときの全取り消しはありません。詳細は後述します。

## 8. read_pass_measurements：指定を検証してrowsへ変える

### 8.1 3つの状態を用意する

```python
records = {}
used_paths = set()
reference_measurement = None
```

`records` は「実験回・区間・パス」というキーから計測辞書を引くための辞書、`used_paths` はすでに読んだCSVの絶対パスの集合、`reference_measurement` は計測条件を比較するための最初の1件です。

この「条件比較の最初の1件」は、必ずしもパス0ではありません。リストの入力順で最初に読み込んだ計測です。初回差の基準となるパス0とは、用途が違います。

### 8.2 1つのタプルを4つの変数へ分ける

```python
for experiment_id, pass_number, section_id, csv_name in measurements:
    experiment_id = experiment_id.strip()
    section_id = section_id.strip()
```

`for` が1行分のタプルを取り出し、それぞれの要素を4変数へ割り当てます。実験回と区間IDの前後の空白を取り除きます。たとえば `" run01 "` は `"run01"` になります。

続く `if not experiment_id or not section_id or not csv_name.strip():` は、どれかが空なら止めます。CSV名の前後の空白も、後のパス作成時に取り除きます。文字列の途中の空白は取り除きません。

### 8.3 パス番号は「0以上の偶数のint」に限定する

```python
if type(pass_number) is not int or pass_number < 0 or pass_number % 2 != 0:
    raise ValueError("パス番号は0以上の偶数整数にしてください")
```

`type(...) is not int` で、値が整数型そのものかを確認しています。`2` は通りますが、`2.0` と `"2"` は通りません。`True` も通りません。Pythonではboolがintの一種として扱われる場面があるため、ここは厳密な型比較です。

`pass_number % 2` は2で割った余りです。0なら偶数です。負数、奇数も拒否します。ファイル名の番号を読み替えたり、文字列を整数へ自動変換したりはしません。

### 8.4 キーの重複とCSVの重複を分けて確認する

```python
key = (experiment_id, section_id, pass_number)
measurement_path = (BASE_DIRECTORY / csv_name.strip()).resolve()
```

たとえばキーは `("run01", "a", 2)`、パスは `src/output/run01_pass02_a.csv` の絶対パスになります。

`key in records` なら「同じ実験回・区間・パスが2回ある」ので拒否します。別のCSVを指していても同じキーにはできません。

`measurement_path in used_paths` なら「同じCSVを使い回している」ので拒否します。別のIDを付けても同じCSVは使えません。`.resolve()` を先に行うため、`output/a.csv` と `output/../output/a.csv` のような表記だけの違いも通常は同じ場所として比較します。

### 8.5 read_lengthsが実際に検証する内容

`measurement = read_lengths(measurement_path)` は、自作モジュール `utils/measurement_csv.py` の関数を呼びます。CSVは文字列の表なので、ここで数値へ変換し、次を検証します。

| 項目 | 検査・処理 |
| --- | --- |
| 文字コード | `utf-8-sig` で読む。BOM付きにも対応する |
| 必須列 | `image_path`、`mm_per_px`、`interval_length_mm`、`left_mm`、`right_mm`、左右の超過率、評価間隔、平滑化幅 |
| データ行数 | ヘッダーを除き、ちょうど1行 |
| 空欄 | 必須列の空欄を拒否 |
| 倍率・基準長・評価間隔 | 有限な正の数 |
| 平滑化幅 | 有限で0以上。0は平滑化なし |
| 側辺長 | 有限な正の数で、基準区間長より不自然に短くない |
| 超過率 | 保存された数値が、側辺長から再計算した値と近いか |
| 画像名 | `image_path` を解決したパスから `.name` で作る |

`image_name` 列は保存時にはありますが、読込時の必須列ではありません。旧形式の `start_y`・`end_y` から基準長を補う処理もありません。

CSV内の相対的な `image_path` は、**CSVが置かれたフォルダが基準**です。`MEASUREMENTS` に書くCSVの相対パスが `src/` 基準なのとは、別の段階の話です。

画像そのものの存在確認や画素の読込は行いません。`image_path` は画像名の取得と、後で行う入力保護にも使われます。

戻る辞書には、長さ・超過率・条件などの数値に加え、`left_per_100mm`・`right_per_100mm` も入ります。この100mm換算値は他の比較処理との共通読込で作りますが、今回の3図には使いません。

`read_pass_measurements()` 内にはさらに `"left_excess_percent" not in measurement` という検査があります。現行の `read_lengths()` では左右超過率を必須にしているので、正常な読込結果にはこのキーが含まれます。新形式を期待する意図を読み取りつつ、現行の読込経路では先に共通関数が検査していると理解します。

### 8.6 全CSVの条件を揃える

最初の計測を `reference_measurement` に保持し、次の4列をすべての計測と比較します。

```text
interval_length_mm       基準区間長
mm_per_px                倍率
evaluation_interval_mm   側辺に沿う評価間隔
smoothing_width_mm       平滑化窓の全幅
```

比較には `math.isclose(..., rel_tol=1e-8, abs_tol=1e-8)` を使います。浮動小数点の微小な誤差は許容しますが、異なる設定を自由に混ぜてよい意味ではありません。これは実験回をまたいだ全計測に適用されます。異なる基準長のデータは、実験回名を変えただけでは同じ実行へ入れられません。

### 8.7 計測辞書へ識別情報を足す

```python
measurement["experiment_id"] = experiment_id
measurement["section_id"] = section_id
measurement["pass_number"] = pass_number
measurement["measurement_csv"] = str(measurement_path)
records[key] = measurement
used_paths.add(measurement_path)
```

CSVから読んだ長さの辞書に、コードで指定したIDとパス番号、CSV自身の絶対パスを足します。CSVに実験回やパス番号を手で追加しておく必要はありません。

`records[key] = measurement` は、キーの場所へその辞書を登録します。`used_paths.add(...)` は、次の繰り返しで同じCSVを検出するための記録です。

### 8.8 パス0を確認し、整列したリストを返す

`records` が空なら、1件以上指定するように例外を出します。その後、`for key in sorted(records):` でキーを並べます。タプルは実験回→区間ID→パス番号の順で比較されます。

```python
initial_key = (key[0], key[1], 0)
```

現在のキーが `("run01", "a", 4)` なら、`initial_key` は `("run01", "a", 0)` です。これが `records` にないと、初回差が作れないため拒否します。区間bにパス0があってもaの代用にはしません。

`rows.append(records[key])` で計測辞書を順番にリストへ追加し、最後に返します。欠けているパスの行は生成しません。文字列IDの整列なので、`"run10"` と `"run2"` は数値の10と2として比較しているわけではありません。揃えた桁数で命名すると読みやすくなります。

## 9. create_graphs：3枚の図をメモリ上に作る

### 9.1 FigureとAxesの違い

`Figure` は図全体、`Axes` はその中の、目盛りや線を描く座標領域です。このコードでは各FigureにAxesが1つです。`axis` という変数にAxesを入れています。長手軸を求める `02` の `axis` とは別物です。

`figures = []` には3枚の図、`axes = []` にはその3つの座標領域を同じ順番で保存します。0番目が超過率、1番目が初回差、2番目が左右差になります。

空の `rows` は最初に拒否します。これは `create_graphs()` を他から直接呼ぶ場合にも備えた検査です。

### 9.2 フォントと計測条件の文字列

```python
rcParams["font.sans-serif"] = [FONT_FAMILY, "DejaVu Sans"]
rcParams["font.size"] = FONT_SIZE
```

共通の文字サイズとフォント候補を設定します。`Meiryo` を使えない環境では、代替フォントで日本語が揃わない場合があります。設定した名前を印字するだけでフォントがインストールされるわけではありません。

`first = rows[0]` から基準区間長・倍率・評価間隔・平滑化幅を読み、`conditions` という説明文字列を作ります。先に全行の条件一致を確認しているので、代表の1行から説明を作れます。`f"...{first['mm_per_px']:g}..."` の `:g` は数値を簡潔に表示する指定です。

丸括弧内に隣り合って並ぶ複数のf文字列は、1つの文字列へ結合されます。`conditions` は複数要素のタプルではありません。タプルになるかどうかは、括弧だけでなくカンマの有無も関係します。

### 9.3 グループの二重辞書を作る

```python
key = (row["experiment_id"], row["section_id"])
if key not in groups:
    groups[key] = {}
groups[key][row["pass_number"]] = row
passes.add(row["pass_number"])
```

`groups` は外側が実験回・区間、内側がパス番号の辞書です。構造は次のようになります。

```text
groups
  ("run01", "a")
    0 → パス0の計測辞書
    2 → パス2の計測辞書
    4 → パス4の計測辞書
  ("run01", "b")
    0 → 区間b・パス0の計測辞書
    2 → 区間b・パス2の計測辞書
```

`groups[key][2]` は「そのグループのパス2の計測」を取り出します。`passes` は全グループに登場したパス番号をまとめる集合です。図の共通の横軸目盛りへ使います。

### 9.4 3種類の図を同じ手順で初期化する

`for title, ylabel, limits in (...)` は、図題・縦軸名・縦軸範囲の3つの組を、3図分繰り返します。

```python
figure = Figure(figsize=FIGURE_SIZE, layout="constrained")
axis = figure.subplots()
figure.suptitle(title)
axis.set_title(conditions, fontsize=FONT_SIZE - 2)
axis.set_xlabel("圧延パス数")
axis.set_ylabel(ylabel)
```

`layout="constrained"` は、図題や軸名などを収める配置調整です。`suptitle()` が図全体の題目、`set_title()` が座標領域の題目で、ここでは条件の説明を入れます。GUIウィンドウは開かず、メモリ上で図の内容を作っています。

`set_xticks(sorted(passes))` は、実際のパス番号の位置へ目盛りを置きます。数値軸なので、0→2の距離と2→6の距離は異なります。

`axhline(0, ...)` で0の水平線、`grid(alpha=0.3)` で薄い補助線を描きます。`alpha` は不透明度です。`margins(x=0.06)` は横方向の表示範囲へ余裕を持たせる指定です。

手動範囲が指定されていれば `set_xlim()`・`set_ylim()` で反映します。最後に図と座標領域をそれぞれのリストへ追加します。

### 9.5 グループごとの線種とマーカーを選ぶ

```python
for index, key in enumerate(sorted(groups)):
    group = groups[key]
    pass_numbers = sorted(group)
    label = f"{key[0]} / {key[1]}"
    line_style = LINE_STYLES[index % len(LINE_STYLES)]
    marker = MARKERS[index % len(MARKERS)]
```

グループを実験回・区間順に整列し、`index` は0、1、2…になります。線種が4種類なので、`index % 4` により0、1、2、3、0…と巡回します。マーカーも同様に7種類を巡回します。

**この版では線種とマーカーは実験回だけでなく、実験回・区間の組ごとに変わります。** 同じグループのDRとOPは同じ線種・記号で、色が違います。グループ数が増えれば、線種やマーカー単体は再利用されます。

`group` に0がなければ、ここでも例外にします。通常の呼び出しでは読込時に確認済みですが、`create_graphs()` を直接呼んだ場合にも初回値が必要だからです。

### 9.6 DRとOPを同じ処理で描く

```python
for edge, side, color in (
    ("left", "DR", DR_COLOR),
    ("right", "OP", OP_COLOR),
):
    values = []
    changes = []
    initial = group[0][f"{edge}_excess_percent"]
    for pass_number in pass_numbers:
        excess = group[pass_number][f"{edge}_excess_percent"]
        values.append(excess)
        changes.append(excess - initial)
```

最初の繰り返しでは `edge` が `"left"` になり、列名は `"left_excess_percent"` になります。次は `"right_excess_percent"` です。列名はCSV・辞書側の名前、DR／OPは図へ表示する側の名前です。

`initial` は各側のパス0です。`values` は超過率そのもの、`changes` はそこから初回値を引いた結果のリストです。ここで先ほどの `[1, 3, 5]` と `[0, 2, 4]` のような並びが作られます。

`axes[0].plot(pass_numbers, values, ...)` で超過率図へ、`axes[1].plot(pass_numbers, changes, ...)` で初回差図へ線とマーカーを描きます。

`label=f"{label} {side}"` は、たとえば `"run01 / a DR"` という凡例名です。`color`、`linestyle`、`marker` は、位置や数値を変更せず、見た目を指定します。

### 9.7 左右差を作り、凡例を追加する

```python
differences = []
for pass_number in pass_numbers:
    row = group[pass_number]
    differences.append(row["left_excess_percent"] - row["right_excess_percent"])
```

左右差は1パス内の対応するDRとOPを引きます。別パスや別区間の値は引きません。`axes[2].plot(...)` で、グループごとに1本の線を描きます。凡例名にはDR／OPを追加せず、`run01 / a` のようにします。

最後に各 `axis.legend(...)` で、`plot()` へ渡した `label` を一覧表示し、3枚のFigureを返します。この時点ではファイルへ保存していません。

### 9.8 欠測と線の意味

パス0と4しかなければ、x値は `[0, 4]` の2点です。パス2を0として追加することはありません。ただし `plot()` は0と4の点を直線で結びます。パス2を推定した値ではありません。欠測位置で線を途切れさせるためのNaN挿入も、この版にはありません。

グループごとに観測したパスだけを使うため、区間aにパス2があり区間bにないことも表現できます。横軸目盛りは全グループの和集合です。

## 10. write_graphs：入力を保護して保存する

### 10.1 上書きしてはいけない場所を集める

```python
inputs = [Path(__file__)]
for row in rows:
    inputs.append(Path(row["measurement_csv"]))
    inputs.append(Path(row["image_path"]))
```

保護するリストは、このスクリプト自身、入力CSV、CSVが示す元画像です。元画像はここでも読み込みません。保護するパスとして列挙しています。共通設定や `utils/` の全ファイルまで、一般的な保護対象として走査するわけではありません。

### 10.2 3つの保存先をすべて先に検査する

```python
paths = []
for name in ("excess.png", "change_from_initial.png", "dr_op_difference.png"):
    paths.append(check_output_path(directory / name, ".png", inputs))
```

`check_output_path()` は絶対パスへ解決し、拡張子が `.png` か、入力のどれかと同じ場所でないかを確認します。入力を上書きする指定なら保存前に拒否します。

既存の出力PNGがあるだけでは拒否しません。PNGの画素内容を検査したり、同名出力の上書き確認を出したりする関数でもありません。

### 10.3 図を作ってから順番に書く

```python
figures = create_graphs(rows)
directory.mkdir(parents=True, exist_ok=True)
for path, figure in zip(paths, figures):
    figure.savefig(path, dpi=SAVE_DPI)
return paths
```

`zip()` により、1枚目の場所と1枚目の図、2枚目の場所と2枚目の図…を対応させます。`savefig()` が実際のPNG保存です。Figureを作っただけでは保存されません。

3枚の一括保存を、全体で成功か失敗のどちらかにする仕組みはありません。たとえば2枚目で書込に失敗した場合、1枚目の保存済みPNGは残ります。ディスク書込失敗時の旧ファイル復元もありません。必要な結果は別のフォルダへ保存してから再実行します。

## 11. main：処理をつなぎ、利用者へ結果を知らせる

```python
def main() -> None:
    try:
        rows = read_pass_measurements(MEASUREMENTS)
        paths = write_graphs(GRAPH_DIRECTORY, rows)
    except (ValueError, OSError) as error:
        raise SystemExit(f"作図できません: {error}") from error
    for path in paths:
        print(f"保存: {path}")
```

読込と保存のどちらかで、値の不正や入出力の失敗が起きたら、説明を付けて終了します。正常終了では3つの保存先を表示します。

すべての種類のプログラム誤りを、この `except` が包むわけではありません。たとえば `MEASUREMENTS` の要素を文字列でない不正な型に書き換えると、想定外の例外になる場合があります。冒頭は説明された形で編集してください。

最後の `if __name__ == "__main__": main()` により、コマンドとして実行したときに `main()` を開始します。importして計算関数を読み込むだけなら、設定例のCSVを勝手に読んで保存することはありません。

## 12. よくある失敗をコードと結び付ける

| 表示・症状 | 対応する箇所 | 確認する内容 |
| --- | --- | --- |
| パス番号は偶数整数というエラー | `read_pass_measurements` の型・値の検査 | `2` と書いているか。`"2"`・`2.0`・奇数・負数になっていないか |
| 同じ実験回・区間ID・パス番号が重複 | `key in records` | 1計測につき1組か。別区間には別の区間IDを付けたか |
| 同じ計測CSVを重複指定 | `used_paths` | IDだけ変えて同じCSVを指定していないか |
| CSVの列が不足 | 共通 `read_lengths` | `02` の現行形式か。不足列と読込先の絶対パスを確認する |
| CSVは1行にするというエラー | 共通 `read_lengths` | 複数計測を1つのCSVへ結合していないか |
| 側辺長と超過率が一致しない | 共通 `read_lengths` | CSVの数値を片方だけ手で変更していないか |
| 計測条件が一致しない | 4列の `math.isclose` | 基準長・倍率・評価間隔・平滑化幅が全入力で同じか |
| パス0がない | 各実験回・区間の初回確認 | 区間aだけでなくbにも同じ実験回のパス0があるか |
| 図に平均・SDが出ない | この版の `create_graphs` | このコードは区間ごとの線を描く版。設定ミスではない |
| 日本語が欠ける | `rcParams` | 指定したフォントが実行環境で利用可能か |
| 点が見えない | `set_xlim` / `set_ylim` | 手動範囲で切り落としていないか |

CSVの不足列を埋めて数値の根拠を作り直すより、計測コードと共通処理の版を揃え、必要なら `02` で測定・保存し直してください。

## 13. 変更するときの具体的な目安

- 読むCSVを増やす：`MEASUREMENTS` に同じ4要素の形で追加する。各区間のパス0も指定する。
- 別の結果を残す：`GRAPH_DIRECTORY` を変える。
- 図を大きくする：`FIGURE_SIZE` を変える。単位はインチ。
- 文字を大きくする：`FONT_SIZE` を変える。図題・条件・凡例にはそこから少し小さくした値も使う。
- 画素数を増やす：`SAVE_DPI` を変える。計測値の精度は変わらない。
- 色や記号を変える：`DR_COLOR` など、`LINE_STYLES`、`MARKERS` を変える。巡回に使うので線種・マーカーの並びを空にしない。
- 比較する図の範囲を揃える：各 `*_LIMITS` に下限・上限を指定する。負の初回差や左右差も見える範囲か確認する。

初回差の式、`group[0]`、CSVの検証を変更すると、図の意味が変わります。色やフォントの変更とは区別し、数値例を使って確認します。

このスクリプトは、区間IDが圧延後も同じ材料位置を指しているか、抽出が正しいか、基準長が実験に適切かまでは判定しません。計測時の確認PNGと実験記録が必要です。

## 14. 読み終えた後の確認問題

1. `("run01", "a", 2)` と `("run01", "b", 2)` が別計測になる理由を説明できるか。
2. 条件比較に使う `reference_measurement` と、初回差に使う `group[0]` の違いを説明できるか。
3. パス0のDRが2%、パス4が5%なら、初回差が3ポイントになると追えるか。
4. 同じパスのDRが5%、OPが3%なら、左右差が2ポイントになると追えるか。
5. `values.append(excess)` と `changes.append(excess - initial)` の違いを説明できるか。
6. パス0・4しかない場合、パス2のデータ行は作られないが線は結ばれる、と説明できるか。
7. `create_graphs()` の戻り値は図、`write_graphs()` の戻り値は保存先のリスト、と区別できるか。

## 15. この章の確認範囲

対象ファイルと `utils/measurement_csv.py`・`utils/file_io.py`・`workflow_settings.py` を照合しています。冒頭の設定値と、4関数に分かれた実装が対象です。

合成CSVを一時フォルダへ作る独立した確認で、読込順の整列、区間ごとの初回差、DR−OP差、PNG3枚の保存、1800×1080pxの画像サイズを照合しました。実験データの読込や既存出力の上書きは行っていません。

既存の `tests/test_pass_metrics.py` には、別の版の `summarize_measurements()`・平均・SDなどを前提にする試験があるため、この章の版について「既存の作図試験が全件成功した」とは記載しません。本番CSV・別PCのフォント・原稿へ組み込んだ体裁は未確認です。

[全体の入口へ戻る](../IMPLEMENTATION_GUIDE.md)
