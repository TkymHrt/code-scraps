# 1台のカメラでOP／DRの2表示を読む比較試験

保存画像で読み方を試すスクリプトです。本体の`src`、ロガー、親プロセスを使わず、このフォルダだけで撮影・校正・比較ができます。本体への方式採用とライブ取得への組込みは別作業です。

| スクリプト | 役割 |
| --- | --- |
| `capture_bayer.py` | BG505LMCFからBayerBG8を保存。カメラSDKが必要なのはこの処理だけ |
| `check_snapshot.py` | 保存したBayerBG8を直接グレー化し、固定しきい値の全画面PNGを出力。校正後は同じ二値画像からOP／DRの数字を表示 |
| `calibrate.py` | 保存した静止画像でOP／DR各42点を指定し、校正JSONを保存 |
| `compare.py` | 同じ画像・校正点で固定二値化、適応二値化、Bayer赤画素の中央値を比較 |

校正・比較にはNumPyとOpenCVを使います。校正画面は**Qt対応OpenCV**の標準機能で拡大・移動します。以下のコマンドは`logger-ocr-live`フォルダで実行します。各スクリプトは1ファイルで実行できます。別の場所へコピーしたら、先頭の変数に入力・出力のパスを指定します。

## WindowsのQt環境

PyPIのWindows用`opencv-python`はWIN32表示のため、Qt版を含むconda-forgeの環境を別に作ります。`pip install PyQt6`だけではOpenCVをQt版に切り替えられません。本体用の`.venv`はそのまま使い、比較試験用はリポジトリ外の`%LOCALAPPDATA%\code-scraps\logger-ocr-qt`に置きます。

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
& $qtMamba run --prefix $qtPrefix python -c "import cv2; print(cv2.__version__, cv2.currentUIFramework())"
```

`5.0.0 QT`のように`QT`が出ることを確認します。校正はQt以外では起動時にエラーにします。Qt環境にはpip版OpenCVを重ねて入れず、`uv sync`も実行しません。必要なDLLの検索先を設定するため、環境内の`python.exe`を直接実行せず、上の`micromamba run`経由で起動します。

## 1. 試験画像を用意する

### カメラ到着時の最小テスト

各スクリプトの設定はファイル先頭で変更します。初回は撮影から校正まで初期値でつながります。以下は `logger-ocr-live` で実行します。

1. 下の「BG505LMCFから記録する場合」に従ってSDKと撮影条件を用意し、ビューアを閉じます。できれば両計器を全点灯（`888888`）にして撮ります。

   ```powershell
   .\.venv\Scripts\python.exe sandbox/ocr-comparison/capture_bayer.py
   .\.venv\Scripts\python.exe sandbox/ocr-comparison/check_snapshot.py
   ```

2. 二値化の入力は反転なし・偶数オフセットのBayerBG8配列（2次元uint8の `.npy`）1枚です。`results/snapshot-01/gray.png` と `binary.png` を見比べます。点灯線の中央が白く、線同士の隙間が黒くなるかを確認します。しきい値を試すには `check_snapshot.py` の `THRESHOLD`（初期値50）と `OUTPUT_DIR` を変え、同じ `FRAME` で再実行します。
3. 「2. OP／DRを校正する」の手順で、選んだ二値画像に両側各42点を指定し、`calibration.json` を保存します。初期値以外の画像を選んだ場合は `calibrate.py` の `SOURCE` を合わせます。
4. カメラとROIを固定し、両側に異なる既知の値を表示して数字を控えます。以下の設定を変え、手順1の2コマンドをもう一度実行します。

   | ファイル | 2枚目の設定例 |
   | --- | --- |
   | `capture_bayer.py` | `OUTPUT_DIR = FOLDER / "captures/check"` |
   | `check_snapshot.py` | `FRAME = FOLDER / "captures/check/frame-000000.npy"`、`OUTPUT_DIR = FOLDER / "results/check"`、`CALIBRATION = FOLDER / "calibration.json"`。しきい値は校正時と同じ値 |

   端末に出たOP・DRの数字をそれぞれ目視値と照合します。`ok`でも別の数字なら誤読です。欠測なら理由と `binary.png` を確認します。
5. 静止表示で一致したら、撮影側の `FRAME_COUNT` を例えば10にし、新しい保存先で表示切替中を短く撮ります。判定側の `FRAME` と `OUTPUT_DIR` を変えれば、同じ校正で切替前後を1枚ずつ確認できます。

### カメラが届く前・通常の画像を使う場合

OP／DRの両表示が写った静止画像を用意します。JPEG・BMP・PNGなど、OpenCVが読める形式を使えます。拡張子による形式制限はありません。動画のフレーム選択・画像への書き出しは動画プレーヤーなどで行います。実データはリポジトリ外か、このフォルダの`captures/`に置きます。

校正と判定は同じ解像度・切り出し・向きの画像を使います。画像は8bit BGRとして読み、EXIFによる自動回転は行いません。保存画像の向きは表示して確認してください。JPEGも使えますが、圧縮の影響を避けたい比較では無劣化の画像を使います。

通常画像では固定二値化と適応二値化を比較します。BGRのRチャンネルを生Bayerの代わりにはしません。

### BG505LMCFから記録する場合

親READMEのTeliCamSDK導入を済ませ、Qt環境で撮影する場合は同じPython 3.13用pytelicam wheelを`& $qtMamba run --prefix $qtPrefix python -m pip install "配布物内のwheelの実パス"`で追加します。撮影だけはpytelicam導入済みの本体用`.venv`でも実行でき、保存物をQt環境で校正・比較できます。SDKの実機動作はカメラ接続後に確認します。

メーカーのビューアでピント・露光・ゲイン・ROIを調整し、露光をManual、GainAutoとBalanceWhiteAutoをOff、ReverseX・ReverseYをOff、ROI開始位置OffsetX・OffsetYを偶数にします。その後ビューアを終了します。

```powershell
& $qtMamba run --prefix $qtPrefix python sandbox/ocr-comparison/capture_bayer.py
```

初期値は `CAMERA_INDEX = 0`、`FRAME_COUNT = 1`、`OUTPUT_DIR = FOLDER / "captures/run-01"` です。保存先の既存フォルダには書き込みません。最初は少ない枚数で撮影条件と保存時間を確認します。全画素100枚の画像部分は約501MBです。

取得時にTriggerModeをOff、PixelFormatをBayerBG8にし、露光・ゲイン・画像補正・ROIは現在の設定を使います。カメラのユーザー設定保存は実行しません。

| 保存物 | 内容 |
| --- | --- |
| `session.json` | 機種・解像度・ROI・反転・露光・ゲイン等の撮影条件 |
| `frames.jsonl` | 画像ファイル名、PC取得時刻、カメラのフレーム番号・時刻、取得・保存時間 |
| `frame-000000.npy`以降 | SDKのバッファを解放する前にコピーしたBayerBG8画像 |
| `preview.png` | 最初の画像をBGRへ変換した校正用画像 |

最新画像を取得するため、全フレームの保存は保証しません。`block_gap`は保存したフレーム番号の飛び数で、通信損失と処理による読み飛ばしを区別しません。PC時刻`received_at`は撮影時刻ではなく、カメラの`timestamp_ticks`とも別の時計です。

カメラ側の`BayerProcessingMode=Raw`と、SDKから変換せず取り出す`OutputImageType.Raw`は別の設定です。黒レベル・ガンマ・色ゲインは記録に残りますが、カメラ側のRawモードでは適用されません。

`Ctrl+C`で中断できます。比較で使うのは`frames.jsonl`に記録できた画像だけです。10/12bitや別のBayer配列は扱いません。

## 2. OP／DRを校正する

`calibrate.py`先頭の設定を編集します。`FOLDER`はこのスクリプトのあるフォルダです。

```python
SOURCE = FOLDER / "results/snapshot-01/binary.png"
OUTPUT = FOLDER / "calibration.json"
REFLECTION = "none"
SAMPLE_RADIUS = 1
SAMPLE_LENGTH_RADIUS = None
```

`SOURCE`はJPEGなどにも変更できます。`OUTPUT`の親フォルダは用意しておきます。既存ファイルには上書きしないため、やり直すときは別名を指定するか、不要な校正ファイルを自分で削除します。

`REFLECTION`は`none`・`horizontal`・`vertical`・`both`。両表示が同じ補正で正しく見える取付けを前提とします。カメラの反転機能は使わず、ここで見た目を補正します。

```powershell
& $qtMamba run --prefix $qtPrefix python sandbox/ocr-comparison/calibrate.py
```

1. 全セグメントの位置が分かる画像を使います。可能なら両計器の表示テストを利用します。
2. **OP側を先に**、左から各桁の上→右上→右下→下→左下→左上→中央をクリックします。42点です。
3. 続けて**DR側**を同じ順で42点指定します。画像の左にある計器がOPとは限りません。実機の対応を確認します。
4. OPは黄色、DRは水色で読み取り範囲が表示されます。84点を確認し、Enterで保存します。

画像上の**ホイールでカーソル位置を中心に拡大縮小**し、拡大中の**左ドラッグで移動**します。Qt標準ツールバーの元のサイズへ戻すボタンで全体表示に戻せます。拡大・移動モードの切替は不要です。点は移動せずに左クリックを離したときだけ確定し、ドラッグ操作は点として登録しません。

拡大・移動・画面サイズの変更後も選択済みの点を保持します。座標変換はQt版OpenCVに任せ、コールバックに渡された元画像座標を保存します。[OpenCVのQt表示](https://docs.opencv.org/4.x/dc/d46/group__highgui__qt.html)

`B`で直前の点を取り消せます。OP／DRの境界を戻ることもできます。`Q`・Esc・ウィンドウの×で中止し、中止時はファイルを作りません。静止画像なので一時停止やコマ送りはありません。設定は先頭、操作説明はこのREADMEと画面に置き、CLIの出力形式切替や独自ヘルプは設けていません。

校正JSONの保存は84点指定後のEnterです。ツールバーの保存ボタンは表示画像の書き出しで、校正JSONの保存ではありません。

点は赤い縁を探すのではなく、セグメントの内側を選びます。半径1・長手半径Noneなら3×3画素、長手半径3なら横線は7×3、縦線は3×7画素です。隣の線や背景が入らず、Bayer比較では赤画素を十分含む大きさにします。

JSONには画像サイズ、反転、読み取り半径、`op_points_px`・`dr_points_px`（各6桁×7点）と元画像のパスが入ります。座標は向き補正後の画像上の元解像度で、表示サイズには依存しません。比較では反転前の座標に戻して画素を読みます。生Bayer画像を反転してから赤画素を選ぶことはしません。

閾値を調整するだけなら再校正は不要です。カメラ・計器・ミラーの位置や、解像度・ROIを変えたときは再校正します。同じ画像サイズのまま位置が変わった場合はプログラムでは検出できません。

## 3. 同じ画像で方式を比較する

`compare.py`先頭の設定を編集します。

```python
SOURCE = FOLDER / "captures/run-01"
CALIBRATION = FOLDER / "calibration.json"
OUTPUT_DIR = FOLDER / "results/run-01"
```

`SOURCE`がフォルダなら`capture_bayer.py`の記録を読み、3方式を比較します。通常画像では`SOURCE = FOLDER / "captures/trial.jpg"`のように画像ファイルを指定します。通常画像のフォルダ一括読込や動画再生は行いません。

```powershell
& $qtMamba run --prefix $qtPrefix python sandbox/ocr-comparison/compare.py
```

`OUTPUT_DIR`は毎回新しい名前にします。既存フォルダには書き込みません。判定条件は`THRESHOLDS`のOP／DR欄と`OFF_FRACTION`・`ON_FRACTION`です。

| 設定 | 意味・初期値 |
| --- | --- |
| `binary` | グレースケールの固定閾値。111より大きい画素を白にする |
| `block_size`, `c` | 適応二値化の近傍サイズ25と定数0。`ADAPTIVE_THRESH_GAUSSIAN_C`・`THRESH_BINARY`を使う |
| `OFF_FRACTION`, `ON_FRACTION` | 白画素率が0.15以下なら消灯、0.65以上なら点灯。その間は欠測 |
| `off_red`, `on_red` | 生Bayer赤画素の中央値が30以下なら消灯、70以上なら点灯。その間は欠測 |

111・25・0はGoProでの試行を出発点にした値で、本番カメラの調整済み設定ではありません。赤画素の閾値も未調整です。OP／DRで明るさが違う場合は各側の値を変更します。位置の校正JSONは共用します。

二値化はBGRをグレースケールへ変換して行います。各側の読み取り領域を囲み、適応二値化の近傍半径分を加えた範囲を処理します。3×3などの小さなサンプル領域だけを切り出して適応二値化することはありません。白飛びだけを理由とした除外はありません。白い映り込みも点灯に見えるため、消灯位置での誤読を確認します。

| 出力 | 内容 |
| --- | --- |
| `settings.json` | 実際に使った撮影条件、校正、閾値、二値化画像の切り出し範囲 |
| `results.jsonl` | 1画像・1側・1方式につき1行。Bayerなら1画像で6行、通常画像なら4行 |
| `op-binary.png`など4枚 | 最初の画像のOP／DR各固定・適応二値化。反転前の向きで保存 |
| `summary.json` | 処理完了時の画像数と側・方式・理由別の件数。途中で失敗した場合は作らない |

各行は`file`・`block_id`・`side`・`method`で対応付けます。`display`は先頭空白を保つ6文字、`raw_value`は整数、`value`は1000で割った値です。`reason`は`ok`・`ambiguous`・`invalid_pattern`・`invalid_display`。`segment_scores`は各桁7点の順の42個で、二値化は白画素率、Bayerは赤画素の中央値です。

先頭消灯はゼロサプレスとして許容し、`    12`は`0.012`です。全消灯、途中・末尾の空白、不正な7セグパターン、曖昧な点灯はその側だけを欠測にします。OPの欠測でDRは捨てず、前フレームの値で補いません。連続一致待ちもしません。

`load_ms`は画像読込、`bgr_gray_ms`は共通のBGR・グレースケール変換、`process_ms`はその側・方式の処理時間です。共通時間は同じ画像の各行に同じ値を記録するため合計しません。Bayer赤画素判定自体はBGR変換を必要としません。ファイル出力時間は含まず、この数値をライブ取得のFPSや遅延とは扱いません。

## 確認する点

- 全数字、ゼロ付近、桁上がり・桁下がり、通常の変化速度、強い反射を含む記録を使う。
- 点灯・消灯の判定値の間に余裕があるかを見る。閾値を決めた記録と、評価する記録を分ける。
- 適応二値化でセグメントの中心が黒く抜けていないか、保存画像と判定値で確認する。
- `ok`の件数を正解件数と扱わない。既知の表示や目視の正解と照合し、誤読と欠測を分ける。
- 片側の白飛び・反射や表示切替中に、もう片側の読み取りが保たれるかを見る。

露光・ゲイン・しきい値は撮影条件に合わせて設定します。カメラやROIを動かしたら読み取り位置を再校正します。

## 既存の1表示比較

`read_bgr_fraction.py`と`read_bayer_red.py`は従来の1表示試作として残しています。新しい2表示JSONとは互換性がありません。既存の1表示校正JSONと記録でのみ使います。BGR方式は赤画素率と白い画素の除外、Bayer方式は赤画素の中央値を使います。1表示試作を使うときは各ファイル先頭の `CAPTURE_DIR` と `CALIBRATION` に撮影フォルダと1表示用の校正JSONを指定します。

## 検証

```powershell
& $qtMamba run --prefix $qtPrefix python -B -m unittest discover -s tests
& $qtMamba run --prefix $qtPrefix ruff check src sandbox/ocr-comparison tests
& $qtMamba run --prefix $qtPrefix ruff format --check src sandbox/ocr-comparison tests
```

合成画像と模擬入力で、2台の全数字・反転・ゼロサプレス・片側欠測、静止画像の形式、校正の取り消し・中止・上書き防止、標準ツールバーでの拡大・移動・全体表示後の座標、独立したフォルダでの比較実行を検証します。実機の撮影・最適露光・閾値・性能差は現物で確認してください。`captures/`・`results/`・`calibration.json`はGitの対象外です。
