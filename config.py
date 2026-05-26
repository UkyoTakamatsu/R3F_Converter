"""
設定ファイル管理モジュール。

.env が存在しない場合は GUI で初期設定を行う。
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


ENV_FILE = Path(__file__).parent / ".env"
ENV_EXAMPLE = Path(__file__).parent / ".env.example"


def is_env_configured() -> bool:
    """`.env` ファイルが存在して有効に設定されているか確認。"""
    if not ENV_FILE.exists():
        return False
    load_dotenv(ENV_FILE)
    dll_path = os.environ.get("RSA_API_DLL", "").strip()
    return dll_path and dll_path != "RSA_API.dll"


def create_env_from_user_input(dll_path: str) -> bool:
    """ユーザー入力から .env ファイルを生成。"""
    try:
        content = f"""# RSA_API.dll の絶対パスを指定してください
# 例: C:\\Tektronix\\RSA_API\\lib\\x64\\RSA_API.dll
RSA_API_DLL="{dll_path}"
"""
        ENV_FILE.write_text(content, encoding="utf-8")
        return True
    except Exception as e:
        print(f"Error writing .env: {e}")
        return False


def show_initial_setup_dialog() -> bool:
    """初期設定ダイアログを表示して .env を生成。成功時 True。"""
    from PyQt6.QtWidgets import (
        QApplication,
        QDialog,
        QVBoxLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QFileDialog,
        QMessageBox,
    )

    app = QApplication.instance() or QApplication([])

    dlg = QDialog()
    dlg.setWindowTitle("初期設定 - R3F → CSV 変換ツール")
    dlg.setMinimumWidth(600)

    layout = QVBoxLayout(dlg)

    layout.addWidget(
        QLabel(
            ".env ファイルが見つかりません。\n"
            "Tektronix RSA_API.dll のパスを指定してください。"
        )
    )

    input_layout = QHBoxLayout()
    input_field = QLineEdit()
    input_field.setPlaceholderText("C:\\Tektronix\\RSA_API\\lib\\x64\\RSA_API.dll")
    input_layout.addWidget(QLabel("DLL パス:"))
    input_layout.addWidget(input_field, stretch=1)
    layout.addLayout(input_layout)

    btn_layout = QHBoxLayout()

    def browse_dll() -> None:
        path, _ = QFileDialog.getOpenFileName(
            dlg, "RSA_API.dll を選択", "", "DLL Files (*.dll);;All Files (*)"
        )
        if path:
            input_field.setText(path)

    btn_browse = QPushButton("参照…")
    btn_browse.clicked.connect(browse_dll)
    btn_layout.addWidget(btn_browse)
    btn_layout.addStretch()

    btn_ok = QPushButton("OK")
    btn_cancel = QPushButton("キャンセル")

    def on_ok() -> None:
        dll_path = input_field.text().strip()
        if not dll_path:
            QMessageBox.warning(dlg, "警告", "DLL パスを入力してください。")
            return
        if not Path(dll_path).exists():
            QMessageBox.warning(dlg, "警告", f"ファイルが見つかりません:\n{dll_path}")
            return
        if create_env_from_user_input(dll_path):
            QMessageBox.information(dlg, "完了", ".env ファイルを作成しました。")
            dlg.accept()
        else:
            QMessageBox.critical(dlg, "エラー", ".env ファイルの作成に失敗しました。")

    btn_ok.clicked.connect(on_ok)
    btn_cancel.clicked.connect(dlg.reject)

    btn_layout.addWidget(btn_ok)
    btn_layout.addWidget(btn_cancel)
    layout.addLayout(btn_layout)

    result = dlg.exec()
    return result == QDialog.DialogCode.Accepted
