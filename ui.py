"""
PyQt6 GUI モジュール。

処理フロー:
[Open r3f] -> [Read Metadata] -> [Extract IQ] -> [FFT / Waterfall] -> [Export CSV]
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

import matplotlib
matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


# ---------------------------------------------------------------------------
# バックグラウンドワーカー
# ---------------------------------------------------------------------------

class ConvertWorker(QThread):
    progress   = pyqtSignal(int, int)
    finished   = pyqtSignal(str)
    error      = pyqtSignal(str)

    def __init__(
        self,
        r3f_path: str,
        out_dir: str,
        fmt: str,
        record_length: int,
    ) -> None:
        super().__init__()
        self.r3f_path     = r3f_path
        self.out_dir      = out_dir
        self.fmt          = fmt
        self.record_length = record_length

    def run(self) -> None:
        try:
            from converter import convert_r3f_to_csv, convert_r3f_to_parquet

            def cb(done: int, total: int) -> None:
                self.progress.emit(done, total)

            if self.fmt == "CSV":
                out = convert_r3f_to_csv(
                    self.r3f_path, self.out_dir, self.record_length, cb
                )
            else:
                out = convert_r3f_to_parquet(
                    self.r3f_path, self.out_dir, self.record_length, cb
                )
            self.finished.emit(str(out))
        except Exception as exc:
            self.error.emit(str(exc))


class AnalysisWorker(QThread):
    finished = pyqtSignal(object, object, object, object)
    error    = pyqtSignal(str)

    def __init__(self, r3f_path: str, record_length: int) -> None:
        super().__init__()
        self.r3f_path     = r3f_path
        self.record_length = record_length

    def run(self) -> None:
        try:
            from rsa_api import RSAAPI
            from converter import compute_fft, compute_spectrogram

            rsa = RSAAPI()
            rsa.open_disk_file(self.r3f_path)
            rsa.device_run()
            rsa.set_record_length(self.record_length)
            sr = rsa.get_sample_rate()
            i_data, q_data = rsa.acquire_iq_data()
            rsa.device_stop()
            rsa.disconnect()

            freqs, psd    = compute_fft(i_data, q_data, sr)
            f, t, sxx     = compute_spectrogram(i_data, q_data, sr)

            self.finished.emit(freqs, psd, (f, t, sxx), sr)
        except Exception as exc:
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# メインウィンドウ
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("R3F → CSV 変換ツール")
        self.setMinimumSize(900, 700)

        self._r3f_path: str | None = None
        self._worker: QThread | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # ---- ファイル選択 ----
        file_group = QGroupBox("1. R3F ファイルを開く")
        fl = QHBoxLayout(file_group)
        self._file_label = QLabel("(未選択)")
        self._file_label.setWordWrap(True)
        btn_open = QPushButton("参照…")
        btn_open.clicked.connect(self._on_open_file)
        fl.addWidget(self._file_label, stretch=1)
        fl.addWidget(btn_open)
        root.addWidget(file_group)

        # ---- メタデータ ----
        meta_group = QGroupBox("2. メタデータ")
        ml = QHBoxLayout(meta_group)
        self._lbl_cf = QLabel("中心周波数: -")
        self._lbl_sr = QLabel("サンプルレート: -")
        btn_meta = QPushButton("取得")
        btn_meta.clicked.connect(self._on_read_metadata)
        ml.addWidget(self._lbl_cf)
        ml.addWidget(self._lbl_sr)
        ml.addStretch()
        ml.addWidget(btn_meta)
        root.addWidget(meta_group)

        # ---- 変換設定 ----
        conv_group = QGroupBox("3. 変換設定 / エクスポート")
        cl = QHBoxLayout(conv_group)

        cl.addWidget(QLabel("形式:"))
        self._fmt_combo = QComboBox()
        self._fmt_combo.addItems(["CSV", "Parquet"])
        cl.addWidget(self._fmt_combo)

        cl.addWidget(QLabel("レコード長:"))
        self._rec_spin = QSpinBox()
        self._rec_spin.setRange(256, 1 << 20)
        self._rec_spin.setValue(65536)
        self._rec_spin.setSingleStep(1024)
        cl.addWidget(self._rec_spin)

        btn_outdir = QPushButton("出力先…")
        btn_outdir.clicked.connect(self._on_choose_outdir)
        self._outdir_label = QLabel(str(Path("output").resolve()))
        cl.addWidget(btn_outdir)
        cl.addWidget(self._outdir_label, stretch=1)

        btn_export = QPushButton("エクスポート")
        btn_export.clicked.connect(self._on_export)
        cl.addWidget(btn_export)
        root.addWidget(conv_group)

        # ---- プログレス ----
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        root.addWidget(self._progress)

        # ---- 分析 ----
        plot_group = QGroupBox("4. 分析 (FFT / Waterfall)")
        pl = QVBoxLayout(plot_group)

        btn_analyze = QPushButton("IQ を取得して解析")
        btn_analyze.clicked.connect(self._on_analyze)
        pl.addWidget(btn_analyze)

        self._figure = Figure(figsize=(8, 4))
        self._canvas = FigureCanvas(self._figure)
        pl.addWidget(self._canvas)
        root.addWidget(plot_group, stretch=1)

        self.setStatusBar(QStatusBar())

    # ------------------------------------------------------------------
    # イベントハンドラ
    # ------------------------------------------------------------------

    def _on_open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "R3F ファイルを選択", "", "R3F Files (*.r3f);;All Files (*)"
        )
        if path:
            self._r3f_path = path
            self._file_label.setText(path)
            self.statusBar().showMessage(f"開きました: {path}")

    def _on_choose_outdir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "出力フォルダを選択", "output")
        if d:
            self._outdir_label.setText(d)

    def _on_read_metadata(self) -> None:
        if not self._r3f_path:
            QMessageBox.warning(self, "警告", "先に R3F ファイルを選択してください。")
            return
        try:
            from rsa_api import RSAAPI
            rsa = RSAAPI()
            rsa.open_disk_file(self._r3f_path)
            rsa.device_run()
            cf = rsa.get_center_freq()
            sr = rsa.get_sample_rate()
            rsa.device_stop()
            rsa.disconnect()
            self._lbl_cf.setText(f"中心周波数: {cf / 1e6:.3f} MHz")
            self._lbl_sr.setText(f"サンプルレート: {sr / 1e6:.3f} MSps")
            self.statusBar().showMessage("メタデータ取得完了")
        except Exception as exc:
            QMessageBox.critical(self, "エラー", str(exc))

    def _on_export(self) -> None:
        if not self._r3f_path:
            QMessageBox.warning(self, "警告", "先に R3F ファイルを選択してください。")
            return
        if self._worker and self._worker.isRunning():
            return

        self._progress.setValue(0)
        self._worker = ConvertWorker(
            self._r3f_path,
            self._outdir_label.text(),
            self._fmt_combo.currentText(),
            self._rec_spin.value(),
        )
        self._worker.progress.connect(
            lambda d, t: self._progress.setValue(int(d / t * 100))
        )
        self._worker.finished.connect(self._on_export_done)
        self._worker.error.connect(lambda e: QMessageBox.critical(self, "エラー", e))
        self._worker.start()
        self.statusBar().showMessage("変換中…")

    def _on_export_done(self, out_path: str) -> None:
        self._progress.setValue(100)
        self.statusBar().showMessage(f"保存完了: {out_path}")
        QMessageBox.information(self, "完了", f"保存しました:\n{out_path}")

    def _on_analyze(self) -> None:
        if not self._r3f_path:
            QMessageBox.warning(self, "警告", "先に R3F ファイルを選択してください。")
            return
        if self._worker and self._worker.isRunning():
            return

        self._worker = AnalysisWorker(self._r3f_path, self._rec_spin.value())
        self._worker.finished.connect(self._on_analysis_done)
        self._worker.error.connect(lambda e: QMessageBox.critical(self, "エラー", e))
        self._worker.start()
        self.statusBar().showMessage("解析中…")

    def _on_analysis_done(
        self,
        freqs: np.ndarray,
        psd: np.ndarray,
        spectrogram_data: tuple,
        sample_rate: float,
    ) -> None:
        f, t, sxx = spectrogram_data
        self._figure.clear()

        ax1 = self._figure.add_subplot(1, 2, 1)
        ax1.plot(freqs / 1e6, psd, linewidth=0.5)
        ax1.set_xlabel("周波数 [MHz]")
        ax1.set_ylabel("電力 [dBFS]")
        ax1.set_title("FFT スペクトル")
        ax1.grid(True, alpha=0.3)

        ax2 = self._figure.add_subplot(1, 2, 2)
        ax2.pcolormesh(t * 1e3, f / 1e6, sxx, shading="auto", cmap="inferno")
        ax2.set_xlabel("時間 [ms]")
        ax2.set_ylabel("周波数 [MHz]")
        ax2.set_title("ウォーターフォール")

        self._figure.tight_layout()
        self._canvas.draw()
        self.statusBar().showMessage(f"解析完了 (SR={sample_rate / 1e6:.1f} MSps)")


# ---------------------------------------------------------------------------
# エントリーポイント
# ---------------------------------------------------------------------------

def run_gui() -> None:
    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.show()
    app.exec()
