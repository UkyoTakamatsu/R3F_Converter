"""
r3f ファイル フォーマット パーサー

PLAYBACK API が失敗した場合、直接ファイルを解析してメタデータとIQデータを抽出する。
r3f ファイルフォーマット:
  - 16KB (16384 bytes) 構成ブロック
  - 続く 16KB IQ データフレーム（複数）
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import NamedTuple


class R3FConfigBlock(NamedTuple):
    """r3f 設定ブロック構造"""
    center_freq: float
    sample_rate: float
    data_type: str
    version: str
    num_frames: int


class R3FParser:
    """r3f ファイルを直接解析するパーサー。"""

    CONFIG_BLOCK_SIZE = 16384
    DATA_FRAME_SIZE = 16384

    @staticmethod
    def read_config_block(file_path: str) -> dict | None:
        """設定ブロックを読む。

        Returns:
            設定情報の辞書、またはパースに失敗した場合は None
        """
        try:
            path = Path(file_path)
            if not path.exists():
                return None

            with open(path, "rb") as f:
                config_data = f.read(R3FParser.CONFIG_BLOCK_SIZE)

            if len(config_data) < 256:  # 最小サイズ
                return None

            result = {
                "file_path": str(path),
                "file_size": path.stat().st_size,
                "config_block_size": len(config_data),
            }

            # 簡易的なパターンマッチで情報抽出
            # (実際の形式は複数存在するため、ここでは基本的なチェックのみ)

            # テキスト部分から情報抽出を試みる
            text_part = config_data[:512].decode("utf-8", errors="ignore")
            result["config_text_sample"] = text_part[:200]

            # バイナリ解析（ヘッダの既知の位置から抽出）
            # 注：実際の位置はフォーマットバージョンに依存する
            try:
                # 一般的な位置からサンプルレートを抽出
                if len(config_data) >= 128:
                    # 浮動小数点数としてのサンプルレート候補
                    sr_candidates = []
                    for offset in [64, 80, 96, 112]:
                        try:
                            val = struct.unpack("<d", config_data[offset:offset + 8])[0]
                            if 1e6 < val < 1e9:  # 通常は 1MHz ~ 1GHz
                                sr_candidates.append((offset, val))
                        except:
                            pass
                    if sr_candidates:
                        result["sample_rate_candidates"] = sr_candidates

            except Exception:
                pass

            return result

        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def estimate_metadata(file_path: str) -> dict | None:
        """ファイルサイズからメタデータを推定。"""
        try:
            path = Path(file_path)
            if not path.exists():
                return None

            file_size = path.stat().st_size

            # 設定ブロック + データフレーム
            # 典型的: 1フレーム = 16KB = 8192 I/Q サンプル (各 16-bit float)
            data_size = file_size - R3FParser.CONFIG_BLOCK_SIZE
            if data_size <= 0:
                return {"error": "ファイルサイズが小さすぎます"}

            # フレーム数の推定
            estimated_frames = data_size // R3FParser.DATA_FRAME_SIZE
            estimated_samples = estimated_frames * 8192

            return {
                "file_size": file_size,
                "estimated_config_block": R3FParser.CONFIG_BLOCK_SIZE,
                "estimated_data_size": data_size,
                "estimated_frames": estimated_frames,
                "estimated_total_samples": estimated_samples,
            }

        except Exception as e:
            return {"error": str(e)}


def main() -> None:
    """診断スクリプト。"""
    import sys

    if len(sys.argv) < 2:
        print("使い方: python r3f_parser.py <r3f_file_path>")
        sys.exit(1)

    r3f_path = sys.argv[1]

    print(f"[*] r3f ファイルを解析中: {r3f_path}")
    print()

    # 設定ブロックを読む
    print("[*] 設定ブロック:")
    config = R3FParser.read_config_block(r3f_path)
    if config:
        for key, value in config.items():
            if isinstance(value, (list, tuple)):
                print(f"  {key}:")
                for item in value:
                    print(f"    {item}")
            else:
                print(f"  {key}: {value}")
    print()

    # メタデータを推定
    print("[*] メタデータ推定:")
    metadata = R3FParser.estimate_metadata(r3f_path)
    if metadata:
        for key, value in metadata.items():
            print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
