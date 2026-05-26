"""
RSA_API.dll の ctypes ラッパー。
実機がない場合は DLL_PATH = None のままにするとダミーモードで動作する。
"""

from __future__ import annotations

import ctypes
import os
from ctypes import c_bool, c_char_p, c_double, c_float, c_int, c_uint, POINTER
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
DLL_PATH = os.environ.get("RSA_API_DLL", "RSA_API.dll")

ReturnStatus = c_int

IQBLK_STATUS_INPUT_OVERRANGE = 0x01
IQBLK_STATUS_DISCONT         = 0x02


class RSAError(RuntimeError):
    pass


def _check(status: int, fn_name: str = "") -> None:
    if status != 0:
        raise RSAError(f"{fn_name} returned error code {status}")


class RSAAPI:
    """RSA_API.dll の薄いラッパー。DLL が見つからない場合はダミーモード。"""

    def __init__(self, dll_path: str = DLL_PATH) -> None:
        self._dummy = False
        try:
            self._lib = ctypes.WinDLL(dll_path)
            self._setup_prototypes()
        except (OSError, AttributeError):
            print(f"[WARN] {dll_path} が見つかりません。ダミーモードで起動します。")
            self._dummy = True

    # ------------------------------------------------------------------
    # プロトタイプ設定
    # ------------------------------------------------------------------

    def _setup_prototypes(self) -> None:
        lib = self._lib

        # PLAYBACK_OpenDiskFile
        lib.PLAYBACK_OpenDiskFile.restype  = ReturnStatus
        lib.PLAYBACK_OpenDiskFile.argtypes = [
            c_char_p,   # fileName
            c_double,   # startPercentage
            c_double,   # stopPercentage
            c_double,   # skipTimeBetweenFullAcquisitions
            c_bool,     # loopAtEndOfFile
            c_bool,     # emulateRealTime
        ]

        # DEVICE_Run / DEVICE_Stop
        lib.DEVICE_Run.restype  = ReturnStatus
        lib.DEVICE_Run.argtypes = []
        lib.DEVICE_Stop.restype  = ReturnStatus
        lib.DEVICE_Stop.argtypes = []

        # CONFIG_GetCenterFreq
        lib.CONFIG_GetCenterFreq.restype  = ReturnStatus
        lib.CONFIG_GetCenterFreq.argtypes = [POINTER(c_double)]

        # IQBLK_GetIQSampleRate
        lib.IQBLK_GetIQSampleRate.restype  = ReturnStatus
        lib.IQBLK_GetIQSampleRate.argtypes = [POINTER(c_double)]

        # IQBLK_SetIQBandwidth
        lib.IQBLK_SetIQBandwidth.restype  = ReturnStatus
        lib.IQBLK_SetIQBandwidth.argtypes = [c_double]

        # IQBLK_SetIQRecordLength
        lib.IQBLK_SetIQRecordLength.restype  = ReturnStatus
        lib.IQBLK_SetIQRecordLength.argtypes = [c_int]

        # IQBLK_GetIQRecordLength
        lib.IQBLK_GetIQRecordLength.restype  = ReturnStatus
        lib.IQBLK_GetIQRecordLength.argtypes = [POINTER(c_int)]

        # IQBLK_AcquireIQData
        lib.IQBLK_AcquireIQData.restype  = ReturnStatus
        lib.IQBLK_AcquireIQData.argtypes = []

        # IQBLK_WaitForIQDataReady
        lib.IQBLK_WaitForIQDataReady.restype  = ReturnStatus
        lib.IQBLK_WaitForIQDataReady.argtypes = [c_int, POINTER(c_bool)]

        # IQBLK_GetIQData
        lib.IQBLK_GetIQData.restype  = ReturnStatus
        lib.IQBLK_GetIQData.argtypes = [POINTER(c_float), POINTER(c_int), POINTER(c_uint)]

        # DEVICE_Disconnect
        lib.DEVICE_Disconnect.restype  = ReturnStatus
        lib.DEVICE_Disconnect.argtypes = []

    # ------------------------------------------------------------------
    # 公開 API
    # ------------------------------------------------------------------

    def open_disk_file(
        self,
        file_path: str,
        start_pct: float = 0.0,
        stop_pct: float = 100.0,
        skip_time: float = 0.0,
        loop: bool = False,
        emulate_realtime: bool = False,
    ) -> None:
        if self._dummy:
            print(f"[DUMMY] open_disk_file: {file_path}")
            return
        _check(
            self._lib.PLAYBACK_OpenDiskFile(
                file_path.encode(),
                c_double(start_pct),
                c_double(stop_pct),
                c_double(skip_time),
                c_bool(loop),
                c_bool(emulate_realtime),
            ),
            "PLAYBACK_OpenDiskFile",
        )

    def device_run(self) -> None:
        if self._dummy:
            print("[DUMMY] DEVICE_Run")
            return
        _check(self._lib.DEVICE_Run(), "DEVICE_Run")

    def device_stop(self) -> None:
        if self._dummy:
            return
        _check(self._lib.DEVICE_Stop(), "DEVICE_Stop")

    def get_center_freq(self) -> float:
        if self._dummy:
            return 1e9
        val = c_double(0.0)
        _check(self._lib.CONFIG_GetCenterFreq(ctypes.byref(val)), "CONFIG_GetCenterFreq")
        return val.value

    def get_sample_rate(self) -> float:
        if self._dummy:
            return 56e6
        val = c_double(0.0)
        _check(self._lib.IQBLK_GetIQSampleRate(ctypes.byref(val)), "IQBLK_GetIQSampleRate")
        return val.value

    def set_iq_bandwidth(self, bw: float) -> None:
        if self._dummy:
            return
        _check(self._lib.IQBLK_SetIQBandwidth(c_double(bw)), "IQBLK_SetIQBandwidth")

    def set_record_length(self, length: int) -> None:
        if self._dummy:
            return
        _check(self._lib.IQBLK_SetIQRecordLength(c_int(length)), "IQBLK_SetIQRecordLength")

    def get_record_length(self) -> int:
        if self._dummy:
            return 4096
        val = c_int(0)
        _check(self._lib.IQBLK_GetIQRecordLength(ctypes.byref(val)), "IQBLK_GetIQRecordLength")
        return val.value

    def acquire_iq_data(self, timeout_ms: int = 5000) -> tuple[list[float], list[float]]:
        """IQ データを取得して (I_list, Q_list) のタプルで返す。"""
        if self._dummy:
            import numpy as np
            n = 4096
            t = np.linspace(0, n / 56e6, n)
            noise = np.random.randn(n) * 0.01
            i_data = (np.cos(2 * np.pi * 1e6 * t) + noise).tolist()
            q_data = (np.sin(2 * np.pi * 1e6 * t) + noise).tolist()
            return i_data, q_data

        _check(self._lib.IQBLK_AcquireIQData(), "IQBLK_AcquireIQData")

        ready = c_bool(False)
        _check(
            self._lib.IQBLK_WaitForIQDataReady(c_int(timeout_ms), ctypes.byref(ready)),
            "IQBLK_WaitForIQDataReady",
        )
        if not ready.value:
            raise RSAError("IQ data not ready (timeout)")

        rec_len = self.get_record_length()
        buf = (c_float * (rec_len * 2))()
        actual = c_int(0)
        iq_info = c_uint(0)
        _check(
            self._lib.IQBLK_GetIQData(buf, ctypes.byref(actual), ctypes.byref(iq_info)),
            "IQBLK_GetIQData",
        )
        # int16 interleaved I0,Q0,I1,Q1,...
        n = actual.value
        i_data = [buf[k * 2]     for k in range(n)]
        q_data = [buf[k * 2 + 1] for k in range(n)]
        return i_data, q_data

    def disconnect(self) -> None:
        if self._dummy:
            return
        try:
            self._lib.DEVICE_Disconnect()
        except Exception:
            pass
