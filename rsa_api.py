"""
Tektronix RSA_API.dll の Playback モード専用ラッパー。

r3f ファイルから IQ データを再生・抽出するのみ。
デバイス接続は不要。

RSA デバイス固有の DLL（RSA300API.dll, RSA500API.dll など）も読み込み。
"""

from __future__ import annotations

import ctypes
import os
import struct
from ctypes import c_bool, c_char_p, c_double, c_float, c_int, c_uint, c_uint64, c_wchar_p, POINTER
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
DLL_PATH = os.environ.get("RSA_API_DLL", "RSA_API.dll")

# DLL が存在するディレクトリを特定
if Path(DLL_PATH).exists():
    DLL_DIR = str(Path(DLL_PATH).parent)
else:
    DLL_DIR = None

ReturnStatus = c_int


class IQBLK_ACQINFO(ctypes.Structure):
    _fields_ = [
        ("sample0Timestamp",   c_uint64),
        ("acqStartSample",     c_uint64),
        ("triggerSampleIndex", c_double),
        ("acqStatus",          c_uint),
    ]


class RSAError(RuntimeError):
    pass


class PlaybackRSA:
    """RSA_API.dll の Playback 専用ラッパー。

    r3f ファイルから IQ データを再生・抽出するためのシンプルなインターフェース。
    デバイス接続は不要。RSA デバイス固有の DLL も読み込み。
    """

    def __init__(self, dll_path: str = DLL_PATH) -> None:
        try:
            # デバイス固有の DLL を先に読み込む
            # (RSA300API.dll, RSA500API.dll など)
            if DLL_DIR:
                self._load_device_dlls(DLL_DIR)

            # メイン API DLL を読み込む
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

        # PLAYBACK_OpenDiskFile - r3f ファイルを開く
        lib.PLAYBACK_OpenDiskFile.restype = ReturnStatus
        lib.PLAYBACK_OpenDiskFile.argtypes = [
            c_wchar_p,  # fileName (ワイド文字パス)
            c_int,      # startPercentage (int 型)
            c_int,      # stopPercentage (int 型)
            c_double,   # skipTimeBetweenFullAcquisitions
            c_bool,     # loopAtEndOfFile
            c_bool,     # emulateRealTime
        ]

        # CONFIG_GetCenterFreq - 中心周波数取得
        lib.CONFIG_GetCenterFreq.restype = ReturnStatus
        lib.CONFIG_GetCenterFreq.argtypes = [POINTER(c_double)]

        # IQBLK_GetIQSampleRate - サンプルレート取得
        lib.IQBLK_GetIQSampleRate.restype = ReturnStatus
        lib.IQBLK_GetIQSampleRate.argtypes = [POINTER(c_double)]

        # IQBLK_SetIQRecordLength - レコード長設定
        lib.IQBLK_SetIQRecordLength.restype = ReturnStatus
        lib.IQBLK_SetIQRecordLength.argtypes = [c_int]

        # IQBLK_GetIQRecordLength - レコード長取得
        lib.IQBLK_GetIQRecordLength.restype = ReturnStatus
        lib.IQBLK_GetIQRecordLength.argtypes = [POINTER(c_int)]

        # IQBLK_AcquireIQData - IQ データ取得開始
        lib.IQBLK_AcquireIQData.restype = ReturnStatus
        lib.IQBLK_AcquireIQData.argtypes = []

        # IQBLK_WaitForIQDataReady - IQ データ準備完了待機
        lib.IQBLK_WaitForIQDataReady.restype = ReturnStatus
        lib.IQBLK_WaitForIQDataReady.argtypes = [c_int, POINTER(c_bool)]

        # IQBLK_GetIQData - IQ データ取得
        lib.IQBLK_GetIQData.restype = ReturnStatus
        lib.IQBLK_GetIQData.argtypes = [POINTER(c_float), POINTER(c_int), POINTER(IQBLK_ACQINFO)]

        # DEVICE_Run - デバイス（プレイバック）を開始
        lib.DEVICE_Run.restype = ReturnStatus
        lib.DEVICE_Run.argtypes = []

        # DEVICE_Stop - デバイス（プレイバック）を停止
        lib.DEVICE_Stop.restype = ReturnStatus
        lib.DEVICE_Stop.argtypes = []

        # SYSTEM_GetAPIVersion - API バージョン取得（初期化確認用）
        if hasattr(lib, "SYSTEM_GetAPIVersion"):
            lib.SYSTEM_GetAPIVersion.restype = ReturnStatus
            lib.SYSTEM_GetAPIVersion.argtypes = [POINTER(c_int), POINTER(c_int), POINTER(c_int)]

    # ------------------------------------------------------------------
    # 公開 API (Playback 専用)
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
        """r3f ファイルを開く。

        Args:
            file_path: .r3f ファイルパス
            start_pct: 開始位置（%）
            stop_pct: 終了位置（%）
            skip_time: スキップ時間
            loop: ファイル終了時にループするか
            emulate_realtime: リアルタイム計測をエミュレートするか
        """
        # ファイルパスを絶対パスに変換
        abs_path = str(Path(file_path).resolve())

        if not Path(abs_path).exists():
            raise RSAError(f"ファイルが見つかりません: {abs_path}")

        # DLL は共有シングルトンのため前のセッション状態をリセット
        self._lib.DEVICE_Stop()

        print(f"[*] r3f ファイルを開いています: {abs_path}")

        status = self._lib.PLAYBACK_OpenDiskFile(
            abs_path,  # c_wchar_p は Python str を受け付ける
            c_int(int(start_pct)),
            c_int(int(stop_pct)),
            c_double(skip_time),
            c_bool(loop),
            c_bool(emulate_realtime),
        )

        if status != 0:
            error_msgs = {
                1206: "ファイルを開けません。ファイルの存在確認、アクセス権、ファイルサイズ、またはファイル形式を確認してください。PLAYBACK API が対応していないファイル形式の可能性があります。",
                1209: "ファイルフォーマットが正しくないか、破損しています。",
                1210: "ファイルが見つかりません。",
                1211: "ファイルへのアクセス権がありません。",
            }
            msg = error_msgs.get(status, f"不明なエラー (コード {status})")

            # 診断情報を追加
            diag = self.diagnose_r3f_file(abs_path)
            diag_str = "\n".join(f"  {k}: {v}" for k, v in diag.items())

            raise RSAError(f"r3f ファイルを開けません: {msg}\n診断情報:\n{diag_str}")

        print(f"[OK] ファイルを開きました")

    def close(self) -> None:
        """DLL セッションを閉じて状態をリセットする。
        メタデータのみ取得するケースで必ず呼ぶこと。
        呼ばずに次の IQBLK 操作を行うと IQBLK_GetIQData が 302 を返す。
        """
        self._lib.DEVICE_Stop()

    def get_center_freq(self) -> float:
        """中心周波数を取得 [Hz]。"""
        val = c_double(0.0)
        status = self._lib.CONFIG_GetCenterFreq(ctypes.byref(val))
        if status != 0:
            raise RSAError(f"中心周波数取得失敗 (コード {status})")
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

    def get_record_length(self) -> int:
        """レコード長を取得。"""
        val = c_int(0)
        status = self._lib.IQBLK_GetIQRecordLength(ctypes.byref(val))
        if status != 0:
            raise RSAError(f"レコード長取得失敗 (コード {status})")
        return val.value

    def acquire_iq_data(self, timeout_ms: int = 5000) -> tuple[list[float], list[float]]:
        """IQ データを取得する。

        Returns:
            (I_data, Q_data) のタプル
        """
        # バッファサイズを取得開始前に確定（WaitForReady 後に呼ぶと ready 状態が壊れる）
        rec_len = self.get_record_length()

        # IQ データ取得を開始
        status = self._lib.IQBLK_AcquireIQData()
        if status != 0:
            raise RSAError(f"IQ データ取得開始失敗 (コード {status})")

        # データ準備完了を待機
        ready = c_bool(False)
        status = self._lib.IQBLK_WaitForIQDataReady(c_int(timeout_ms), ctypes.byref(ready))
        if status != 0:
            raise RSAError(f"IQ データ準備待機失敗 (コード {status})")

        if not ready.value:
            raise RSAError(f"IQ データがタイムアウト後も準備完了しません ({timeout_ms}ms)")

        # データを取得
        buf = (c_float * (rec_len * 2))()
        actual = c_int(0)
        acq_info = IQBLK_ACQINFO()

        status = self._lib.IQBLK_GetIQData(buf, ctypes.byref(actual), ctypes.byref(acq_info))
        if status != 0:
            raise RSAError(f"IQ データ取得失敗 (コード {status})")

        # int16 interleaved (I0,Q0,I1,Q1,...) を分離
        n = actual.value
        i_data = [buf[k * 2] for k in range(n)]
        q_data = [buf[k * 2 + 1] for k in range(n)]

        return i_data, q_data

    @staticmethod
    def diagnose_r3f_file(file_path: str) -> dict:
        """r3f ファイルの構造を診断する（API 呼び出し前）。

        Returns:
            ファイルフォーマット情報の辞書
        """
        abs_path = Path(file_path).resolve()
        if not abs_path.exists():
            return {"error": f"ファイルが見つかりません: {abs_path}"}

        try:
            with open(abs_path, "rb") as f:
                # 最初の 512 バイトを読む
                header = f.read(512)

                if len(header) < 512:
                    return {"error": "ファイルサイズが小さすぎます"}

                # 一般的なマジックナンバーをチェック
                magic = header[:4]

                # R3F ファイルの場合、通常最初の数バイトには識別情報が含まれる
                # 実際の形式は複数存在するため、簡易的なチェックのみ実施
                is_text_like = all(32 <= b < 127 for b in header[:100] if b != 0)

                return {
                    "file_path": str(abs_path),
                    "file_size": abs_path.stat().st_size,
                    "magic_bytes": magic.hex(),
                    "header_sample": header[:64].decode("latin1", errors="replace"),
                    "appears_binary": not is_text_like,
                }
        except Exception as e:
            return {"error": f"診断失敗: {e}"}
