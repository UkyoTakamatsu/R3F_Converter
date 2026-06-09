"""
R3F → CSV 変換アプリ  エントリーポイント

Playback モード専用（デバイス接続不要）。DPX を使用してスペクトラム・
スペクトログラムデータを取得し frequency_hz / time_s / amplitude_dbm の
3 列 CSV / Parquet に変換します。

使い方:
    # GUI モード (デフォルト)
    python main.py

    # CLI モード — CSV 出力
    python main.py --input samples/sample.r3f --format csv

    # CLI モード — Parquet 出力
    python main.py --input samples/sample.r3f --format parquet

    # メタデータだけ確認
    python main.py --input samples/sample.r3f --meta-only

DLL の場所を変えるには .env ファイルの RSA_API_DLL を編集してください。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def cli_main(args: argparse.Namespace) -> int:
    from rsa_api import PlaybackRSA
    from converter import (
        convert_r3f_to_csv,
        convert_r3f_to_parquet,
    )

    r3f_path = str(args.input)

    if args.meta_only:
        try:
            rsa = PlaybackRSA()
            rsa.open_r3f_file(r3f_path)
            cf = rsa.get_center_freq()
            sr = rsa.get_sample_rate()
            print(f"中心周波数  : {cf / 1e6:.6f} MHz")
            print(f"サンプルレート: {sr / 1e6:.6f} MSps")
            return 0
        except Exception as e:
            print(f"エラー: {e}")
            return 1

    out_dir = str(args.output)

    def progress(done: int, total: int) -> None:
        if total == 0:
            return
        pct = int(done / total * 100)
        bar = "#" * (pct // 5)
        print(f"\r[{bar:<20}] {pct:3d}%", end="", flush=True)

    try:
        fmt = (args.format or "csv").lower()
        if fmt == "parquet":
            out = convert_r3f_to_parquet(r3f_path, out_dir, progress_cb=progress)
        else:
            out = convert_r3f_to_csv(r3f_path, out_dir, progress_cb=progress)
        print(f"\n保存完了: {out}")
        return 0
    except Exception as e:
        print(f"\nエラー: {e}")
        return 1


def gui_main() -> int:
    from ui import run_gui
    run_gui()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="r3f-converter",
        description="Tektronix RSA .r3f ファイルを CSV / Parquet に変換するツール",
    )
    p.add_argument("--input",    "-i", type=Path, help=".r3f ファイルパス (省略時は GUI 起動)")
    p.add_argument("--output",   "-o", type=Path, default=Path("output"), help="出力ディレクトリ (default: output)")
    p.add_argument("--format",   "-f", choices=["csv", "parquet"], default="csv", help="出力形式 (default: csv)")
    p.add_argument("--meta-only","-m", action="store_true", help="メタデータだけ表示して終了")
    return p


def main() -> int:
    from config import is_env_configured, show_initial_setup_dialog

    # CLI 実行時は .env チェックをスキップ（後で DLL 接続で判明）
    parser = build_parser()
    args = parser.parse_args()

    if args.input is not None:
        return cli_main(args)

    # GUI モード: .env 確認 → なければ初期設定ダイアログ表示
    if not is_env_configured():
        if not show_initial_setup_dialog():
            print("初期設定がキャンセルされました。")
            return 1

    return gui_main()


if __name__ == "__main__":
    sys.exit(main())
