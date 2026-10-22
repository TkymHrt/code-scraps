# 01_rectify_images.py を上から理解する

この文書は [01_rectify_images.py](../01_rectify_images.py) の現行実装を、Python の記法から説明します。全体の入口は [実装解説の案内](../IMPLEMENTATION_GUIDE.md)、代入・関数・配列などの共通説明は [Python の基礎](python_basics.md) です。この文書中の数値例は、処理を理解するための例であり、本番カメラの設定値ではありません。

## 1. このスクリプトが実現すること

写真の中の「画素で測った長さ」を、そのまま物体の実寸にはできません。レンズの歪みがあると直線が曲がり、斜めから撮ると手前と奥で見かけの倍率が変わるためです。このコードは、校正済みの魚眼カメラの係数でレンズの歪みを直し、写真内の ChArUco 板の既知の寸法で遠近を補正し、一定の `MM_PER_PX` に揃えた PNG を保存します。

処理の順序は次のとおりです。

~~~text
入力写真を読む
  → 魚眼レンズの歪みを補正する
  → 歪み補正後の画像から ChArUco 板を検出する
  → 画像座標から板の平面上の mm 座標へ移す変換を求める
  → 写真に写った向きを考慮する
  → 出力範囲と出力の画素数を決める
  → 0.25 mm/px などの一定倍率へ変換する
  → PNG を保存する
~~~

このコードでは、**補正する写真の一枚一枚に板が必要**です。各写真で板を検出し直すためです。固定カメラで撮影し、板のある基準画像だけから全フレームを補正する場合は、[基準画像方式の解説](01_rectify_frames_from_reference.md) を読みます。

| 項目 | このコードの扱い |
| --- | --- |
| 入力 | `INPUT_DIRECTORY` 直下の対応画像 |
| 出力 | `RECTIFIED_DIRECTORY` 直下の PNG |
| 変換の基準 | 各写真に写った ChArUco 板 |
| レンズ係数 | 冒頭の三つの設定。自動校正はしない |
| mm と px の対応 | `workflow_settings.py` の `MM_PER_PX` |
| 出力範囲 | 歪み補正後の画像に対する `RECTIFY_ROI` |
| 処理対象の面 | 板と同じ平面として扱える試料面 |

板と試料の高さや傾きが異なる場合、その差をこの二次元変換だけで復元することはできません。また、ここでは試料の伸びや凹凸を計測前に消さないよう、試料そのものを「四角にする基準」には使いません。

## 2. 最初に区別する四つの座標

後の式に入る前に、同じ二つの数字でも何を表しているかを分けます。

| 座標 | 例 | 単位と意味 |
| --- | --- | --- |
| 元写真の座標 | `(480, 360)` | px。魚眼の歪みを含む |
| 歪み補正後の画像座標 | `(u, v)` | px。この画像で板を検出する |
| 板の平面の座標 | `(X, Y)` | mm。板の実寸で決まる |
| 保存 PNG の座標 | `(x_out, y_out)` | px。一定の mm/px に換算し、左上へ移動したもの |

OpenCV の通常の画像座標は右向きが x、下向きが y です。NumPy の画像配列では `image[y, x]` の順に参照します。座標の `(x, y)` と、画像配列の添字の `[y, x]` を混同しないでください。

`MM_PER_PX = 0.25` は「1 px の間隔が 0.25 mm に相当する」という意味です。例えば保存 PNG 上の 100 px の距離は 25 mm です。倍率を 0.125 にすると同じ実長が約二倍の画素数になります。細かい出力にしても、元写真になかった細部が実測情報として増えるわけではありません。

## 3. import と設定を読む

### 3.1 使う道具の読み込み

~~~python
import math
from pathlib import Path

import cv2 as cv
import numpy as np
~~~

`import` は、別のモジュールにある機能を使えるようにする記述です。`math.isfinite()` で数値が有限か調べ、`Path` でフォルダやファイルの場所を扱います。`cv2 as cv` は OpenCV を `cv` という短い名前で、`numpy as np` は NumPy を `np` という名前で使う宣言です。`as` は別名を付けるもので、画像を変換する処理ではありません。

`from utils.file_io import ...` は、この題材の [utils/file_io.py](../utils/file_io.py) から画像一覧・読込・保存の関数を読み込みます。`from workflow_settings import (...)` は、[共通設定](../workflow_settings.py) に書かれた値を読み込みます。括弧の中を複数行にすることで、必要な設定名を一つずつ確認できます。

共通設定の現行値は次のとおりです。

| 名前 | 現行値 | 役割 |
| --- | --- | --- |
| `BOARD_SQUARES` | `(7, 5)` | 板の横・縦のマス数 |
| `SQUARE_MM` | `30.0` | 一つのマスの一辺、mm |
| `MARKER_MM` | `18.0` | マスに入るマーカーの一辺、mm |
| `MM_PER_PX` | `0.25` | 補正 PNG 上の一画素の間隔、mm/px |
| `RECTIFY_ROI` | `(0.25, 0.0, 0.75, 1.0)` | 歪み補正後の画像の中央幅 50%、高さ全体 |
| `INPUT_DIRECTORY` | `src/input/` | 補正する写真を置く場所 |
| `RECTIFIED_DIRECTORY` | `src/output/rectified/` | 補正結果を保存する場所 |

共通設定の `BASE_DIRECTORY = Path(__file__).resolve().parent` は、設定ファイル自身がある `src/` を基準にします。そのため既定の入出力先は、実行した PowerShell の現在の場所ではなく、設定ファイルの場所に結び付いています。設定は起動時に読み込まれるため、変更したらスクリプトや GUI を起動し直します。

### 3.2 三つのカメラ設定

~~~python
CALIBRATION_SIZE: tuple[int, int] | None = None
CAMERA_MATRIX: list[list[float]] | None = None
DIST_COEFFS: list[float] | None = None
~~~

一行目を細かく読むと、`CALIBRATION_SIZE` が変数名、`: tuple[int, int] | None` が値の種類の説明、`= None` が実際の代入です。型注釈は値を自動で変換する機能ではありません。`tuple[int, int]` は整数二つのタプル、`| None` は「未設定の `None` もあり得る」を表します。

`list[list[float]]` は、小数を並べたリストを、さらにリストにまとめたものです。`CAMERA_MATRIX` には 3 行 3 列のカメラ行列 K が入ります。`DIST_COEFFS` には魚眼モデルの四つの歪み係数 `k1, k2, k3, k4` が入ります。一般的な別のレンズモデルの五つなどの係数を流用する欄ではありません。

`CALIBRATION_SIZE` は `(幅, 高さ)` です。例えば `(960, 720)` なら横 960 px、縦 720 px の撮影条件を意味します。実際の値は [カメラ校正](00_2_calibrate_camera.md) の出力から三つまとめて貼り付けます。現在のコードは三つとも `None` なので、未設定のまま実行すると補正を開始できません。K がない場合に「遠近補正だけで続行する」という分岐はありません。

カメラ行列の一般的な見方は次のとおりです。

~~~text
K = [ fx   0  cx ]
    [  0  fy  cy ]
    [  0   0   1 ]
~~~

`fx, fy` は画素単位の焦点距離に対応する値、`cx, cy` は画像中の主点の位置です。これらを適当な数字へ置き換えても、正しい寸法の補正にはなりません。同じ画素数でも、撮影モードや画角が変われば同じ K を使えるとは限りません。

## 4. 関数が定義される順と実行される順

このファイルには `rectify_image()` と `main()` の二つの関数があります。`def` は処理に名前を付けて用意する記述で、定義を読んだ時点で関数本体が動くわけではありません。

末尾は次の形です。

~~~python
if __name__ == "__main__":
    main()
~~~

このファイルを実行対象として起動したとき、`__name__` が `"__main__"` になり、`main()` が呼ばれます。別のコードやテストが読み込んだ場合は、この条件で一括保存を始めません。

実行時の呼出しは次の順です。

~~~text
main()
  → find_images()
  → 出力名を事前確認
  → 写真ごとに繰り返す
       read_image()
       rectify_image()
       write_png()
       保存した結果を表示
  → 完了件数を表示
~~~

次の節からは、計算の中心である `rectify_image()` をソースの上から追い、その後で `main()` のファイル操作を説明します。

## 5. rectify_image()：入力の条件を確かめる

~~~text
def rectify_image(image: np.ndarray) -> dict:
~~~

`image` は呼出し元から受け取る引数です。`np.ndarray` は NumPy の配列を意味します。戻り値の `dict` は、`"image"` などの名前と値を対応させた辞書です。この関数は保存先を受け取らず、補正結果を計算して返すところまでを担当します。

最初の `if` は、三つのカメラ設定に `None` があるかを確認します。`is None` は未設定かを調べる書き方です。`or` でつなぐと、どれか一つでも該当したら条件全体が成立します。`raise ValueError(...)` は、誤った条件で先へ進まず、理由を付けて処理を停止させます。

~~~python
height, width = image.shape[:2]
if (width, height) != tuple(CALIBRATION_SIZE):
    raise ValueError("カメラ校正と同じ解像度・撮影モードの画像を指定してください")
~~~

カラー画像の `shape` は通常 `(高さ, 幅, 3)` です。例えば `(720, 960, 3)` の `[:2]` は最初の二つを取り出して `(720, 960)` にします。`height, width = ...` は、その二つを順番に別々の変数へ入れる「展開代入」です。比較時は校正設定に合わせて `(width, height)` へ並べ直しています。`!=` は「等しくない」です。

次に設定のリストを計算用の配列にします。

~~~python
matrix = np.array(CAMERA_MATRIX, dtype=np.float64)
distortion = np.array(DIST_COEFFS, dtype=np.float64)
~~~

`dtype=np.float64` は、64 ビットの浮動小数点数として値を持つ指定です。`matrix.shape` は `(3, 3)`、`distortion.shape` は `(4,)` を期待しています。`(4,)` の末尾のカンマは、一要素のタプルを表すための記法で、「要素数四つの一次元配列」という形状を表します。`[[k1], [k2], [k3], [k4]]` の形状 `(4, 1)` は、この検査では受け付けません。

大きな `if (...)` は、次のどれかを見つけると停止します。

| 検査 | 意味 |
| --- | --- |
| `matrix.shape != (3, 3)` | K の行列の大きさが違う |
| `distortion.shape != (4,)` | 魚眼係数が一次元の四つではない |
| `not np.isfinite(...).all()` | NaN や無限大などが含まれる |
| `matrix[0, 0] <= 0`、`matrix[1, 1] <= 0` | `fx`、`fy` が正でない |
| `not math.isfinite(MM_PER_PX)` | 倍率が有限でない |
| `MM_PER_PX <= 0` | 倍率がゼロ以下 |

`np.isfinite(matrix)` は各要素について真偽の配列を作り、`.all()` は全部が真かを調べます。`not` は真偽を反転します。`matrix[0, 0]` は、0 から数えて 0 行目・0 列目の値です。

これらは必要な条件の確認です。例えば「同じ解像度だがデジタルズームが変わった」ことまで、自動で見抜く検査ではありません。

## 6. 魚眼の歪みを先に直す

~~~python
new_matrix = cv.fisheye.estimateNewCameraMatrixForUndistortRectify(
    matrix, distortion, (width, height), np.eye(3), balance=1.0
)
undistorted = cv.fisheye.undistortImage(
    image, matrix, distortion, Knew=new_matrix, new_size=(width, height)
)
~~~

一つ目の呼出しで、歪みを直した後の画像に使うカメラ行列を求めます。`np.eye(3)` は対角だけが 1、それ以外が 0 の 3 行 3 列の単位行列です。ここではカメラ座標の追加の回転を与えません。`balance=1.0` は周辺の画角をなるべく残す側の指定です。出力先のすべての画素が元画像の有効な画素で埋まる保証ではなく、周辺に黒い領域が出る場合もあります。

二つ目で、実際の画素を `undistorted` へ写します。`Knew=...` や `new_size=...` は、引数名を明示する「キーワード引数」です。出力の幅・高さはこの段階では元と同じです。ただし、画素の並びや対応する視線が変わるため、単なるコピーではありません。

歪み補正は画像全体で行います。その後で板を検出し、その後で遠近を補正します。魚眼の曲がりを、後述の 3 行 3 列の平面変換一つでまとめて直しているわけではありません。

## 7. ChArUco 板の角と ID を得る

~~~python
dictionary = cv.aruco.getPredefinedDictionary(cv.aruco.DICT_4X4_50)
board = cv.aruco.CharucoBoard(BOARD_SQUARES, SQUARE_MM, MARKER_MM, dictionary)
detector = cv.aruco.CharucoDetector(board)
corners, ids, _, _ = detector.detectBoard(undistorted)
~~~

`dictionary` はマーカーの種類の決まり、`board` はマス数や実寸を含む板の設計情報、`detector` はその板を探すための道具です。`DICT_4X4_50` は板生成や校正と同じ種類を使います。

`detectBoard()` は複数の値を返すため、カンマで並べた四つの変数に受け取ります。ここで使うのは、ChArUco の交点の画素座標 `corners` と、その交点が板のどこかを示す `ids` です。残りの二つは後で使わないため `_` に受けます。`_` は「受け取るが使わない」という慣習的な変数名であり、検出処理を省く特別な構文ではありません。

検出交点が N 点なら、今回確認した OpenCV 5.0.0 の `corners` は `(N, 2)`、`ids` は `(N,)` の配列です。角は「マーカー四角形の四隅」ではなく、ここでは板のチェス盤の内部の交点を指します。古い資料で見かける `(N, 1, 2)`・`(N, 1)` とは区別してください。

~~~python
if ids is None or len(ids) < 6 or board.checkCharucoCornersCollinear(ids):
    raise ValueError("ChArUco板の角を縦横に6点以上読める画像を指定してください")
~~~

`len(ids)` は検出交点の数です。交点がない、六つ未満、または一直線に並ぶ場合は停止します。六点あっても一列だけでは縦横の遠近関係を決める基準として不十分だからです。`or` は左から調べ、`ids is None` が真なら後ろの `len(ids)` には進みません。これにより、存在しない配列の長さを調べるエラーも避けています。

板の一部が隠れていても、この条件を満たせば処理できる場合があります。ただし、検出数が条件を満たすことと、実画像で十分な寸法精度があることは別です。

## 8. 画像の点と実寸の点を同じ順番に揃える

~~~python
all_board_points = np.array(board.getChessboardCorners(), dtype=np.float32)
board_xy = all_board_points[ids.astype(np.int32).ravel(), :2]
detected_xy = corners.reshape(-1, 2)
~~~

`all_board_points` は設計上の全内部交点の三次元座標です。現在の板は横 7 マス、縦 5 マスなので、内部交点は `6 × 4 = 24` 点あり、配列は `(24, 3)` になります。三つの値は x、y、z で、板の上なので z は 0、長さの単位は `SQUARE_MM` に合わせた mm です。

`ids.astype(np.int32)` は ID を整数配列として扱い、`.ravel()` は `(N,)` の平らな並びへ揃えます。すでに一次元なら形は変わりません。`all_board_points[ID の配列, :2]` は、その ID の行を指定の順で取り出し、各行の最初の二列、つまり x と y だけを残します。こうして `board_xy` は `(N, 2)` の mm 座標になります。

`corners.reshape(-1, 2)` は、検出座標を二つずつの組の `(N, 2)` へ揃えます。`-1` は「要素数が合うように、この方向の個数を計算する」という指定です。点の場所を変更する補正ではありません。今回の環境では元から `(N, 2)` なので、形も座標値も変わりません。

例えば検出順の ID が `[5, 2, 8]` なら、`board_xy` も板の ID 5、2、8 の順です。`detected_xy[0]` と `board_xy[0]` が同じ現物の交点を表すことが大切です。板の全交点を単に先頭から使うと、この対応を失います。

## 9. ホモグラフィを求め、誤差を確かめる

### 9.1 変換 H の向き

~~~python
homography, _ = cv.findHomography(detected_xy, board_xy)
~~~

ホモグラフィは、一つの平面の見え方を別の平面座標へ写す 3 行 3 列の行列です。ここでは入力の順番が重要です。

~~~text
detected_xy：歪み補正後の画像の px
        ↓ homography（H）
board_xy：板の平面上の mm
~~~

つまり H は **画像 → 板** の向きです。`cv.findHomography(board_xy, detected_xy)` へ逆にすると、意味も逆になります。この呼出しでは RANSAC などの方式を追加指定していません。二つ目の戻り値はこの実装では使いません。

H の成分を `h11` などと書くと、画像の点 `(u, v)` は次のように変わります。

~~~text
d = h31*u + h32*v + h33
X = (h11*u + h12*v + h13) / d
Y = (h21*u + h22*v + h23) / d
~~~

最後に d で割るため、遠近による場所ごとの倍率の違いを表現できます。`d = 0` では有限の座標になりません。後で ROI の範囲についてこの問題を確認します。

求まった H が `None` または有限でない値を含む場合は、`ValueError` で停止します。

### 9.2 逆向きに戻して、画素単位の RMS を出す

~~~python
board_to_image = np.linalg.inv(homography)
predicted = cv.perspectiveTransform(
    board_xy.reshape(-1, 1, 2), board_to_image
).reshape(-1, 2)
error_px = float(np.sqrt(np.mean(np.sum((predicted - detected_xy) ** 2, axis=1))))
~~~

`np.linalg.inv(H)` は逆行列で、ここでは **板の mm → 歪み補正後の画像の px** へ戻します。`perspectiveTransform()` に渡す点を `(N, 1, 2)` へ変えているのは OpenCV の受け取る形に合わせるためです。戻ってから `(N, 2)` へ直しています。

`predicted` は H の逆変換から予測した交点、`detected_xy` は実際に検出した交点です。誤差の一行は内側から読むと分かります。

1. `predicted - detected_xy`：各点の x と y のずれ、px。
2. `** 2`：各ずれを二乗する。
3. `np.sum(..., axis=1)`：点ごとに x と y の二乗を足す。形状は `(N,)`。
4. `np.mean(...)`：全点の平均を求める。
5. `np.sqrt(...)`：平方根を取り、px の単位へ戻す。
6. `float(...)`：Python の通常の小数として受け取る。

式では `sqrt((点1の距離² + … + 点Nの距離²) / N)` です。x と y を別々の点として数えて 2N で割っているわけではありません。これがここで表示する再投影誤差です。

`error_px > 2.0` なら「保存しません」というエラーで止めます。ちょうど 2.0 はこの条件では拒否しません。この値は今回の写真の板の対応関係の誤差であり、カメラ校正全体の RMS や試料寸法の誤差 mm とは別です。

この個別画像版には、逆行列計算そのものに対する `try/except` はありません。H が特異行列で逆行列を作れない場合は、NumPy の `LinAlgError` がそのまま出る可能性があります。後述の基準画像版には、この例外を説明付きの `ValueError` に変える処理があります。

## 10. 板の横軸が写真に写った向きを残す

~~~python
center = board_xy.mean(axis=0)
board_axis = np.array([center, center + [SQUARE_MM, 0]], dtype=np.float64)
~~~

`axis=0` は行をまたいで平均する指定です。`board_xy` が N 行 2 列なら、`center` は `[平均x, 平均y]` になります。これは検出できた板の点の平均位置であり、板全体の幾何学的な中心とは限りません。

`board_axis` は、その位置と、板の x 方向へ一マス分ずらした位置の二点です。形状は `(2, 2)`、単位は mm です。二点を `board_to_image` で画像へ戻し、写真内で板の x 軸がどちらを向いているか調べます。

~~~python
direction = image_axis[1] - image_axis[0]
direction = direction / np.linalg.norm(direction)
dx, dy = direction
rotation = np.array([[dx, -dy, 0], [dy, dx, 0], [0, 0, 1]])
homography = rotation @ homography
~~~

`image_axis[1] - image_axis[0]` は二点間の向きと長さを持つベクトルです。`np.linalg.norm(direction)` はその長さで、割り算により長さ 1 の向きだけにします。例えば右下 45 度なら `dx ≈ 0.707`、`dy ≈ 0.707` です。

`rotation` は板の mm 平面を回す行列です。`@` は行列の掛け算です。右側の H で画像から板へ写し、その後で左側の `rotation` を適用します。結果も同じ `homography` という変数へ代入するため、この行より後の H は回転を含みます。再投影誤差はこの上書きの前に計算済みです。

この回転は、板の置き方によって出力が板の軸へ大きく回ってしまうのを抑え、写真中の板の横軸の向きに合わせるためです。試料の輪郭から長手方向を検出し、必ず縦に揃える処理ではありません。また、遠近補正自体が形を直すので、写真内のすべての線の角度を完全にそのまま残す、という意味でもありません。

## 11. RECTIFY_ROI から出力範囲を決める

### 11.1 比率を画素座標へ変える

~~~python
left, top, right, bottom = RECTIFY_ROI
if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
    raise ValueError("RECTIFY_ROIは0〜1の範囲で、左 < 右、上 < 下にしてください")
~~~

四つを順番に変数へ受けます。`0 <= left < right <= 1` は「0 以上、左より右が大きい、右が 1 以下」をまとめた比較です。`and` なので横と縦の両方が成立する必要があります。

~~~python
left_px = left * (width - 1)
right_px = right * (width - 1)
top_px = top * (height - 1)
bottom_px = bottom * (height - 1)
~~~

画素座標は 0 から数えるため、幅 960 px の最後の x 座標は 959 です。そのため `width` ではなく `width - 1` を掛けます。例えば既定 ROI、幅 960、高さ 720 なら、左は `0.25 × 959 = 239.75`、右は `0.75 × 959 = 719.25`、上は 0、下は 719 です。ここは小数の座標でよく、整数へ先に丸めません。

この範囲は、**元の魚眼写真ではなく歪み補正後の画像**に対する指定です。元画像を先に切り抜くとカメラ行列と画像の位置関係が変わり、現在の処理の前提を崩します。板の検出も ROI に限定せず、歪み補正後の全画像で行われます。

`frame_corners` は左上・右上・右下・左下の四点を並べた `(4, 2)` 配列です。名前に `frame` があっても、このスクリプトが動画を直接開く意味ではありません。

### 11.2 有限の画像にできる範囲か確認する

~~~python
denominators = frame_corners @ homography[2, :2] + homography[2, 2]
if not (np.all(denominators > 0) or np.all(denominators < 0)):
    raise ValueError("撮影角度が浅すぎます。計測面へ向けて撮り直してください")
~~~

`homography[2, :2]` は H の三行目の最初の二つ、`homography[2, 2]` は右下の値です。この行は、先の式の分母 `d = h31*u + h32*v + h33` を四隅それぞれについて計算します。`(4, 2) @ (2,)` の結果は `(4,)` です。

四隅の分母が全部正、または全部負なら先へ進みます。ゼロがある場合や正負が混ざる場合、指定した長方形の中に分母がゼロになる線、つまり消失線を含むため、有限の出力画像にできません。分母は座標に対して一次式なので、凸な長方形の四隅で符号を確認できます。

### 11.3 四隅を mm、次に px へ換算する

~~~python
world_corners = cv.perspectiveTransform(
    frame_corners.reshape(-1, 1, 2), homography
).reshape(-1, 2)
pixel_corners = world_corners / MM_PER_PX
~~~

`world_corners` の `world` は、ここでは回転を含む板の平面座標を指します。四隅が mm へ移り、`MM_PER_PX` で割ると出力側の px 間隔になります。例えば 25 mm を 0.25 mm/px で割ると 100 px です。`pixel_corners` に NaN や無限大がある場合も停止します。

~~~python
minimum = np.floor(pixel_corners.min(axis=0))
maximum = np.ceil(pixel_corners.max(axis=0))
output_width = int(maximum[0] - minimum[0] + 1)
output_height = int(maximum[1] - minimum[1] + 1)
~~~

`min(axis=0)` は四点の最小 x と最小 y、`max(axis=0)` は最大 x と最大 y を取り出します。`floor` は小さい側の整数へ、`ceil` は大きい側の整数へ丸めます。負の値の `floor(-10.2)` は -11 です。四隅がはみ出さない外接長方形を作るため、外側へ丸めます。

例えば x の範囲が -10.2〜100.4 px なら、整数の範囲は -11〜101、幅は `101 - (-11) + 1 = 113` px です。`+ 1` は両端の画素座標を含めるためです。`int()` は結果を画像サイズ指定に使う整数へ変えます。

ここで次の条件も調べます。

| 条件 | 停止する理由 |
| --- | --- |
| 幅か高さが 2 未満 | 有効な二次元画像の大きさを確保できない |
| 幅か高さが 32767 以上 | 極端な画像サイズを拒否する |
| 幅 × 高さが 20,000,000 を超える | 画素数が大きすぎる処理を拒否する |

これは単に画像を小さく表示する処理ではありません。ROI を狭めると保存対象の範囲を絞り、倍率を保ったまま画素数を減らせます。遠近変換後の四角形を囲む長方形を出すため、幅 50% の指定でも出力画素数が必ず 50% にはなりません。

また、ROI の外側を厳密なマスクで消してはいません。後の `warpPerspective()` には全体の `undistorted` を渡すため、変換後の外接長方形の中に入る周辺部分が少し残ることがあります。

## 12. 最後の変換を合成して画素を作る

~~~python
world_to_pixels = np.array(
    [[1 / MM_PER_PX, 0, -minimum[0]], [0, 1 / MM_PER_PX, -minimum[1]], [0, 0, 1]],
    dtype=np.float64,
)
transform = world_to_pixels @ homography
~~~

`world_to_pixels` は「mm を px にする拡大縮小」と「出力の左上へ移す平行移動」を一つにまとめます。式は次のとおりです。

~~~text
x_out = X / MM_PER_PX - minimum[0]
y_out = Y / MM_PER_PX - minimum[1]
~~~

`minimum` はすでに px 単位なので、移動量にさらに `MM_PER_PX` を掛けたり割ったりしません。例えば最小 x が -11 なら、-(-11) で 11 px 右へずらします。

`transform` は **歪み補正後の画像 px → 保存 PNG の px** の変換です。行列積は右の `homography` を先に、左の `world_to_pixels` を後に適用します。魚眼の歪み補正はこの行列に含まれず、すでに `undistorted` を作る段階で済ませています。

~~~python
corrected = cv.warpPerspective(
    undistorted, transform, (output_width, output_height), flags=cv.INTER_LINEAR
)
~~~

`warpPerspective()` が最終的な画素配列を作ります。`(output_width, output_height)` は幅・高さの順です。`flags=cv.INTER_LINEAR` は、元の画素の間に対応する位置の色を周囲から補間する指定です。ここで渡す行列は入力から出力へ向かう変換です。画素を埋める内部処理では必要な入力位置を逆向きに調べますが、それを理由に自分で `transform` を逆行列へ変えて渡す必要はありません。

戻り値は次の辞書です。

~~~python
return {
    "image": corrected,
    "mm_per_px": MM_PER_PX,
    "corner_count": len(ids),
    "error_px": error_px,
}
~~~

`"image"` の値が補正画像、`"mm_per_px"` が倍率、`"corner_count"` が検出数、`"error_px"` が今回の板の再投影誤差です。`return` で関数を終え、呼出し元へ渡します。例えば `correction["image"]` で画像を取り出します。PNG そのものへ倍率などの辞書情報を書き込む処理はありません。後工程も同じ共通設定の倍率を使います。

## 13. main()：写真の一覧を作り、順に保存する

### 13.1 入出力の場所を決める

~~~python
input_directory = Path(INPUT_DIRECTORY).resolve()
output_directory = Path(RECTIFIED_DIRECTORY).resolve()
if input_directory == output_directory:
    raise ValueError("入力と出力は別のフォルダにしてください")
input_paths = find_images(input_directory)
~~~

`Path(...)` は場所を扱うオブジェクトを作り、`resolve()` は絶対パスに直します。`==` は二つが等しいかを比較します。入力と出力が同じフォルダだと元画像を同名 PNG で上書きするおそれがあるため拒否します。

`find_images()` はフォルダ直下だけを名前順に調べます。対象は拡張子が `.png, .jpg, .jpeg, .bmp, .tif, .tiff` の通常ファイルで、拡張子の大文字・小文字は区別しません。サブフォルダの画像を再帰的に探しません。フォルダがない場合や、対応画像が一枚もない場合は `ValueError` です。

### 13.2 すべての出力名を先に確認する

~~~python
output_names = []
for path in input_paths:
    output_name = f"{path.stem}.png"
    if output_name.casefold() in output_names:
        raise ValueError(
            f"出力名が重複します。入力名を変えてください: {output_name}"
        )
    output_names.append(output_name.casefold())
~~~

`[]` は空のリストです。`for path in input_paths:` は、一覧の各要素を順に `path` へ代入して、その下の字下げされた処理を繰り返します。`path.stem` は拡張子を除いた名前です。`f"..."` は f 文字列で、`{path.stem}` の中の結果を文章へ埋め込みます。

例えば `pass00.jpg` は `pass00.png` になります。入力に `pass00.jpg` と `pass00.tif` があると二枚とも同じ出力名になってしまうため、まだ保存しない段階で止めます。`casefold()` は大文字小文字の違いをならして比較するためです。`in` はリストに同じ値があるかを調べ、`append()` はリストの末尾に追加します。

これは「今回の入力どうしで出力名がぶつからないか」の確認です。以前の実行で作った出力 PNG の存在を調べ、上書き確認を出す処理ではありません。同名の既存出力は上書きされます。

### 13.3 一枚ずつ読む、直す、保存する

~~~python
for input_path in input_paths:
    output_path = output_directory / f"{input_path.stem}.png"
    image = read_image(input_path)
    correction = rectify_image(image)
    write_png(output_path, correction["image"])
~~~

`Path / 文字列` はファイルパスの結合です。ここでの `/` は数字の割り算ではありません。`read_image()` で一枚を読み、`rectify_image()` で計算し、戻った辞書から画像を取り出して保存します。

`read_image()` の内部では、`path.read_bytes()` でバイト列を読み、`np.frombuffer(..., np.uint8)` で一バイトずつの配列として扱い、`cv.imdecode(..., cv.IMREAD_COLOR)` でカラー画像へ展開します。日本語の場所も扱うため、ファイルの読込と画像のデコードを分けています。戻る画像は通常 `(高さ, 幅, 3)` の BGR 順、8 ビットの配列です。白黒画像もカラーとして読みます。元が高ビット深度や透過付きでも、その情報をそのまま保存するための読込ではありません。

`write_png()` は `check_output_path()` で `.png` の拡張子を確認し、`encode_png()` で先に PNG のバイト列へ変換し、その後で親フォルダを作り、`write_bytes()` で保存します。PNG 変換が失敗した時点では書込を始めません。ただし、バッチ全体を一括で取り消す仕組みや、書込中の障害に対する全面的な復旧処理ではありません。

この個別画像版は `write_png()` に入力一覧を渡さず、同一フォルダの拒否と出力名重複確認を行います。基準画像版のように、出力候補のすべてを入力パス一覧と突き合わせる専用の事前確認はありません。

### 13.4 結果を表示する

保存後の `correction["image"].shape[:2]` から高さ・幅を受け、画面には幅 × 高さ、交点数、再投影誤差を表示します。`{...:.3f}` は小数点以下三桁で表示する指定で、計算中の値自体を三桁へ丸めているわけではありません。

最後の `len(input_paths)` は全入力の枚数です。途中で例外が出ると `main()` にそれを受け止める `try/except` がないため、残りの画像の処理も完了表示も行いません。それまでに保存した PNG は残ります。「不良画像を飛ばして残りを続ける」校正スクリプトとは挙動が異なります。

## 14. 実行前後に確認することと変更しやすい場所

題材フォルダ `scraps/opencv-grabcut/` からの実行例は次のとおりです。

~~~powershell
uv run src/01_rectify_images.py
~~~

コマンドライン引数や画像選択 GUI はなく、ファイル内の設定を使います。

| 変更したい内容 | 変更する場所と注意 |
| --- | --- |
| カメラの撮影条件を変えた | このスクリプト冒頭の三設定を、対応する校正結果に更新する |
| 入出力のフォルダを変えたい | `workflow_settings.py` の `INPUT_DIRECTORY`、`RECTIFIED_DIRECTORY` を確認する |
| 周辺を減らしたい | `RECTIFY_ROI` を変える。試料の両側辺と計測区間が残るか出力 PNG で確認する |
| 倍率を変えたい | 共通の `MM_PER_PX` を変え、補正 PNG を作り直す。後工程の倍率も一致させる |
| 板の実寸を変えたい | 共通の板設定だけで済ませず、板の生成・印刷実寸・カメラ校正を揃え直す |

まず保存 PNG の板の既知距離や独立した定規の距離を [二点間距離の確認 GUI](../measure_point_distance_gui.py) などで照合します。板が出力 ROI の外になる場合も、板の検出には全体を使えますが、補正結果で板を目視確認する範囲は別途考える必要があります。

`cv.findHomography()` の二つの入力の順、`@` の左右、`shape[:2]` とサイズタプルの順、`MM_PER_PX` の掛け算・割り算は、意味を理解する前に見た目で変更しない箇所です。エラーしきい値を緩めて出力できるようにする前に、板の読み取り、実寸、撮影角度、撮影モードの整合を確認します。

## 15. この説明の確認範囲

この文書のために、現行の実装・共通設定・画像入出力と、[基準画像補正のテスト](../../tests/test_reference_frame_rectification.py) を照合しました。`tests/` で `uv run python -m unittest -v test_reference_frame_rectification` を実行し、14 件が成功しました。

テストには、同じ基準画像をこのコードと基準画像版で補正した画素の一致、不正 ROI の拒否、中央範囲へ絞っても既知の合成試料 150 × 40 mm の寸法を保つ確認が含まれます。これは合成画像に対する確認です。実カメラの校正結果、本番の圧延画像での寸法精度、反射・ブレ・試料の高さの差への影響は、この文書作成では確認していません。

[実装解説の案内へ戻る](../IMPLEMENTATION_GUIDE.md) / [Python の基礎](python_basics.md) / [基準画像方式を読む](01_rectify_frames_from_reference.md)
