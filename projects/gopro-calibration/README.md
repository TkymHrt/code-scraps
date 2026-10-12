# GoProの広角写真を校正・補正する

通常使うのは `practical/main.py` だけです。8bitのJPG/PNGを読み、OpenCVの魚眼モデルで歪みを補正してPNGに保存します。
必要なライブラリはNumPyとOpenCVだけです。作成日：2026-10-09。

```text
gopro-calibration/
  practical/
    main.py                    校正・補正（この1本で動く）
    checkerboard.png           印刷用の盤
  tests/                       合成画像での検証と記録
  requirements.txt
  README.md
```

相対パスの入力・出力は実行時の作業フォルダが基準です。以下はこのフォルダからの実行例です。

## 準備

Python 3.10以上で、このフォルダから実行します。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

仮想環境のPythonを直接指定するので、Activateは不要です。
macOS/Linuxでは `.\.venv\Scripts\python.exe` を `.venv/bin/python` に置き換えます。

## 1. チェッカーボードを撮影する

[practical/checkerboard.png](practical/checkerboard.png) を印刷し、平らな板に貼って撮影します。

- 内側の交点は横9・縦6です。白黒のマス数は横10・縦7です。
- 印刷後にマスの一辺を測ります。下の例は25mmです。
- 20〜30枚を目安に、盤の位置・距離・傾きを変え、中央と画面の周辺まで写します。
- 盤全体と外側の白い余白を写し、交点が鮮明になるようにします。
- 撮影モード・画角・ズーム・解像度をそろえ、写真を回転・切り抜き・リサイズしません。

## 2. 校正する

校正とは、写真からカメラの歪みを表す係数を求めることです。
撮影した盤のJPGを `photos/` に入れて実行します。

```powershell
.\.venv\Scripts\python.exe practical/main.py calibrate "photos/*.JPG" --square 25
```

`--square` は実測したマスの一辺のmmです。別の盤を使う場合は `--pattern 横の交点数 縦の交点数` も指定します。
画像のパターンは引用符で囲みます。最低10枚で全交点を検出できる必要があります。

- `calibration.json`: カメラ行列 `K`、歪み係数 `D`、画像サイズ、検出枚数、全体の再投影誤差。
- `calibration_corners/`: 検出した交点を描いた画像。盤の正しい交点を結んでいるか確認します。

再投影誤差は、推定した交点の位置と検出した位置のずれです。単位は画素です。
1画素を超える場合や検出図が盤に合っていない場合は、撮影を見直してください。
誤差が小さくても、同じ位置の写真ばかりでは画面周辺の精度は確認できません。

## 3. 別の写真を補正する

校正時と同じ撮影設定・解像度の写真に使います。

```powershell
.\.venv\Scripts\python.exe practical/main.py undistort calibration.json photo.JPG --out corrected.png
```

`--balance 0`（既定）は黒い余白を減らし、`--balance 1` は画角を広く残します。途中の値も使えます。
補正すると周辺が伸び、画角の一部が失われたり黒い余白が出たりします。自動で切り抜きません。

`corrected.png.json` に補正後のカメラ行列も保存します。補正画像で座標計算する場合は、この行列を使います。
被写体の斜めからの見え方は残ります。真上からの画像にする処理は別です。
EXIFとICCプロファイルは引き継ぎません。

撮影モードや画角を変えたら校正し直します。Linearなどで補正済みの画像では、この魚眼モデルが合わない場合があります。
360度の合成画像は対象外です。
疑似画像の係数を実機へ流用せず、実機で撮影した盤の写真から係数を求めてください。

## コードを読むとき

`calibrate()` は「盤の交点位置を作る → 写真から検出する → 係数を求める → JSONに保存する」の順です。
`undistort()` は保存した係数を読み、OpenCVの `fisheye.undistortImage()` で写真を補正します。
`read_image()` と `write_image()` はWindowsの日本語パスを扱うための小さな補助関数です。

スクリプトは1本を別の場所へコピーしても動きます。

検証コードと結果は [tests/README.md](tests/README.md) にまとめました。通常の校正・補正では検証コードを実行する必要はありません。

参考: [OpenCVの魚眼モデル](https://docs.opencv.org/4.x/db/d58/group__calib3d__fisheye.html)、[カメラ校正の説明](https://docs.opencv.org/4.x/dc/dbb/tutorial_py_calibration.html)。
