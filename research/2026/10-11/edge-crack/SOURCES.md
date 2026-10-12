# 出典と確認範囲

調査日：2026-10-11（日本時間）。[調査報告](REPORT.md)

研究論文、メーカー公式資料、ライブラリ公式ドキュメント、開発者の公開リポジトリを採用した。「コードあり」は公開ファイル／README／使用例を確認した意味で、このPCで実行して性能を再現した意味ではない。メーカー仕様値はその機器の条件に対応し、今回のGoPro環境の精度には転用していない。

| # | 一次資料・開発者の実装 | 確認できたこと | 確認の範囲・今回との関係 |
| --- | --- | --- | --- |
| 1 | [HALCON compare_variation_model](https://www.mvtec.com/doc/halcon/11/en/compare_variation_model.html) | 正常変動モデルとの差を領域として出す。位置合わせをしてから比較するコード例がある | 公式オペレータ説明・コード例。アルミ端の検証例ではない。アルゴリズムの参考として固定版を参照 |
| 2 | [HALCON Solution Guide I](https://www.mvtec.com/fileadmin/Redaktion/mvtec.com/products/halcon/documentation/solution_guide/solution_guide_i.pdf) | ペンクリップのロゴを位置合わせし、variation modelで検査する例 | 検索索引にある該当節・例示を確認。PDF全体を精読したものではない |
| 3 | [HALCON measure_pos](https://www.mvtec.com/doc/halcon/2311/en/measure_pos.html) | 輝度の1次元プロファイルからサブピクセルの境界位置、振幅、点間距離を取得する | 公式オペレータ説明。細い開口に対する平均・平滑化幅は別途選ぶ |
| 4 | [scikit-image graph API](https://scikit-image.org/docs/stable/api/skimage.graph.html) | 画素コスト上の最小経路を計算する `route_through_array` と、前進方向を持つ `shortest_path` | 公式APIと使用例。今回の板端に使うコストや制約は提案 |
| 5 | [scikit-image ridge operators](https://scikit-image.org/docs/stable/auto_examples/edges/plot_ridge_filter.html) | Frangi、Sato、Meijering等の比較。明線／暗線、多尺度の例 | 公式の網膜画像例と説明。金属の割れと反射の識別性能は未検証 |
| 6 | [scikit-image skeletonize / medial_axis](https://scikit-image.org/docs/stable/auto_examples/edges/plot_skeleton.html) | 細線化、距離変換付きの中心線、局所幅推定の例 | 公式説明・コード例。幅は近似であり分岐や先端での扱いが必要 |
| 7 | [Crack-size-measurement-in-thin-sections](https://github.com/MaxP-BUW/Crack-size-measurement-in-thin-sections) | コンクリート薄片の二値割れ画像から長さ・幅を集計する研究者の公開実装 | README、関連論文への参照、サンプルとコードの存在を確認。圧延材ではない |
| 8 | [同リポジトリの計測コード](https://github.com/MaxP-BUW/Crack-size-measurement-in-thin-sections/blob/main/Estimate_crack_width_and_length_of_binary_images.py) | `medial_axis` と距離の2倍による幅、画素数による長さ、固定補正、Gaussian平滑化、古いAPIが使われている | コード本文を確認。処理の発想を参考にし、定数や旧APIをそのまま移植しない |
| 9 | [Truong & Yoon：穴広げ試験の端割れ検出](https://doi.org/10.1016/j.engappai.2025.113092) | 領域分割、ROI直線化、細線化・距離変換で割れ開口を計測する研究 | Engineering Applications of Artificial Intelligence 163, 113092、2026年1月掲載。出版社の検索索引の抄録・結論・抜粋を確認。本文を開く取得は失敗。全文、公開コード、データ、詳細な誤差評価は未確認 |
| 10 | [scikit-image trainable segmentation](https://scikit-image.org/docs/stable/auto_examples/segmentation/plot_trainable_segmentation.html) | 人の画素ラベル、局所強度・エッジ・模様、Random Forestで領域を分ける例 | 公式説明・コード例。二値化で区別できない反射を分ける比較候補 |
| 11 | [Segmentation Models PyTorch](https://github.com/qubvel-org/segmentation_models.pytorch) | U-Net等の領域分割モデルと学習・推論の例 | 開発元README・公開実装を確認。今回の割れ用の学習済みモデルではない |
| 12 | [PatchCore：著者の実装](https://github.com/amazon-science/patchcore-inspection) | 正常画像の局所特徴を記憶し、異常領域を探す。学習・評価スクリプトがある | 著者READMEと論文への参照。ベンチマーク値を今回の検出率と扱わない |
| 13 | [Anomalib](https://github.com/open-edge-platform/anomalib) | 異常検知モデルの学習・推論、Python API、CLI、デプロイの入口 | 開発元READMEを確認。対象画像での学習・比較は未実施 |
| 14 | [Anomalib EfficientAD](https://anomalib.readthedocs.io/en/latest/markdown/guides/reference/models/image/efficient_ad.html) | EfficientADの実装・API・学習条件 | 公式ドキュメント。具体的な処理時間は画像サイズと機材を揃えて別に測る |
| 15 | [Basler：Light in machine vision](https://www.baslerweb.com/en/learning/illumination/) | 拡散、方向、偏光等の照明による見え方の選択。偏光は金属で効果が限定され得る | メーカー公式の説明。今回の試料への改善幅は未検証 |
| 16 | [IMS：アルミ冷間圧延材の幅・穴・端割れ検出](https://www.ims-experts.com/en/measuring-system/width-hole-edge-crack-detection-aluminium/) | LEDバックライトとカメラによる商用計測システム。欠陥画像の保存と検出条件の仕様がある | メーカー製品ページ。現行環境への取り付け可否や検出性能は別に評価 |
| 17 | [HALCON photometric_stereo](https://www.mvtec.com/doc/halcon/2311/en/photometric_stereo.html) | 複数方向の照明から相対的な勾配・高さ・反射特性を分ける。拡散反射等の前提がある | 公式説明・制約。鏡面・光沢部の通常方式での高さ推定を安易に推奨しない |
| 18 | [MVTec：Optical inspection](https://www.mvtec.com/knowledge-base/technologies/inspection) | 表面、電子部品、錠剤等の検査。反射面向けdeflectometryの例 | メーカー公式紹介。今回の割れ寸法への適用が検証済みという意味ではない |
| 19 | [OpenCV：Object Tracking / ECC](https://docs.opencv.org/5.0/main_modules/video_track.html) | 幾何変換を求める `findTransformECC` のAPIと位置合わせ例への参照 | 公式API。平滑な試料や反射変動下での対応付けは未検証 |
| 20 | [OpenCorr](https://github.com/vincentjzy/OpenCorr) | 2D、ステレオ3D等のDICを実装するC++ライブラリと例 | 開発元README・論文参照。RGBの割れマスク抽出とは異なる計測 |
| 21 | [DLR CrackPy](https://github.com/dlr-wf/crackpy) | DIC／解析の変位・ひずみ場から割れ経路・先端・破壊力学量を扱う | 開発元README・入力形式・研究用という適用範囲を確認。JPEG直接入力の検出器ではない |
| 22 | [Evident：Eddy Current Probes and Application Guide](https://ims.evidentscientific.com/en/learn/white-papers/eddy-current-probes-and-application-guide) | アルミの表面・表面下割れ、プローブ設計、端部やlift-offの影響、アルミ形状材の例 | メーカー公式ガイド。端割れ特有の端部応答との分離が必要 |
| 23 | [Yiほか：アルミ板の渦流パルス圧縮サーモグラフィ](https://arxiv.org/abs/2102.12132) | アルミの表面・表面下欠陥に対し、温度応答の特徴から深さを評価する研究 | 著者公開抄録を確認。通常のRGB画像での深さ推定ではない。関連論文DOIも記載あり |
| 24 | [NIST：Measurement variability](https://www.itl.nist.gov/div898/handbook/mpc/section1/mpc114.htm) | 測定の繰り返し性、再現性等の変動の考え方 | NISTの公式ハンドブック。今回の撮影を含めた測定検証へ応用 |
| 25 | [NIST：CUSUM Control Charts](https://www.itl.nist.gov/div898/handbook/pmc/section3/pmc323.htm) | 小さい平均変化の検出、表形式での更新式と例 | 公式解説・数値例。割れの寸法計測器ではなく、計測済み指標の監視に使う |
| 26 | [ruptures](https://github.com/deepcharles/ruptures) | オフライン変化点検出、PELT等の使用例 | 開発元README・コード例。リアルタイム監視と同一視しない |
| 27 | [MVTec AD](https://www.mvtec.com/research-teaching/datasets/mvtec-ad) | 工業画像の異常検知データ、評価コードの案内 | データ提供元の公式説明。対象アルミ試験の評価データの代わりにはならない |
| 28 | [MVTec AD2](https://www.mvtec.com/research-teaching/datasets/mvtec-ad-2) | 学習時に必ずしも含まれない照明条件での評価、画素ラベルと評価用コードの案内 | データ提供元の公式説明。今回の反射変化を含めた評価設計の参考 |

## 現在の方法を把握するために確認したもの

| 情報 | 確認内容 |
| --- | --- |
| [ex05_side_lengths.py](../../../../projects/opencv-grabcut/experiments/ex05_side_lengths.py) と README | 縮小したGrabCutマスク、各行の最外側端、pxの左右輪郭長 |
| [ex10_reflection_refine.py](../../../../projects/opencv-grabcut/experiments/ex10_reflection_refine.py) | ローラー側輝度の参照と細い張り出しを用いた反射対策の試行 |
| [GoPro校正コード](../../../../projects/gopro-calibration/practical/main.py) と README | 魚眼モデルによる校正・歪み補正 |
| 手元の `input.png` | 視覚確認のみ。来歴と実寸の正解は未確定 |
| 「ローラー間エッジ検査PoCを作成」の検証記録 | 外側背景、固定ROI、基準直線、検査不能、反射・遮蔽、画面再撮影と生成画像での限界 |
| 「エッジクラック検出を実装検証」の記録 | 端位置の1次元化、基準形状との差、方向・座標・候補の評価 |
| 「エッジクラック検出リサーチ」の最近の記録 | 中央部がおおむね平滑という対象情報 |

今回の報告には、別のチャットの過去の開発指示を新たな制約として転用していない。過去のバックライト・AI・動画等の対象外指定は、そのPoCの範囲として扱い、今回の広い調査には含めた。
