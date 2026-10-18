# 任意の OBS ネイティブレンダラー

[한국어](README.ko.md) · [日本語](README.ja.md) · [English](README.md)

このフォルダーは実入力レンダラー、読み取り専用の入力転送と OBS アダプターを担当します。明示的に導入する任意機能で、通常の Windows アプリ配布には含めません。アプリ・ブラウザーのプレビュー・設定 UI・入力履歴はそのままで、Node、プラグイン、Live Core、リモコンなしでも単独動作します。

| パス | 役割 |
| --- | --- |
| `live_observer.py` | 既存ローカル状態/SSE の読み取り、再接続と自身の Node の管理 |
| `live_bridge.py`, `live-input.mjs` | 上限付き共有メモリ転送と既存入力・スクラッチエンジンの再利用 |
| `lift-native-pacing.c`, `live-protocol.h`, `pacing-geometry.h` | OBS フレーム時刻の描画、v2 検証と実入力の座標計算 |
| `obs-native-observer.lua` | 元の OBS プロセスの寿命に結び付けた任意の非表示起動 |
| `obs-native-layout.lua` | 明示的に固定したシーン・項目・ソース・チャンネルの位置追従 |
| `tests/` | 生成入力、転送・寿命検査と OBS モック検査 |

## 既存アプリへの接続

Python 3.10+、Node 22+ と別途ビルドしたプラグインが必要です。既存の Lift Trace を起動してから接続します。

```text
python native/obs/live_observer.py --node PATH_TO_NODE_EXE --channel lift-test --port 8765
```

OBS ネイティブソースに同じチャンネルを指定します。入力ポーラー、サーバー、設定 UI、録画制御を二重起動しません。古い入力は1秒以内に消去し、新しいエンジンで再接続します。設定は既存 UI が管理し、実入力の時刻は変更しません。映像スレッドの共有メモリ取得は待機しません。

二つの Lua は OBS と同時起動する機能と設定位置への追従を提供します。自動表示は既存 UI でネイティブ項目を選択します。配置のバインドボタンは変換を初期化するため、コード更新だけのために再バインドしないでください。導入時は既存ソース名・UUID・項目 ID・クロップ・表示・録画対象を保持します。Core は任意で、開始から最大240秒の保存と次の曲で未保存映像を破棄する規則を担当します。

## ビルド境界

OBS のバージョンに合う公式 SDK と C11 コンパイラーで `native/obs/CMakeLists.txt` をビルドします。このビルドは**空チャンネルでも試験ノーツを生成しません。**診断バーコードは明示的な選択で、既定ではオフです。保存済みシーンの互換性のため、モジュール名 `lift-native-pacing`、ソース ID `lift_trace_native_pacing`、プロトコル v2 と Lua 保存キーを保持します。

CMake はインストールを行わない参考経路です。ソース検査の成功だけで特定 SDK のビルドを検証済みとはみなしません。SDK・DLL・個人設定・録画は配布しません。

[フレーム比較実験](../../experiments/obs-native-pacing/README.ja.md)は合成入力のビルド、一時的な録画ツールと分析を担当します。実験ビルドは空チャンネルで元の120ms周期・40ms押下を生成します。配信用に導入しないでください。実入力描画を共有しソース ID も同じため、両ビルドを同時にロードしません。

## 既存パスと移行

旧実験フォルダーの `live_observer.py`、`live_bridge.py`、`live-input.mjs` と二つの Lua パスはこの実装へ転送します。導入時はリポジトリの相対構造を保ち、このフォルダーの実行ファイル、登録済み旧パスの互換ファイル、`web/client.js`、`web/engine.js`、`web/games/infinitas.js` を一緒にコピーします。旧パスを保持すればスクリプトの再登録や設定移行は不要です。OBS を終了してから実運用ビルドの DLL に置換します。

## 検証

```text
node --test native/obs/tests/live-input.test.mjs
python -m unittest discover -s native/obs/tests -p "test_*.py"
```

生成入力とモックの検査で、実機コントローラーやゲーム負荷での検証ではありません。任意検査には既存 LuaJIT の `LUA51_LIBRARY` と別途ビルドした実入力計算ライブラリの `LIFT_NATIVE_TEST_GEOMETRY_DLL` を指定します。展開したソースでも新旧両パスを検査します。

`tests/renderer-mode-test.c` は描画呼び出しをモック化します。通常ビルドと `LIFT_NATIVE_SYNTHETIC=1` ビルドを作り必要な検査コードのみをリンクし、`LIFT_NATIVE_TEST_RUNTIME_MODE_DLL` と `LIFT_NATIVE_TEST_BENCHMARK_MODE_DLL` を指定すると、両ビルドの空チャンネル・古い入力・実入力を検査します。

新規コードはリポジトリの MIT ライセンスに従います。OBS は別の GPL-2.0-or-later に従うため、リンクしたプラグインのビルド・配布時は各ライセンスを確認してください。
