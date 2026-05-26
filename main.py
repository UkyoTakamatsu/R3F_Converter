"""
R3F → CSV 変換アプリ  エントリーポイント

使い方:
    # GUI モード (デフォルト)
    python main.py

    # CLI モード — CSV 出力
    python main.py --input samples/sample.r3f --format csv

    # CLI モード — Parquet 出力
    python main.py --input samples/sample.r3f --format parquet

    # メタデータだけ確認
    python main.py --input samples/sample.r3f --meta-only

RSA_API.dll が見つからない場合はダミーモード（サイン波）で動作します。
DLL の場所を変えるには環境変数 RSA_API_DLL に絶対パスを指定してください。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def cli_main(args: argparse.Namespace) -> int:
    from rsa_api import RSAAPI
    from converter import (
        convert_r3f_to_csv,
        convert_r3f_to_parquet,
        iq_to_dataframe,
    )

    r3f_path = str(args.input)

    if args.meta_only:
        rsa = RSAAPI()
        rsa.open_disk_file(r3f_path)
        rsa.device_run()
        cf = rsa.get_center_freq()
        sr = rsa.get_sample_rate()
        rsa.device_stop()
        rsa.disconnect()
        print(f"中心周波数  : {cf / 1e6:.6f} MHz")
        print(f"サンプルレート: {sr / 1e6:.6f} MSps")
        return 0

    out_dir = str(args.output)

    def progress(done: int, total: int) -> None:
        pct = int(done / total * 100)
        bar = "#" * (pct // 5)
        print(f"\r[{bar:<20}] {pct:3d}%", end="", flush=True)

    fmt = (args.format or "csv").lower()
    if fmt == "parquet":
        out = convert_r3f_to_parquet(r3f_path, out_dir, args.record_length, progress)
    else:
        out = convert_r3f_to_csv(r3f_path, out_dir, args.record_length, progress)

    print(f"\n保存完了: {out}")
    return 0


def gui_main() -> int:
    from ui import run_gui
    run_gui()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="r3f-converter",
        description="Tektronix RSA .r3f ファイルを CSV / Parquet に変換するツール",
    )
    p.add_argument("--input",         "-i", type=Path, help=".r3f ファイルパス (省略時は GUI 起動)")
    p.add_argument("--output",        "-o", type=Path, default=Path("output"), help="出力ディレクトリ (default: output)")
    p.add_argument("--format",        "-f", choices=["csv", "parquet"], default="csv", help="出力形式 (default: csv)")
    p.add_argument("--record-length", "-r", type=int, default=65536, help="1 取得あたりのサンプル数 (default: 65536)")
    p.add_argument("--meta-only",     "-m", action="store_true", help="メタデータだけ表示して終了")
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
