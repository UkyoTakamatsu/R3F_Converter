"""
r3f ファイル診断ツール

PLAYBACK_OpenDiskFile が失敗する原因を調査するためのスクリプト。
"""

from pathlib import Path
import sys

from rsa_api import PlaybackRSA


def main() -> None:
    if len(sys.argv) < 2:
        print("使い方: python diagnose.py <r3f_file_path>")
        print()
        print("例: python diagnose.py samples/sample.r3f")
        sys.exit(1)

    r3f_path = sys.argv[1]

    print(f"[*] r3f ファイルを診断中: {r3f_path}")
    print()

    # ファイル情報を表示
    p = Path(r3f_path)
    if not p.exists():
        print(f"[ERROR] ファイルが見つかりません: {r3f_path}")
        sys.exit(1)

    stat = p.stat()
    print(f"[INFO] ファイルサイズ: {stat.st_size} bytes")
    print()

    # PlaybackRSA で診断
    print("[*] PlaybackRSA 診断情報:")
    diag = PlaybackRSA.diagnose_r3f_file(r3f_path)
    for key, value in diag.items():
        print(f"  {key}: {value}")
    print()

    # API 呼び出しを試みる
    print("[*] PLAYBACK_OpenDiskFile を試みています...")
    try:
        rsa = PlaybackRSA()
        rsa.open_r3f_file(r3f_path)
        print("[OK] ファイルを開きました")

        # メタデータを取得
        try:
            cf = rsa.get_center_freq()
            sr = rsa.get_sample_rate()
            print(f"[OK] 中心周波数: {cf / 1e6:.3f} MHz")
            print(f"[OK] サンプルレート: {sr / 1e6:.3f} MSps")
        except Exception as e:
            print(f"[WARN] メタデータ取得失敗: {e}")

    except Exception as e:
        print(f"[ERROR] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
