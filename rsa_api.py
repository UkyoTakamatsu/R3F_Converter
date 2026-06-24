"""
Tektronix RSA_API.dll の Playback モード専用ラッパー。

r3f ファイルから DPX / IQ データを再生・抽出するのみ。
デバイス接続は不要。

RSA デバイス固有の DLL（RSA300API.dll, RSA500API.dll など）も読み込み。
"""

from __future__ import annotations

import ctypes
import os
import struct
from ctypes import (
    c_bool, c_char_p, c_double, c_float, c_int, c_uint, c_uint64, c_wchar_p,
    POINTER,
    c_int16, c_int32, c_int64, c_uint8, c_uint32, c_longlong,
)
from pathlib import Path

import sys

from dotenv import load_dotenv

from config import app_dir

load_dotenv(app_dir() / ".env")


def _bundled_dll_dir() -> Path | None:
    """PyInstaller で同梱された RSA_API.dll のあるディレクトリ。

    frozen かつ RSA_API.dll が同梱されていれば、その場所を返す。
    それ以外（通常実行や DLL 非同梱ビルド）は None。
    """
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        if (base / "RSA_API.dll").exists():
            return base
    return None


_bundled = _bundled_dll_dir()
IS_BUNDLED = _bundled is not None

if _bundled is not None:
    # 同梱版: バンドル内の DLL を使用（.env 不要）
    DLL_PATH = str(_bundled / "RSA_API.dll")
    DLL_DIR  = str(_bundled)
else:
    # 外部 DLL 方式: .env の RSA_API_DLL を使用
    DLL_PATH = os.environ.get("RSA_API_DLL", "RSA_API.dll")
    DLL_DIR  = str(Path(DLL_PATH).parent) if Path(DLL_PATH).exists() else None

ReturnStatus = c_int


class IQBLK_ACQINFO(ctypes.Structure):
    _fields_ = [
        ("sample0Timestamp",   c_uint64),
        ("acqStartSample",     c_uint64),
        ("triggerSampleIndex", c_double),
        ("acqStatus",          c_uint),
    ]


class DPX_FrameBuffer(ctypes.Structure):
    """DPX フレームバッファ構造体（API Programmer Manual Table 1 準拠）。

    spectrumTraces は float** で trace 0 = 平均、1 = Max、2 = Min。
    各トレース要素の単位は Watts。
    sogramBitmap は 0-254 のスケール値（最新行が先頭）。
    """
    _fields_ = [
        ("fftPerFrame",                        c_int32),
        ("fftCount",                           c_int64),
        ("frameCount",                         c_int64),
        ("timestamp",                          c_double),
        ("acqDataStatus",                      c_uint32),
        ("minSigDuration",                     c_double),
        ("minSigDurOutOfRange",                c_bool),
        ("spectrumBitmapWidth",                c_int32),
        ("spectrumBitmapHeight",               c_int32),
        ("spectrumBitmapSize",                 c_int32),
        ("spectrumTraceLength",                c_int32),
        ("numSpectrumTraces",                  c_int32),
        ("spectrumEnabled",                    c_bool),
        ("spectrogramEnabled",                 c_bool),
        ("spectrumBitmap",                     POINTER(c_float)),
        ("spectrumTraces",                     POINTER(POINTER(c_float))),
        ("sogramBitmapWidth",                  c_int32),
        ("sogramBitmapHeight",                 c_int32),
        ("sogramBitmapSize",                   c_int32),
        ("sogramBitmapNumValidLines",          c_int32),
        ("sogramBitmap",                       POINTER(c_uint8)),
        ("sogramBitmapTimestampArray",         POINTER(c_double)),
        ("sogramBitmapContainTriggerArray",    POINTER(c_int16)),
    ]


class RSAError(RuntimeError):
    pass


class PlaybackRSA:
    """RSA_API.dll の Playback 専用ラッパー。

    r3f ファイルから DPX / IQ データを再生・抽出するためのシンプルなインターフェース。
    デバイス接続は不要。RSA デバイス固有の DLL も読み込み。
    """

    def __init__(self, dll_path: str = DLL_PATH) -> None:
        self._record_length: int = 0
        try:
            if DLL_DIR:
                self._load_device_dlls(DLL_DIR)

            self._lib = ctypes.WinDLL(dll_path)
            self._setup_prototypes()
            self._initialized = True
            print(f"[OK] RSA_API.dll が正常に読み込まれました: {dll_path}")
        except (OSError, AttributeError) as e:
            raise RSAError(
                f"RSA_API.dll が読み込めません: {dll_path}\n"
                f"詳細: {e}\n"
                f"Tektronix RSA_API SDK がインストールされているか確認してください。"
            )

    @staticmethod
    def _load_device_dlls(dll_dir: str) -> None:
        """デバイス固有の DLL を読み込む（RSA300API.dll, RSA500API.dll など）。"""
        device_dlls = [
            "RSA300API.dll",
            "RSA500API.dll",
            "BaseDSPL.dll",
            "GPMeasDSP.dll",
            "SharedUtils.dll",
        ]

        for dll_name in device_dlls:
            dll_path = Path(dll_dir) / dll_name
            if dll_path.exists():
                try:
                    ctypes.WinDLL(str(dll_path))
                    print(f"[OK] {dll_name} を読み込みました")
                except Exception as e:
                    print(f"[WARN] {dll_name} の読み込みに失敗: {e}")

    # ------------------------------------------------------------------
    # プロトタイプ設定
    # ------------------------------------------------------------------

    def _setup_prototypes(self) -> None:
        lib = self._lib

        # PLAYBACK_OpenDiskFile
        lib.PLAYBACK_OpenDiskFile.restype = ReturnStatus
        lib.PLAYBACK_OpenDiskFile.argtypes = [
            c_wchar_p, c_int, c_int, c_double, c_bool, c_bool,
        ]

        # PLAYBACK_GetReplayComplete
        lib.PLAYBACK_GetReplayComplete.restype = ReturnStatus
        lib.PLAYBACK_GetReplayComplete.argtypes = [POINTER(c_bool)]

        # CONFIG_GetCenterFreq
        lib.CONFIG_GetCenterFreq.restype = ReturnStatus
        lib.CONFIG_GetCenterFreq.argtypes = [POINTER(c_double)]

        # CONFIG_GetReferenceLevel
        lib.CONFIG_GetReferenceLevel.restype = ReturnStatus
        lib.CONFIG_GetReferenceLevel.argtypes = [POINTER(c_double)]

        # IQBLK_GetIQSampleRate
        lib.IQBLK_GetIQSampleRate.restype = ReturnStatus
        lib.IQBLK_GetIQSampleRate.argtypes = [POINTER(c_double)]

        # IQBLK_SetIQRecordLength
        lib.IQBLK_SetIQRecordLength.restype = ReturnStatus
        lib.IQBLK_SetIQRecordLength.argtypes = [c_int]

        # IQBLK_GetIQRecordLength
        lib.IQBLK_GetIQRecordLength.restype = ReturnStatus
        lib.IQBLK_GetIQRecordLength.argtypes = [POINTER(c_int)]

        # IQBLK_AcquireIQData
        lib.IQBLK_AcquireIQData.restype = ReturnStatus
        lib.IQBLK_AcquireIQData.argtypes = []

        # IQBLK_WaitForIQDataReady
        lib.IQBLK_WaitForIQDataReady.restype = ReturnStatus
        lib.IQBLK_WaitForIQDataReady.argtypes = [c_int, POINTER(c_bool)]

        # IQBLK_GetIQData
        lib.IQBLK_GetIQData.restype = ReturnStatus
        lib.IQBLK_GetIQData.argtypes = [POINTER(c_float), POINTER(c_int), POINTER(IQBLK_ACQINFO)]

        # DEVICE_Run
        lib.DEVICE_Run.restype = ReturnStatus
        lib.DEVICE_Run.argtypes = []

        # DEVICE_Stop
        lib.DEVICE_Stop.restype = ReturnStatus
        lib.DEVICE_Stop.argtypes = []

        # DEVICE_Disconnect
        if hasattr(lib, "DEVICE_Disconnect"):
            lib.DEVICE_Disconnect.restype = ReturnStatus
            lib.DEVICE_Disconnect.argtypes = []

        # SYSTEM_GetAPIVersion
        if hasattr(lib, "SYSTEM_GetAPIVersion"):
            lib.SYSTEM_GetAPIVersion.restype = ReturnStatus
            lib.SYSTEM_GetAPIVersion.argtypes = [POINTER(c_int), POINTER(c_int), POINTER(c_int)]

        # --- DPX 関数 ---

        # DPX_SetParameters
        lib.DPX_SetParameters.restype = ReturnStatus
        lib.DPX_SetParameters.argtypes = [
            c_double,   # fspan
            c_double,   # rbw
            c_int32,    # bitmapWidth
            c_int32,    # tracePtsPerPixel (1/3/5)
            c_int,      # yUnit (0=dBm, 1=Watt, ...)
            c_double,   # yTop
            c_double,   # yBottom
            c_bool,     # infinitePersistence
            c_double,   # persistenceTimeSec
            c_bool,     # showOnlyTrigFrame
        ]

        # DPX_SetSogramParameters
        lib.DPX_SetSogramParameters.restype = ReturnStatus
        lib.DPX_SetSogramParameters.argtypes = [
            c_double,   # timePerBitmapLine (s)
            c_double,   # timeResolution (s, >= 1 ms)
            c_double,   # maxPower (dBm)
            c_double,   # minPower (dBm)
        ]

        # DPX_Configure
        lib.DPX_Configure.restype = ReturnStatus
        lib.DPX_Configure.argtypes = [c_bool, c_bool]

        # DPX_SetEnable
        lib.DPX_SetEnable.restype = ReturnStatus
        lib.DPX_SetEnable.argtypes = [c_bool]

        # DPX_WaitForDataReady
        lib.DPX_WaitForDataReady.restype = ReturnStatus
        lib.DPX_WaitForDataReady.argtypes = [c_int, POINTER(c_bool)]

        # DPX_GetFrameBuffer
        lib.DPX_GetFrameBuffer.restype = ReturnStatus
        lib.DPX_GetFrameBuffer.argtypes = [POINTER(DPX_FrameBuffer)]

        # DPX_FinishFrameBuffer
        lib.DPX_FinishFrameBuffer.restype = ReturnStatus
        lib.DPX_FinishFrameBuffer.argtypes = []

        # DPX_Reset
        lib.DPX_Reset.restype = ReturnStatus
        lib.DPX_Reset.argtypes = []

        # DPX_GetRBWRange
        lib.DPX_GetRBWRange.restype = ReturnStatus
        lib.DPX_GetRBWRange.argtypes = [c_double, POINTER(c_double), POINTER(c_double)]

        # DPX_GetSogramHiResLineCountLatest
        lib.DPX_GetSogramHiResLineCountLatest.restype = ReturnStatus
        lib.DPX_GetSogramHiResLineCountLatest.argtypes = [POINTER(c_int32)]

        # DPX_GetSogramHiResLine
        lib.DPX_GetSogramHiResLine.restype = ReturnStatus
        lib.DPX_GetSogramHiResLine.argtypes = [
            POINTER(c_int16),   # vData
            POINTER(c_int32),   # vDataSize
            c_int32,            # lineIndex
            POINTER(c_double),  # dataSF
            c_int32,            # tracePoints
            c_int32,            # firstValidPoint
        ]

        # DPX_GetSogramHiResLineTimestamp
        lib.DPX_GetSogramHiResLineTimestamp.restype = ReturnStatus
        lib.DPX_GetSogramHiResLineTimestamp.argtypes = [POINTER(c_double), c_int32]

        # REFTIME_GetTimeFromTimestamp — タイムスタンプ(tick)を実時刻(整数秒)へ変換
        lib.REFTIME_GetTimeFromTimestamp.restype = ReturnStatus
        lib.REFTIME_GetTimeFromTimestamp.argtypes = [
            c_uint64,           # timestamp (tick)
            POINTER(c_longlong),  # o_timeSec (Unix 秒)
            POINTER(c_double),    # o_timeNsec (本 DLL では未充填)
        ]

        # REFTIME_GetTimestampRate — タイムスタンプの tick レート [tick/s]
        lib.REFTIME_GetTimestampRate.restype = ReturnStatus
        lib.REFTIME_GetTimestampRate.argtypes = [POINTER(c_uint64)]

    # ------------------------------------------------------------------
    # 公開 API (Playback 専用) — IQ
    # ------------------------------------------------------------------

    def open_r3f_file(
        self,
        file_path: str,
        start_pct: float = 0.0,
        stop_pct: float = 100.0,
        skip_time: float = 0.0,
        loop: bool = False,
        emulate_realtime: bool = False,
    ) -> None:
        """r3f ファイルを開く。"""
        abs_path = str(Path(file_path).resolve())

        if not Path(abs_path).exists():
            raise RSAError(f"ファイルが見つかりません: {abs_path}")

        print(f"[*] r3f ファイルを開いています: {abs_path}")

        status = self._lib.PLAYBACK_OpenDiskFile(
            abs_path,
            c_int(int(start_pct)),
            c_int(int(stop_pct)),
            c_double(skip_time),
            c_bool(loop),
            c_bool(emulate_realtime),
        )

        if status != 0:
            error_msgs = {
                1206: "ファイルを開けません。ファイルの存在確認、アクセス権、ファイルサイズ、またはファイル形式を確認してください。",
                1209: "ファイルフォーマットが正しくないか、破損しています。",
                1210: "ファイルが見つかりません。",
                1211: "ファイルへのアクセス権がありません。",
            }
            msg = error_msgs.get(status, f"不明なエラー (コード {status})")
            diag = self.diagnose_r3f_file(abs_path)
            diag_str = "\n".join(f"  {k}: {v}" for k, v in diag.items())
            raise RSAError(f"r3f ファイルを開けません: {msg}\n診断情報:\n{diag_str}")

        print(f"[OK] ファイルを開きました")

    def close(self) -> None:
        """DLL セッションを閉じて状態をリセットする。

        RSA_API.dll はプロセス内でグローバルに 1 つの再生セッションしか持たない。
        DEVICE_Stop() だけでは再生セッションが解放されず、次回 PLAYBACK_OpenDiskFile()
        を呼ぶと DLL 内部で不正アクセスが起きてプロセスごとクラッシュする。
        DEVICE_Disconnect() でセッションを完全に解放し、再オープン可能な状態に戻す。
        """
        try:
            self._lib.DEVICE_Stop()
        except Exception:
            pass
        if hasattr(self._lib, "DEVICE_Disconnect"):
            try:
                self._lib.DEVICE_Disconnect()
            except Exception:
                pass

    def get_center_freq(self) -> float:
        """中心周波数を取得 [Hz]。"""
        val = c_double(0.0)
        status = self._lib.CONFIG_GetCenterFreq(ctypes.byref(val))
        if status != 0:
            raise RSAError(f"中心周波数取得失敗 (コード {status})")
        return val.value

    def get_reference_level(self) -> float:
        """基準レベルを取得 [dBm]。失敗時は 0.0 を返す。"""
        val = c_double(0.0)
        status = self._lib.CONFIG_GetReferenceLevel(ctypes.byref(val))
        if status != 0:
            return 0.0
        return val.value

    def get_sample_rate(self) -> float:
        """サンプルレートを取得 [Hz]。"""
        val = c_double(0.0)
        status = self._lib.IQBLK_GetIQSampleRate(ctypes.byref(val))
        if status != 0:
            raise RSAError(f"サンプルレート取得失敗 (コード {status})")
        return val.value

    def set_record_length(self, length: int) -> None:
        """1 取得あたりのサンプル数を設定。"""
        status = self._lib.IQBLK_SetIQRecordLength(c_int(length))
        if status != 0:
            raise RSAError(f"レコード長設定失敗 (コード {status})")
        self._record_length = length

    def get_record_length(self) -> int:
        """レコード長を取得。"""
        val = c_int(0)
        status = self._lib.IQBLK_GetIQRecordLength(ctypes.byref(val))
        if status != 0:
            raise RSAError(f"レコード長取得失敗 (コード {status})")
        return val.value

    def acquire_iq_data(self, timeout_ms: int = 5000) -> tuple[list[float], list[float]]:
        """IQ データを取得する。"""
        if self._record_length == 0:
            raise RSAError("set_record_length() を先に呼んでください")
        rec_len = self._record_length

        status = self._lib.IQBLK_AcquireIQData()
        if status != 0:
            raise RSAError(f"IQ データ取得開始失敗 (コード {status})")

        ready = c_bool(False)
        status = self._lib.IQBLK_WaitForIQDataReady(c_int(timeout_ms), ctypes.byref(ready))
        if status != 0:
            raise RSAError(f"IQ データ準備待機失敗 (コード {status})")

        if not ready.value:
            raise RSAError(f"IQ データがタイムアウト後も準備完了しません ({timeout_ms}ms)")

        buf = (c_float * (rec_len * 2))()
        actual = c_int(0)
        acq_info = IQBLK_ACQINFO()

        status = self._lib.IQBLK_GetIQData(buf, ctypes.byref(actual), ctypes.byref(acq_info))
        if status != 0:
            raise RSAError(f"IQ データ取得失敗 (コード {status})")

        n = actual.value
        i_data = [buf[k * 2] for k in range(n)]
        q_data = [buf[k * 2 + 1] for k in range(n)]

        return i_data, q_data

    # ------------------------------------------------------------------
    # 公開 API (Playback 専用) — DPX
    # ------------------------------------------------------------------

    # 従来の測定方法に合わせた固定 RBW [Hz]。
    # DPX のレベルは RBW フィルタ内電力なので、RBW が違うと全データが
    # 一律にシフトする（従来法と 2-3 dB ずれる）。従来法と同じ 300 kHz に固定する。
    DEFAULT_RBW_HZ = 300e3

    def acquire_dpx_data(
        self,
        fspan: float,
        rbw: float | None = None,
        y_top: float = 0.0,
        y_bottom: float = -120.0,
        trace_length: int = 801,
        time_per_bitmap_line: float = 0.1,
        time_resolution: float = 0.01,
        timeout_ms: int = 10000,
    ) -> dict:
        """DPX を設定・実行してセッション情報を返す。

        マニュアル（API Programmer Manual, DPX_Configure の手順）に従い、
        再生がファイル終端に達するまで
        WaitForDataReady → GetFrameBuffer → FinishFrameBuffer を繰り返す。
        これにより r3f 全期間分の高分解能スペクトログラムラインが
        内部バッファに蓄積され、停止後に get_dpx_hires_lines() で全取得できる。
        （1 フレームのみ処理すると HiRes ラインが数本しか得られず途切れる。）

        Returns:
            dict with keys: trace_length, fspan, y_top, y_bottom, frame_count
        """
        # RBW 範囲を取得
        min_rbw = c_double(0.0)
        max_rbw = c_double(0.0)
        self._lib.DPX_GetRBWRange(c_double(fspan), ctypes.byref(min_rbw), ctypes.byref(max_rbw))

        if rbw is None:
            rbw = self.DEFAULT_RBW_HZ

        # 実機の許容範囲にクランプ（範囲が取得できた場合のみ）
        lo = min_rbw.value if min_rbw.value > 0 else None
        hi = max_rbw.value if max_rbw.value > 0 else None
        if lo is not None:
            rbw = max(rbw, lo)
        if hi is not None:
            rbw = min(rbw, hi)

        # DPX_SetParameters (VerticalUnit_dBm = 0)
        status = self._lib.DPX_SetParameters(
            c_double(fspan),
            c_double(rbw),
            c_int32(trace_length),
            c_int32(1),
            c_int(0),
            c_double(y_top),
            c_double(y_bottom),
            c_bool(False),
            c_double(1.0),
            c_bool(False),
        )
        if status != 0:
            raise RSAError(f"DPX_SetParameters 失敗 (コード {status})")

        # DPX_SetSogramParameters
        t_res = max(time_resolution, 0.001)
        status = self._lib.DPX_SetSogramParameters(
            c_double(time_per_bitmap_line),
            c_double(t_res),
            c_double(y_top),
            c_double(y_bottom),
        )
        if status != 0:
            raise RSAError(f"DPX_SetSogramParameters 失敗 (コード {status})")

        # DPX_Configure → DPX_SetEnable → DEVICE_Run
        status = self._lib.DPX_Configure(c_bool(True), c_bool(True))
        if status != 0:
            raise RSAError(f"DPX_Configure 失敗 (コード {status})")

        status = self._lib.DPX_SetEnable(c_bool(True))
        if status != 0:
            raise RSAError(f"DPX_SetEnable 失敗 (コード {status})")

        status = self._lib.DEVICE_Run()
        if status != 0:
            raise RSAError(f"DEVICE_Run 失敗 (コード {status})")

        # 再生終端までフレームを取得し続ける。
        # 1 フレームしか処理しないと HiRes ラインが数本しか溜まらず
        # 出力が途中で途切れるため、ここでファイル全体を消費する。
        fb = DPX_FrameBuffer()
        complete = c_bool(False)
        frame_count = 0
        empty_waits = 0
        max_empty_waits = 3  # 終端でもないのにフレームが来ない場合の安全弁

        while True:
            # 先に終端状態を確認（最後の長いタイムアウト待ちを避ける）
            self._lib.PLAYBACK_GetReplayComplete(ctypes.byref(complete))

            ready = c_bool(False)
            status = self._lib.DPX_WaitForDataReady(c_int(timeout_ms), ctypes.byref(ready))
            if status != 0:
                self._lib.DEVICE_Stop()
                raise RSAError(f"DPX_WaitForDataReady 失敗 (コード {status})")

            if ready.value:
                # GetFrameBuffer → FinishFrameBuffer でフレームを送り、
                # HiRes スペクトログラムバッファに 1 フレーム分を蓄積する。
                if self._lib.DPX_GetFrameBuffer(ctypes.byref(fb)) == 0:
                    frame_count += 1
                self._lib.DPX_FinishFrameBuffer()
                empty_waits = 0
            else:
                # フレームが来ない。終端に達していれば（残フレームも無いので）終了。
                if complete.value:
                    break
                empty_waits += 1
                if empty_waits >= max_empty_waits:
                    break

        if frame_count == 0:
            self._lib.DEVICE_Stop()
            raise RSAError(f"DPX データが準備できませんでした ({timeout_ms}ms タイムアウト)")

        self._lib.DEVICE_Stop()

        return {
            "trace_length": trace_length,
            "fspan":        fspan,
            "y_top":        y_top,
            "y_bottom":     y_bottom,
            "frame_count":  frame_count,
        }

    def get_dpx_hires_lines(
        self,
        trace_points: int,
    ) -> list[tuple[list[float], float]]:
        """DPX スペクトログラム高分解能ラインを全取得する。

        DEVICE_Stop() 後に呼ぶこと。
        Returns: [(power_dbm_list, timestamp), ...]  — 時系列順（古い順）
                 timestamp は Unix エポック秒（小数部含む）。
        """
        count_c = c_int32(0)
        status = self._lib.DPX_GetSogramHiResLineCountLatest(ctypes.byref(count_c))
        if status != 0:
            return []

        count = count_c.value
        if count == 0:
            return []

        # tick レート [tick/s] を取得（小数秒分解能の算出に使う）
        rate_c = c_uint64(0)
        rate = 0.0
        if self._lib.REFTIME_GetTimestampRate(ctypes.byref(rate_c)) == 0:
            rate = float(rate_c.value)

        # 各ラインの (電力配列, 生 tick) を収集
        raw = []
        for i in range(count):
            vdata = (c_int16 * trace_points)()
            vdata_size = c_int32(0)
            data_sf = c_double(0.0)

            status = self._lib.DPX_GetSogramHiResLine(
                vdata,
                ctypes.byref(vdata_size),
                c_int32(i),
                ctypes.byref(data_sf),
                c_int32(trace_points),
                c_int32(0),
            )
            if status != 0:
                continue

            ts = c_double(0.0)
            self._lib.DPX_GetSogramHiResLineTimestamp(ctypes.byref(ts), c_int32(i))

            n = vdata_size.value
            sf = data_sf.value
            power_dbm = [float(vdata[j]) * sf for j in range(n)]
            raw.append((power_dbm, float(ts.value)))

        if not raw:
            return []

        # tick を Unix エポック秒へ変換する。
        # REFTIME_GetTimeFromTimestamp は整数秒しか返さないため、基準となる 1 本の
        # 実時刻(整数秒)に対し tick レートで小数秒分解能を付与する:
        #   unix(tick) = base_sec + (tick - base_tick) / rate
        base_tick = raw[0][1]
        base_sec = base_tick
        t_sec = c_longlong(0)
        t_nsec = c_double(0.0)
        if self._lib.REFTIME_GetTimeFromTimestamp(
            c_uint64(int(base_tick)), ctypes.byref(t_sec), ctypes.byref(t_nsec)
        ) == 0:
            base_sec = float(t_sec.value)

        result = []
        for power_dbm, tick in raw:
            if rate > 0:
                unix_sec = base_sec + (tick - base_tick) / rate
            else:
                unix_sec = tick
            result.append((power_dbm, unix_sec))

        # タイムスタンプ昇順（古い順）に整列する
        result.sort(key=lambda x: x[1])
        return result

    # ------------------------------------------------------------------
    # 診断
    # ------------------------------------------------------------------

    @staticmethod
    def diagnose_r3f_file(file_path: str) -> dict:
        """r3f ファイルの構造を診断する（API 呼び出し前）。"""
        abs_path = Path(file_path).resolve()
        if not abs_path.exists():
            return {"error": f"ファイルが見つかりません: {abs_path}"}

        try:
            with open(abs_path, "rb") as f:
                header = f.read(512)
                if len(header) < 512:
                    return {"error": "ファイルサイズが小さすぎます"}
                magic = header[:4]
                is_text_like = all(32 <= b < 127 for b in header[:100] if b != 0)
                return {
                    "file_path":     str(abs_path),
                    "file_size":     abs_path.stat().st_size,
                    "magic_bytes":   magic.hex(),
                    "header_sample": header[:64].decode("latin1", errors="replace"),
                    "appears_binary": not is_text_like,
                }
        except Exception as e:
            return {"error": f"診断失敗: {e}"}
