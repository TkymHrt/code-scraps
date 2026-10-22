# 01_rectify_frames_from_reference.py を上から理解する

この文書は [01_rectify_frames_from_reference.py](../01_rectify_frames_from_reference.py) の現行実装を、処理の目的と Python の記法を結び付けながら説明します。全体の入口は [実装解説の案内](../IMPLEMENTATION_GUIDE.md)、基本記法の共通説明は [Python の基礎](python_basics.md) です。[写真ごとに板を読む方式の解説](01_rectify_images.md) には、共通する座標変換の計算も詳しく載せています。

## 1. 基準画像から一度だけ補正を求める理由

このスクリプトは、固定したカメラで撮った動画などについて、板の写った一枚の画像を「基準画像」にし、その基準画像から求めた同じ補正を、板が写っていない各画像へ適用します。

圧延中の試料のそばへ毎回板を置けなくても、カメラと測定面の位置関係が変わらなければ、板があった時点で得た対応関係を使えます。各フレームの試料の形を補正基準にはしないため、試料の伸びや凹凸を「基準の形に戻す」こともありません。

~~~text
ボード付き基準画像
  → prepare_rectification()
      レンズ係数を確認
      歪み補正して板を検出
      遠近変換・倍率・出力枠を決定
  → correction という辞書を得る
       ↓
ボードなし frame_001.png → rectify_frame(..., correction) → 補正 PNG
ボードなし frame_002.png → rectify_frame(..., correction) → 補正 PNG
ボードなし frame_003.png → rectify_frame(..., correction) → 補正 PNG
~~~

`correction` は、複数の値を名前でまとめた Python の辞書です。画像ごとに新しく H を探す代わりに、この辞書を全フレームで再利用します。辞書を設定ファイルへ書き出す処理はなく、スクリプトを実行するたびに基準画像から計算し直します。

このスクリプトに渡すのは PNG や JPEG などの**静止画像ファイル**です。`cv.VideoCapture()` で動画を直接開く処理や、フレームを選ぶ GUI はありません。動画からの切り出しには [video_frame_gui.py](../video_frame_gui.py) などを使います。

## 2. 写真ごとに補正する方式との違い

| 比較項目 | `01_rectify_images.py` | このスクリプト |
| --- | --- | --- |
| 板を検出する画像 | 入力の一枚一枚 | 基準画像の一枚だけ |
| 測定フレームに板が必要か | 必要 | 不要 |
| 遠近変換 H | 各写真から求める | 基準画像の H を固定する |
| 出力の幅・高さ | 各写真の変換により決まる | 全フレームで同じ |
| カメラと測定面 | 各写真の板から関係を求める | 基準画像と同じ関係を保つ必要がある |
| カメラ係数の設定 | そのファイル冒頭 | このファイル冒頭へ別途貼り付ける |
| 補正の基本計算 | 魚眼補正→板から遠近補正→一定倍率 | 同じ |

「固定」はカメラの位置だけを意味しません。高さ、向き、画角、ズーム、撮影モード、画像の切り抜き方も揃えます。電子手ぶれ補正、自動クロップ、水平維持などで画素と視線の対応が変わると、基準画像の変換を使い回す前提が崩れます。

試料が板の基準面と同じ平面内を移動することは、この方法で扱う想定に入ります。ただし試料の反りや厚さ変化で面が手前・奥へずれた分は補正しません。結果は板の基準面へ換算した二次元の長さです。同じ材料部分を追跡したり、見えていない試料の全長を復元したりするコードでもありません。

## 3. ファイル先頭の import と設定

### 3.1 読み込む機能

`math` は有限値の確認、`Path` はファイルの場所の操作、`cv2 as cv` は OpenCV、`numpy as np` は配列と行列の計算に使います。`as` は別名を付ける構文です。

自作の補助処理は [utils/file_io.py](../utils/file_io.py) から、共通の板寸法・倍率・出力範囲は [workflow_settings.py](../workflow_settings.py) から読み込みます。このスクリプトには `check_output_path` の import もあり、保存候補が入力ファイルと一致しないかを事前に確認します。

現行の共通設定は、`BOARD_SQUARES = (7, 5)`、`SQUARE_MM = 30.0`、`MARKER_MM = 18.0`、`MM_PER_PX = 0.25`、`RECTIFY_ROI = (0.25, 0.0, 0.75, 1.0)` です。板の実寸、校正時の板、補正で想定する板が一致する必要があります。

### 3.2 三つの場所を指定する

~~~python
REFERENCE_IMAGE_PATH = INPUT_DIRECTORY / "video_reference" / "reference.png"
FRAMES_DIRECTORY = INPUT_DIRECTORY / "video_frames"
RECTIFIED_FRAMES_DIRECTORY = OUTPUT_DIRECTORY / "rectified_frames"
~~~

`INPUT_DIRECTORY` と `OUTPUT_DIRECTORY` は `Path` オブジェクトです。ここでの `/` はパスの結合を表します。例えば `INPUT_DIRECTORY / "video_frames"` は、入力フォルダの下の `video_frames` フォルダです。数値を割っているわけではありません。

| 用途 | `src/` を基準にした既定の場所 |
| --- | --- |
| 基準画像一枚 | `input/video_reference/reference.png` |
| 測定する画像のフォルダ | `input/video_frames/` |
| 測定画像の補正結果 | `output/rectified_frames/` |
| 基準画像の補正結果 | `output/rectified_frames/reference/reference.png` |

`REFERENCE_IMAGE_PATH` はファイル一つ、`FRAMES_DIRECTORY` は複数の画像を入れるフォルダです。役割が違います。基準画像は測定フレームのフォルダと分けて置きます。もし基準画像を `FRAMES_DIRECTORY` 直下にも置けば、コードはそれを自動除外せず、一枚の入力フレームとしても扱います。

基準画像の補正確認用 PNG の名前は、固定の `reference.png` ではなく、基準画像の元の `stem` によります。例えば基準画像を `board_start.jpg` にすると、確認用の出力は `reference/board_start.png` です。

### 3.3 校正の三設定はこのファイルへ貼る

~~~python
CALIBRATION_SIZE: tuple[int, int] | None = None
CAMERA_MATRIX: list[list[float]] | None = None
DIST_COEFFS: list[float] | None = None
~~~

`= None` が現在の値です。`: ...` は型注釈で、`| None` は未設定もあり得るという説明です。`tuple[int, int]` は整数二つのタプル、`list[list[float]]` は小数のリストを行ごとにまとめた二重のリストを表します。

| 設定 | 必要な内容 |
| --- | --- |
| `CALIBRATION_SIZE` | 校正時の `(幅, 高さ)`、px |
| `CAMERA_MATRIX` | 3 行 3 列のカメラ行列 K |
| `DIST_COEFFS` | 魚眼モデルの `k1, k2, k3, k4` の一次元リスト |

[00_2 の校正結果](00_2_calibrate_camera.md) を使います。写真用と動画用で画角や解像度が変わるカメラでは、動画の撮影条件に合う係数が必要です。別の `01_rectify_images.py` に貼った設定は読み込みません。両者を使うなら、それぞれの設定欄を揃えます。

三つのうち一つでも `None` なら停止します。K が未設定のまま、板だけで補正する経路はありません。また、魚眼とは異なるモデルの歪み係数をそのまま使うこともできません。

## 4. 三つの関数と実行時の順序

| 関数 | 入力 | 戻り値・役割 |
| --- | --- | --- |
| `prepare_rectification(reference_image)` | 基準画像の配列 | 全画像で使い回す補正情報の辞書 |
| `rectify_frame(image, correction)` | 一枚の配列と補正情報 | 補正後の画像配列 |
| `main()` | 引数なし。冒頭の設定を使う | ファイルの確認、読込、保存、結果表示 |

`def` で関数を定義しただけでは、画像の読込や保存は始まりません。末尾の `if __name__ == "__main__":` により、このファイルを直接実行したときに `main()` を呼びます。

~~~text
main()
  → 基準画像・入力・出力の場所を決定
  → find_images() で測定画像一覧を取得
  → 全保存候補が入力を上書きしないか確認
  → read_image() で基準画像を読む
  → prepare_rectification() で補正情報を一回作る
  → rectify_frame() で基準画像の補正確認 PNG を作る
  → 各フレームを順に
       read_image() → rectify_frame() → write_png()
~~~

計算の中心を理解するため、まず `prepare_rectification()`、次に `rectify_frame()`、最後に `main()` を詳しく読みます。

## 5. prepare_rectification() の前半：基準画像の条件と歪み補正

### 5.1 引数と解像度を確認する

~~~text
def prepare_rectification(reference_image: np.ndarray) -> dict:
~~~

`reference_image` は画像のデータを持つ NumPy 配列で、ファイル名ではありません。通常は形状 `(高さ, 幅, 3)`、8 ビットの BGR 画像です。`-> dict` は辞書を返すという型注釈です。

三設定が未設定でないことを確認した後、`height, width = reference_image.shape[:2]` で高さと幅を取得します。`[:2]` は形状の先頭二つ、展開代入はそれぞれを別の変数へ受ける構文です。画像配列の順は高さ・幅ですが、校正サイズと OpenCV のサイズ指定は幅・高さなので、`(width, height)` で比較します。

`(width, height) != tuple(CALIBRATION_SIZE)` なら `ValueError` を出します。この検査が確認するのは画素数です。同じ 1920 × 1080 でも、画角やズームの違いを検知できるわけではありません。

### 5.2 カメラ行列・歪み係数・倍率を検査する

`np.array(..., dtype=np.float64)` でリストを小数計算用の配列へ変えます。その後の一つの大きな `if` は `or` で条件をつなぎ、どれか一つでも不正なら止めます。

| 確認対象 | 受け付ける状態 |
| --- | --- |
| `matrix.shape` | `(3, 3)` |
| `distortion.shape` | `(4,)`。四要素の一次元配列 |
| 配列中の値 | `np.isfinite(...).all()` が真、つまりすべて有限 |
| `matrix[0, 0]` と `matrix[1, 1]` | 正の値 |
| `MM_PER_PX` | 有限かつ正 |

`matrix[0, 0]` は最初の行・最初の列です。添字は 0 から数えます。`np.isfinite()` は要素ごとの真偽を返し、`.all()` は全部が真かを一つの真偽にまとめます。`not` は反転です。`math.isfinite()` は一つの数値を調べます。

### 5.3 新しいカメラ行列を求め、基準画像を歪み補正する

~~~python
new_matrix = cv.fisheye.estimateNewCameraMatrixForUndistortRectify(
    matrix, distortion, (width, height), np.eye(3), balance=1.0
)
undistorted = cv.fisheye.undistortImage(
    reference_image, matrix, distortion, Knew=new_matrix, new_size=(width, height)
)
~~~

`new_matrix` は歪み補正後の画像に使う 3 行 3 列のカメラ行列です。`np.eye(3)` は単位行列で、追加のカメラ回転を指定しません。`balance=1.0` は周辺の画角をなるべく残す指定です。有効な画素がない周辺に黒い部分が出ることはあります。

`Knew=...`、`new_size=...` は引数名を付けて値を渡す記述です。基準画像はこの時点では元と同じ画素数です。魚眼補正は画素と視線の対応を直す処理なので、画像サイズが同じでも画素の位置は変わります。

順序は **魚眼の歪み補正→板の検出→平面の遠近変換** です。元の魚眼画像で求めた板の座標を、歪み補正後の画像へそのまま流用する処理ではありません。

## 6. prepare_rectification() の中盤：板から変換を得る

### 6.1 板の設計情報と検出

`getPredefinedDictionary(cv.aruco.DICT_4X4_50)` でマーカーの種類、`CharucoBoard(...)` でマス数と実寸、`CharucoDetector(board)` で検出用の道具を用意します。最後に次を呼びます。

~~~python
corners, ids, _, _ = detector.detectBoard(undistorted)
~~~

`corners` は検出交点、`ids` はその交点が板のどれかを示す ID です。後ろの二つの値は使わないため `_` に受けます。`_` も変数名であり、検出しないという指示ではありません。

`ids is None`、`len(ids) < 6`、`checkCharucoCornersCollinear(ids)` のどれかに当てはまると停止します。少なくとも六つ、かつ一直線ではない交点を要求しています。`or` は手前から判定し、`ids` が `None` なら `len(ids)` を調べる前に停止側へ進みます。

N 点を検出したときの形状は次のとおりです。検出直後の `corners` と `ids` は、今回確認した OpenCV 5.0.0 の形です。

| 変数 | 形状 | 内容 |
| --- | --- | --- |
| `corners` | `(N, 2)` | 歪み補正後の画像の x、y、px |
| `ids` | `(N,)` | 各交点の ID |
| `all_board_points` | `(24, 3)` | 現行 7 × 5 マスの板の全内部交点、mm |
| `board_xy` | `(N, 2)` | 検出 ID の順に取り出した板の x、y、mm |
| `detected_xy` | `(N, 2)` | 検出した画像の x、y、px |

### 6.2 ID を使って対応する点を並べる

~~~python
all_board_points = np.array(board.getChessboardCorners(), dtype=np.float32)
board_xy = all_board_points[ids.astype(np.int32).ravel(), :2]
detected_xy = corners.reshape(-1, 2)
~~~

板には内部交点が `(7 - 1) × (5 - 1) = 24` 個あり、その設計上の三次元座標を取得します。z は板の面上なので 0、単位は設定した mm です。`dtype=np.float32` は 32 ビットの小数として持つ指定です。

`astype(np.int32)` は ID を整数型として扱い、`ravel()` は一次元へ揃えます。すでに `(N,)` なら形は変わりません。その ID 群を行の添字にし、`:2` で x と y だけを選びます。`reshape(-1, 2)` は全要素を二つ一組の点へ並べ直します。`-1` の方向の個数は自動で計算され、今回の検出座標は元から `(N, 2)` なので、その形を保ちます。

例えば検出 ID が 8、1、5 の順なら、`board_xy` も ID 8、1、5 の順にします。画像の点と実寸の点が一対一で対応するためです。

### 6.3 H は「歪み補正後の画像 px → 板 mm」

~~~python
homography, _ = cv.findHomography(detected_xy, board_xy)
~~~

この第一引数が変換元、第二引数が変換先です。H は 3 行 3 列で、画像の `(u, v)` を平面の `(X, Y)` へ写します。追加の推定方式はこの呼出しでは指定していません。

~~~text
d = h31*u + h32*v + h33
X = (h11*u + h12*v + h13) / d
Y = (h21*u + h22*v + h23) / d
~~~

`None` や有限でない H は拒否します。次に逆行列で「板→画像」を求めます。

~~~python
try:
    board_to_image = np.linalg.inv(homography)
except np.linalg.LinAlgError as error:
    raise ValueError("基準画像の板から遠近補正を求められません") from error
~~~

`try` の中で逆行列を作り、逆行列が存在しない場合の `LinAlgError` を `except` で受けます。`as error` は元の例外へ名前を付ける記述です。`raise ... from error` は、原因の例外とのつながりを残したまま、利用者へ説明しやすいエラーへ変えます。失敗を無視して処理を続ける書き方ではありません。

### 6.4 再投影誤差を画素単位で確認する

板の実寸点を `board_to_image` で画像へ戻した `predicted` と、検出点 `detected_xy` を比較します。`perspectiveTransform()` に合わせるため、途中で点の配列を `(N, 1, 2)` に変え、戻り値は `(N, 2)` に戻します。

~~~python
error_px = float(np.sqrt(np.mean(np.sum((predicted - detected_xy) ** 2, axis=1))))
~~~

`predicted - detected_xy` で x と y のずれを出し、`** 2` で二乗、`sum(..., axis=1)` で点ごとの x²+y²、`mean()` で全点の平均、`sqrt()` で平方根を求めます。単位は px、RMS と呼ぶ平均誤差です。例えば全交点が同じ 1 px だけずれていれば、結果は 1 px です。

`error_px > 2.0` の場合は停止し、ちょうど 2.0 はこの条件では拒否しません。この値は**基準画像の板の誤差**です。後で板のないフレームへ適用したときの寸法誤差は計算していません。

### 6.5 写真に写った板の軸の向きを考慮する

`board_xy.mean(axis=0)` は、検出した点の平均 x・平均 y です。その位置 `center` と、板の x 方向へ `SQUARE_MM` だけ進めた点を `board_axis` に入れます。形状は `(2, 2)`、mm 単位です。この二点を画像へ戻し、`image_axis[1] - image_axis[0]` で向きを求めます。

~~~python
direction = direction / np.linalg.norm(direction)
dx, dy = direction
rotation = np.array([[dx, -dy, 0], [dy, dx, 0], [0, 0, 1]])
homography = rotation @ homography
~~~

長さで割って向きだけの長さ 1 のベクトルにし、`dx, dy` へ受けます。`rotation` は平面内で向きを合わせる回転行列です。`@` は行列積で、「右の H で画像から板へ、左の行列で平面内を回転」の順になります。この行から後の `homography` は、回転を含んだ同じ単位 mm の平面へ向かいます。

試料の向きを画像から自動検出して縦に揃えているわけではありません。板の置き方だけで補正画像が大きく回ってしまうことを抑え、写真内での向きを考慮する処理です。遠近補正に伴う角度の変化までなくすものではありません。

## 7. prepare_rectification() の後半：ROI、画素数、最終変換

### 7.1 ROI は歪み補正後の画像に対する比率

`left, top, right, bottom = RECTIFY_ROI` で四つの比率を受け取ります。`0 <= left < right <= 1` と `0 <= top < bottom <= 1` が両方成立しない場合は停止します。

~~~python
left_px = left * (width - 1)
right_px = right * (width - 1)
top_px = top * (height - 1)
bottom_px = bottom * (height - 1)
~~~

画素座標の先頭が 0 なので、幅 960 の右端は 959、高さ 720 の下端は 719 です。既定値なら、歪み補正後の画像の x は 239.75〜719.25、y は 0〜719 の範囲です。比率から求めた四隅は小数でも構いません。

板の検出は、この ROI に絞る前に全画像で行っています。板が中央範囲の外にあっても、全体で検出できれば補正を求められます。元画像やフレームを先に切り抜いて小さくする操作は、この処理の代わりにはなりません。

四隅を左上・右上・右下・左下の順に `frame_corners`、形状 `(4, 2)` へ入れます。

### 7.2 消失線と有限値を調べる

~~~python
denominators = frame_corners @ homography[2, :2] + homography[2, 2]
if not (np.all(denominators > 0) or np.all(denominators < 0)):
    raise ValueError(
        "基準画像の撮影角度が浅すぎます。計測面へ向けて撮り直してください"
    )
~~~

`homography[2, :2]` は H の三行目の先頭二要素で、各隅の分母 `d = h31*u + h32*v + h33` を計算しています。四つすべてが正、またはすべてが負なら通します。ゼロがあったり符号が混ざったりすると、ROI 内に分母がゼロになる線があり、有限の画像へできません。

次に `perspectiveTransform()` で四隅を平面の mm へ移して `world_corners` にし、`world_corners / MM_PER_PX` で出力側の px へ換算して `pixel_corners` にします。例えば 25 mm は倍率 0.25 mm/px で 100 px です。有限でない結果も拒否します。

### 7.3 外接長方形の大きさを出す

~~~python
minimum = np.floor(pixel_corners.min(axis=0))
maximum = np.ceil(pixel_corners.max(axis=0))
output_width = int(maximum[0] - minimum[0] + 1)
output_height = int(maximum[1] - minimum[1] + 1)
~~~

四隅の最小 x・最小 y を `minimum`、最大 x・最大 y を `maximum` にします。`floor` は小さい整数側、`ceil` は大きい整数側へ丸め、全体を囲みます。例えば x が -10.2〜100.4 なら -11〜101、幅は 113 px です。`+ 1` は両端の座標を含める分、`int()` は画像サイズに使う整数への変換です。

幅か高さが 2 未満、どちらかが 32767 以上、または総画素数が 20,000,000 を超える場合は停止します。倍率を極端に細かくすると出力は大きくなり、この制限にも当たります。

ROI で幅を半分にしても、遠近変換後の四角形を囲む外接長方形は必ずしも幅半分になりません。ROI の輪郭で切り抜いてマスクする処理もありません。全体の歪み補正画像を変換するため、外接長方形内に入った周辺が少し残る場合があります。

この段階で求めた `output_width` と `output_height` を全フレームで共有するので、試料の動きや板の有無で保存 PNG の大きさが変わりません。

### 7.4 mm から保存 PNG の px への変換を合成する

~~~python
world_to_pixels = np.array(
    [[1 / MM_PER_PX, 0, -minimum[0]], [0, 1 / MM_PER_PX, -minimum[1]], [0, 0, 1]],
    dtype=np.float64,
)
transform = world_to_pixels @ homography
~~~

`world_to_pixels` は、`X / MM_PER_PX` と `Y / MM_PER_PX` で一定倍率へ変え、`minimum` を引いて画像左上へ移す行列です。`minimum` はすでに px 単位です。全体の方向は次のようになります。

~~~text
元の魚眼画像
  → fisheye.undistortImage（魚眼歪み補正）
歪み補正後の px
  → homography（板から求めた平面変換と向きの調整）
平面の mm
  → world_to_pixels（mm/px で換算し、左上へ移動）
保存 PNG の px
~~~

`transform` がまとめるのは後ろの二段階だけです。魚眼の歪み補正も含む一個のホモグラフィを作っているわけではありません。

## 8. prepare_rectification() が返す辞書

~~~python
return {
    "matrix": matrix,
    "distortion": distortion,
    "new_matrix": new_matrix,
    "input_size": (width, height),
    "transform": transform,
    "output_size": (output_width, output_height),
    "mm_per_px": MM_PER_PX,
    "corner_count": len(ids),
    "error_px": error_px,
}
~~~

`return` は関数の処理を終え、`{...}` で作った辞書を呼出し元へ渡します。文字列のキーで値を取り出せます。

| キー | 形状・単位 | 後で使う目的 |
| --- | --- | --- |
| `"matrix"` | `(3, 3)` | 元カメラの K |
| `"distortion"` | `(4,)` | 魚眼の歪み係数 |
| `"new_matrix"` | `(3, 3)` | 歪み補正後のカメラ行列 |
| `"input_size"` | `(幅, 高さ)`、px | フレーム寸法の検査と歪み補正 |
| `"transform"` | `(3, 3)` | 歪み補正後の px から保存 PNG の px へ |
| `"output_size"` | `(幅, 高さ)`、px | 全フレームで共通の出力画像サイズ |
| `"mm_per_px"` | mm/px | 固定倍率の表示 |
| `"corner_count"` | 点数 | 基準画像で読めた交点数の表示 |
| `"error_px"` | px | 基準画像の再投影誤差の表示 |

この辞書に基準画像そのものは入れません。`prepare_rectification()` も保存しません。計算した行列と条件をまとめて渡す関数です。

## 9. rectify_frame()：毎回同じ処理を一枚へ適用する

~~~python
def rectify_frame(image: np.ndarray, correction: dict) -> np.ndarray:
    height, width = image.shape[:2]
    if (width, height) != correction["input_size"]:
        raise ValueError("基準画像と同じ解像度のフレームを指定してください")
~~~

`image` に一枚の画像、`correction` に先ほどの辞書を受け取ります。`correction["input_size"]` は辞書のキー `"input_size"` に対応する値の参照です。この関数ではグローバル設定の校正サイズより、準備済みの辞書のサイズを使います。

画素数が異なれば停止します。例えば基準画像 960 × 720 に対し、480 × 360 の画像や 720 × 960 へ回した画像は拒否します。ただし画素数を変えない回転やズーム、カメラの微小移動まで検知する機能はありません。

~~~python
undistorted = cv.fisheye.undistortImage(
    image,
    correction["matrix"],
    correction["distortion"],
    Knew=correction["new_matrix"],
    new_size=correction["input_size"],
)
~~~

すべてのフレームを基準画像と同じカメラ係数、新しいカメラ行列、入力サイズで歪み補正します。ここではフレームごとの `estimateNewCameraMatrixForUndistortRectify()` や板検出は行いません。歪み補正された画像そのものは各フレームで新しく作ります。

~~~python
corrected = cv.warpPerspective(
    undistorted,
    correction["transform"],
    correction["output_size"],
    flags=cv.INTER_LINEAR,
)
return corrected
~~~

同じ `transform` で遠近補正と倍率・移動を適用し、同じ `output_size` の画像を作ります。`INTER_LINEAR` は画素間の色の補間方法です。この行列は「入力→出力」の向きで渡します。OpenCV の内部で出力画素に対応する入力位置を調べるために、呼出し側で逆行列へ変える必要はありません。

戻り値は補正画像そのものです。`prepare_rectification()` の辞書のように `["image"]` で取り出すものではありません。`rectify_frame()` には板を検出する呼出しが一つもないため、フレームに板が写っていても、それを使って補正を調整し直しません。

## 10. main() の前半：保存前の確認

### 10.1 場所と入力一覧を作る

`Path(...).resolve()` で基準ファイル・入力フォルダ・出力フォルダの三つを絶対パスにします。共通設定から作る既定パスは `workflow_settings.py` の場所を基準にしており、別の作業ディレクトリからでも同じ場所を指します。手動で `Path("相対パス")` に置き換えた場合の相対パスは、実行時の現在の場所が基準です。

入力と出力が同じフォルダなら拒否し、`find_images(input_directory)` で入力フレームを一覧にします。対象拡張子は `.png, .jpg, .jpeg, .bmp, .tif, .tiff` です。直下の通常ファイルだけを名前順に取り出し、サブフォルダへは降りません。

入力フォルダがない、または画像がない場合は、この時点で停止します。基準画像が正しくても、測定フレームがゼロのまま「基準画像だけ補正して保存する」処理には進みません。

### 10.2 上書きしてはいけない入力一覧を作る

~~~python
protected_paths = [reference_path]
protected_paths.extend(input_paths)
~~~

`[reference_path]` は基準画像一つを入れたリストです。`extend(input_paths)` は入力一覧の要素を一つずつ同じリストへ足します。`append(input_paths)` なら「リスト全体を一要素として入れる」ので意味が違います。

これで `protected_paths` は「基準画像、frame_001、frame_002、…」という一本のリストになります。この一覧と各出力候補を照合します。

~~~python
reference_output_path = check_output_path(
    output_directory / "reference" / f"{reference_path.stem}.png",
    ".png",
    protected_paths,
)
~~~

`reference_path.stem` は拡張子を除いた名前です。f 文字列の `{...}` へ埋め込み、基準画像の補正結果の場所を作っています。

`check_output_path()` は候補を絶対パスへ変え、拡張子が `.png` であること、入力一覧のどの絶対パスとも一致しないことを確認して返します。この時点ではフォルダもファイルも作りません。入力が出力フォルダの内側へ特殊に配置されていても、実際の保存先と一致する場合には止めるためです。

### 10.3 フレームの出力名と入力保護をまとめて調べる

~~~python
output_names = []
for input_path in input_paths:
    output_name = f"{input_path.stem}.png"
    if output_name.casefold() in output_names:
        raise ValueError(
            f"出力名が重複します。入力名を変えてください: {output_name}"
        )
    output_names.append(output_name.casefold())
    check_output_path(output_directory / output_name, ".png", protected_paths)
~~~

`for` は入力ごとの繰返しです。例えば `frame_001.jpg` と `frame_001.tif` は、両方が `frame_001.png` になるため拒否します。`casefold()` により大文字小文字の違いをならして比較します。`in` は既出かの確認、`append()` は今見た名前をリストへ追加する操作です。

このループでは画像をまだ読み込みません。全出力名と入力への上書きを事前確認します。ただし、既存の出力 PNG があること自体は拒否しません。同名の出力は、後の保存で確認ダイアログなしに上書きされます。既存の結果を残したい場合は、冒頭の出力先を別フォルダにします。

## 11. main() の後半：基準画像、フレームの順に保存する

### 11.1 基準画像を読み、確認用の補正画像を保存する

~~~python
reference_image = read_image(reference_path)
correction = prepare_rectification(reference_image)
corrected_reference = rectify_frame(reference_image, correction)
write_png(reference_output_path, corrected_reference)
~~~

`read_image()` は日本語パスを扱うため、ファイルを `read_bytes()` で読み、`np.frombuffer(..., np.uint8)` で一バイト単位の配列にし、`cv.imdecode(..., cv.IMREAD_COLOR)` で画像へ展開します。通常の戻り値は高さ × 幅 × 3 の BGR 画像です。読めないファイルや画像として展開できない内容は `ValueError` です。

`prepare_rectification()` で H などを一回求めます。その後、基準画像自身にも `rectify_frame()` を呼び、同じ処理経路で補正画像を作って保存します。つまり基準画像の歪み補正は、板検出用の準備段階と、確認 PNG 作成時の二回で実行されます。二回目へ「すでに歪み補正した画像」を渡すわけではなく、どちらも元の `reference_image` を入力にしています。

`write_png()` は拡張子の確認、PNG のバイト列への変換、親フォルダの作成、ファイル書込の順です。PNG へ変換できない場合は、書込を始める前に止まります。バッチ全体の保存を一括で戻す機能ではありません。

### 11.2 基準の条件を表示する

角数と `error_px` は一度だけ表示します。`{...:.3f}` は再投影誤差の表示を小数点以下三桁にする書式です。計算値自体を三桁へ丸める処理ではありません。

続いて基準の補正画像の保存先、固定倍率、幅 × 高さを表示します。`output_width, output_height = correction["output_size"]` は、幅と高さの二要素を展開して受けます。

この表示から分かるのは、基準画像で何点読め、どの倍率・どの画素数を全フレームに適用するかです。各フレームについて同じ精度が確認済み、という表示ではありません。

### 11.3 各フレームを同じ correction で処理する

~~~python
for input_path in input_paths:
    image = read_image(input_path)
    try:
        corrected = rectify_frame(image, correction)
    except ValueError as error:
        raise ValueError(f"{input_path.name}: {error}") from error
    output_path = output_directory / f"{input_path.stem}.png"
    write_png(output_path, corrected)
    print(f"保存: {output_path.name}")
~~~

`correction` をループの中で作り直していないことに注目します。`input_path.name` は拡張子を含む名前、`stem` は拡張子を除く名前です。処理で使う画像 `image` と補正後の `corrected` は、毎回そのフレームの配列へ変わります。

この `try/except` は `rectify_frame()` が出す `ValueError` にファイル名を加えて再送出します。例えば `frame_002.png: 基準画像と同じ解像度のフレームを指定してください` と表示でき、どの入力を直すか分かります。

`read_image()` と `write_png()` はこの `try` の外です。これらのエラーは、それぞれの関数が持つエラー表示のまま上へ伝わります。OpenCV が出すすべての例外をこの `except ValueError` が捕まえるわけでもありません。

一枚で失敗したらループを続けません。たとえば frame_001 の保存後に frame_002 の寸法不一致が起きると、基準画像の確認 PNG と frame_001 の補正 PNG は残り、frame_002 とそれ以降は保存しません。全件を先にメモリ上で補正してから一括保存する方式ではありません。

最後の `print(f"完了: {len(input_paths)}枚 → {output_directory}")` は全フレームが成功したときだけ実行されます。この枚数には別途保存した基準画像の確認 PNG は含めません。

## 12. 初回の実行と結果の確かめ方

題材フォルダ `scraps/opencv-grabcut/` から実行します。

~~~powershell
uv run src/01_rectify_frames_from_reference.py
~~~

このコードにはコマンドライン引数やファイル選択画面はありません。冒頭の三つのパスと三つのカメラ設定、共通の板設定・倍率・ROI が実行条件です。

1. 基準画像と測定画像を、同じ動画条件・元解像度で保存します。回転・切り抜き・リサイズを加えません。
2. 動画条件に合う魚眼校正の三設定を、このファイルへ貼り付けます。
3. 基準の板を試料の計測面と同じ高さ・傾きに置き、十分な交点が見えていることを確認します。
4. 出力先と ROI を確認して実行します。
5. まず `reference/` の補正 PNG で、既知の板間隔や独立した定規の寸法を照合します。
6. フレームの補正 PNG で試料の両側辺と測りたい区間が残り、反射・影・ブレで境界を誤っていないかを確認します。
7. `02_measure_edge_lengths_gui.py` などの画像選択から `output/rectified_frames/` を開きます。

既存の計測 GUI の既定の読込開始先は `output/rectified/` です。このスクリプトを使っても、自動で `rectified_frames/` へ変更されません。保存 PNG と計測 GUI が同じ `MM_PER_PX` を使うことを確認して、ファイルを選びます。

PNG に倍率やカメラ係数を特別なメタデータとして保存する処理はありません。結果の意味を再確認できるよう、基準画像、設定済みのこのスクリプト、共通設定と出力を対応させて保管します。

## 13. 変更する場所と、コードでは確かめられないこと

| 変更したいこと | 対応する場所・必要な作業 |
| --- | --- |
| 別の撮影の画像を使いたい | 三つのパスを変更する。同じ基準が使える撮影条件か確認する |
| カメラや画角を変えた | 適合する校正係数と、新しい基準画像を用意する |
| カメラを移動した | 新しい基準画像から求め直し、出力先を分ける |
| 出力周辺を減らしたい | 共通の `RECTIFY_ROI` を変更し、補正 PNG を作り直す |
| 倍率を変えたい | 共通の `MM_PER_PX` を変更し、全補正 PNG を作り直す |
| 板寸法を変えたい | 生成・印刷の実寸・校正・補正の設定を揃え直す |

解像度の検査だけでは、同じ画素数のまま生じた構図のずれや電子手ぶれ補正を検出できません。動画中の動かない設備の位置や、終了時に同じ面へ置いた板などを撮影時に確認します。基準画像だけの誤差表示で、動作中の全画像の寸法精度を保証したことにはなりません。

基準面からの高さのずれ、試料の反り、動体ブレ、反射による輪郭のずれは、この座標変換で解消しません。エラーを回避するためにしきい値だけを上げる前に、撮影条件、板の実寸、写り方を確認します。

## 14. この説明の確認範囲

現行コード、共通設定、画像入出力、[基準画像補正のテスト](../../tests/test_reference_frame_rectification.py) を照合しました。`tests/` から次の 14 件を実行し、すべて成功しました。

~~~powershell
uv run python -m unittest -v test_reference_frame_rectification
~~~

確認には、同じ基準画像を個別画像版とこの方式で処理した画素の一致、ボードなしの合成フレームの一定出力、150 × 40 mm の既知形状の寸法、ROI 変更時の倍率維持、不正係数・不正 ROI・不正サイズの拒否、基準画像とフレームの上書き防止、途中失敗時の保存状態、日本語パスと別の作業ディレクトリからの実行、補正後の計測・CSV 保存への受渡しが含まれます。

これは合成画像と現在の環境での確認です。実カメラの係数、本番動画の振動・電子補正・面外変形を含む寸法精度、別の撮影環境での再現性は、この文書作成では確認していません。

[実装解説の案内へ戻る](../IMPLEMENTATION_GUIDE.md) / [Python の基礎](python_basics.md) / [写真ごとに補正する方式を読む](01_rectify_images.md)
