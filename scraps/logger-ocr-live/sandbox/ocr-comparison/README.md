# BayerBG8の静止画でOP／DRの2計器を読む

BG505LMCFからBayerBG8を1枚保存し、グレースケール画像を固定しきい値で二値化します。二値画像で各計器の6桁×7点を指定し、別の静止画で表示値と読み取り結果を照合します。

以下のコマンドは `scraps/logger-ocr-live` で実行します。各スクリプトの入出力パスと設定はファイル先頭にあります。

## WindowsのQt環境

PyPIのWindows用`opencv-python`はWIN32表示のため、Qt版を含むconda-forgeの環境を別に作ります。`pip install PyQt6`だけではOpenCVをQt版に切り替えられません。本体用の`.venv`はそのまま使い、校正用はリポジトリ外の`%LOCALAPPDATA%\code-scraps\logger-ocr-qt`に置きます。

初回だけ、[公式配布のmicromamba](https://mamba.readthedocs.io/en/latest/installation/micromamba-installation.html)を展開します。シェルの設定やシステムのPATHは変更しません。

```powershell
$qtTools = Join-Path $env:LOCALAPPDATA 'code-scraps/qt-tools'
New-Item -ItemType Directory -Force $qtTools | Out-Null
Invoke-WebRequest 'https://micro.mamba.pm/api/micromamba/win-64/latest' -OutFile "$qtTools/micromamba.tar.bz2"
tar -xjf "$qtTools/micromamba.tar.bz2" -C $qtTools Library/bin/micromamba.exe
```

続けて環境を作ります。新しいPowerShellを開いたときも、先頭の3変数を設定してから実行コマンドを使います。環境の作成は初回のみです。

```powershell
$qtMamba = Join-Path $env:LOCALAPPDATA 'code-scraps/qt-tools/Library/bin/micromamba.exe'
$qtRoot = Join-Path $env:LOCALAPPDATA 'code-scraps/mamba'
$qtPrefix = Join-Path $env:LOCALAPPDATA 'code-scraps/logger-ocr-qt'
& $qtMamba create --root-prefix $qtRoot --prefix $qtPrefix --file sandbox/ocr-comparison/environment-qt.yml --yes
```

Qt環境にはpip版OpenCVを重ねて入れず、`uv sync`も実行しません。必要なDLLの検索先を設定するため、`micromamba run`経由で起動します。

## 1. 校正用のBayerBG8を1枚撮る

[題材READMEのTeliCamSDK導入手順](../../README.md#東芝テリーを使う場合)に従い、本体用の `.venv` にpytelicamを導入します。SDKを使うのは撮影時だけです。

メーカーのビューアでピント・露光・ゲイン・ROIを調整し、ReverseX・ReverseYをOff、OffsetX・OffsetYを偶数にします。カメラと計器の位置を固定し、可能なら両計器を全点灯（`888888`）にしてビューアを終了します。

```powershell
.\.venv\Scripts\python.exe sandbox/ocr-comparison/capture_bayer.py
.\.venv\Scripts\python.exe sandbox/ocr-comparison/check_snapshot.py
```

初期設定で `captures/run-01/frame-000000.npy` にBayerBG8の2次元uint8配列を保存します。`check_snapshot.py` は `results/snapshot-01/` に `gray.png` と `binary.png` を保存します。初期しきい値は50で、グレー値がしきい値より大きい画素が白になります。点灯線の中心が白く、背景が黒いことを確認します。値を調整する場合は `THRESHOLD` を変え、新しい `OUTPUT_DIR` を指定して同じ画像で再実行します。

## 2. 二値画像でOP／DR各42点を指定する

`calibrate.py` の `SOURCE` に選んだ `binary.png` を指定します。初期設定は `results/snapshot-01/binary.png` です。鏡像で撮影した場合は `REFLECTION` を `horizontal`・`vertical`・`both` のいずれかに設定し、数字が正しい向きに見えるか確認します。

```powershell
& $qtMamba run --prefix $qtPrefix python sandbox/ocr-comparison/calibrate.py
```

1. **OP側を先に**、左の桁から各桁の上→右上→右下→下→左下→左上→中央の順に、セグメントの中心をクリックします。
2. **DR側**も同じ順に42点を指定します。OPとDRは実機の対応を確認してください。
3. 84点が揃ったらEnterで `calibration.json` を保存します。

ホイールで拡大縮小、拡大中の左ドラッグで移動できます。Bで直前の点を取り消し、Q・Esc・ウィンドウの×で中止します。中止時に校正ファイルは作成されません。ツールバーの保存ボタンは表示画像の書き出し用です。

## 3. 別の静止画で両計器の数値を確かめる

カメラ・ROI・計器の位置を固定したまま、OP／DRに異なる既知の値を表示して控えます。次の設定で手順1の2コマンドを再実行します。

| スクリプト | 2枚目の設定例 |
| --- | --- |
| `capture_bayer.py` | `OUTPUT_DIR = FOLDER / "captures/check"` |
| `check_snapshot.py` | `FRAME = FOLDER / "captures/check/frame-000000.npy"`、`OUTPUT_DIR = FOLDER / "results/check"`、`CALIBRATION = FOLDER / "calibration.json"` |

しきい値は校正画像を作ったときと同じ値を使います。各セグメントは指定した1画素が白なら点灯、黒なら消灯です。端末に `OP 123`、`DR 456789` のように整数を表示します。先頭の空白は許容し、全消灯・途中や末尾の空白・数字にないパターンは該当側を `欠測` と表示します。

**両側の値が目視と一致すれば成功です。** 誤読や欠測のときは二値画像上の点灯・消灯とクリック位置を確認します。位置・解像度・ROIを変えた場合は再校正します。

撮影先・結果の保存先・校正JSONはそれぞれ既存のものに上書きしません。撮り直しや設定変更で再実行するときは新しい保存先を指定します。実データは `captures/`・`results/` またはリポジトリ外に置きます。

## 検証

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests
.\.venv\Scripts\ruff.exe check src sandbox/ocr-comparison tests
.\.venv\Scripts\ruff.exe format --check src sandbox/ocr-comparison tests
```

模擬SDKで1枚の保存・解放・上書き防止を、合成画像で全点灯画像からの校正と別画像の両側の値を確認します。
