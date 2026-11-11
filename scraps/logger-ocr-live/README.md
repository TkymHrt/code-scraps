# ロガーの電圧とOCR値のリアルタイム照合

同じWindows PCでNR-600の電圧とカメラの圧下表示を読みます。1つの入力ユニットから必要なCHの電圧を取得・換算し、時刻の近いOCR値と一緒に表示します。今回行う計算は各CHの2点による線形換算までです。

| スクリプト | 役割 |
| --- | --- |
| `logger.py` | NR-600から指定CHの現在電圧を `GetCurrentData()` で読む |
| `camera_calibration.py` | 各桁7点をクリックし、OCRの校正設定を表示する |
| `counter.py` | 赤い6桁の7セグを読み、同じ値が続いたら確定する |
| `camera_sdk.py` | TeliCamSDKで東芝テリー製カメラを開き、カラー画像を取得する |
| `main.py` | `logger.py` と `counter.py` を起動し、電圧の換算とOCR値との時刻照合を行う |

## 実行環境

Windows x64とPython 3.13を使います。pytelicam 1.1.1の対応Pythonは3.9～3.13のため、この題材は3.13に固定しています。以下のコマンドはすべて `scraps/logger-ocr-live` で実行します。

```powershell
uv python install 3.13
uv sync --inexact
uv run python --version
```

Webカメラ・動画・東芝テリー・ロガーで同じ `.venv` を使います。東芝テリー用のpytelicamはメーカー配布wheelを別途導入します。導入後も保持するため、依存関係の同期には `uv sync --inexact` を使います。`uv run` も追加導入したパッケージを保持します。

## 設定と実行

1. 使用するユニットの電圧CH（初期設定ではユニット1のCH1〜8）を有効にし、入力レンジを±10Vにして、連続収集用の `.ucf` を作ります。WAVE LOGGER PROを終了し、`logger.py` の `SETTINGS_FILE` にそのパスを、`DEVICE_ID` に本体IDを設定します。[NR-600の準備手順](../rolling-gauge-meter/README.md#準備)
2. OCRを校正し、表示された5項目をこのフォルダの `counter.py` に貼り付け、入力を選びます。初期の点は既存の合成動画用です。対象は `0.000`〜`999.999` の赤い6桁7セグです。[入力の切り替え](#ocrの入力を切り替える)・[OCRの校正手順](#ocrを校正する)
3. `main.py` の `CHANNELS` に取得・換算するCHを設定します。初期状態では8CH分あり、割当は下表のとおりです。必要なCHだけを使う場合は、使わないキーを削除します。実配線に合わせて名称と対応を確認し、各CHの `unit` と、`low_point`・`high_point` の `None` を現場の値に置き換えます。未設定のままでは取得を開始しません。計算側がCH名を取得側に渡すため、取得側でCHを重ねて設定する必要はありません。

| CH | 初期の名称 | 信号 |
| --- | --- | --- |
| `U1_CH1` | `rolling_speed` | 圧延速度 |
| `U1_CH2` | `load_OP` | 圧延荷重OP |
| `U1_CH3` | `load_DR` | 圧延荷重DR |
| `U1_CH4` | `tension_in` | 入側張力 |
| `U1_CH5` | `tension_out` | 出側張力 |
| `U1_CH6` | `bender_Inc` | ベンダーInc |
| `U1_CH7` | `bender_Dec` | ベンダーDec |
| `U1_CH8` | `exit_thickness` | 出側板厚 |

`U1_CH1` はユニット1の電圧CH1です。例えばCH2が1～3Vで0～100tonを表す場合、その設定欄は次のようになります。説明用の仮値なので、実際の単位・対応値に置き換えます。

```python
"U1_CH2": {
    "name": "load_OP",
    "unit": "ton",
    "low_point": (1.0, 0.0),
    "high_point": (3.0, 100.0),
},
```

`low_point` と `high_point` はそれぞれ `(電圧, 換算後の値)` です。電圧は−10～10V内で、低い点から順に指定します。換算後の値は増加・減少のどちらでも構いません。基準2点の電圧範囲をそのまま有効範囲にし、端点を含めて換算します。範囲外は外挿せず、換算値を欠測にします。以前の `valid_voltage` は不要です。

ロガーの測定レンジ±10Vと、信号ごとの換算範囲は別です。0～8V、1～3VなどをCHごとに設定できます。例えば `(0.0, 0.0)` と `(8.0, 80.0)` なら4Vは40になります。`unit` は換算後の数値に付ける表記で、mpm・ton・kgなどをCHごとに指定できます。単位同士の自動変換やCH間の加減算は行いません。±10Vの実際の入力レンジは `.ucf` 側で設定します。

`Ctrl+C` または片方の取得終了で両方の取得を停止します。終了後はWAVE LOGGER PROの画面で収集停止を確認してください。

```powershell
uv run python main.py
```

## 単体で確認する

ロガー取得とOCR取得はそれぞれ単体で動きます。以下は `scraps/logger-ocr-live` を開いた状態で実行します。単体起動では `--managed` を付けません。終了は `Ctrl+C` です。

### OCRの入力を切り替える

`counter.py` 先頭の `SOURCE = None` を、使う入力に対応する下表の設定例に置き換えます。

| 入力 | 設定例 | 実行環境 |
| --- | --- | --- |
| Webカメラ | `SOURCE = 0` | 通常の `.venv` |
| 動画 | `SOURCE = r"C:\measurement\recorded.avi"` | 通常の `.venv` |
| 東芝テリー | `SOURCE = ("teli", 0)` | 同じ `.venv` にpytelicamを追加、TeliCamSDKが必要 |

東芝テリーの番号はTeliCamSDKの検出順で、1台なら番号 `0` です。入力や撮影解像度を変えたら、その条件で校正します。

#### 東芝テリーを使う場合

TeliCamSDK（64bit）と使用するカメラのドライバをメーカーの手順に沿ってインストールします。ダウンロードした `pytelicam_v1_1_1_win64` はPython用ライブラリ・マニュアル・サンプルの配布物です。

次に、同じ `.venv` にPython 3.13用のwheelを導入します。配布物の展開先が異なる場合はパスを変更します。

```powershell
uv pip install --python .venv\Scripts\python.exe "hoge\wheel_files\pytelicam-1.1.1-cp313-cp313-win_amd64.whl"
uv run python -c "import pytelicam; print(pytelicam.__version__)"
```

校正にはライブ取得と同じ解像度・向きのPNGを使います。`camera_calibration.py` の `SOURCE` にPNGのパスを設定して校正し、表示された設定を `counter.py` に貼り付け、`SOURCE = ("teli", 0)` に変更します。

`camera_sdk.py` は開始前にトリガーモードをOFFにし、最新の受信画像をBGR24に変換します。モノクロ画像は受け付けません。解像度や露光はカメラ側で設定し、校正条件と合わせます。画像が1秒間届かなければ取得をエラー終了します。

### OCRを校正する

このフォルダの `camera_calibration.py` を使います。先頭の `SOURCE` にWebカメラの番号、動画のパス、または校正用PNGのパスを指定します。`REFLECTION` は `none`（補正なし）、`horizontal`（左右反転）、`vertical`（上下反転）、`both`（両方）から選び、既知の数字が正しく見えることを確認します。

```powershell
uv run python camera_calibration.py
```

`SAMPLE_RADIUS = 1`、`SAMPLE_LENGTH_RADIUS = None` は各点の周囲3×3画素を読みます。`SAMPLE_LENGTH_RADIUS` を `4` にすると、同じ半径1で横線は横長9×3、縦線は縦長3×9になります。線の一部がぼやける場合に試し、プレビューで帯が線の内側に収まり、隣の線や反射を含まない位置を選びます。半径は元の撮影画像上の画素数です。

カメラと計器を固定し、ピントや露光を調整します。全桁が `8` の表示テストなど、消灯部を含む全セグメントの位置が分かる画像を使ってください。

`Space` で画像を止め、左の桁から、各桁の上→右上→右下→下→左下→左上→中央の順に、点灯時に白飛びしない赤い箇所を左クリックします。計42クリックです。`B` で直前の点を取り消せます。42点が揃ったら `Enter` で確定し、出力した `FRAME_SIZE`、`REFLECTION`、`SAMPLE_RADIUS`、`SAMPLE_LENGTH_RADIUS`、`SEGMENT_POINTS` を同じフォルダの `counter.py` に貼り付けます。

動画では停止前に `N` で次のフレームへ進めます。中止は `Q`、`Esc`、画面の×です。中止した場合は設定を出力しません。画像端から読み取り範囲がはみ出す点は受け付けず、同じ部位を選び直します。縮小表示でも点と半径は元の撮影画像の座標です。カメラを動かしたときや解像度を変えたときも再校正します。校正スクリプトは単独で動き、設定値を表示するだけで読み取り側のファイルは書き換えません。

既定では領域内の赤い画素率で点灯・消灯を判定します。読み取り時は校正座標を元画像の向きに変換し、必要な画素だけを抽出します。判定が曖昧な場合や、白い画素率が `OFF_FRACTION`（初期値0.15）を超える場合は、そのフレームの値を `null` にして連続確定をリセットします。

#### 明るい場所で点灯の赤みが弱い場合

`--segment-scores` を付けると、領域ごとの `R - max(G, B)` の中央値と、白い画素が多い領域の番号を標準エラーに表示します。数字は校正時と同じ順で、左端の桁の上が1番です。標準出力のJSONLとは別に記録できます。

### OCRだけ取得する

OCRだけを動かす場合は、校正した設定と `SOURCE` を指定して次を実行します。ロガーや換算の設定は不要です。

```powershell
uv run python counter.py
uv run python counter.py --segment-scores
```

標準出力に `received_at` と `value` のJSONLが出ます。未確定・読取不能は `null` です。読み取り位置は校正画面で、赤みと白い画素は `--segment-scores` で確認できます。

### ロガーだけ取得する

ロガーだけを動かす場合は、`logger.py` 冒頭の `SETTINGS_FILE` に実機の `.ucf`、`DEVICE_ID` に本体ID、`UNIT_NUMBER` に取得対象の入力ユニット番号（初期値 `1`）を設定します。`CHANNEL_NUMBERS` は単体起動で取得するCH番号の一覧です。初期値は `[1, 2, 3, 4, 5, 6, 7, 8]` で、例えばCH1・CH3・CH5だけなら `[1, 3, 5]` とします。引数なしで実行すると、この設定に従います。OCRや `main.py` の設定は不要です。

`UNIT_NUMBER` を変更する場合は、`.ucf` のユニット構成とCHの設定を確認してください。`main.py` と連携するときは、`main.py` の `CHANNELS` のキー（例：`U2_CH1`）も同じユニット番号に揃える必要があります。

その実行だけ取得するCHを変える場合は、従来どおり引数で `U1_CH3` などのCH名を指定できます（ユニット番号は設定に合わせます）。引数のCH名を `CHANNEL_NUMBERS` より優先します。連携起動時は `main.py` の `CHANNELS` のキーからCH名を渡すため、`CHANNEL_NUMBERS` は参照しません。

```powershell
uv run python logger.py
uv run python logger.py U1_CH1 U1_CH8
```

標準出力に `received_at` と取得CHの `voltages` のJSONLが出ます。出力は換算前の電圧で、無効値は `null` です。終了は `Ctrl+C` です。終了後はWAVE LOGGER PROの画面で収集停止を確認します。連携起動では `CHANNEL_NUMBERS` の変更は不要ですが、`UNIT_NUMBER` は `main.py` のCH名と一致させてください。

`main.py` は両方の取得を起動して、電圧の換算とOCR値の時刻照合を行います。片方だけで換算・照合する起動方法はありません。

## 出力と時刻の照合

- ロガーは `received_at` と、CH名ごとの `voltages` を出力します。ロガーの無効値は `null` です。
- OCRは `received_at` と `value` を出力します。未確定の `value` は `null` です。
- 照合結果は標準出力のCSVに出ます。ロガーの新しい行ごとに、生電圧、換算値、最新のOCR値、時刻差、`voltage_status`、`ocr_status` を表示します。範囲外の生電圧はCSVに残り、対応する換算欄は空欄になります。他の有効なCHはそのまま換算します。記録する場合は標準出力を新しいCSVファイルにリダイレクトします。

`voltage_status` は `valid`（設定した全CHを換算できた）または `invalid`（いずれかのCHが欠測・範囲外）です。`ocr_status` は `ready`（OCR値が確定し、時刻差が上限以内）、`waiting`（OCR待ち、または受信停止）、`unreadable`（OCR未確定）、`time_gap`（時刻差が上限を超過）のいずれかです。電圧とOCRの状態は独立しており、照合に使えるのは `valid` かつ `ready` の行です。以前の `status` 列はこの2列に置き換えました。片側の受信が途切れたときは、`INPUT_TIMEOUT` 秒後にコンソールへ欠測を通知します。

時刻差は両方の `received_at` の絶対差です。ロガーは指定CHを読み終えたPC時刻、OCRはPCがフレームを読み込んだ時刻です。`MAX_TIME_GAP` の初期値は0.15秒で、実機で両方に現れる変化を見ながら調整します。動画の `received_at` は再生中にPCが読み込んだ時刻です。

ロガーは `READ_INTERVAL`（初期値0.2秒）の待ち時間を挟み、CHごとに `GetCurrentData()` で各ユニットの現在値を読みます。PCに転送済みの波形の最新位置とは別の値です。値が前回と同じでも毎回出力し、保存番号やサンプル位置での重複判定は行いません（Automationマニュアル p.44）。

NR-600の計測ユニット間同期は±1μs以下であり、今回の速報値の照合には現在値を使う方針です（NR-600マニュアル 10-2～10-3）。この仕様はCHを順に読むCOM呼出しの時間差や、カメラとの同期を保証するものではありません。多チャンネルリンクモードではサンプリング周期のずれが40ms以下、NR-CA04と他種ユニットの組み合わせでは設定に応じて最大40msまたは1サンプリング周期になる注記があります。現場の構成とOCRとの実際の時刻差を確認します。
