# ロガーの電圧とOCR値のリアルタイム照合

同じWindows PCでNR-600の電圧とカメラの圧下表示を読みます。電圧をチャンネルごとに換算し、時刻の近いOCR値と一緒に表示します。板厚を求める前に、CHの割り当て・単位・符号・時刻差を照合するための試作です。

| スクリプト | 役割 |
| --- | --- |
| `collect_logger.py` | NR-600から指定CHの最新電圧を、共通のサンプル位置で読む |
| `read_meter.py` | 赤い6桁の7セグを読み、同じ値が続いたら確定する |
| `calculate_readings.py` | 上の2本を起動し、電圧の換算とOCR値との時刻照合を行う |

## 設定と実行

Python 3.10以降と製品版WAVE LOGGER PROを用意します。このフォルダを開き、3本とも同じPythonで実行します。

```powershell
python -m pip install pywin32 'opencv-python>=4.10,<6' 'numpy>=2,<3'
```

1. 連続収集用の `.ucf` を作り、WAVE LOGGER PROを終了します。`collect_logger.py` の `SETTINGS_FILE` にそのパスを、`DEVICE_ID` に本体IDを設定します。[NR-600の準備手順](../rolling-gauge-meter/README.md#準備)
2. OCRを校正し、得られた `FRAME_SIZE`、`REFLECTION`、`SEGMENT_BOXES` を新しい `read_meter.py` に貼り付け、`SOURCE` にカメラ番号を指定します。入力の確認には動画ファイルも使えます。初期の枠は既存の合成動画用です。対象は `0.000`〜`999.999` の赤い6桁7セグです。[OCRの校正手順](../seven-segment-ocr/README.md#実機を校正する)
3. `calculate_readings.py` の `CHANNELS` に必要な電圧CHと換算を設定します。計算側がここにあるCH名を取得側に渡します。`U1_CH1` はユニット1の電圧CH1です。以下の例は仮の校正値です。実際のCH・名称・単位・校正値に置き換えてから実行します。

```python
CHANNELS = {
    "U1_CH1": {
        "name": "OP_load",
        "unit": "kN",
        "low_point": (1.0, 0.0),
        "high_point": (5.0, 500.0),
        "valid_voltage": (1.0, 5.0),
    },
    "U1_CH2": {
        "name": "DR_load",
        "unit": "kN",
        "low_point": (0.0, 0.0),
        "high_point": (10.0, 500.0),
        "valid_voltage": (0.0, 10.0),
    },
}
```

`low_point` と `high_point` はそれぞれ `(電圧, 換算後の値)` です。電圧が低い点から順に並べます。`valid_voltage` は換算に使える電圧の下限・上限で、基準2点の内側に指定します。端点も含みます。ロガーの入力レンジは `.ucf` 側の設定です。

```powershell
python calculate_readings.py
```

`Ctrl+C` または片方の取得終了で両方の取得を停止します。終了後はWAVE LOGGER PROの画面で収集停止を確認してください。取得スクリプトを単体で動かす場合は `python collect_logger.py U1_CH1 U1_CH2` または `python read_meter.py` を実行すると、標準出力にJSONLが出ます。

## 出力と時刻の照合

- ロガーは `received_at` と、CH名ごとの `voltages` を出力します。ロガーの無効値は `null` です。
- OCRは `received_at` と `value` を出力します。未確定の `value` は `null` です。
- 照合結果は標準出力のCSVに出ます。ロガーの新しい行ごとに、生電圧、換算値、最新のOCR値、時刻差、`status` を表示します。範囲外の生電圧はCSVに残り、対応する換算欄は空欄になります。記録する場合は標準出力を新しいCSVファイルにリダイレクトします。

`status` は `ready`（照合可）、`waiting_ocr`（OCR待ち、または受信停止）、`ocr_unreadable`（OCR未確定）、`time_gap`（時刻差が上限を超過）、`invalid_voltage`（必要なCHが欠測または範囲外）のいずれかです。片側の受信が途切れたときは、`INPUT_TIMEOUT` 秒後にコンソールへ欠測を通知します。

時刻差は両方の `received_at` の絶対差です。これはPCでの受領時刻です。`MAX_TIME_GAP` の初期値は0.15秒で、実機で両方に現れる変化を見ながら調整します。動画の `received_at` は再生中にPCが読み込んだ時刻です。ロガー側は更新時点の最新サンプルを使うため、この出力は速報値の照合に使います。

## 検証

模擬COMと合成動画で3本を起動し、指定CHだけの取得、範囲外の生電圧の保持、保存切替をまたぐ行の破棄、片側の終了時や異常時の停止を確認しました。合成動画168フレームのOCR確定値は既存の読み取り処理と一致しました。照合処理には模擬データも渡し、`0.0` と `null` の扱い、150msと151msの境界、受信停止を確認しました。既存のロガーとOCRの自動テストは計45件が通りました。実機での取得、現場の換算値、許容時刻差は未確認です。
