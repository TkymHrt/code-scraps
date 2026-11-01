# 赤い6桁7セグをカメラから読む

ハーフミラーで反射した赤色7セグを、OpenCVによる色抽出と点灯パターンの照合で読みます。学習モデルは使いません。
左から3桁目と4桁目の間に小数点があるものとし、整数側の不要な先頭桁は消灯していても位置を保ちます。

実行用は `read_meter.py`、動画シミュレーションは `sandbox/simulate_meter.py`、自動検証は `tests/` に置きます。
実機画像がまだないため、撮影位置と赤色のしきい値は現場で校正する前提です。

## 方式と対象

```text
カメラ / 動画
  → 鏡像を戻す
  → 選んだ四隅から表示面を720×200に透視補正
  → 赤い画素を抽出
  → 6個の固定枠で7本の点灯状態を調べる
  → 数字へ変換し、3桁目と4桁目の間に小数点を補う
  → 同じ値が連続したら確定し、JSONLとCSVへ出力
```

桁の位置を固定するので、`"  1234"` は `1.234`、`" 12345"` は `12.345`、`"123456"` は `123.456` になります。`"  0000"` は `0.000` です。整数部の先頭消灯だけを許し、整数の1の位や小数部の消灯、途中の空白、全消灯は無効にします。

対象は **0.000〜999.999の非負数、赤色、固定された6桁の通常の7セグ** です。負号、単位表示、桁数や小数点位置の変更は扱いません。学習データ、Tesseract、GPU、ネット接続は認識時に不要です。カメラと計器の位置は固定してください。

数字全体の輪郭を自動検出すると、消灯桁や幅の狭い `1` で位置がずれます。そのため、最初に人が表示面と6桁の位置を指定する方式を選びました。自動的に最も近い数字へ置き換える処理は入れていません。

## まずシミュレーションで試す

Python 3.10以降を使います。PowerShellでリポジトリのルートから実行します。

```powershell
Set-Location scraps/seven-segment-ocr
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

.\.venv\Scripts\python.exe sandbox/simulate_meter.py
.\.venv\Scripts\python.exe read_meter.py read --video outputs/simulation/meter.avi --config outputs/simulation/meter_config.json --csv outputs/simulation/readings.csv
```

上段に補正後の表示と読み取り領域、下段に赤色の抽出結果が出ます。黄色い小枠は点灯・消灯を決められない領域です。`Q` または `Esc` で停止します。動画はおおむね元のfpsで表示しますが、処理時間が加わるので厳密な再生時計にはなりません。

シミュレーターは、透視、鏡像、ぼけ、雑音、輝度低下、弱い白い反射、読み取り範囲外の赤い物体を加えます。正常値のほか、全消灯・途中消灯・数字にない点灯・正常値への復帰を含む14条件、168フレーム、30fpsの動画です。以下が生成されます。

| ファイル | 内容 |
|---|---|
| `outputs/simulation/meter.avi` | 合成したカメラ動画 |
| `outputs/simulation/truth.csv` | フレームごとの正解と条件名 |
| `outputs/simulation/meter_config.json` | 合成動画に対応する校正 |
| `outputs/simulation/preview.png` | 鏡像のサンプル画像 |
| `outputs/simulation/readings.csv` | 読み取りプログラムの出力 |

画面を出さず、各フレームを順番に処理する場合は `--headless` を付けます。JSONLもファイルに残せます。

```powershell
.\.venv\Scripts\python.exe read_meter.py read --video outputs/simulation/meter.avi --config outputs/simulation/meter_config.json --csv outputs/simulation/headless.csv --headless > outputs/simulation/readings.jsonl
```

校正・CSV・シミュレーションの生成先は上書きしません。再実行時は新しい保存先を指定します。生成物、実測データ、仮想環境はGitの対象外です。

```powershell
.\.venv\Scripts\python.exe sandbox/simulate_meter.py --output-dir outputs/simulation-vertical --reflection vertical --frames-per-value 20 --fps 30
```

## 実機を校正する

1. ハーフミラーとカメラを固定し、6桁が十分な大きさで写るようにします。映り込みを遮る黒い覆いを使い、ピント、露光、ゲイン、ホワイトバランスをカメラ側で調整します。赤が白飛びすると色抽出ができません。調整後は自動変更を止めます。
2. 可能なら全桁が `8` になる表示テスト、または全セグメントの外形が分かる状態を使います。消灯や `1` の細い光だけを囲まず、**その桁が8だった場合の7本すべての外接枠**を指定する必要があります。
3. 以下を実行します。カメラ番号が違う場合は `0` を変更します。

```powershell
.\.venv\Scripts\python.exe read_meter.py calibrate --camera 0 --config meter_config.json --reflection horizontal
```

反射補正は設置方向に合わせて選びます。「カメラが上にある」ことだけでは補正方向は決まりません。既知の数字、例えば `123.456` が正しい順序・上下で見える設定を選んでください。

| `--reflection` | 補正 |
|---|---|
| `horizontal` | 左右反転（既定） |
| `vertical` | 上下反転 |
| `both` | 上下・左右の両方を反転 |
| `none` | 反転しない |

4. プレビューで `Space` を押して画像を止めます。**反射補正後の画像**で、6桁全体を含む表示面の四隅を「左上→右上→右下→左下」の順にクリックし、`Enter` を押します。消灯した桁の場所も含めます。四隅の選び直しは `R`、中止は `Q` または `Esc` です。
5. 透視補正後の画像で、左から順に6個の桁枠をドラッグし、各回 `Enter` で確定します。枠は7本の外接枠に合わせ、余分な背景や桁間の隙間を入れません。消灯した桁も選びます。選択済みの枠は黄色で表示されます。中止は `C` です。
6. 保存されたJSONを使って読み取ります。

```powershell
.\.venv\Scripts\python.exe read_meter.py read --camera 0 --config meter_config.json --csv outputs/measurement-001.csv
```

校正用に録画した動画も使えます。動画の校正プレビューでは `N` で次のフレームへ進み、`Space` で選択に入ります。

```powershell
.\.venv\Scripts\python.exe read_meter.py calibrate --video recorded.avi --config outputs/recorded_config.json --reflection vertical
```

撮影解像度が校正時と違えば停止します。カメラ読み取りでは校正時の解像度を要求しますが、カメラが対応しない場合は自動的に合わせられません。カメラやミラーを動かしたときも再校正してください。

## 出力の読み方

標準出力は1フレーム1行のJSONL、`--csv` は同じ項目のCSVです。説明やエラーは標準エラーに出します。`Ctrl+C` でもCSVを閉じてカメラを解放します。カメラの途中切断はエラー終了します。

```json
{"frame_index":2,"captured_at":"2026-11-02T00:00:00.067+00:00","source_time_seconds":0.066667,"status":"ok","display":"  1234","raw_value":"1.234","value":"1.234","reason":""}
```

| 項目 | 意味 |
|---|---|
| `frame_index` | 0から始まるフレーム番号 |
| `captured_at` | PCで処理を始めた時刻。UTC。センサーの撮影時刻ではない |
| `source_time_seconds` | 動画は番号÷fps、カメラは収集開始からの経過秒 |
| `display` | 6文字の読取結果。消灯は空白、読めない桁は `?` |
| `raw_value` | そのフレームだけの読取値。確定前の値も含む |
| `value` | 連続判定を通った値だけ。後段で使う列 |
| `status` | `warming_up` は連続判定待ち、`ok` は確定、`invalid` は読取不能 |
| `reason` | `all_blank` は全消灯、`misplaced_blank` は不正位置の消灯、`uncertain_segments` は曖昧・不正な点灯 |

`value` と `raw_value` は、`0.001` や末尾のゼロを保持するため文字列です。数値計算では `decimal.Decimal` などへ変換します。`invalid` と `warming_up` の `value` はJSONでは `null`、CSVでは空欄です。直前の確定値を埋め直すことはしません。後段は `status == "ok"` の値を使ってください。

初期設定では同じ有効値が3フレーム続くと確定し、その後もフレームごとに出力します。値の変更や無効フレームで連続判定はリセットされます。30fpsでは最初の観測から確定まで約67msですが、撮影・転送・処理の遅延が別に加わります。変化が速く3フレーム続かない値は確定しません。

## 赤抽出と点灯判定の調整

設定JSONの次の値を現場に合わせます。

| 設定 | 初期値 | 意味 |
|---|---|---|
| `red_min` | 70 | 赤成分Rの下限（0〜255の画像） |
| `red_margin` | 40 | `R - max(G, B)` の下限。白い反射を除く |
| `off_fraction` | 0.15 | 各サンプル領域の赤い画素率がこれ以下なら消灯 |
| `on_fraction` | 0.65 | 赤い画素率がこれ以上なら点灯 |
| `stable_frames` | 3 | 確定に必要な同じ有効値の連続フレーム数 |

例えば赤い画素率が0.40なら、消灯にも点灯にも寄せず、そのフレームを無効にします。下段の抽出画像を見て、背景が黒、点灯部が白になるように調整してください。境界を無理に緩める前に、撮影の白飛び・ピント・枠のずれを確認します。

各桁の7領域は `read_meter.py` 冒頭の `SEGMENT_REGIONS` にあります。桁枠の幅・高さを1とした割合で、上、右上、右下、下、左下、左上、中央の順です。字体の傾きや太さが違い、小枠がセグメントから外れる場合はここを調整します。設定・反射補正・認識・保存の処理は実行用スクリプト1本で追えます。

## 検証記録

2026-11-02、Windowsで以下を確認しました。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

- Python 3.14.8 / OpenCV 5.0.0 / NumPy 2.5.4、および Python 3.12.14 / OpenCV 4.14.0 / NumPy 2.5.3で13テスト成功。
- 0〜9の全数字を6桁の全位置で照合。固定小数、先頭消灯、4種類の反射、透視、ぼけ、雑音、暗い表示を確認。
- 曖昧な点灯、途中・小数側の消灯、非赤色、全消灯を拒否。無効後の同値復帰でも連続判定をやり直すことを確認。
- 動画からJSONL・CSVへの通し実行、保存先の上書き拒否、解像度不一致、模擬カメラ切断時の停止と解放を確認。
- 別途、既定の合成動画168フレームを正解CSVと照合。正常132フレームの `raw_value` は全件一致、異常36フレームは全件無効。確定値110件、安定待ち22件、無効36件。
- 校正GUIで動画送り、静止、四隅・6桁枠の選択、JSON保存を操作確認。GUIで選んだ枠でも同じ168フレームの `raw_value` が全件正解と一致。表示比率と中止操作も確認。
- このPCで合成フレーム504枚の反射補正・透視補正・認識を測定し、中央値0.79ms、95パーセンタイル0.97ms/枚。撮影・動画復号・GUI・ログ保存を含まない参考値。

シミュレーターは認識側の定数を読み込まず、別途定義した多角形で描画しています。ただし、枠の位置を正確に知っている合成条件です。上の結果は実機の精度や撮影速度の保証ではありません。

## 実機で残る確認

- LEDのPWMや時分割点灯と露光が合わないと、一部のセグメントだけが欠けます。露光時間や撮影fpsを調整し、表示更新の途中を含む録画と目視値で照合してください。単純な複数フレームの画像合成は、値の切替中に架空の数字を作るため採用していません。
- 欠けた点灯が別の正しい数字になる場合（例：`8` の中央が欠けて `0`）、連続判定だけでは検知できません。先頭の点灯欠落と正規の先頭消灯も画像だけでは区別できません。
- ハーフミラーの二重像、強い映り込み、赤い外乱が桁枠に重なる条件、振動・ピント変化、実際の字体、カメラの遅延は未確認です。まず撮影・遮光・固定で改善し、既知値を使って確認してください。
- 固定fpsの動画を前提に時刻を算出します。可変fps動画の厳密な撮影時刻や、計器の真の更新周期を記録するものではありません。

## 参照

四隅による補正は[OpenCVの透視変換](https://docs.opencv.org/4.13.0/da/d6e/tutorial_py_geometric_transformations.html)、枠選択は[HighGUIのselectROI](https://docs.opencv.org/5.0/main_modules/highgui.html)、動画・カメラの入力は[VideoCapture](https://docs.opencv.org/doc/doxygen/html/d8/dfe/classcv_1_1VideoCapture.html)の公式仕様を参照しました。
