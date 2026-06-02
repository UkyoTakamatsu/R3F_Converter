"""
IQ データを CSV / Parquet に変換するモジュール。

CSV 列: index, timestamp, I, Q, magnitude, phase
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd


def iq_to_dataframe(
    i_data: list[float],
    q_data: list[float],
    sample_rate: float,
) -> pd.DataFrame:
    n = len(i_data)
    timestamps = np.arange(n) / sample_rate

    i = np.array(i_data, dtype=np.float32)
    q = np.array(q_data, dtype=np.float32)
    complex_sig = i + 1j * q

    magnitude = np.abs(complex_sig).astype(np.float32)
    phase     = np.angle(complex_sig).astype(np.float32)

    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "I":         i,
            "Q":         q,
            "magnitude": magnitude,
            "phase":     phase,
        }
    )


def save_csv(df: pd.DataFrame, out_path: str | Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index_label="index", float_format="%.6f")
    return out_path


def save_parquet(df: pd.DataFrame, out_path: str | Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=True)
    return out_path


def compute_fft(
    i_data: list[float],
    q_data: list[float],
    sample_rate: float,
) -> tuple[np.ndarray, np.ndarray]:
    """周波数軸と電力スペクトル密度 (dBFS) を返す。"""
    complex_sig = np.array(i_data, dtype=np.float64) + 1j * np.array(q_data, dtype=np.float64)
    n = len(complex_sig)
    window = np.blackman(n)
    spec = np.fft.fftshift(np.fft.fft(complex_sig * window))
    freqs = np.fft.fftshift(np.fft.fftfreq(n, d=1.0 / sample_rate))
    power_db = 20 * np.log10(np.abs(spec) / n + 1e-12)
    return freqs, power_db


def compute_spectrogram(
    i_data: list[float],
    q_data: list[float],
    sample_rate: float,
    nperseg: int = 512,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """時間・周波数・電力の 3 配列を返す (spectrogram)。"""
    from scipy.signal import spectrogram as _spectrogram

    complex_sig = np.array(i_data, dtype=np.float64) + 1j * np.array(q_data, dtype=np.float64)
    f, t, sxx = _spectrogram(complex_sig, fs=sample_rate, nperseg=nperseg, return_onesided=False)
    f = np.fft.fftshift(f)
    sxx = np.fft.fftshift(sxx, axes=0)
    return f, t, 10 * np.log10(np.abs(sxx) + 1e-12)


def convert_r3f_to_csv(
    r3f_path: str,
    out_dir: str = "output",
    record_length: int = 65536,
    progress_cb: Callable[[int, int], None] | None = None,
) -> Path:
    """r3f ファイルを CSV に変換。"""
    from rsa_api import PlaybackRSA

    rsa = PlaybackRSA()
    rsa.open_r3f_file(r3f_path)

    sample_rate = rsa.get_sample_rate()
    rsa.set_record_length(record_length)

    # IQ データ取得
    i_data, q_data = rsa.acquire_iq_data()

    if progress_cb:
        progress_cb(1, 1)

    df = iq_to_dataframe(i_data, q_data, sample_rate)

    stem = Path(r3f_path).stem
    out_path = Path(out_dir) / f"{stem}.csv"
    return save_csv(df, out_path)


def convert_r3f_to_parquet(
    r3f_path: str,
    out_dir: str = "output",
    record_length: int = 65536,
    progress_cb: Callable[[int, int], None] | None = None,
) -> Path:
    """r3f ファイルを Parquet に変換。"""
    from rsa_api import PlaybackRSA

    rsa = PlaybackRSA()
    rsa.open_r3f_file(r3f_path)

    sample_rate = rsa.get_sample_rate()
    rsa.set_record_length(record_length)

    i_data, q_data = rsa.acquire_iq_data()

    if progress_cb:
        progress_cb(1, 1)

    df = iq_to_dataframe(i_data, q_data, sample_rate)

    stem = Path(r3f_path).stem
    out_path = Path(out_dir) / f"{stem}.parquet"
    return save_parquet(df, out_path)
