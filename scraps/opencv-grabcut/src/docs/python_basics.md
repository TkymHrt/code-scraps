# 基礎編：この6本を読むためのPython・配列・ファイル・GUI

[全体の入口へ戻る](../IMPLEMENTATION_GUIDE.md)

この章はPython全体の教科書ではありません。対象6本に出てくる書き方を、コードを読むために説明します。例に「説明用」と書いてある場合は、考え方を小さく示した例であり、実ファイルの丸写しではありません。説明用の例はそれぞれ別の例として読んでください。実コードの抜粋は、前後で定義した変数などを必要とするため、単独で実行できるとは限りません。

## 1. プログラムと実行順

プログラムは、コンピューターに行わせる処理を決まった書き方で並べたものです。`.py` ファイルにはPythonの文章である「ソースコード」が入っています。PowerShellから実行を指示すると、Pythonがソースを読み、指示された計算やファイル操作を行います。

基本は上から順ですが、関数の定義・条件分岐・繰り返し・GUIの待機があるため、ファイルのすべての行を1回ずつ実行するわけではありません。

```python
# 説明用
def greet():
    print("こんにちは")

print("開始")
greet()
print("終了")
```

順序は「`greet` という処理を登録する」→「開始を表示」→「`greet()` の中へ入り、こんにちはを表示」→「呼び出し元へ戻る」→「終了を表示」です。`def` の直後に、その中の `print()` が実行されるわけではありません。

### コメント・文字列・空行

- 文字列の外にある `#` からその行の末尾まではコメントです。説明のための文章で、通常の処理として実行しません。色の文字列 `"#d96c17"` の `#` は文字列の一部です。
- `"文字"` や `'文字'` は文字列です。引用符そのものは値に含めません。どちらの引用符も使えます。
- ファイルや関数の最初にある `"""説明"""` は、説明を持つ特別な位置の文字列で、ドキュメンテーション文字列と呼びます。
- 空行は処理の区切りを読みやすくします。

## 2. インデントとコロン

```python
# 説明用
length_mm = 100
if length_mm > 0:
    print("計測できる長さです")
    print(length_mm)
print("確認終了")
```

`if ...:` の末尾の `:` は「この条件のときに行うまとまりが続く」という合図です。行頭の空白をインデントと呼びます。上の2つの `print()` は同じ深さなので、どちらも `if` の中です。最後の行は左へ戻っているので、`if` の外です。

Pythonでは、この空白が処理の所属を決めます。見た目だけの飾りではありません。対象コードでは通常4個の空白で1段深くしています。`def`、`for`、`try`、`except`、`with` の後にも同じ考え方が使われます。

括弧 `()`・角括弧 `[]`・波括弧 `{}` の内側では、1つの式を複数行に分けられます。長い関数呼び出しが数行に分かれていても、別々の処理とは限りません。

## 3. 変数と代入：値に名前を付ける

```python
# 説明用
scale = 0.25
length_px = 400
length_mm = length_px * scale
```

`=` は、右側を計算して、その結果に左側の名前を付ける「代入」です。数学の「左右は等しい」という宣言とは用途が違います。上では `length_mm` に `100.0` が入ります。

変数名を読むときは単位も確認します。`length_px` は画素数、`length_mm` はmm、`MM_PER_PX` は1pxあたりのmmです。式が似ていても、単位が違えば意味が変わります。

```python
# 説明用
count = 2
count = count + 1
count += 1
```

2行目は、変更前の `count` に1を足して、同じ名前へ入れ直します。3行目も、この整数の例では同じ意味です。最終値は `4` です。NumPy配列での `+=` は配列そのものを更新することがあり、後述の参照の共有に注意が必要です。

`height = width = 1` は、両方に `1` を代入します。`contour = bounds = axis = None` は、3つをすべて「未設定」に戻します。

大文字の `MM_PER_PX` などは「設定値として扱う」という命名上の約束です。Pythonが自動で変更を禁止するものではありません。

## 4. 値の種類：数値・文字列・真偽値・None

| 書き方 | 種類 | この題材での例 |
| --- | --- | --- |
| `4` | `int`、整数 | パス番号、画素の添字 |
| `0.25` | `float`、浮動小数点数 | mm/px、計算した距離 |
| `"run01"` | `str`、文字列 | 実験回ID、ファイル名 |
| `True` / `False` | `bool`、真偽値 | 検査結果、条件 |
| `None` | 値がないことを表す特別な値 | 画像未読込、軸未推定、軸範囲の自動指定 |

`None` と `0`、空文字列 `""` は別の値です。距離0mmと距離未計算も意味が違います。

`float("100.5")` は文字列を数値へ変換します。`int(100.9)` は `100` になり、小数部分を切り捨てます。`str(100)` は文字列 `"100"` になります。数値への変換に失敗すると例外が発生します。

`float` は多くの小数を厳密には表せません。計算結果にごく小さなずれがあるため、このコードでは `math.isclose()` などで近さを比較します。一方、`nan` や無限大は通常の有限な計測値として扱えないため、`math.isfinite()` や `np.isfinite()` で検査します。

## 5. 演算子を読む

| 記号 | 意味 | 例 |
| --- | --- | --- |
| `+` / `-` | 足す／引く | `excess - initial` |
| `*` / `/` | 掛ける／割る | `length_px * MM_PER_PX` |
| `**` | べき乗 | `difference ** 2` は2乗 |
| `%` | 割った余り | `pass_number % 2` は偶数なら0 |
| `==` / `!=` | 等しい／等しくないか比較 | `pass_number == 0` |
| `<` / `<=` / `>` / `>=` | 大小の比較 | `length_mm <= 0` |
| `and` / `or` / `not` | 両方／どちらか／否定 | `not rows` |
| `in` / `not in` | 含まれる／含まれない | `key in records` |
| `is None` / `is not None` | Noneかどうか | `image is None` |
| `@` | NumPyでは行列積・内積 | `(points - origin) @ direction` |
| `&` / `\|` | NumPyの真偽配列では要素ごとのAND／OR | `(labels == 1) \| (labels == 3)` |

`=` と `==` を区別してください。前者は値を入れる指示、後者は比較して `True` または `False` を得る計算です。

`and` と `or` は左から判定し、必要がなければ右側を評価しません。たとえば `image is None or image.shape[0] == 0` では、画像が `None` なら後半を評価しないため、`None.shape` を読み取らずに済みます。

配列全体に `and` を使って画素ごとの比較をすることはできません。配列の条件は `&`・`|` で結び、比較式をそれぞれ括弧で囲みます。普通の条件分岐の `or` と、マスクを作る `|` を区別します。

## 6. リスト・タプル・辞書・集合

### リスト：順番のある複数の値

```python
# 説明用
values = [1.0, 3.0]
values.append(5.0)
first = values[0]
last = values[-1]
```

`[]` で作るリストには、順番を持つ値が入ります。添字は0から始まるため、`values[0]` は先頭です。`append()` は末尾に1つ追加します。上では `[1.0, 3.0, 5.0]` になります。`-1` は末尾を指します。空リストは `[]` です。

`len(values)` は要素数、`values.clear()` は全要素の削除、`values.pop(index)` は指定位置の取り出しと削除です。

### タプル：位置に意味を持たせた組

```python
# 説明用
entry = ("run01", 2, "a", "output/run01_pass02_a.csv")
experiment_id, pass_number, section_id, csv_name = entry
```

この組では、1番目は実験回、2番目はパス番号、3番目は区間ID、4番目はCSVです。2行目は「アンパック」で、順番に4つの変数へ割り当てます。右側が4要素なのに左側が3変数なら、そのままでは受け取れません。

タプルは要素の位置を後から入れ替えたり代入したりできません。リストとの違いは、単に括弧の見た目だけではありません。`(3,)` のように1要素のタプルにはカンマが必要です。NumPyで `shape == (3,)` と書くときにも出てきます。

### 辞書：名前や組を鍵にして値を取り出す

```python
# 説明用
row = {"left_mm": 103.0, "right_mm": 101.0}
dr = row["left_mm"]
row["experiment_id"] = "run01"
```

`{キー: 値}` という対応を保持するのが辞書です。`row["left_mm"]` は、数値の添字ではなく、キー文字列で値を探します。存在しないキーを `[]` で読むと `KeyError` になります。

`row.items()` はキーと値の組を順に返し、`row.update(other)` は別の辞書の内容を追加します。同じキーがあれば値は置き換わります。辞書は `for key in row:` で回すとキーを返します。

`04` は `("run01", "a", 2)` のようなタプルを辞書のキーにしています。「実験回・区間・パスが全部一致する1計測」を特定できます。要素を変更できるリストは、この用途のキーにはできません。

### 集合：重複のない値の集まり

`set()` は空集合です。`used_paths.add(path)` で値を加え、`path in used_paths` で既出かを調べます。`04` ではCSVの重複と、横軸に出すパス番号の重複を除く用途に使います。集合自体の並びに頼らず、必要な箇所では `sorted()` で整列します。

空の `{}` は辞書です。空集合ではありません。

## 7. 繰り返し・条件分岐・途中で抜ける処理

```python
# 説明用
values = [0, 2, 4]
for value in values:
    if value == 0:
        continue
    print(value)
```

`for` は、リストから1つずつ値を受け取り、中の処理を繰り返します。`continue` は今回の繰り返しの残りを飛ばし、次の値へ進みます。上では2と4を表示します。

`break` は繰り返し全体を終了します。`while True:` は、`break` や例外などで抜けるまで繰り返します。校正では、問題写真を除いて再試行するために使っています。

`return` は、繰り返しだけでなく**その関数の実行を終えます**。`return result` なら結果を返し、値なしの `return` なら `None` を返します。GUIでファイル選択を取り消したときの `return` は、GUI全体を終了するのではなく、そのボタンの処理を終えて操作待ちへ戻ります。

`if`・`elif`・`else` は条件に応じた分岐です。該当した枝の処理を行い、別の枝は飛ばします。`if not rows:` は、この題材のリストなら「空だったら」と読めます。NumPy配列の空判定へ、そのまま置き換えないでください。

### enumerate・zip・sorted

```python
# 説明用
names = ["a.png", "b.png"]
errors = [0.3, 0.5]
for index, name in enumerate(names):
    print(index, name)
for name, error in zip(names, errors):
    print(name, error)
```

`enumerate()` は「0から始まる番号と値」を返します。`zip()` は複数の並びの同じ位置を組にします。標準の `zip()` は短い方の長さで終了するため、このコードは元々対応する長さのリストを渡す前提です。

`sorted(values)` は並べ替えた新しいリストを返します。文字列は文字列として、数値は数値として比べます。タプルの整列は先頭の要素を比べ、同じなら次を比べます。`04` の辞書キーの整列が、この規則で実験回→区間ID→パス番号の順になります。

## 8. 関数・引数・戻り値・型注釈

実際のコードの見出しを見ます。

```python
def read_pass_measurements(measurements: list[tuple[str, int, str, str]]) -> list[dict]:
    records = {}
```

`def` は関数定義、`read_pass_measurements` は関数名、`measurements` は呼ぶ側から受け取る値の名前です。ここでは見出しと最初の行だけを抜き出しています。

`measurements: list[tuple[str, int, str, str]]` は「文字列・整数・文字列・文字列という4要素のタプルを並べたリストを想定する」という型注釈です。`-> list[dict]` は「辞書を並べたリストを返す想定」です。型注釈自体が値を変換したり、不正な値を自動で拒否したりするわけではありません。実際の検査は関数内で行います。

`-> None` は、呼び出し元へ利用する結果の値を返さない想定です。保存・表示・画面の更新などの仕事は行えます。

関数の呼び出しでは、`write_graphs(GRAPH_DIRECTORY, rows)` のように順番で渡す引数と、`figure.savefig(path, dpi=SAVE_DPI)` のように名前で渡す「キーワード引数」があります。`dpi=` は保存解像度という引数名です。

`def render(_event=None):` のような `=None` は、引数を省略した場合の初期値です。引数名先頭の `_` は、このコードでは「受け取るが使わない」という意図を示しています。

`type Axis = tuple[np.ndarray, np.ndarray]` は、型の書き方に `Axis` という別名を付けます。軸の数値を計算している行ではありません。`Path | None` など型の間の `|` は「どちらの型もあり得る」という意味で、画素のOR演算とは別の使い方です。

## 9. import：別のファイルの道具を使う

```python
import math
import cv2 as cv
import numpy as np
from pathlib import Path
from utils.file_io import read_image
```

- `math` はPythonに付属する数値用のモジュールです。`math.isfinite()` のように使います。
- `cv2` はOpenCVのPython向けの名前です。`as cv` により、このファイル内では `cv` と短く呼びます。
- `numpy` も、このファイルでは `np` と呼びます。
- `from pathlib import Path` は、`pathlib` 内の `Path` を取り出し、`Path(...)` と直接使う書き方です。
- `utils.file_io` は、このプロジェクト内の `utils/file_io.py` です。外部ライブラリと同じ書き方で、自作の処理も読み込みます。

`image.shape` の `.` は、その値に属する情報や操作をたどる記号です。`shape` は属性、`image.copy()` のように `()` を付けて実行する操作はメソッドと呼びます。最初は「情報を読む」「処理を呼ぶ」と区別できれば十分です。

読み込まれたファイルの最上位のコードは、import時にも評価されます。そのため、各スクリプトの最後に次の仕組みがあります。

```python
if __name__ == "__main__":
    main()
```

ファイルを直接実行したとき、`__name__` は `"__main__"` になり、`main()` を呼びます。別ファイルからimportしたときには別の名前になり、この条件の中は実行しません。テストが関数を読み込むだけでGUIや画像保存を始めないためにも役立ちます。

## 10. パス：ファイルの場所を表す

```python
from pathlib import Path

# workflow_settings.py にある書き方
BASE_DIRECTORY = Path(__file__).resolve().parent
INPUT_DIRECTORY = BASE_DIRECTORY / "input"
```

`__file__` は、この行が書いてあるPythonファイルの場所です。`Path(...)` は場所を操作するための値を作り、`.resolve()` は絶対パスへ解決し、`.parent` は親フォルダを返します。`workflow_settings.py` の場合、`BASE_DIRECTORY` は `src/` になります。

`Path` 同士や `Path` と文字列を `/` でつなぐと、パスを組み立てます。この位置の `/` は数値の割り算ではありません。`src/` の場所に `"input"` を足して `src/input/` を表します。

絶対パスはドライブから指定した場所、相対パスは基準から見た場所です。`04` は明示的に `BASE_DIRECTORY / csv_name` とするので、相対CSV名はPowerShellの現在地ではなく `src/` が基準です。Windowsの絶対パスを右側へ渡す場合は、その絶対パスを使います。

| 操作 | 例のパスが `C:/work/sample.jpg` の場合 |
| --- | --- |
| `.name` | `sample.jpg` |
| `.stem` | `sample` |
| `.suffix` | `.jpg` |
| `.parent` | `C:/work` を表すPath |
| `.with_suffix(".png")` | `C:/work/sample.png` を表すPath |
| `.with_name("other.png")` | `C:/work/other.png` を表すPath |

これらは、呼んだだけではファイル名を実際に変更しません。新しい場所を表す値を作っています。ファイルを作るのは `write_bytes()`・`savefig()`・`open("w", ...)` などの書込操作です。

`mkdir(parents=True, exist_ok=True)` は、必要な親フォルダも作り、フォルダがすでに存在しても、それだけを理由には失敗しない指定です。書込権限がない場合などは失敗します。

Python文字列にWindowsのパスを書く場合、`"C:/work/sample.png"` のように `/` を使うと、`\n` などのエスケープと衝突しません。`r"C:\work\sample.png"` の `r` は、バックスラッシュの特別な解釈を抑える書き方です。

## 11. 画像は数値の配列

NumPyの `ndarray` は、数値を格子状に保持して計算するための配列です。OpenCVが読み込む通常のカラー画像は、概ね次の形です。

```text
image.shape == (高さ, 幅, 色の成分数)
例：高さ800px・幅1200pxのカラー画像なら (800, 1200, 3)
image.dtype == uint8
```

`uint8` は、各数値を0〜255で表す符号なし8ビット整数です。OpenCVでのカラー成分は、このコードではB・G・Rの順です。赤を強くするなら `(0, 0, 255)` です。Tkinter向けのRGB表示では順番が異なるので変換します。

### x・yと行・列の順番が逆になる理由

- 点の座標は通常 `(x, y)`、つまり横・縦の順です。
- 配列は `image[y, x]`、つまり行・列の順です。
- 画像サイズをOpenCVへ渡すときは `(width, height)` という横・縦の順がよく使われます。
- `.shape` は `(height, width, ...)` という縦・横の順です。

これは特に間違えやすい箇所です。`height, width = image.shape[:2]` で取り出し、サイズ指定で `(width, height)` と並べ直している行を見つけてください。

画像座標の原点は左上で、xは右へ、yは下へ増えます。横幅1200pxの画素添字は0〜1199なので、最後のxは `width - 1` です。

## 12. 添字・スライス・reshape

```python
import numpy as np

# 説明用
points = np.array([[10, 20], [30, 40], [50, 60]], dtype=np.float64)
x_values = points[:, 0]
first_two = points[:2]
reversed_points = points[::-1]
```

`points` の形は `(3, 2)` です。3個の点にそれぞれxとyがあります。`points[:, 0]` は「すべての行の0列目」、つまり `[10, 30, 50]` です。`:` は、その軸をまとめて選ぶ記号です。

`start:stop` はstartを含み、stopを含みません。`points[:2]` は0行目と1行目を取り出します。`image[top:bottom, left:right]` もbottom行・right列を含みません。`[::-1]` は末尾から逆順に取り出す指定です。

`reshape(-1, 2)` は、数値の並びを「2個ずつの行」に組み直します。`-1` の場所の要素数は、元の全要素数からNumPyが決めます。OpenCVの輪郭が `(N, 1, 2)` で返ってきたときに、扱いやすい `(N, 2)` にする用途があります。形を変えるのであって、座標の値を拡大縮小する処理ではありません。

`ravel()` は平らな1次元の並びへ変えます。`astype(np.int32)` は、各数値を32ビット整数へ変換します。点IDを添字へ使う場面や、描画用の整数座標を作る場面に出てきます。

### 代入・ビュー・copy

`other = image` と書いても、画像の独立した複製は作られません。2つの名前から同じ配列を参照します。通常のスライスも元配列を共有する「ビュー」になるため、スライスへの書込が元へ影響する場合があります。独立した画像を編集したい箇所では `.copy()` を使います。NumPyの公式説明でも、この共有が説明されています。[配列の添字とスライス](https://numpy.org/doc/stable/user/basics.indexing.html)

## 13. 配列の計算・マスク・軸

```python
import numpy as np

# 説明用
points = np.array([[10.0, 20.0], [30.0, 40.0]])
shifted = points + (100, 200)
```

NumPy配列への加算は、要素ごとに行います。この例では、各行のxへ100、yへ200を足し、`[[110, 220], [130, 240]]` になります。形の合う小さい値を各行へ対応させる仕組みをブロードキャストと呼びます。

同じ `+` でも、Pythonリストに対する `list_a + list_b` は連結です。対象が配列かリストかを確かめて読んでください。

```python
import numpy as np

# 説明用
labels = np.array([[0, 1, 3], [2, 0, 3]], dtype=np.uint8)
foreground = (labels == 1) | (labels == 3)
mask = np.zeros(labels.shape, dtype=np.uint8)
mask[foreground] = 255
```

`labels == 1` は各場所に `True` / `False` が入った配列を作ります。`foreground` がTrueの場所だけを `mask[foreground]` で選び、255を入れます。二値マスクは「採用する画素／しない画素」の地図です。カラー画像そのものとは別です。

`np.zeros((height, width), dtype=np.uint8)` はすべて0、`np.full((height, width), value, dtype)` はすべて指定値の配列を作ります。最初の `(height, width)` は配列の形です。

`array.any()` は「1つでもTrueか」、`array.all()` は「全部Trueか」を返します。`np.isfinite(points).all()` はすべての座標が有限であるかを検査します。

2次元配列で `axis=0` は行方向にまとめ、列ごとの結果を作ります。`axis=1` は列方向にまとめ、行ごとの結果を作ります。たとえば `points.mean(axis=0)` は点群全体のx平均・y平均という2要素になります。幾何学的な長手の「軸」と、NumPyの `axis=0` などの「配列の次元」は別の意味です。

## 14. ベクトル・内積・行列を小さく読む

この題材の「ベクトル」は、主に `[x, y]` のような2個の数値で、点の位置や方向を表します。2点を引くと、片方からもう片方への移動量になります。

```python
import numpy as np

# 説明用
start = np.array([10.0, 20.0])
end = np.array([13.0, 24.0])
direction = end - start
length = np.linalg.norm(direction)
unit_direction = direction / length
```

`direction` は `[3, 4]`、長さは `sqrt(3² + 4²) = 5`、`unit_direction` は `[0.6, 0.8]` です。長さ1の方向ベクトルにしておくと、「何px進むか」と「どちらへ進むか」を分けて扱えます。

`(point - origin) @ unit_direction` は、その点が基準から軸方向にどれだけ進んだ位置にあるかを表す内積です。軸が `[0, 1]` なら、`[3, 4] @ [0, 1] = 4` です。横方向のずれ3は軸方向の距離へ加わりません。

3×3の行列は、画像の点の位置を一括して変換するためにも使います。2次元の点を一時的に `[x, y, 1]` として扱い、変換後は最後の成分で割って2次元へ戻す方法です。これを同次座標と呼びます。`01` の章で、どの座標からどこへ変換しているかを具体的に説明します。

`A @ B` は行列積で、`A * B` という要素ごとの積とは異なります。通常の列ベクトルの考え方なら、`A @ B @ point` は右側のBから点へ適用します。計算順を逆にしても同じとは限りません。

## 15. 文字列の整形・内包表記・展開

```python
# 説明用
length_mm = 103.123456
edge = "left"
message = f"長さ: {length_mm:.3f} mm"
column = f"{edge}_excess_percent"
```

先頭の `f` は、`{...}` の中を評価して文字列へ埋め込む指定です。`message` は `"長さ: 103.123 mm"`、`column` は `"left_excess_percent"` になります。

`:.3f` は小数点以下3桁、`:g` は数値を簡潔な形で表示する形式、`:.12g` は有効数字12桁です。`{red:02x}` は16進数2桁の色成分を作ります。これらは主に表示・保存する文字列の形を変えるもので、元の数値変数の精度をその場で変えるものではありません。

`text.strip()` は前後の空白を取り除いた新しい文字列を返し、`suffix.lower()` は英字を小文字にした文字列を返します。`"\n"` は文字列内の改行です。

```python
# 説明用
labels = [1, 3]
regions = {label: [] for label in labels}
```

これは辞書の内包表記です。「ラベルを1つずつ取り、それぞれ空リストを作る」と読みます。対象のGUIで多角形をラベル別に持つ初期化に使われます。普通の `for` で書くと次と同じ内容です。

```python
# 説明用
labels = [1, 3]
regions = {}
for label in labels:
    regions[label] = []
```

`func(*values)` の `*` は要素を複数の引数へ展開します。`func(**options)` の `**` は辞書をキーワード引数へ展開します。関数定義の `def on_interval_changed(*_args):` は、逆に複数の位置引数を1つのタプルとして受け取ります。べき乗の `** 2` とは位置と用途が違います。

## 16. 例外：失敗を呼び出し元へ知らせる

```python
# 説明用
def read_length(text):
    try:
        length = float(text)
    except ValueError as error:
        raise ValueError("長さを数値で入力してください") from error
    return length
```

`try` は失敗する可能性のある処理、`except` は指定された種類の失敗への対応です。`as error` で失敗の情報を受け取ります。`raise` は例外を発生させて、通常の処理を中断します。`from error` は元の原因とのつながりを残します。

`ValueError` は値が条件に合わない失敗、`OSError` はファイルや入出力の失敗、`cv.error` はOpenCVの失敗などに使われます。ただし補助関数が、ライブラリの例外を `ValueError` へ変換して伝える場合もあります。

対象コードには `except (ValueError, OSError) as error:` のような複数種類の指定があります。`02` には **`except OSError, cv.error:`** という括弧なしの指定もあります。これは、このプロジェクトが使うPython 3.14で認められる構文です。古いPythonの構文エラーと混同しないでください。この行では `as error` による例外変数の受取はしていません。[Python 3.14のexcept構文](https://docs.python.org/3.14/reference/compound_stmts.html#except-clause)

`raise SystemExit("説明")` は、コマンド実行を説明付きで終了させます。GUIのように `status.set(str(error))` してから `return` する処理なら、失敗を画面に表示し、その操作だけを終えます。どこで例外を受け取るかによって、利用者から見た動作が変わります。

### withとファイルの文字コード

```python
# 説明用：実行すると指定先の内容を上書きする例です
from pathlib import Path

path = Path("example.csv")
with path.open("w", encoding="utf-8-sig", newline="") as output:
    output.write("name,value\na,1\n")
```

`with` は、処理を抜けるときにファイルを閉じる後始末を行います。`"w"` は書込で、既存ファイルがあれば内容を置き換えます。`utf-8-sig` はBOM付きUTF-8で、CSVをExcelなどへ渡す用途を考慮しています。CSVモジュールに渡す `newline=""` は、改行の扱いをCSV側へ任せるための指定です。

## 17. GUI：画面を作った後に利用者の操作を待つ

コマンド用の `00`・`01`・`04` は、基本的に読み込み→計算→保存→終了です。`02` のGUIは、画面を作った後、`root.mainloop()` で操作を待ちます。

```text
mainが開始する
  → 状態変数と関数を用意する
  → ボタンや画像表示領域を作る
  → ボタンと処理を結び付ける
  → mainloopで待つ
       → 画像読込ボタンが押されたら load_image
       → 画像がクリックされたら click_image
       → 計測ボタンが押されたら calculate
       → 各関数が終わると再び待つ
```

このように、何か起きたときに呼ばれる関数をコールバックと呼びます。

`command=calculate` は、ボタンへ関数そのものを渡す指定です。`command=calculate()` と書くと、その場で計算を実行して戻り値を渡してしまい、意味が変わります。

`canvas.bind("<ButtonPress-1>", click_image)` は、左クリックと関数を結びます。イベント用の関数は `event` を受け取り、`event.x`・`event.y` からCanvas内のクリック位置を調べます。画像が拡大・移動されていれば、そのまま元画像の座標にはできません。`02` の章で逆変換を説明します。

### ネストした関数とnonlocal

`02` では、`main()` の中に `load_image()` などを定義します。これらは `main()` の状態変数を参照できます。

```python
# 説明用
def outer():
    count = 0

    def add_one():
        nonlocal count
        count = count + 1

    add_one()
    return count
```

`nonlocal count` は、内側の関数で新しいローカル変数を作るのではなく、外側の関数の `count` を変更する指定です。上の `outer()` は `1` を返します。`02` では、読込画像・軸・計測結果などを複数のコールバックで共有するために使います。

辞書の中身の変更やリストの `append()` は、外側の名前自体を付け直す処理とは違うため、常に `nonlocal` が必要なわけではありません。「名前を別の値へ代入し直すか」を見分けます。

### Tkinterの変数と普通の変数

`tk.StringVar()` は、入力欄やラベルと連動させるためのTkinter側の値です。普通の文字列変数とは異なり、`.get()` で現在値を読み、`.set("...")` で書き換えます。`trace_add("write", on_interval_changed)` は、入力値が書き換わったときに呼ぶ処理を登録します。

画面を拡大する `scale` と、実寸換算の `MM_PER_PX` も別物です。表示だけ大きくしても、元画像の画素間隔や計測倍率は変わりません。

## 18. 読むときのチェック例

複雑な1行に出会ったら、次の4つに分けて読みます。

1. 右側が何を受け取るか。型・形状・単位は何か。
2. どの関数・演算で値を変えるか。
3. 左側へどんな値が返るか。
4. 失敗した場合、どこで受け止めるか。

たとえば `length_mm = float(np.linalg.norm(steps, axis=1).sum()) * MM_PER_PX` なら、「点間の差の配列」→「各差の長さ」→「全区間の和」→「通常のfloat」→「mm換算」です。各章では必要な箇所を、このように中間結果へ分けて説明します。

基礎の追加資料として [Python公式チュートリアル](https://docs.python.org/ja/3.14/tutorial/) と [NumPyの初心者向け資料](https://numpy.org/doc/stable/user/absolute_beginners.html) があります。この解説では、実装に出てくる順に必要な部分を扱うので、公式資料を先に全部読む必要はありません。

[次は00_1：板生成の解説へ](00_1_generate_charuco_board.md)
