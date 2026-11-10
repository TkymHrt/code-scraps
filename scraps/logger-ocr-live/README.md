# ロガーの電圧とOCR値のリアルタイム照合

同じWindows PCでNR-600の電圧とカメラの圧下表示を読みます。1つの入力ユニットの8CHをそれぞれの単位に換算し、時刻の近いOCR値と一緒に表示します。今回行う計算は各CHの2点による線形換算までです。

| スクリプト | 役割 |
| --- | --- |
| `collect_logger.py` | NR-600から指定CHの現在電圧を `GetCurrentData()` で読む |
| `calibrate_meter.py` | 各桁7点をクリックし、OCRの校正設定を表示する |
| `read_meter.py` | 赤い6桁の7セグを読み、同じ値が続いたら確定する |
| `teli_camera.py` | TeliCamSDKで東芝テリー製カメラを開き、カラー画像を取得する |
| `calculate_readings.py` | `collect_logger.py` と `read_meter.py` を起動し、電圧の換算とOCR値との時刻照合を行う |

## 設定と実行

Windows で Python 3.14 と製品版WAVE LOGGER PROを使います。このフォルダの `.python-version` で、uv が使う Python を 3.14 系に指定しています。

```powershell
uv venv
uv pip install --python .venv/Scripts/python.exe -r requirements.txt
.venv/Scripts/python.exe --version
```

既存の `.venv` が Python 3.13 などの場合は、先に別名に移してから作り直します。`--version` の出力が `Python 3.14.x` になっていることを確認します。以下のコマンドもこのフォルダで実行します。仮想環境の有効化は不要です。計算スクリプトは同じ仮想環境のPythonで取得スクリプトを起動します。

1. ユニット1の電圧CH1～8を有効にし、入力レンジをすべて±10Vにして、連続収集用の `.ucf` を作ります。通常起動モードではWAVE LOGGER PROを終了し、`collect_logger.py` の `SETTINGS_FILE` にそのパスを、`DEVICE_ID` に本体IDを設定します。起動済みアプリに接続する `--attach` モードでは終了しません。[NR-600の準備手順](../rolling-gauge-meter/README.md#準備)
2. OCRを校正し、表示された5項目をこのフォルダの `read_meter.py` に貼り付け、入力を選びます。初期の点は既存の合成動画用です。対象は `0.000`〜`999.999` の赤い6桁7セグです。[入力の切り替え](#ocrの入力を切り替える)・[OCRの校正手順](#ocrを校正する)
3. `calculate_readings.py` の `CHANNELS` にある8CH分の設定を埋めます。初期の割当は下表のとおりです。実配線に合わせて名称と対応を確認し、各CHの `unit` と、`low_point`・`high_point` の `None` を現場の値に置き換えます。未設定のままでは取得を開始しません。計算側がCH名を取得側に渡すため、取得側でCHを重ねて設定する必要はありません。

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

```powershell
.venv/Scripts/python.exe calculate_readings.py
```

`Ctrl+C` または片方の取得終了で両方の取得を停止します。終了後はWAVE LOGGER PROの画面で収集停止を確認してください。アプリを残す `--attach` モードを使う場合は、`calculate_readings.py` の `logger_command` に `"--attach"` を追加し、WAVE LOGGER PROを先に手動起動します。

## 単体で確認する

ロガー取得とOCR取得はそれぞれ単体で動きます。以下は `scraps/logger-ocr-live` を開いた状態で実行します。単体起動では `--managed` を付けません。終了は `Ctrl+C` です。

### OCRの入力を切り替える

`read_meter.py` 先頭の `SOURCE = None` を、使う入力に対応する下表の設定例に置き換えます。

| 入力 | 設定例 | 実行環境 |
| --- | --- | --- |
| Webカメラ | `SOURCE = 0` | 通常の `.venv` |
| 動画 | `SOURCE = r"C:\measurement\recorded.avi"` | 通常の `.venv` |
| 東芝テリー | `SOURCE = ("teli", 0)` | TeliCamSDKと `.venv-teli` |

東芝テリーの番号はTeliCamSDKの検出順で、1台なら番号 `0` です。入力や撮影解像度を変えたら、その条件で校正します。

#### 東芝テリーを使う場合

TeliCamSDKと `pytelicam` が使えるPython 3.13環境（`.venv-teli`）と、カラー・連続撮影の対応機を前提とします。 [メーカーのSDK情報](https://www.toshiba-teli.co.jp/cgi/ss/jp/service_j.cgi)

校正にはライブ取得と同じ解像度・向きのPNGを使います。`read_meter.py` の `SOURCE` を `("teli", 0)` にし、単体なら `.venv-teli/Scripts/python.exe read_meter.py`、ロガーとの連携なら `.venv-teli/Scripts/python.exe calculate_readings.py` で起動します。

### OCRを校正する

このフォルダの `calibrate_meter.py` を使います。先頭の `SOURCE` にWebカメラの番号、動画のパス、または校正用PNGのパスを指定します。`REFLECTION` は `none`（補正なし）、`horizontal`（左右反転）、`vertical`（上下反転）、`both`（両方）から選び、既知の数字が正しく見えることを確認します。

`SAMPLE_RADIUS = 1`、`SAMPLE_LENGTH_RADIUS = None` は各点の周囲3×3画素を読みます。`SAMPLE_LENGTH_RADIUS` を `4` にすると、同じ半径1で横線は横長9×3、縦線は縦長3×9になります。線の一部がぼやける場合に試し、プレビューで帯が線の内側に収まり、隣の線や反射を含まない位置を選びます。半径は元の撮影画像上の画素数です。

カメラと計器を固定し、ピントや露光を調整します。全桁が `8` の表示テストなど、消灯部を含む全セグメントの位置が分かる画像を使ってください。

```powershell
.venv/Scripts/python.exe calibrate_meter.py
```

`Space` で画像を止め、左の桁から、各桁の上→右上→右下→下→左下→左上→中央の順に、点灯時に白飛びしない赤い箇所を左クリックします。計42クリックです。`B` で直前の点を取り消せます。42点が揃ったら `Enter` で確定し、出力した `FRAME_SIZE`、`REFLECTION`、`SAMPLE_RADIUS`、`SAMPLE_LENGTH_RADIUS`、`SEGMENT_POINTS` を同じフォルダの `read_meter.py` に貼り付けます。

動画では停止前に `N` で次のフレームへ進めます。中止は `Q`、`Esc`、画面の×です。中止した場合は設定を出力しません。画像端から読み取り範囲がはみ出す点は受け付けず、同じ部位を選び直します。縮小表示でも点と半径は元の撮影画像の座標です。カメラを動かしたときや解像度を変えたときも再校正します。校正スクリプトは単独で動き、設定値を表示するだけで読み取り側のファイルは書き換えません。

既定では領域内の赤い画素率で点灯・消灯を判定します。読み取り時は校正座標を元画像の向きに変換し、必要な画素だけを抽出します。判定が曖昧な場合や、白い画素率が `OFF_FRACTION`（初期値0.15）を超える場合は、そのフレームの値を `null` にして連続確定をリセットします。

#### 明るい場所で点灯の赤みが弱い場合

`--segment-scores` を付けると、領域ごとの `R - max(G, B)` の中央値と、白い画素が多い領域の番号を標準エラーに表示します。数字は校正時と同じ順で、左端の桁の上が1番です。標準出力のJSONLとは別に記録できます。

```powershell
.venv/Scripts/python.exe read_meter.py --segment-scores 2> ocr-scores.log
```

東芝テリーの場合は上のコマンドの `.venv` を `.venv-teli` に読み替えます。実際の設置場所で、全点灯の `888.888` と、各線が消灯する複数の既知値（例 `111.111`、`222.222`、`555.555`）を別々に表示してスコアを比較します。白い画素が多いフレームは除きます。点灯と消灯の値に間隔がある場合は、`read_meter.py` の `RED_EXCESS_LIMITS` に `(消灯の上限, 点灯の下限)` を設定すると中央値で判定します。両者の間は `null` です。点灯と消灯が重なる場合は、遮光・露光・選択位置を見直します。判定方法や領域を変えたら、しきい値調整とは別の既知値で誤確定と欠測を確認します。

### OCRだけ取得する

OCRだけを動かす場合は、校正した設定と `SOURCE` を指定して次を実行します。ロガーや換算の設定は不要です。

```powershell
.venv/Scripts/python.exe read_meter.py
```

標準出力に `received_at` と `value` のJSONLが出ます。未確定・読取不能は `null` です。読み取り位置は校正画面で、赤みと白い画素は `--segment-scores` で確認できます。

### ロガーだけ取得する

ロガーだけを動かす場合は、`collect_logger.py` の `SETTINGS_FILE` に実機の `.ucf`、`DEVICE_ID` に本体IDを設定します。`CHANNEL_NAMES` は単体起動で取得するCHの一覧で、初期値は `U1_CH1`〜`U1_CH8` の8CHです。実機で有効にしたCHに合わせて変更し、引数なしで実行します。OCRや `calculate_readings.py` の設定は不要です。

```powershell
.venv/Scripts/python.exe collect_logger.py
```

**Ctrl+CでWAVE LOGGER PROのウィンドウまで終了させたくない場合**は、WAVE LOGGER PROを通常の方法で先に起動し、収集していない状態で次のように接続します。

```powershell
.venv/Scripts/python.exe collect_logger.py --attach
```

`--attach` は `GetActiveObject()` で起動済みのAutomationサーバに接続します。`DispatchEx()` によるアプリの新規起動は行いません。接続できなければエラーで終了し、別のWAVE LOGGER PROを勝手に起動しません。事前にアプリ側で現在の設定・測定が変更されても問題ない状態か確認してください。このスクリプトは指定した `.ucf` を読み込み、`Start()`・`Stop()` を実行します。

Ctrl+Cを受けると直ちにPythonの処理を中断する代わりに停止要求を記録し、通常の終了処理で `Stop()` を呼びます。`Stop()` は収集停止であり、アプリ終了の `Quit()` は呼びません。ただし、WAVE LOGGER PROが起動中インスタンスの取得に対応しているか、停止後にウィンドウが残るかは実機で確認が必要です。`--attach` なしではこれまでどおり `DispatchEx()` で新規起動します。

その実行だけ取得するCHを変える場合は、引数で指定します。指定したCHを `CHANNEL_NAMES` より優先します。

```powershell
.venv/Scripts/python.exe collect_logger.py U1_CH1 U1_CH2
```

標準出力に `received_at` と取得CHの `voltages` のJSONLが出ます。出力は換算前の電圧で、無効値は `null` です。終了は `Ctrl+C` です。終了後はWAVE LOGGER PROの画面で収集停止を確認します。連携起動では計算側がCHを明示的に渡すため、この単体用設定を重ねて変更する必要はありません。

`calculate_readings.py` は両方の取得を起動して、電圧の換算とOCR値の時刻照合を行います。片方だけで換算・照合する起動方法はありません。

## Ctrl+CでWAVE LOGGER PROが消える場合の切り分け

WAVE LOGGER PROのウィンドウが消えても、NR-600本体の収集が続いている場合があります。**GUIの存続・Pythonプロセスの存続・COM上の収集状態・装置本体の収集状態は別々に確認**してください。ログで確認できるのはCOM戻り値・状態とWindowsプロセスの有無までであり、本体の収集停止は実機で必ず確認します。誤った停止でデータを失わないよう、試験前に記録先と保存状況も確認してください。

### 1. 別ターミナルでGUIのプロセスを監視

コンソールを2つ開き、**先に**監視側で次を実行します。監視はCOMや装置に接続せず、Windowsの `tasklist /v` を約0.5秒ごとに記録します。Python側の取得プロセスが終了しても別ターミナルでは監視が続きます。

```powershell
.venv/Scripts/python.exe watch_logger_processes.py --seconds 90
```

`logger_process_watch_<日付>_<PID>.jsonl` が作られます。検出対象は `watch_logger_processes.py` の `PROCESS_KEYWORDS` にあり、起動中のWAVE LOGGER PROがログに現れなければ実際のexe名・ウィンドウタイトルに合わせて変更してください。プロセスが見えないことだけで装置の停止を判断しないでください。

### 2. Ctrl+Cを使わずにQキーで終了

もう一つのターミナルで実行します。`SETTINGS_FILE` と `DEVICE_ID` は正しい実機設定にします。

```powershell
.venv/Scripts/python.exe collect_logger.py --diagnose --stop-on-key
```

**Qキー**を押すと停止要求が入り、`Stop()`、停止後の`GetState()`、Python終了の各段階を記録します。エンターキーは不要です。`--stop-on-key` はWindowsコンソールでの単体起動専用です。起動済みのアプリに接続して比較する場合は、事前にWAVE LOGGER PROを手動起動し、`--attach` を追加してください。

```powershell
.venv/Scripts/python.exe collect_logger.py --attach --diagnose --stop-on-key
```

次に同じ条件で `--stop-on-key` を外して起動し、**Ctrl+C**で終了します（`--diagnose` は残します）。WAVE LOGGER PROのウィンドウが消えるタイミング、収集状態とプロセスのログを比較してください。

`collect_logger_diag_<日付>_<PID>.jsonl` は実行したターミナルのカレントディレクトリに保存され、取得値のJSONL（標準出力）に混ざりません。特に次のイベントを見ます。

| イベント | 判断のポイント |
| --- | --- |
| `configuration`, `com_connected` | 新規起動か既存インスタンスへの接続か |
| `start_result` | `Start()` の戻り値（0は成功） |
| `cleanup_begin` | 終了処理まで到達したか、Ctrl+CをPythonが認識したか |
| `stop_begin`, `stop_result`, `stop_exception` | `Stop()` を呼べたか、戻り値はどうか（0が成功） |
| `get_state_after_stop` | `GetState() == 1`（収集停止）になったか |
| `hold_com_begin`, `hold_com_end` | COM参照を保持している期間 |
| `releasing_com_references`, `trace_close` | Python側の処理が終了に向かったか |

`stop_result` がなく `stop_begin` もなければ、収集停止前に処理が中断されたか、別の経路で終了した可能性があります。`stop_result` が0でも `get_state_after_stop` が1にならない場合は、収集停止完了を確認できていません。`GetState() == 1` でも装置本体の収集継続を否定する証拠にはなりません。

### 3. コメントを切り替えて原因を絞る

`collect_logger.py` 冒頭に診断実験用の定数と、コメントアウトした切り替え例を置いています。**1回の試行につき1項目だけ変更**し、実行した条件とログファイル名を記録してください。`--diagnose` を付けた場合だけ有効です。

| 変更箇所 | 分かること |
| --- | --- |
| `--attach` の有無 | 新規COMサーバの終了なのか、起動済みGUIにも影響するのか |
| `DIAG_HOLD_COM_SECONDS = 15.0` | `Stop()` 後、PythonがCOM参照を保持している間はGUIが残るか。残るならCOM参照の寿命との関連が強い |
| `DIAG_SKIP_INITIALIZE_ON_ATTACH = True` | 既存アプリへの `Initialize()` が影響するか |
| `DIAG_SKIP_IDENTIFIER_ON_ATTACH = True` | 既存アプリへの `SetIdentifier()` が影響するか |
| `DIAG_SKIP_OPEN_FILE_ON_ATTACH = True` | 既存アプリへの `OpenFile()` が影響するか |
| `DIAG_SKIP_VISIBLE_ON_ATTACH = True` | 既存アプリへの `Visible = True` が影響するか |
| `DIAG_SKIP_STOP = True` | `Stop()` 呼出しそのものがGUI終了に関係するか（**危険な最終確認用**） |

`Initialize`・`SetIdentifier`・`OpenFile`・`Visible` の省略は `--attach` 時だけです。省略する試験は、GUI側で接続・設定ファイルの読込を先に済ませた場合に限ります。省略時に起動できないことはGUI終了の原因の証明にはなりません。

**`DIAG_SKIP_STOP = True` は装置の収集が続いたままスクリプトが終了することがあります。** 通常運転では使用せず、必ず実機側から手動停止できることを確認した監視下でのみ試します。まずはQキー・Ctrl+C・COM保持の比較を優先してください。

### 4. `calculate_readings.py` を使う場合

こちらはPythonが2つの子プロセス（ロガー・OCR）を起動するため、親のCtrl+Cや停止待ちタイムアウトによる強制終了も区別します。親側でもQキー停止を試せます。

```powershell
.venv/Scripts/python.exe calculate_readings.py --stop-on-key
```

同ファイル冒頭の `LOGGER_DIAGNOSE` を `True` にするとロガー子プロセスへ `--diagnose` を渡します。既存GUIに接続する場合は `LOGGER_ATTACH = True` にします。必要な場合だけ `CHILD_STOP_TIMEOUT` を5秒から20秒に上げて、親プロセスによる `kill()` と区別してください。まず単体の `collect_logger.py` で原因を切り分けることを推奨します。

### 結果の読み方

- **Qキーでは消えずCtrl+Cだけで消える:** WindowsコンソールのCtrl+CイベントがPython以外のプロセスにも影響している可能性があります。
- **Stop後のCOM保持中は消えず、Python終了と同時に消える:** COMサーバへの参照がなくなるとGUIが終了する構造の可能性があります。
- **Stop直後に消える:** `Stop()` 自体、COM側の状態遷移、アプリ内の例外が疑われます。
- **COM状態は停止、装置は収集継続:** 別の測定インスタンス・機器状態を確認してください。Windowsプロセスの有無だけでは収集の継続を証明できません。

## 出力と時刻の照合

- ロガーは `received_at` と、CH名ごとの `voltages` を出力します。ロガーの無効値は `null` です。
- OCRは `received_at` と `value` を出力します。未確定の `value` は `null` です。
- 照合結果は標準出力のCSVに出ます。ロガーの新しい行ごとに、生電圧、換算値、最新のOCR値、時刻差、`voltage_status`、`ocr_status` を表示します。範囲外の生電圧はCSVに残り、対応する換算欄は空欄になります。他の有効なCHはそのまま換算します。記録する場合は標準出力を新しいCSVファイルにリダイレクトします。

`voltage_status` は `valid`（設定した全CHを換算できた）または `invalid`（いずれかのCHが欠測・範囲外）です。`ocr_status` は `ready`（OCR値が確定し、時刻差が上限以内）、`waiting`（OCR待ち、または受信停止）、`unreadable`（OCR未確定）、`time_gap`（時刻差が上限を超過）のいずれかです。電圧とOCRの状態は独立しており、照合に使えるのは `valid` かつ `ready` の行です。以前の `status` 列はこの2列に置き換えました。片側の受信が途切れたときは、`INPUT_TIMEOUT` 秒後にコンソールへ欠測を通知します。

時刻差は両方の `received_at` の絶対差です。ロガーは指定CHを読み終えたPC時刻、OCRはPCがフレームを読み込んだ時刻です。`MAX_TIME_GAP` の初期値は0.15秒で、実機で両方に現れる変化を見ながら調整します。動画の `received_at` は再生中にPCが読み込んだ時刻です。

ロガーは `READ_INTERVAL`（初期値0.2秒）の待ち時間を挟み、CHごとに `GetCurrentData()` で各ユニットの現在値を読みます。PCに転送済みの波形の最新位置とは別の値です。値が前回と同じでも毎回出力し、保存番号やサンプル位置での重複判定は行いません（Automationマニュアル p.44）。

NR-600の計測ユニット間同期は±1μs以下であり、今回の速報値の照合には現在値を使う方針です（NR-600マニュアル 10-2～10-3）。この仕様はCHを順に読むCOM呼出しの時間差や、カメラとの同期を保証するものではありません。多チャンネルリンクモードではサンプリング周期のずれが40ms以下、NR-CA04と他種ユニットの組み合わせでは設定に応じて最大40msまたは1サンプリング周期になる注記があります。現場の構成とOCRとの実際の時刻差を確認します。

## Ruffで静的チェックする

このフォルダで実行します。1行目はファイル名と行番号、2行目はルールごとの件数を表示します。

```powershell
uvx ruff@0.17.4 check .
uvx ruff@0.17.4 check --statistics .
```

`ruff.toml` は Python 3.14 を基準に、未定義の名前や未使用の import、`zip()` の `strict=` 未指定などのバグにつながりやすい書き方、import の並び、古い Python の書き方をチェックします。安全性のチェックには `eval`、`exec`、シェル経由のコマンド実行を含めます。[Ruff のルール一覧](https://docs.astral.sh/ruff/rules/)

2026-11-07、全ルールから上記のルールに絞り、Ruff 0.17.4 で指摘0件、自動テスト36件の成功を確認しました。

## 検証

2026-11-08、`calculate_readings.py` の設定確認とCSV行の組み立てを関数に分けました。Python 3.14で自動テスト52件、Python 3.13で換算・照合のテスト9件が通り、Ruffの指摘は0件でした。OCRの受信停止を一度だけ通知し、古い行を捨て、新しい行で照合が復帰することを確認しました。模擬の子プロセスでCSV出力と両方の正常終了も確認しました。実機での取得は未確認です。

2026-11-08、東芝テリーのSDK処理を `teli_camera.py` に分離しました。Python 3.14と3.13で自動テスト51件、Ruffチェックが通りました。Webカメラ経路は補助スクリプトとSDKを読み込まず、模擬SDKでは停止要求中に画像待ちがタイムアウトしても正常に解放・終了することを確認しました。

2026-11-08、OCRを校正領域だけの処理に変更し、東芝テリー入力、PNG校正、細帯と赤みの中央値による判定を追加しました。Python 3.14と3.13で自動テスト50件、Ruffチェックが通りました。既定設定は合成画像の4種類の反転で旧版の認識値と一致し、960×360の合成画像で反転と認識の中央値が約3.19 msから約0.13 msになりました。生成したAVIでJSONLと動画終了、日本語のファイル名を含むPNGで校正画像の読み込みを確認しました。東芝テリーは模擬SDKで画像の取得・重複除外・タイムアウト・解放を確認しました。SDKを入れた実機での取得、明所での精度、カメラからの取得遅延は未計測です。

2026-11-07、ロガーの機器ID設定・設定ファイル読込・収集開始で共通する戻り値チェックをまとめました。模擬COMで、各操作の失敗時に操作名とエラーコードが出て電圧取得へ進まないことを確認しました。自動テスト37件とRuffが通りました。実機での確認は未実施です。

2026-11-07、ロガーのCOMオブジェクト作成を `DispatchEx` に簡略化しました。COMのメソッドを明示するため、`dynamic.Dispatch` と `_FlagAsMethod` を使っています。模擬COMで初期化から電圧取得・停止までを確認し、自動テスト36件が通りました。変更後のWAVE LOGGER PROとNR-600での動作は未確認です。

2026-11-07、Windows x64 の Python 3.14.9 で、既存の `requirements.txt` から pywin32 312・opencv-python 5.0.0.93・NumPy 2.5.4 をインストールしました。依存関係の整合性と読み込みを確認し、`-X dev -W error` を指定して自動テスト36件が通りました。合成動画と模擬ロガーを使い、子プロセスからの出力をCSVで照合できることと、動画の終了時に両方の子プロセスが停止することも確認しました。NR-600と実カメラでの取得は未確認です。

2026-11-06、GM式の試算を追加したコミット `525249f` をリバートし、電圧換算とOCR照合までの動作へ戻しました。ロガー単体は引数なしで `CHANNEL_NAMES` のCHを取得できるようにしました。自動テスト36件が通り、模擬COMで単体8CH、単体のCH変更、引数の優先、連携時の親プロセス監視とCH指定を確認しています。実機での取得は未確認です。

2026-11-06、このフォルダ内で単独実行できる `calibrate_meter.py` を追加し、自動テスト30件が通りました。校正GUIを模擬して、42点と4設定の出力、同じフォルダの読み取り側での認識、範囲外クリックの拒否、桁をまたぐ取り消し、中止、半径の設定、4K画像の座標維持を確認しました。実画面と実カメラでの操作確認は未実施です。

2026-11-06、点の周囲3×3画素での認識へ変更し、この題材の自動テスト21件と `seven-segment-ocr` の43件が通りました。各桁の0〜9、`0.0`、不正な消灯位置、白飛びの拒否、1画素の雑音、曖昧な色、範囲外設定の拒否、JSONLの形式と白飛び後の連続確定リセットを確認しました。共通校正の4項目を両方の読み取り側に貼り付けて使えることも確認しています。実画面の操作確認は省略し、実機の精度と遅延は未確認です。

2026-11-06にWindows上のuv 0.13.5、Python 3.13.18で `.venv` を作成しました。依存パッケージの整合性、pywin32・OpenCV 5.0.0・NumPy 2.5.4の読み込み、自動テスト14件の成功を確認しました。NR-600とカメラを使った取得・照合はこの環境では未確認です。

現在値の取得・換算処理は、このフォルダで次のコマンドを実行して確認できます。

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -v
```

2026-11-05に模擬COMの自動テスト5件が通りました。指定CHの現在値、同値が続くときの出力、無効値の `null` 化、開始直後の停止状態での待機、異常時の収集停止を確認しました。実機での取得、現場の換算値、許容時刻差は未確認です。

2026-11-06に自動テスト14件が通りました。1ユニット8CHの指定、異なる電圧範囲・単位での換算、増加・減少する出力、端点・範囲外・欠測、未設定や±10V外の基準点での起動防止を確認しました。CSVでは生電圧と各CHの換算値を確認し、OCR待ち・未確定・時刻差超過でも電圧の異常が隠れないこと、150msと151msの境界を確認しました。現場の換算値と実機動作は未確認です。

点方式への変更前には、模擬COMと合成動画で3本の連携と片側の終了・異常時の停止を確認しています。合成動画168フレームのOCR確定値は当時の読み取り処理と一致しました。照合処理では `0.0` と `null`、150msと151msの境界、受信停止を確認しました。
