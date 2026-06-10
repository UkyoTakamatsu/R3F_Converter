# R3F Converter — 詳細仕様書

Tektronix RSA シリーズ `.r3f` ファイルを CSV / Parquet に変換する PyQt6 デスクトップアプリケーション。

---

## 目次

1. [概要](#1-概要)
2. [システム要件](#2-システム要件)
3. [モジュール構成](#3-モジュール構成)
4. [起動フロー](#4-起動フロー)
5. [モジュール別仕様](#5-モジュール別仕様)
   - 5.1 [main.py](#51-mainpy)
   - 5.2 [config.py](#52-configpy)
   - 5.3 [rsa_api.py](#53-rsa_apipy)
   - 5.4 [converter.py](#54-converterpy)
   - 5.5 [ui.py](#55-uipy)
6. [データフロー](#6-データフロー)
7. [出力データ仕様](#7-出力データ仕様)
8. [GUI 操作仕様](#8-gui-操作仕様)
9. [CLI 操作仕様](#9-cli-操作仕様)
10. [設定ファイル仕様](#10-設定ファイル仕様)
11. [エラーハンドリング](#11-エラーハンドリング)
12. [依存ライブラリ](#12-依存ライブラリ)

---

## 1. 概要

本アプリケーションは Tektronix RSA300/500/600 シリーズのスペクトラムアナライザが録画した `.r3f` ファイルを **Playback モード**（デバイス接続不要）で再生し、DPX（Digital Phosphor Spectrum）データを解析・エクスポートするツールである。

### 主な機能

| 機能 | 説明 |
|------|------|
| メタデータ表示 | 中心周波数・サンプルレートを読み取り表示する |
| DPX 解析・可視化 | スペクトラム（Spectrum）とウォーターフォール（Waterfall/Spectrogram）をグラフ表示する |
| CSV エクスポート | `frequency_hz, timestamp, amplitude_dbm` の 3 列 CSV を出力する |
| Parquet エクスポート | 同データを Apache Parquet 形式で出力する |
| CLI モード | `--input` 引数でバッチ変換を実行できる |

---

## 2. システム要件

| 項目 | 要件 |
|------|------|
| OS | Windows（`RSA_API.dll` が Windows 専用のため） |
| Python | 3.9 以上 |
| RSA SDK | Tektronix RSA API SDK（`RSA_API.dll` が必要） |
| アーキテクチャ | x64 |

### 必須 DLL

`RSA_API.dll` と同じディレクトリに以下が存在すると自動的に読み込まれる：

- `RSA300API.dll`
- `RSA500API.dll`
- `BaseDSPL.dll`
- `GPMeasDSP.dll`
- `SharedUtils.dll`

---

## 3. モジュール構成

```
R3F_Converter/
├── main.py        エントリーポイント（CLI / GUI 振り分け、.env チェック）
├── config.py      .env 読み書きと初期設定ダイアログ
├── rsa_api.py     RSA_API.dll の ctypes ラッパー（PlaybackRSA クラス）
├── converter.py   DPX データ → DataFrame → CSV / Parquet 変換
├── ui.py          PyQt6 メインウィンドウ・Worker スレッド・matplotlib 描画
├── .env           RSA_API_DLL パス（ユーザー作成）
├── .env.example   .env のテンプレート
├── requirements.txt
└── docs/
    ├── specification.md   本仕様書
    └── program_flow.md    フロー解説
```

### モジュール依存関係

```
main.py
  ├── config.py
  ├── ui.py
  │     ├── rsa_api.py
  │     └── converter.py
  │           └── rsa_api.py
  └── rsa_api.py (CLI モード直接使用)
      └── converter.py
```

---

## 4. 起動フロー

### 4.1 GUI モード（デフォルト）

```
python main.py
    └─ main()                             [main.py:93]
         ├─ argparse で引数解析
         ├─ args.input が None の場合 → GUI モード
         ├─ is_env_configured()           [config.py:19]
         │    └─ .env が存在し RSA_API_DLL が設定済みか確認
         │    └─ 未設定なら show_initial_setup_dialog()  [config.py:42]
         │         └─ PyQt6 ダイアログで DLL パスを入力
         │              └─ create_env_from_user_input()  [config.py:28]
         │                   └─ .env ファイルを生成
         └─ gui_main()                    [main.py:75]
              └─ run_gui()                [ui.py:362]
                   ├─ QApplication 作成（または既存のものを使用）
                   ├─ MainWindow() 作成   [ui.py:128]
                   ├─ win.show()
                   └─ app.exec()          イベントループ（以降は GUI 操作待ち）
```

### 4.2 CLI モード

```
python main.py --input <path> [--format csv|parquet] [--meta-only]
    └─ main()
         └─ cli_main()                   [main.py:31]
              ├─ (--meta-only 時)
              │    └─ PlaybackRSA() → open_r3f_file() → get_center_freq() / get_sample_rate() → 表示して終了
              └─ (通常変換)
                   ├─ format が "parquet" → convert_r3f_to_parquet()
                   └─ format が "csv"     → convert_r3f_to_csv()
                        └─ 進捗をコンソールに # バーで表示
```

---

## 5. モジュール別仕様

### 5.1 `main.py`

エントリーポイント。引数解析、モード振り分け、.env 確認を行う。

#### 関数一覧

| 関数 | 説明 |
|------|------|
| `main() -> int` | メイン処理。CLI / GUI の振り分けと .env チェックを行う |
| `cli_main(args) -> int` | CLI モード処理。変換またはメタデータ表示を実行する |
| `gui_main() -> int` | GUI モード処理。`run_gui()` を呼び出す |
| `build_parser() -> ArgumentParser` | argparse パーサーを構築して返す |

#### コマンドライン引数

| 引数 | 短縮形 | デフォルト | 説明 |
|------|--------|-----------|------|
| `--input` | `-i` | なし | `.r3f` ファイルパス（省略時は GUI 起動） |
| `--output` | `-o` | `output` | 出力ディレクトリ |
| `--format` | `-f` | `csv` | 出力形式（`csv` または `parquet`） |
| `--meta-only` | `-m` | `False` | メタデータのみ表示して終了 |

---

### 5.2 `config.py`

`.env` ファイルの読み書きと初期設定 GUI ダイアログを提供する。

#### 定数

| 定数 | 値 | 説明 |
|------|----|------|
| `ENV_FILE` | `<project_dir>/.env` | 設定ファイルのパス |
| `ENV_EXAMPLE` | `<project_dir>/.env.example` | テンプレートのパス |

#### 関数一覧

| 関数 | 戻り値 | 説明 |
|------|--------|------|
| `is_env_configured() -> bool` | `bool` | `.env` が存在し `RSA_API_DLL` がデフォルト値以外に設定されているか確認する |
| `create_env_from_user_input(dll_path: str) -> bool` | `bool` | 指定されたパスで `.env` を生成する。成功時 `True` |
| `show_initial_setup_dialog() -> bool` | `bool` | PyQt6 ダイアログで DLL パス入力を促す。ユーザーが OK を押して `.env` 生成が成功した場合 `True` |

#### `.env` ファイル形式

```ini
# RSA_API.dll の絶対パスを指定してください
# 例: C:\Tektronix\RSA_API\lib\x64\RSA_API.dll
RSA_API_DLL="C:\path\to\RSA_API.dll"
```

---

### 5.3 `rsa_api.py`

`RSA_API.dll` の ctypes ラッパー。Playback モード専用。

#### 主要クラス・型

| クラス/型 | 説明 |
|-----------|------|
| `RSAError(RuntimeError)` | RSA API エラーの例外クラス |
| `PlaybackRSA` | RSA_API.dll の Playback モード専用ラッパークラス |
| `IQBLK_ACQINFO` | IQ データ取得情報の ctypes 構造体 |
| `DPX_FrameBuffer` | DPX フレームバッファの ctypes 構造体 |

#### `PlaybackRSA` クラス

**コンストラクタ**

```python
PlaybackRSA(dll_path: str = DLL_PATH)
```

`.env` の `RSA_API_DLL` から DLL パスを読み込み、`ctypes.WinDLL` で読み込む。デバイス固有 DLL（RSA300API.dll 等）も同ディレクトリから自動ロードする。

**公開メソッド一覧**

| メソッド | 使用 DLL 関数 | 説明 |
|----------|--------------|------|
| `open_r3f_file(file_path, ...)` | `PLAYBACK_OpenDiskFile` | r3f ファイルを開く |
| `close()` | `DEVICE_Stop` | セッションを閉じる |
| `get_center_freq() -> float` | `CONFIG_GetCenterFreq` | 中心周波数を取得する [Hz] |
| `get_reference_level() -> float` | `CONFIG_GetReferenceLevel` | 基準レベルを取得する [dBm]（失敗時は 0.0） |
| `get_sample_rate() -> float` | `IQBLK_GetIQSampleRate` | サンプルレートを取得する [Hz] |
| `set_record_length(length: int)` | `IQBLK_SetIQRecordLength` | 1 取得あたりのサンプル数を設定する |
| `get_record_length() -> int` | `IQBLK_GetIQRecordLength` | レコード長を取得する |
| `acquire_iq_data(timeout_ms) -> tuple[list, list]` | `IQBLK_AcquireIQData` / `IQBLK_GetIQData` | IQ データを取得して (I リスト, Q リスト) を返す |
| `acquire_dpx_data(fspan, ...) -> dict` | `DPX_SetParameters` / `DEVICE_Run` / `DPX_WaitForDataReady` | DPX を設定・実行してセッション情報辞書を返す |
| `get_dpx_hires_lines(trace_points) -> list` | `DPX_GetSogramHiResLine` | DPX 高分解能ラインを全取得する（時系列昇順） |
| `diagnose_r3f_file(file_path) -> dict` | （静的メソッド・DLL 不要） | r3f ファイルのバイナリ構造を診断する |

**`open_r3f_file` 詳細**

```python
def open_r3f_file(
    file_path: str,
    start_pct: float = 0.0,    # 再生開始位置 [%]
    stop_pct: float = 100.0,   # 再生終了位置 [%]
    skip_time: float = 0.0,    # スキップ時間 [s]
    loop: bool = False,        # ループ再生
    emulate_realtime: bool = False,  # リアルタイムエミュレート
) -> None
```

PLAYBACK_OpenDiskFile を呼び出し、失敗時は DLL エラーコードを日本語メッセージに変換して `RSAError` を送出する。

**`acquire_dpx_data` 戻り値辞書**

| キー | 型 | 説明 |
|-----|----|------|
| `trace_length` | `int` | トレースの周波数ビン数（デフォルト 801） |
| `fspan` | `float` | スパン [Hz] |
| `y_top` | `float` | 振幅上限 [dBm]（デフォルト 0.0） |
| `y_bottom` | `float` | 振幅下限 [dBm]（デフォルト -120.0） |

**`get_dpx_hires_lines` 戻り値**

```python
list[tuple[list[float], float]]
# [(power_dbm_list, timestamp_s), ...]  古い順（時系列昇順）
```

---

### 5.4 `converter.py`

DPX データを numpy 配列・DataFrame に変換し、CSV / Parquet に保存する。

#### 単位変換関数

| 関数 | 説明 |
|------|------|
| `watts_to_dbm(watts: ndarray) -> ndarray` | 電力 [W] → [dBm]。ゼロ/負値を 1e-20 にクリップしてアンダーフロー防止 |

#### データ変換関数

| 関数 | 説明 |
|------|------|
| `dpx_spectrum_arrays(dpx_data, center_freq) -> (freqs_hz, power_dbm)` | DPX 辞書のスペクトラムトレースから周波数配列と電力配列を生成する |
| `dpx_sogram_arrays(dpx_data, center_freq) -> (freqs_hz, times_s, power_matrix_dbm)` | DPX ビットマップから周波数・時間・電力の 3 次元データを生成する |
| `dpx_hires_to_arrays(hires_lines, center_freq, fspan) -> (freqs, times, power_2d)` | 高分解能ラインから (freq×time) の 2D 配列を生成する |
| `dpx_to_dataframe(dpx_data, center_freq, hires_lines) -> DataFrame` | DPX データから `(frequency_hz, timestamp, amplitude_dbm)` の DataFrame を生成する |

**`dpx_to_dataframe` の動作**

- `hires_lines` が存在する場合：hi-res ラインを優先使用。各タイムスタンプ × `n_freq` 行を展開する
- `hires_lines` が空の場合：`y_bottom` で埋めた空のフォールバック DataFrame を返す

#### ファイル保存関数

| 関数 | 説明 |
|------|------|
| `save_csv(df, out_path) -> Path` | DataFrame を CSV に保存する（`float_format="%.6f"`） |
| `save_parquet(df, out_path) -> Path` | DataFrame を Parquet に保存する |

#### 高水準変換関数

| 関数 | 説明 |
|------|------|
| `convert_r3f_to_csv(r3f_path, out_dir, fspan, progress_cb) -> Path` | r3f ファイルを DPX 経由で CSV に変換する |
| `convert_r3f_to_parquet(r3f_path, out_dir, fspan, progress_cb) -> Path` | r3f ファイルを DPX 経由で Parquet に変換する |

**変換フロー（`convert_r3f_to_csv` / `convert_r3f_to_parquet`）**

```
PlaybackRSA() → open_r3f_file()
    → get_center_freq() / get_sample_rate()
    → acquire_dpx_data(fspan)          ← DPX 設定・実行・停止
    → get_dpx_hires_lines(trace_len)   ← 高分解能タイムライン取得
    → dpx_to_dataframe()               ← DataFrame 生成
    → save_csv() / save_parquet()      ← ファイル保存
```

`fspan` は `min(sample_rate, 40 MHz)` で自動決定される（明示指定も可能）。

`progress_cb(done: int, total: int)` は変換の進捗を 0/3 → 1/3 → 2/3 → 3/3 のステップで呼び出す。

---

### 5.5 `ui.py`

PyQt6 を使ったメインウィンドウと、バックグラウンドワーカースレッドを提供する。

#### Worker クラス

**`ConvertWorker(QThread)`**

| 属性 | 説明 |
|------|------|
| シグナル `progress(int, int)` | `(done, total)` で進捗を通知する |
| シグナル `finished(str)` | 完了時に出力ファイルパスを通知する |
| シグナル `error(str)` | エラー時にメッセージを通知する |
| `run()` | `convert_r3f_to_csv()` または `convert_r3f_to_parquet()` を実行する |

**`AnalysisWorker(QThread)`**

| 属性 | 説明 |
|------|------|
| シグナル `finished(freqs, psd_dbm, sog_data, sample_rate, center_freq)` | 解析完了時に全データを通知する |
| シグナル `error(str)` | エラー時にメッセージを通知する |
| `run()` | DPX 取得・hi-res ライン解析を実行する |

`AnalysisWorker.run()` の処理：

```
PlaybackRSA() → open_r3f_file()
    → get_center_freq() / get_sample_rate()
    → fspan = min(sample_rate, 40 MHz)
    → acquire_dpx_data(fspan)
    → get_dpx_hires_lines(trace_len)
    → power_matrix = ndarray(n_time, n_freq)
    → psd_dbm = max(power_matrix, axis=0)   ← 各周波数ビンの最大値
    → sxx = power_matrix.T                  ← (n_freq, n_time) ウォーターフォール用
    → finished シグナルを emit
```

#### `MainWindow` クラス

4 つのセクションで構成される：

| セクション | コントロール | 説明 |
|-----------|------------|------|
| 1. Open R3F File | Browse ボタン、ファイルパスラベル | QFileDialog でファイルを選択する |
| 2. Metadata | Center Freq / Sample Rate ラベル、Read ボタン | 選択ファイルのメタデータを表示する |
| 3. Export Settings | Format コンボ (CSV/Parquet)、Output Dir ボタン、Export ボタン | 出力設定と変換実行 |
| 4. DPX Analysis | Acquire DPX & Analyze ボタン、matplotlib キャンバス | スペクトラムとウォーターフォールを表示する |

---

## 6. データフロー

### 6.1 エクスポートフロー（全体）

```
.r3f ファイル
    │
    ▼  PLAYBACK_OpenDiskFile()
RSA_API.dll (Playback モード)
    │
    ▼  DPX_SetParameters / DPX_SetSogramParameters
DPX 設定（fspan, RBW, 振幅レンジ）
    │
    ▼  DPX_Configure / DPX_SetEnable / DEVICE_Run
DPX 実行（Sogram + Spectrum を同時収集）
    │
    ▼  DPX_WaitForDataReady
データ準備完了待ち
    │
    ▼  DPX_FinishFrameBuffer / DEVICE_Stop
フレーム解放・停止
    │
    ▼  DPX_GetSogramHiResLineCountLatest / DPX_GetSogramHiResLine
Hi-Res ライン取得（各ライン: 801 周波数ビン × タイムスタンプ）
    │
    ▼  dpx_to_dataframe()
DataFrame (frequency_hz, timestamp, amplitude_dbm)
    │
    ▼  save_csv() / save_parquet()
output/<stem>.csv または output/<stem>.parquet
```

### 6.2 DPX パラメータ決定ロジック

| パラメータ | 決定方法 |
|-----------|---------|
| `fspan` | `min(sample_rate, 40 MHz)`（明示指定も可） |
| `rbw` | `DPX_GetRBWRange()` で取得した範囲内で `fspan / 200` を基準に決定 |
| `trace_length` | 801 ビン（固定） |
| `y_top` | 0.0 dBm（固定） |
| `y_bottom` | -120.0 dBm（固定） |
| `time_per_bitmap_line` | 0.1 s |
| `time_resolution` | 0.01 s（最小 1 ms） |

### 6.3 ウォーターフォール表示フロー

```
get_dpx_hires_lines() → list[(power_dbm_list, timestamp), ...]
    │
    ▼  ndarray(n_time, n_freq)
power_matrix (各行がタイムスタンプに対応する周波数スペクトラム)
    │
    ├─ max(axis=0) → psd_dbm (n_freq,)          ← スペクトラム表示用（各周波数の最大値）
    │
    └─ .T → sxx (n_freq, n_time)                ← ウォーターフォール用
         └─ pcolormesh(t * 1e3, f_mhz, sxx)    ← X: 時間 [ms]、Y: 周波数 [MHz]
```

---

## 7. 出力データ仕様

### 7.1 CSV 形式

| 列名 | 型 | 単位 | 説明 |
|------|----|------|------|
| `frequency_hz` | float64 | Hz | 絶対 RF 周波数 |
| `timestamp` | float64 | s | DPX API が返す生のタイムスタンプ（正規化なし） |
| `amplitude_dbm` | float64 | dBm | 受信電力 |

- フォーマット：UTF-8、ヘッダあり、カンマ区切り
- 精度：小数点以下 6 桁（`%.6f`）
- ファイル名：`<入力ファイルのステム>.csv`

### 7.2 Parquet 形式

CSV と同じ列構造。インデックスなし。`pyarrow` バックエンドを使用。

### 7.3 行数

```
行数 = n_hires_lines × trace_length
     = (取得した Hi-Res ラインの本数) × 801
```

Hi-Res ラインが 0 本の場合、`y_bottom` (-120 dBm) で埋めた 801 行のフォールバックデータが出力される。

---

## 8. GUI 操作仕様

### 8.1 ファイルを開く

1. `Browse...` ボタンをクリック → `QFileDialog` が開く
2. `.r3f` ファイルを選択 → パスが内部に保存され、ラベルに表示される

### 8.2 メタデータ読み込み

1. `Read` ボタンをクリック
2. `PlaybackRSA()` を構築し、DLL をロード
3. `open_r3f_file()` → `get_center_freq()` / `get_sample_rate()` → `close()`
4. 中心周波数 [MHz] とサンプルレート [MSps] を UI に表示

### 8.3 エクスポート

1. Format コンボで `CSV` または `Parquet` を選択
2. `Output Dir...` で出力先ディレクトリを変更（デフォルト: `output/`）
3. `Export` ボタンをクリック → `ConvertWorker` スレッドが起動
4. プログレスバーが 0 → 100% に更新される
5. 完了後、ダイアログで保存先ファイルパスを通知

### 8.4 DPX 解析

1. `Acquire DPX & Analyze` ボタンをクリック → `AnalysisWorker` スレッドが起動
2. DPX データ取得・Hi-Res ライン取得を実行
3. 完了後、matplotlib キャンバスに以下を描画：

| グラフ | X 軸 | Y 軸 | 内容 |
|--------|------|------|------|
| 左：DPX Spectrum | 周波数 [MHz] | 電力 [dBm] | 各周波数ビンの最大値（scipy でピーク上位 5 点をマーク） |
| 右：Waterfall | 時間 [ms] | 周波数 [MHz] | カラーマップ `inferno` による電力分布 |

---

## 9. CLI 操作仕様

### 9.1 基本変換

```bash
# CSV エクスポート（デフォルト）
python main.py --input samples/sample.r3f

# Parquet エクスポート
python main.py --input samples/sample.r3f --format parquet

# 出力先ディレクトリを指定
python main.py --input samples/sample.r3f --output /path/to/output
```

### 9.2 メタデータのみ表示

```bash
python main.py --input samples/sample.r3f --meta-only
```

出力例：
```
中心周波数  : 2400.000000 MHz
サンプルレート: 56.000000 MSps
```

### 9.3 進捗表示

```
[####################] 100%
保存完了: output/sample.csv
```

---

## 10. 設定ファイル仕様

### 10.1 `.env`

| 変数名 | 説明 | 例 |
|--------|------|-----|
| `RSA_API_DLL` | `RSA_API.dll` の絶対パス | `C:\Tektronix\RSA_API\lib\x64\RSA_API.dll` |

- `is_env_configured()` はこの値が存在し、かつデフォルト値 `RSA_API.dll` でない場合に `True` を返す
- `.env` が存在しない場合、GUI 起動時に初期設定ダイアログが表示される
- CLI モードでは `.env` チェックをスキップする（DLL 読み込み時に判明するため）

### 10.2 `.env.example`

```ini
RSA_API_DLL=RSA_API.dll
```

---

## 11. エラーハンドリング

### 11.1 DLL 読み込みエラー

```
RSAError: RSA_API.dll が読み込めません: <path>
```

`PlaybackRSA.__init__()` で `OSError` が発生した場合に送出される。GUI では `QMessageBox.critical` で表示する。

### 11.2 ファイルオープンエラー

`PLAYBACK_OpenDiskFile` のエラーコードを日本語メッセージに変換：

| エラーコード | メッセージ |
|-------------|-----------|
| 1206 | ファイルを開けません（存在確認・アクセス権・サイズ・形式を確認） |
| 1209 | ファイルフォーマットが正しくないか、破損しています |
| 1210 | ファイルが見つかりません |
| 1211 | ファイルへのアクセス権がありません |
| その他 | 不明なエラー（コード N） |

エラー時は `diagnose_r3f_file()` の診断情報も付加する。

### 11.3 DPX タイムアウトエラー

```
RSAError: DPX データが準備できませんでした (10000ms タイムアウト)
```

`DPX_WaitForDataReady` が指定時間内に完了しなかった場合。`DEVICE_Stop()` 後に送出する。

### 11.4 GUI での Worker エラー

`ConvertWorker` / `AnalysisWorker` はエラーキャッチ後に `error(str)` シグナルを emit し、UI スレッドで `QMessageBox.critical` を表示する。Worker スレッドのエラーが UI をクラッシュさせない設計。

### 11.5 Hi-Res ライン未取得

DPX 取得後に Hi-Res ラインが 0 本の場合：

- `converter.py`：`y_bottom` で埋めたフォールバック DataFrame を返す
- `ui.py`：`AnalysisWorker.run()` で `error` シグナルを emit して終了する

---

## 12. 依存ライブラリ

| ライブラリ | 用途 |
|-----------|------|
| `PyQt6` | GUI フレームワーク |
| `matplotlib` | グラフ描画（QtAgg バックエンド） |
| `numpy` | 配列演算・周波数軸生成 |
| `pandas` | DataFrame 生成・CSV / Parquet 保存 |
| `pyarrow` | Parquet シリアライズ（pandas のバックエンド） |
| `scipy` | ピーク検出（`scipy.signal.find_peaks`、失敗時は無視） |
| `python-dotenv` | `.env` ファイルの読み込み |
