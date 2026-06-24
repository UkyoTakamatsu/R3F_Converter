"""
DPX データを CSV / Parquet に変換するモジュール。

CSV 列: frequency_hz, time_s, amplitude_dbm

変換フロー:
  r3f → DPX_SetParameters → DPX_Configure → DEVICE_Run
      → DPX_GetFrameBuffer (スペクトラムトレース + スペクトログラム)
      → DEVICE_Stop
      → DPX_GetSogramHiResLine (高精度時系列ライン)
      → DataFrame → CSV / Parquet
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# 単位変換ユーティリティ
# ---------------------------------------------------------------------------

def watts_to_dbm(watts: np.ndarray) -> np.ndarray:
    """電力 [W] → [dBm] 変換。ゼロ/負値はクリップしてアンダーフローを防ぐ。"""
    return 10.0 * np.log10(np.clip(watts, 1e-20, None)) + 30.0


# ---------------------------------------------------------------------------
# DPX データから numpy 配列を生成
# ---------------------------------------------------------------------------

def dpx_spectrum_arrays(
    dpx_data: dict,
    center_freq: float,
) -> tuple[np.ndarray, np.ndarray]:
    """平均スペクトラムトレースから (freqs_hz, power_dbm) を返す。

    Args:
        dpx_data   : acquire_dpx_data() が返す辞書
        center_freq: 中心周波数 [Hz]
    Returns:
        freqs_hz  : 絶対 RF 周波数 配列 [Hz]
        power_dbm : 各ビンの電力 [dBm]
    """
    fspan = dpx_data["fspan"]
    n = dpx_data["trace_length"]
    freqs = np.linspace(center_freq - fspan / 2, center_freq + fspan / 2, n)
    watts = np.array(dpx_data["spectrum_watts"], dtype=np.float64)
    return freqs, watts_to_dbm(watts)


def dpx_sogram_arrays(
    dpx_data: dict,
    center_freq: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """スペクトログラムビットマップから (freqs_hz, times_s, power_matrix_dbm) を返す。

    power_matrix の shape は (n_freq, n_time)、時間は古い順（昇順）。
    ビットマップ精度は 0-254 スケール (≈ 0.47 dB/step で 120 dB レンジ時)。
    """
    fspan = dpx_data["fspan"]
    cf = center_freq
    sw = dpx_data["sogram_width"]
    sh = dpx_data["sogram_height"]
    valid = dpx_data["sogram_valid_lines"]
    y_top = dpx_data["y_top"]
    y_bottom = dpx_data["y_bottom"]

    if valid <= 0 or sw <= 0:
        freqs = np.linspace(cf - fspan / 2, cf + fspan / 2, dpx_data["trace_length"])
        return freqs, np.array([0.0]), np.full((len(freqs), 1), y_bottom)

    freqs = np.linspace(cf - fspan / 2, cf + fspan / 2, sw)

    # bitmap: shape (sh, sw), 最新行が先頭
    bitmap = np.array(dpx_data["sogram_bitmap"], dtype=np.float64).reshape(sh, sw)
    power = y_bottom + (bitmap / 254.0) * (y_top - y_bottom)

    # 有効ライン分を取り出して時系列順（古い順）に並べ直す
    power_valid = power[:valid, :][::-1, :]          # (valid, sw), 古い順
    timestamps = np.array(dpx_data["sogram_timestamps"][:valid])[::-1]

    # 開始時刻を 0 に正規化
    if len(timestamps) > 0:
        timestamps = timestamps - timestamps[0]

    # pcolormesh 向けに (freq, time) へ転置
    return freqs, timestamps, power_valid.T


def dpx_hires_to_arrays(
    hires_lines: list[tuple[list[float], float]],
    center_freq: float,
    fspan: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """高分解能ラインから (freqs_hz, times_s, power_matrix_dbm) を返す。

    Args:
        hires_lines : get_dpx_hires_lines() の戻り値
        center_freq : 中心周波数 [Hz]
        fspan       : スパン [Hz]
    Returns:
        freqs    : 絶対 RF 周波数 配列 [Hz]
        times    : 各ラインのタイムスタンプ（開始 0、昇順）[s]
        power_2d : shape (n_freq, n_time) [dBm]
    """
    if not hires_lines:
        n = 1
        freqs = np.linspace(center_freq - fspan / 2, center_freq + fspan / 2, n)
        return freqs, np.array([0.0]), np.zeros((n, 1))

    n_freq = len(hires_lines[0][0])
    freqs = np.linspace(center_freq - fspan / 2, center_freq + fspan / 2, n_freq)
    times = np.array([ts for _, ts in hires_lines])
    if len(times) > 0:
        times = times - times[0]

    power_2d = np.array([pwr for pwr, _ in hires_lines], dtype=np.float64).T  # (freq, time)
    return freqs, times, power_2d


# ---------------------------------------------------------------------------
# DataFrame 生成
# ---------------------------------------------------------------------------

def dpx_to_dataframe(
    dpx_data: dict,
    center_freq: float,
    hires_lines: list[tuple[list[float], float]] | None = None,
) -> pd.DataFrame:
    """DPX データから (frequency_hz, timestamp, amplitude_dbm) の DataFrame を生成。

    timestamp は DPX API が返す生の値（正規化なし）。
    一つの timestamp に周波数ビン数分の行が対応する。
    hires_lines が利用可能なら高精度ラインを優先、なければビットマップで代替。
    """
    fspan = dpx_data["fspan"]
    cf = center_freq

    if hires_lines and len(hires_lines) > 0:
        n_freq = len(hires_lines[0][0])
        freqs = np.linspace(cf - fspan / 2, cf + fspan / 2, n_freq)

        # 各 hi-res ライン：1 つの timestamp × n_freq 行
        freq_col = np.tile(freqs, len(hires_lines))
        ts_col   = np.repeat([ts for _, ts in hires_lines], n_freq)
        amp_col  = np.array([amp for pwr, _ in hires_lines for amp in pwr], dtype=np.float64)

        return pd.DataFrame({
            "frequency_hz":  freq_col,
            "timestamp":     ts_col,
            "amplitude_dbm": amp_col,
        })

    else:
        # hi-res ラインなし: 空データフレームを返す
        n = dpx_data.get("trace_length", 1)
        y_bottom = dpx_data.get("y_bottom", -120.0)
        freqs = np.linspace(cf - fspan / 2, cf + fspan / 2, n)
        return pd.DataFrame({
            "frequency_hz":  freqs,
            "timestamp":     np.zeros(n),
            "amplitude_dbm": np.full(n, y_bottom),
        })


def dpx_freq_max_dataframe(
    hires_lines: list[tuple[list[float], float]],
    center_freq: float,
    fspan: float,
) -> pd.DataFrame:
    """各周波数ビンの全時間にわたる最大電力の表を生成。

    列: frequency_hz, max_amplitude_dbm
    """
    if not hires_lines:
        return pd.DataFrame({"frequency_hz": [], "max_amplitude_dbm": []})

    n_freq = len(hires_lines[0][0])
    freqs = np.linspace(center_freq - fspan / 2, center_freq + fspan / 2, n_freq)
    power = np.array([pwr for pwr, _ in hires_lines], dtype=np.float64)  # (n_time, n_freq)
    max_dbm = np.max(power, axis=0)
    return pd.DataFrame({
        "frequency_hz":      freqs,
        "max_amplitude_dbm": max_dbm,
    })


def dpx_time_max_dataframe(
    hires_lines: list[tuple[list[float], float]],
) -> pd.DataFrame:
    """各時間ライン（タイムスタンプ）の全周波数にわたる最大電力の表を生成。

    列: timestamp, max_amplitude_dbm

    timestamp は DPX API が返す生の値（正規化なし、Unix エポック秒）。
    """
    if not hires_lines:
        return pd.DataFrame({"timestamp": [], "max_amplitude_dbm": []})

    times = np.array([ts for _, ts in hires_lines], dtype=np.float64)
    power = np.array([pwr for pwr, _ in hires_lines], dtype=np.float64)  # (n_time, n_freq)
    max_dbm = np.max(power, axis=1)
    return pd.DataFrame({
        "timestamp":         times,
        "max_amplitude_dbm": max_dbm,
    })


def save_csv(df: pd.DataFrame, out_path: str | Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False, float_format="%.6f")
    return out_path


def save_parquet(df: pd.DataFrame, out_path: str | Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    return out_path


# ---------------------------------------------------------------------------
# r3f → CSV / Parquet 変換 (DPX ベース)
# ---------------------------------------------------------------------------

# 出力内容の種類
CONTENT_RAW      = "raw"        # 生 DPX データ (frequency_hz, timestamp, amplitude_dbm)
CONTENT_FREQ_MAX = "freq_max"   # 各周波数ごとの最大値 (frequency_hz, max_amplitude_dbm)
CONTENT_TIME_MAX = "time_max"   # 各時間ごとの最大値   (timestamp, max_amplitude_dbm)

# 内容種別ごとのファイル名サフィックス
_CONTENT_SUFFIX = {
    CONTENT_RAW:      "_dpx",
    CONTENT_FREQ_MAX: "_freq_max",
    CONTENT_TIME_MAX: "_time_max",
}


def _build_dataframe(
    content: str,
    dpx_data: dict,
    cf: float,
    fspan: float,
    hires: list[tuple[list[float], float]],
) -> pd.DataFrame:
    """内容種別に応じた DataFrame を生成する。"""
    if content == CONTENT_FREQ_MAX:
        return dpx_freq_max_dataframe(hires, cf, fspan)
    if content == CONTENT_TIME_MAX:
        return dpx_time_max_dataframe(hires)
    # デフォルト: 生 DPX データ
    return dpx_to_dataframe(dpx_data, cf, hires_lines=hires if hires else None)


def convert_r3f(
    r3f_path: str,
    out_dir: str = "output",
    fmt: str = "csv",
    content: str = CONTENT_RAW,
    fspan: float | None = None,
    progress_cb: Callable[[int, int], None] | None = None,
) -> Path:
    """r3f ファイルを DPX 経由で CSV / Parquet に変換。

    Args:
        fmt     : "csv" | "parquet"
        content : CONTENT_RAW | CONTENT_FREQ_MAX | CONTENT_TIME_MAX
    """
    from rsa_api import PlaybackRSA

    fmt = (fmt or "csv").lower()
    rsa = PlaybackRSA()
    try:
        rsa.open_r3f_file(r3f_path)
        cf = rsa.get_center_freq()
        sr = rsa.get_sample_rate()

        if fspan is None:
            fspan = min(sr, 40e6)

        if progress_cb:
            progress_cb(0, 3)

        dpx_data = rsa.acquire_dpx_data(fspan)
        trace_len = dpx_data["trace_length"]

        if progress_cb:
            progress_cb(1, 3)

        hires = rsa.get_dpx_hires_lines(trace_len)

        if progress_cb:
            progress_cb(2, 3)

        df = _build_dataframe(content, dpx_data, cf, fspan, hires)

        stem = Path(r3f_path).stem
        suffix = _CONTENT_SUFFIX.get(content, "")
        ext = "parquet" if fmt == "parquet" else "csv"
        out_path = Path(out_dir) / f"{stem}{suffix}.{ext}"
        result = save_parquet(df, out_path) if fmt == "parquet" else save_csv(df, out_path)

        if progress_cb:
            progress_cb(3, 3)

        return result
    finally:
        rsa.close()


def convert_r3f_to_csv(
    r3f_path: str,
    out_dir: str = "output",
    fspan: float | None = None,
    progress_cb: Callable[[int, int], None] | None = None,
) -> Path:
    """r3f → CSV 変換（生 DPX データ）。後方互換用ラッパー。"""
    return convert_r3f(r3f_path, out_dir, "csv", CONTENT_RAW, fspan, progress_cb)


def convert_r3f_to_parquet(
    r3f_path: str,
    out_dir: str = "output",
    fspan: float | None = None,
    progress_cb: Callable[[int, int], None] | None = None,
) -> Path:
    """r3f → Parquet 変換（生 DPX データ）。後方互換用ラッパー。"""
    return convert_r3f(r3f_path, out_dir, "parquet", CONTENT_RAW, fspan, progress_cb)
