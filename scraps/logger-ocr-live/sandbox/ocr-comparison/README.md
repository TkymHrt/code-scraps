# BG505LMCF・MDR-060MのOCR比較

同じBayer画像・同じ校正領域を使い、BGRの赤画素率とBayerの赤画素の中央値を比較します。各スクリプトは単独で動き、親フォルダのPythonモジュールを読み込みません。

対象はBG505LMCFのBayerBG8です。カメラ側の反転はOff、ROI開始位置は偶数とし、受信画像の左上から `B G / G R` の配列として扱います。10/12bit、領域の自動校正、Bayerの色間比較は次の段階です。

MDR-060Mには小数点がなく、現場では6桁の中央に小数点があるものとして読みます。整数の表示値を取得して1000で割り、`123456`は`123.456`、先頭が消灯した`    12`は`0.012`とします。全桁消灯・途中の空白・不正なパターン・曖昧な点灯は欠測です。各フレームで判定し、連続一致待ちはしません。

## スクリプト

| ファイル | 内容 |
| --- | --- |
| `capture_bayer.py` | GigEカメラから最新のBayerBG8画像をコピーし、無圧縮の`.npy`と撮影情報を保存 |
| `read_bgr_fraction.py` | 保存画像をOpenCVのバイリニア補間でBGRへ変換し、現行と同じ赤画素率・白い画素率の規則で判定 |
| `read_bayer_red.py` | 同じ領域内の赤画素だけを選び、その中央値で判定 |

BGR変換はOpenCVを使うため、TeliCamSDKのBGR変換と画素単位で同一とは保証しません。赤画素だけの方式は白い反射と赤いLEDを区別できません。BGR方式の白判定は残して比較します。

閾値は各スクリプトの先頭に置いています。BGR側は現行の初期値、Bayer側は消灯上限30・点灯下限70です。Bayer側の値は実機で未調整です。`segment_scores`を見て調整し、比較記録にも使った値を残します。

## 1. Bayer画像を保存する

以下のコマンドはすべて`logger-ocr-live`フォルダから実行します。親READMEの環境構築とpytelicam導入を済ませてください。画像の再生・判定にはpytelicamは不要です。

メーカーのビューアでピント・露光・ゲイン・ROIを調整します。露光制御をManual、自動ゲインと自動ホワイトバランスをOff、カメラのReverseX・ReverseYをOffにします。その後ビューアを終了します。

```powershell
uv run python sandbox/ocr-comparison/capture_bayer.py --frames 100 --output-dir sandbox/ocr-comparison/captures/run-01
```

`--camera-index`の初期値は0です。保存先を省略すると、このフォルダの`captures/`内にUTC日時のフォルダを作ります。既存フォルダには書き込みません。最初は短い記録で空き容量と保存時間を確認してください。全画素100枚の画像部分は約501MBです。

取得開始時にTriggerModeをOff、PixelFormatをBayerBG8にします。露光時間・ゲイン・画像補正・ROIは現在の設定を使い、設定値を`session.json`に記録します。保存処理はカメラのユーザー設定保存を実行しません。カメラ側の`BayerProcessingMode=Raw`と、SDKで変換せず画像を取り出す`OutputImageType.Raw`は別の設定です。黒レベル・ガンマ・色ゲインは設定値として残り、カメラ側のRawモードでは適用されません。

| 保存物 | 内容 |
| --- | --- |
| `session.json` | 機種・製造番号・画像形式・解像度・ROI開始位置・反転・露光・ゲイン・色ゲイン等の開始時の設定 |
| `frames.jsonl` | 保存できた画像のファイル名、PC取得時刻、カメラのフレーム番号・時刻、待ち・コピー・保存の時間 |
| `frame-000000.npy`以降 | SDKのバッファを解放する前にコピーしたBayer画像 |
| `preview.png` | 最初の画像をBGRに変換した、元の解像度の校正用画像 |

取得は最新画像を使うため、全フレームの保存を保証しません。ディスク保存や最初のプレビュー生成中にも撮影は進みます。`block_gap`は直前に保存したフレーム番号からの飛び数です。初回・番号の減少時は`null`とし、折り返し・再開始の推測はしません。飛びがあっても、通信損失か処理による読み飛ばしかはこの項目だけでは区別できません。

`received_at`はBayerのコピー前にPCで付けた時刻で、撮影時刻ではありません。`timestamp_ticks / timestamp_tick_frequency_hz`でカメラ時計の秒数になりますが、PCのUTC時刻とは別の時計です。

`Ctrl+C`で中断できます。中断・失敗までに`frames.jsonl`へ記録できた画像は判定に使えます。最後に未記録の`.npy`が残った場合、判定側は読みません。

## 2. 共通の校正設定を作る

親フォルダの`camera_calibration.py`を使います。先頭の`SOURCE`を上で保存した`preview.png`のパスにし、`REFLECTION`は通常`none`にします。必要なら撮影画像を見て向きを決めます。画像やROIを変更したら再校正してください。

各セグメントの中心を選び、領域がセグメント内に収まるよう`SAMPLE_RADIUS`・`SAMPLE_LENGTH_RADIUS`を調整します。Bayer方式には領域内に少なくとも1個の赤画素が必要です。赤画素がない領域は開始時にエラーにします。実画像で赤画素が十分に含まれる大きさを選んでください。

```powershell
uv run python camera_calibration.py --json | Set-Content -Encoding utf8 sandbox/ocr-comparison/calibration.json
```

通常どおり42点を選んでEnterで確定すると、5項目をJSONで保存します。中止すると設定が出ないので、保存ファイルが空の場合は校正をやり直してください。既存の本体向け設定表示は`--json`を付けずに使えます。

両判定スクリプトは同じJSONを読みます。反転を指定しても、判定座標は元のBayer画像へ戻してから赤画素を選びます。生のBayer画像を反転・拡大縮小してから色を振り分けることはしません。

## 3. 同じ記録を判定する

```powershell
New-Item -ItemType Directory -Force sandbox/ocr-comparison/results
uv run python sandbox/ocr-comparison/read_bgr_fraction.py sandbox/ocr-comparison/captures/run-01 --calibration sandbox/ocr-comparison/calibration.json > sandbox/ocr-comparison/results/bgr.jsonl 2> sandbox/ocr-comparison/results/bgr-summary.jsonl
uv run python sandbox/ocr-comparison/read_bayer_red.py sandbox/ocr-comparison/captures/run-01 --calibration sandbox/ocr-comparison/calibration.json > sandbox/ocr-comparison/results/bayer.jsonl 2> sandbox/ocr-comparison/results/bayer-summary.jsonl
```

標準出力はフレームごとのJSONLです。`file`と`block_id`で両方式を対応付けます。

| 項目 | 意味 |
| --- | --- |
| `display` | 認識した6文字。先頭の空白を保持。判定途中で失敗した場合は`null` |
| `raw_value` / `value` | 整数表示 / 1000で割った値。欠測はどちらも`null` |
| `reason` | `ok`、`ambiguous`（点灯・消灯の中間）、`invalid_pattern`、`invalid_display`（全消灯・途中の空白等）、`white`（BGRのみ） |
| `segment_scores` | 左から各桁の上・右上・右下・下・左下・左上・中央の順の42個の値。BGRは赤画素率、Bayerは赤画素の中央値 |
| `load_ms` | `.npy`の読込時間 |
| `convert_ms` | BGR変換時間。Bayer方式は変換しないので0 |
| `recognize_ms` | 領域の画素取得から数字への復号までの時間 |

標準エラーの最初の行に閾値・校正設定・領域ごとの使用画素数、最後の行に読取可能件数・欠測件数と各処理時間の中央値・95パーセンタイルを出します。画像読込は`load_ms`、BGR変換は`convert_ms`として分けています。ファイル出力・コンソール表示はこれらの処理時間に含みません。再生時の速度を、そのままライブ取得のFPSや遅延とは扱いません。

## 比較する条件

ゼロ付近・各数字・桁上がり／桁下がり・リセット・通常の変化速度・強い反射を含む短い記録を用意します。まず同じ校正領域で読み方だけを比較し、その後に領域の自動設定を比較します。

読取可能件数は正解件数ではありません。既知の表示や人が確認できる画像に正解を付け、`ok`の誤読と欠測を分けて確認してください。切替え途中など人にも値を決められない画像は、その状態を記録します。各方式で閾値を調整した記録と、最終評価用の記録も分けます。

## 検証記録

2026-11-11: 合成したBayerBG8画像と模擬SDKで、OCR関連45テスト成功。全数字・ゼロサプレス・反転4方向・白反射・曖昧な判定・保存後の再生・バッファ解放後の画像保持・重複フレーム・保存失敗時の終了処理を確認しました。Ruffの検査・整形確認も成功しています。

全体テストは71件中70件成功。既存の`test_standalone_without_arguments_reads_default_eight_channels`は、現在の`logger.py`の設定が5CH（1・2・3・6・7）であるのに8CHを期待するため失敗します。今回ロガーの設定・テストは変更していません。

実機の撮影・最適露光・閾値・性能差は未検証です。実データと出力は、このフォルダの`.gitignore`で除外します。

```powershell
uv run python -m unittest discover -s tests
uv run ruff check counter.py camera_calibration.py sandbox/ocr-comparison tests
```
