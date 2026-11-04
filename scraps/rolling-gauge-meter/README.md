# NR-600の電圧データ取得PoC

[collect_logger.py](collect_logger.py) はWAVE LOGGER PROでUSB収集を開始し、8チャンネルの生データをコンソールとグラフに表示します。

## 準備

1. NR-600をWindows PCにUSBで接続し、製品版WAVE LOGGER PROとTkinterを使えるPythonを用意します。
2. WAVE LOGGER PROで対象の入力と収集周期を設定します。ノーマルモードの「収集設定 → サンプリング」で「連続収集」を選び、リピートとExcel転送を使わない設定で `.ucf` に保存します（NR-600マニュアル 6-39～6-40）。
3. 収集を止めて必要な保存を済ませ、前回の試行で開いた画面も含めてWAVE LOGGER PROをすべて終了します。

このフォルダで依存パッケージをインストールします。

```powershell
python -m pip install -r requirements.txt
```

## 設定と実行

`collect_logger.py` の先頭で現場の設定を指定します。

| 設定 | 意味 |
|---|---|
| `SETTINGS_FILE` | 保存した `.ucf` の絶対パス |
| `DEVICE_ID` | NR-600本体のIDスイッチの値（0～3） |
| `CHANNELS` | `(入力ユニット番号, APIのCH番号)` の一覧。ユニットは1始まり、CHは0始まり |
| `READ_INTERVAL` | 波形の最新位置を確認する間隔（初期値は0.2秒） |
| `WINDOW_SECONDS` | グラフに残す時間幅（初期値は60秒） |

初期設定はユニット1・2の電圧CH1～4（APIのCH番号0～3）です。実行前に `.ucf` のパス、本体ID、有効チャンネルを確認し、更新間隔と時間幅には正の値を指定します。構成が異なる場合はWAVE LOGGER PROの設定とAutomationマニュアル p.8の対応表に合わせて `CHANNELS` を変更します。

WAVE LOGGER PROを手動で開き直さず、次を実行します。

```powershell
python collect_logger.py
```

## 取得と表示

PCに届いた波形の最新サンプル位置を8チャンネルでそろえ、`GetData()` で読みます。保存番号とサンプル位置の組が前回と異なるときに、生データ1行をコンソールに表示してグラフに追加します。読出し中に保存番号が変わった場合はその行を破棄します（Automationマニュアル p.41～44）。

コンソールの出力はCSV形式で、`elapsed_s`、`save_number`、`index`、`U1_CH1` から `U2_CH4` までの値を順に表示します。`elapsed_s` はPCで数えた経過秒です。`index` は保存区間の先頭を0とする位置で、保存切替で先頭に戻る場合があります。更新の間に複数のサンプルが増えた場合は、最新の点を表示します。値はWAVE LOGGER PROでのスケーリング・平滑化・物理量変換前の測定値です。

グラフは右端を現在として直近の時間幅を表示し、時間幅より古くなった点を除きます。縦方向の範囲は表示中の値に合わせて変わります。凡例の `U1_CH1` はユニット1の電圧CH1です。値を取得できない点はコンソールに `nan` と表示され、グラフでは線が途切れます。

## 終了とエラー時

グラフを閉じるか、実行したコンソールで `Ctrl+C` を押すと収集を停止します。WAVE LOGGER PRO側で収集が停止すると表示を終了します。読出しエラー時も停止を試みます。終了後はWAVE LOGGER PROの画面で停止を確認してから閉じます。

エラーが出た場合は、コンソールに表示された内容を確認し、原因を修正してから再実行します。機器IDの設定で `261`（`0x0105`）が出た場合は、WAVE LOGGER PROをすべて終了してから再実行します（NR-600マニュアル 6-18、Automationマニュアル p.14）。

## 旧版と検証

[コンソール版](archive/read_logger.py)、[波形のグラフ版](archive/plot_logger.py)、[現在値のグラフ版](archive/plot_logger_current.py)は `archive/` に保管しています。旧コンソール版の自動テストは次のコマンドで実行できます。

```powershell
python -m unittest discover -s archive/tests -v
```

旧版の自動テスト10件が通りました。取得PoCは模擬COMで8チャンネルの読出し、重複と保存切替をまたぐ行の除外、時間幅の更新、終了時とエラー時の停止を確認しました。現場では旧版によるUSB接続の1チャンネル取得に成功しています。取得PoCの実機動作は未確認です。APIの根拠と板厚計算の検討は [分析文書](ANALYSIS.md) を参照してください。
