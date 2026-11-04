# NR-600からUSBで数値を読む

[read_logger.py](read_logger.py) はWAVE LOGGER PROで収集を開始し、USB接続したNR-600から指定したチャンネルの最新値を表示し続けます。

## 準備

1. NR-600をWindows PCにUSBで接続し、製品版WAVE LOGGER PROとPythonを用意します。
2. WAVE LOGGER PROを手動で開き、対象の入力と収集周期を設定します。ノーマルモードの「収集設定 → サンプリング」で「連続収集」を選び、リピートとExcel転送を使わない設定で `.ucf` に保存します（NR-600マニュアル 6-39～6-40）。
3. 収集を止めて必要な保存を済ませ、前回の試行で開いた画面も含めてWAVE LOGGER PROをすべて終了します。

このフォルダで `pywin32` をインストールします。

```powershell
python -m pip install -r requirements.txt
```

## 設定と実行

`read_logger.py`の先頭を現場に合わせて変更します。

| 設定 | 意味 |
|---|---|
| `SETTINGS_FILE` | 保存した `.ucf` のパス |
| `DEVICE_ID` | NR-600本体のIDスイッチの値（0～3） |
| `CHANNELS` | 表示する `(入力ユニット番号, APIのCH番号)` の一覧。ユニットは1始まり、CHは0始まり |
| `READ_INTERVAL` | Pythonの表示間隔（秒、初期値は1.0）。装置の収集周期はWAVE LOGGER PROで設定 |

初期設定はユニット1・2がともにNR-HA08と仮定し、各ユニットの電圧CH1～8（APIのCH番号0～7）を指定しています。型式や有効チャンネルが異なる場合は、WAVE LOGGER PROの設定とAutomationマニュアル p.8の対応表に合わせて `CHANNELS` を変更します。Automation APIは番号を指定して1チャンネルずつ読む方式なので、対象となるSingle型のチャンネルを表示順にすべて列挙します。

WAVE LOGGER PROを手動で開き直さずに実行します。

```powershell
python read_logger.py
```

`Ctrl+C` で収集を停止します。収集中にWAVE LOGGER PRO側で停止した場合も表示を終了します。読出しエラー時も停止を試みます。終了後はWAVE LOGGER PROの画面で停止を確認してから閉じます。

## 表示の見方

```text
index=2, raw[U1/CH0]=12.5, raw[U2/CH1]=13.5
```

- `index` はPCに届いた最新サンプルの位置です。現在の保存区間の先頭を0とするため、`index=2` は3点目です。1行の値はすべて同じ位置から読みます。
- `raw[U1/CH0]` はユニット1、APIのCH番号0の測定値です。WAVE LOGGER PROでのスケーリング・平滑化・物理量変換前の値を表示し、その位置の値が無効なら `NA` と表示します。

表示するのは読出し時点の最新値なので、表示間隔によって `index` が飛んだり、同じ番号が続いたりします。連続収集の保存切替で `index` が先頭に戻ることがあります。1行の読出し前後で分割保存番号が変わった場合は、その行を表示せず次の読出しに進みます。

## 機器IDのエラー

機器IDの設定で `261`（`0x0105`）が出た場合は、準備手順どおりWAVE LOGGER PROをすべて閉じて再実行します。通常起動の初期設定では、収集していなくてもID 0が割り当てられます（NR-600マニュアル 6-18、Automationマニュアル p.14）。

## 確認状況

現場でUSB接続の1チャンネル取得に成功しています。今回の複数チャンネルの連続表示は、模擬COMを使った自動テスト10件で確認しました。実機での連続表示は未確認です。

```powershell
python -m unittest discover -s tests -v
```

APIの根拠と板厚計算の検討は[分析文書](ANALYSIS.md)を参照してください。
