"""
PyQt6 GUI module.

Processing flow:
[Open r3f] -> [Read Metadata] -> [DPX Acquire] -> [Per-Freq Max / Per-Time Max in dBm] -> [Export CSV]
"""

from __future__ import annotations

import os
from pathlib import Path

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
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

import matplotlib
matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

# ---------------------------------------------------------------------------
# Background workers
# ---------------------------------------------------------------------------

class ConvertWorker(QThread):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(str)
    error    = pyqtSignal(str)

    def __init__(
        self,
        r3f_path: str,
        out_dir: str,
        fmt: str,
        content: str,
    ) -> None:
        super().__init__()
        self.r3f_path = r3f_path
        self.out_dir  = out_dir
        self.fmt      = fmt
        self.content  = content

    def run(self) -> None:
        try:
            from converter import convert_r3f

            def cb(done: int, total: int) -> None:
                self.progress.emit(done, total)

            out = convert_r3f(
                self.r3f_path,
                self.out_dir,
                fmt=self.fmt,
                content=self.content,
                progress_cb=cb,
            )
            self.finished.emit(str(out))
        except Exception as exc:
            self.error.emit(str(exc))


class AnalysisWorker(QThread):
    """DPX hi-res ラインからスペクトラム・スペクトログラムを生成する。

    finished シグナルの引数:
        freqs_hz   : ndarray  — 絶対 RF 周波数 [Hz]
        psd_dbm    : ndarray  — スペクトラム [dBm]（全ラインの平均）
        sog_data   : tuple(f, t, sxx)  — f [Hz], t [s], sxx [dBm] (freq×time)
        sample_rate: float [Hz]
        center_freq: float [Hz]
        start_unix : float  — 最初のタイムスタンプ（測定開始）[Unix 秒]
    """
    finished = pyqtSignal(object, object, object, object, object, object)
    error    = pyqtSignal(str)

    def __init__(self, r3f_path: str) -> None:
        super().__init__()
        self.r3f_path = r3f_path

    def run(self) -> None:
        try:
            from rsa_api import PlaybackRSA

            rsa = PlaybackRSA()
            try:
                rsa.open_r3f_file(self.r3f_path)
                cf = rsa.get_center_freq()
                sr = rsa.get_sample_rate()

                fspan = min(sr, 40e6)
                dpx_data = rsa.acquire_dpx_data(fspan)
                trace_len = dpx_data["trace_length"]
                hires = rsa.get_dpx_hires_lines(trace_len)
            finally:
                rsa.close()

            if not hires:
                self.error.emit("DPX hi-res ラインが取得できませんでした。")
                return

            n_freq = len(hires[0][0])
            freqs = np.linspace(cf - fspan / 2, cf + fspan / 2, n_freq)

            power_matrix = np.array([pwr for pwr, _ in hires], dtype=np.float64)  # (n_time, n_freq)
            psd_dbm = np.max(power_matrix, axis=0)  # 各周波数ごとの最大電力を抜粋

            timestamps = np.array([ts for _, ts in hires])
            start_unix = float(timestamps.min()) if len(timestamps) > 0 else 0.0
            if len(timestamps) > 0:
                timestamps = timestamps - timestamps.min()  # 測定開始を 0 に正規化

            sxx = power_matrix.T  # (n_freq, n_time)

            self.finished.emit(freqs, psd_dbm, (freqs, timestamps, sxx), sr, cf, start_unix)
        except Exception as exc:
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("R3F Converter")
        self.setMinimumSize(960, 720)

        self._r3f_path: str | None = None
        self._worker: QThread | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # ---- File selection ----
        file_group = QGroupBox("1. Open R3F File")
        fl = QHBoxLayout(file_group)
        self._file_label = QLabel("(No file selected)")
        self._file_label.setWordWrap(True)
        btn_open = QPushButton("Browse...")
        btn_open.clicked.connect(self._on_open_file)
        fl.addWidget(self._file_label, stretch=1)
        fl.addWidget(btn_open)
        root.addWidget(file_group)

        # ---- Metadata ----
        meta_group = QGroupBox("2. Metadata")
        ml = QHBoxLayout(meta_group)
        self._lbl_cf = QLabel("Center Freq: -")
        self._lbl_sr = QLabel("Sample Rate: -")
        btn_meta = QPushButton("Read")
        btn_meta.clicked.connect(self._on_read_metadata)
        ml.addWidget(self._lbl_cf)
        ml.addWidget(self._lbl_sr)
        ml.addStretch()
        ml.addWidget(btn_meta)
        root.addWidget(meta_group)

        # ---- Export settings ----
        conv_group = QGroupBox("3. Export Settings")
        cl = QHBoxLayout(conv_group)

        cl.addWidget(QLabel("Data:"))
        self._content_combo = QComboBox()
        # (表示名, converter の content 値)
        self._content_combo.addItem("Raw DPX data", "raw")
        self._content_combo.addItem("Per-frequency max", "freq_max")
        self._content_combo.addItem("Per-time max", "time_max")
        cl.addWidget(self._content_combo)

        cl.addWidget(QLabel("Format:"))
        self._fmt_combo = QComboBox()
        self._fmt_combo.addItems(["CSV", "Parquet"])
        cl.addWidget(self._fmt_combo)

        btn_outdir = QPushButton("Output Dir...")
        btn_outdir.clicked.connect(self._on_choose_outdir)
        self._outdir_label = QLabel(str(Path("output").resolve()))
        cl.addWidget(btn_outdir)
        cl.addWidget(self._outdir_label, stretch=1)

        btn_export = QPushButton("Export")
        btn_export.clicked.connect(self._on_export)
        cl.addWidget(btn_export)
        root.addWidget(conv_group)

        # ---- Progress ----
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        root.addWidget(self._progress)

        # ---- Analysis ----
        plot_group = QGroupBox("4. DPX Analysis (Per-Freq Max / Per-Time Max)")
        pl = QVBoxLayout(plot_group)

        btn_row = QHBoxLayout()
        btn_analyze = QPushButton("Acquire DPX & Analyze")
        btn_analyze.clicked.connect(self._on_analyze)
        btn_row.addWidget(btn_analyze)

        self._btn_save_img = QPushButton("Save Graph Image...")
        self._btn_save_img.clicked.connect(self._on_save_image)
        self._btn_save_img.setEnabled(False)
        btn_row.addWidget(self._btn_save_img)
        pl.addLayout(btn_row)

        self._figure = Figure(figsize=(9, 4.5))
        self._canvas = FigureCanvas(self._figure)
        pl.addWidget(self._canvas)
        root.addWidget(plot_group, stretch=1)

        self.setStatusBar(QStatusBar())

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select R3F File", "", "R3F Files (*.r3f);;All Files (*)"
        )
        if path:
            self._r3f_path = path
            self._file_label.setText(path)
            self.statusBar().showMessage(f"Opened: {path}")

    def _on_choose_outdir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select Output Directory", "output")
        if d:
            self._outdir_label.setText(d)

    def _on_read_metadata(self) -> None:
        if not self._r3f_path:
            QMessageBox.warning(self, "Warning", "Please select an R3F file first.")
            return
        try:
            from rsa_api import PlaybackRSA
            rsa = PlaybackRSA()
            try:
                rsa.open_r3f_file(self._r3f_path)
                cf = rsa.get_center_freq()
                sr = rsa.get_sample_rate()
            finally:
                rsa.close()
            self._lbl_cf.setText(f"Center Freq: {cf / 1e6:.3f} MHz")
            self._lbl_sr.setText(f"Sample Rate: {sr / 1e6:.3f} MSps")
            self.statusBar().showMessage("Metadata loaded.")
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))

    def _on_export(self) -> None:
        if not self._r3f_path:
            QMessageBox.warning(self, "Warning", "Please select an R3F file first.")
            return
        if self._worker and self._worker.isRunning():
            return

        self._progress.setValue(0)
        self._worker = ConvertWorker(
            self._r3f_path,
            self._outdir_label.text(),
            self._fmt_combo.currentText(),
            self._content_combo.currentData(),
        )
        self._worker.progress.connect(
            lambda d, t: self._progress.setValue(int(d / t * 100) if t else 0)
        )
        self._worker.finished.connect(self._on_export_done)
        self._worker.error.connect(lambda e: QMessageBox.critical(self, "Error", e))
        self._worker.start()
        self.statusBar().showMessage("Converting (DPX)...")

    def _on_export_done(self, out_path: str) -> None:
        self._progress.setValue(100)
        self.statusBar().showMessage(f"Saved: {out_path}")
        QMessageBox.information(self, "Done", f"File saved:\n{out_path}")

    def _on_analyze(self) -> None:
        if not self._r3f_path:
            QMessageBox.warning(self, "Warning", "Please select an R3F file first.")
            return
        if self._worker and self._worker.isRunning():
            return

        self._worker = AnalysisWorker(self._r3f_path)
        self._worker.finished.connect(self._on_analysis_done)
        self._worker.error.connect(lambda e: QMessageBox.critical(self, "Error", e))
        self._worker.start()
        self.statusBar().showMessage("DPX acquisition in progress...")

    def _on_analysis_done(
        self,
        freqs: np.ndarray,
        psd_dbm: np.ndarray,
        spectrogram_data: tuple,
        sample_rate: float,
        center_freq: float,
        start_unix: float = 0.0,
    ) -> None:
        f, t, sxx = spectrogram_data
        cf_mhz = center_freq / 1e6
        sr_mhz = sample_rate / 1e6

        # 最初のタイムスタンプ（Unix 秒）を日本標準時 (JST, UTC+9) に変換
        start_str = "-"
        if start_unix and start_unix > 0:
            from datetime import datetime, timezone, timedelta
            jst = timezone(timedelta(hours=9))
            start_str = datetime.fromtimestamp(start_unix, tz=jst).strftime(
                "%Y-%m-%d %H:%M:%S JST"
            )

        rf_freqs_mhz = freqs / 1e6
        t_ms         = t * 1e3

        # sxx は (n_freq, n_time) = (周波数点数 ≈801, タイムスタンプ数)。
        #   左: 各周波数の全時間にわたる最大値 → 周波数軸の折れ線
        #   右: 各タイムスタンプの全周波数点(≈801点)にわたる最大値 → 時間軸の点列
        if sxx.ndim == 2 and sxx.shape[1] > 0:
            freq_max_dbm = np.max(sxx, axis=1)   # (n_freq,)
            time_max_dbm = np.max(sxx, axis=0)   # (n_time,)
        else:
            freq_max_dbm = psd_dbm
            time_max_dbm = np.array([float(np.max(psd_dbm))])

        self._figure.clear()
        self._figure.suptitle(
            f"Start: {start_str}\n"
            f"Center Freq: {cf_mhz:.3f} MHz   Sample Rate: {sr_mhz:.1f} MSps   [DPX]",
            fontsize=10,
        )

        # ---- 左: 周波数ごとの最大電力 ----
        ax1 = self._figure.add_subplot(1, 2, 1)
        ax1.plot(rf_freqs_mhz, freq_max_dbm, linewidth=0.8, color="steelblue")
        ax1.fill_between(
            rf_freqs_mhz, freq_max_dbm.min() - 5, freq_max_dbm,
            alpha=0.2, color="steelblue",
        )

        # 尾根（ピーク）を検出してマーク（失敗しても続行）
        try:
            from scipy.signal import find_peaks
            peaks, props = find_peaks(
                freq_max_dbm,
                prominence=6,
                distance=max(1, len(freq_max_dbm) // 80),
            )
            if len(peaks) > 0:
                top_n = min(5, len(peaks))
                top_peaks = peaks[np.argsort(props["prominences"])[-top_n:]]
                ax1.scatter(
                    rf_freqs_mhz[top_peaks], freq_max_dbm[top_peaks],
                    color="red", s=30, zorder=5, marker="^",
                    label=f"Peaks ({top_n})",
                )
        except Exception:
            pass

        ax1.axvline(cf_mhz, color="red", linewidth=0.8, linestyle="--",
                    label=f"CF {cf_mhz:.1f} MHz")
        ax1.set_xlabel("Frequency [MHz]")
        ax1.set_ylabel("Max Power [dBm]")
        ax1.set_title("Per-Frequency Max")
        ax1.legend(fontsize=8)
        ax1.grid(True, alpha=0.3)

        # ---- 右: 時間ごとの最大電力 ----
        ax2 = self._figure.add_subplot(1, 2, 2)
        # タイムスタンプ数が多い時はマーカーが潰れるので点サイズを調整
        marker_size = 4 if len(time_max_dbm) <= 200 else 2
        ax2.plot(
            t_ms, time_max_dbm,
            linewidth=0.8, color="darkorange",
            marker="o", markersize=marker_size, markerfacecolor="darkorange",
        )
        ax2.set_xlabel("Time [ms]")
        ax2.set_ylabel("Max Power [dBm]")
        ax2.set_title(f"Per-Timestamp Max ({len(time_max_dbm)} pts)")
        ax2.grid(True, alpha=0.3)

        self._figure.tight_layout()
        self._canvas.draw()
        self._btn_save_img.setEnabled(True)
        self.statusBar().showMessage(
            f"DPX analysis done — CF: {cf_mhz:.3f} MHz  SR: {sr_mhz:.1f} MSps"
        )

    def _on_save_image(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Graph Image",
            "dpx_analysis.png",
            "PNG Image (*.png);;PDF (*.pdf);;SVG (*.svg);;All Files (*)",
        )
        if not path:
            return
        try:
            self._figure.savefig(path, dpi=150, bbox_inches="tight")
            self.statusBar().showMessage(f"Image saved: {path}")
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_gui() -> None:
    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.show()
    app.exec()
