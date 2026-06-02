# プログラムフロー解説

Tektronix RSA `.r3f` ファイルを CSV / Parquet に変換する PyQt6 GUI アプリの動作フロー。

---

## 起動フロー

```
python main.py
    └─ main()                          [main.py:90]
         ├─ is_env_configured()        [config.py:19]  .env の存在と RSA_API_DLL の設定確認
         │    └─ (未設定なら) show_initial_setup_dialog()  [config.py:42]
         │         └─ PyQt6 ダイアログで DLL パスを入力 → create_env_from_user_input() → .env 生成
         └─ gui_main()                 [main.py:71]
              └─ run_gui()             [ui.py:330]
                   ├─ QApplication 作成
                   ├─ MainWindow()     [ui.py:115]  ウィンドウ構築
                   └─ app.exec()       イベントループ開始（ここで待機）
```

---

## GUI 上の操作ごとのフロー

### 1. ファイルを開く（Browse... ボタン）

```
_on_open_file()  [ui.py:206]
    └─ QFileDialog でファイル選択 → self._r3f_path に保存
```

---

### 2. メタデータ読み込み（Read ボタン）

```
_on_read_metadata()  [ui.py:220]
    └─ PlaybackRSA()              [rsa_api.py:52]  DLL 読み込み・プロトタイプ設定
         ├─ open_r3f_file()       [rsa_api.py:155]  PLAYBACK_OpenDiskFile() を呼び出し
         ├─ get_center_freq()     [rsa_api.py:215]  CONFIG_GetCenterFreq() → Hz 単位で返す
         ├─ get_sample_rate()     [rsa_api.py:223]  IQBLK_GetIQSampleRate() → Hz 単位で返す
         └─ close()               [rsa_api.py:208]  DEVICE_Stop() でセッション終了
```

DLL の関数は `ctypes.WinDLL` で読み込んだ `RSA_API.dll` を直接呼び出しています。

---

### 3. エクスポート（Export ボタン）

```
_on_export()  [ui.py:237]
    └─ ConvertWorker (QThread) 起動  [ui.py:43]
         └─ run()  [ui.py:61]  ← 別スレッドで実行
              ├─ convert_r3f_to_csv() または convert_r3f_to_parquet()  [converter.py:87/115]
              │    ├─ PlaybackRSA() → open_r3f_file() → get_sample_rate()
              │    ├─ set_record_length()   IQBLK_SetIQRecordLength()
              │    ├─ acquire_iq_data()     [rsa_api.py:246]
              │    │    ├─ IQBLK_AcquireIQData()         取得開始
              │    │    ├─ IQBLK_WaitForIQDataReady()    完了待機（最大5秒）
              │    │    └─ IQBLK_GetIQData()              interleaved float バッファ取得 → I/Q に分離
              │    ├─ iq_to_dataframe()   [converter.py:16]  I/Q → magnitude/phase 計算 → DataFrame
              │    └─ save_csv() / save_parquet()         ファイル保存
              └─ finished シグナル → _on_export_done()  プログレスバー 100% & ダイアログ表示
```

---

### 4. FFT / ウォーターフォール解析（Acquire IQ & Analyze ボタン）

```
_on_analyze()  [ui.py:264]
    └─ AnalysisWorker (QThread) 起動  [ui.py:81]
         └─ run()  [ui.py:90]  ← 別スレッドで実行
              ├─ PlaybackRSA() → open_r3f_file() → get_center_freq() → get_sample_rate()
              ├─ set_record_length() → acquire_iq_data()
              ├─ close()
              ├─ compute_fft()          [converter.py:56]
              │    └─ Blackman 窓 → FFT → fftshift → 20*log10 → dBFS
              └─ compute_spectrogram() [converter.py:71]
                   └─ scipy.signal.spectrogram → fftshift → 10*log10 → dB
              └─ finished シグナル → _on_analysis_done()  [ui.py:277]
                   └─ matplotlib で FFT スペクトルとウォーターフォールを描画 → canvas.draw()
```

---

## CLI モードのフロー

`--input` 引数を指定した場合は GUI を起動せず `cli_main()` を実行します。

```
python main.py --input samples/sample.r3f --format csv

main()
    └─ cli_main()                      [main.py:29]
         ├─ (--meta-only 時)
         │    └─ PlaybackRSA() → open_r3f_file() → get_center_freq() / get_sample_rate() → 表示して終了
         └─ (通常変換)
              ├─ convert_r3f_to_csv()  または  convert_r3f_to_parquet()
              └─ 進捗をコンソールのプログレスバー（#）で表示
```

---

## 全体の設計ポイント

| 観点 | 内容 |
|------|------|
| **DLL アクセス** | `ctypes.WinDLL` で `RSA_API.dll` を読み込み、関数ごとに `argtypes` / `restype` を定義してから呼び出す |
| **スレッド分離** | Export と Analysis は `QThread` サブクラス（Worker）で実行し、完了時に `pyqtSignal` で UI スレッドに通知する（GUI フリーズ防止） |
| **設定管理** | `dotenv` で `.env` から DLL パスを読み込み、未設定ならモーダルダイアログで初回設定を促す |
| **IQ → 物理量** | IQ サンプルはインターリーブ float（I₀,Q₀,I₁,Q₁,...）で来るので分離後、magnitude = \|I+jQ\|、phase = angle(I+jQ) を計算 |

---

## モジュール構成

| ファイル | 役割 |
|----------|------|
| [main.py](../main.py) | エントリーポイント。CLI / GUI の振り分けと `.env` チェック |
| [ui.py](../ui.py) | PyQt6 メインウィンドウ・Worker スレッド・matplotlib 描画 |
| [rsa_api.py](../rsa_api.py) | `RSA_API.dll` の ctypes ラッパー（PlaybackRSA クラス） |
| [converter.py](../converter.py) | IQ → DataFrame 変換・FFT・スペクトログラム・CSV/Parquet 保存 |
| [config.py](../config.py) | `.env` 読み書きと初期設定ダイアログ |
