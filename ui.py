"""
PyQt6 GUI module.

Processing flow:
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
# Background workers
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
    finished = pyqtSignal(object, object, object, object, object)
    error    = pyqtSignal(str)

    def __init__(self, r3f_path: str, record_length: int) -> None:
        super().__init__()
        self.r3f_path     = r3f_path
        self.record_length = record_length

    def run(self) -> None:
        try:
            from rsa_api import PlaybackRSA
            from converter import compute_fft, compute_spectrogram

            rsa = PlaybackRSA()
            rsa.open_r3f_file(self.r3f_path)
            cf = rsa.get_center_freq()
            sr = rsa.get_sample_rate()
            rsa.set_record_length(self.record_length)
            i_data, q_data = rsa.acquire_iq_data()
            rsa.close()

            freqs, psd = compute_fft(i_data, q_data, sr)
            f, t, sxx  = compute_spectrogram(i_data, q_data, sr)

            self.finished.emit(freqs, psd, (f, t, sxx), sr, cf)
        except Exception as exc:
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("R3F Converter")
        self.setMinimumSize(900, 700)

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

        cl.addWidget(QLabel("Format:"))
        self._fmt_combo = QComboBox()
        self._fmt_combo.addItems(["CSV", "Parquet"])
        cl.addWidget(self._fmt_combo)

        cl.addWidget(QLabel("Record Length:"))
        self._rec_spin = QSpinBox()
        self._rec_spin.setRange(256, 1 << 20)
        self._rec_spin.setValue(65536)
        self._rec_spin.setSingleStep(1024)
        cl.addWidget(self._rec_spin)

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
        plot_group = QGroupBox("4. Analysis (FFT / Waterfall)")
        pl = QVBoxLayout(plot_group)

        btn_analyze = QPushButton("Acquire IQ & Analyze")
        btn_analyze.clicked.connect(self._on_analyze)
        pl.addWidget(btn_analyze)

        self._figure = Figure(figsize=(8, 4))
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
            rsa.open_r3f_file(self._r3f_path)
            cf = rsa.get_center_freq()
            sr = rsa.get_sample_rate()
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
            self._rec_spin.value(),
        )
        self._worker.progress.connect(
            lambda d, t: self._progress.setValue(int(d / t * 100))
        )
        self._worker.finished.connect(self._on_export_done)
        self._worker.error.connect(lambda e: QMessageBox.critical(self, "Error", e))
        self._worker.start()
        self.statusBar().showMessage("Converting...")

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

        self._worker = AnalysisWorker(self._r3f_path, self._rec_spin.value())
        self._worker.finished.connect(self._on_analysis_done)
        self._worker.error.connect(lambda e: QMessageBox.critical(self, "Error", e))
        self._worker.start()
        self.statusBar().showMessage("Analyzing...")

    def _on_analysis_done(
        self,
        freqs: np.ndarray,
        psd: np.ndarray,
        spectrogram_data: tuple,
        sample_rate: float,
        center_freq: float,
    ) -> None:
        f, t, sxx = spectrogram_data
        cf_mhz = center_freq / 1e6
        sr_mhz = sample_rate / 1e6

        # Baseband -> absolute RF frequency [MHz]
        rf_freqs = (center_freq + freqs) / 1e6
        rf_f     = (center_freq + f)    / 1e6

        self._figure.clear()
        self._figure.suptitle(
            f"Center Freq: {cf_mhz:.3f} MHz   Sample Rate: {sr_mhz:.1f} MSps",
            fontsize=10,
        )

        # ---- FFT Spectrum ----
        ax1 = self._figure.add_subplot(1, 2, 1)
        ax1.plot(rf_freqs, psd, linewidth=0.5, color="steelblue")
        ax1.axvline(cf_mhz, color="red", linewidth=0.8, linestyle="--", label=f"CF {cf_mhz:.1f} MHz")
        ax1.set_xlabel("Frequency [MHz]")
        ax1.set_ylabel("Amplitude Spectrum [dBFS]")
        ax1.set_title("FFT Spectrum")
        ax1.legend(fontsize=8)
        ax1.grid(True, alpha=0.3)

        # ---- Waterfall (Spectrogram) ----
        ax2 = self._figure.add_subplot(1, 2, 2)
        mesh = ax2.pcolormesh(t * 1e3, rf_f, sxx, shading="auto", cmap="inferno")
        ax2.axhline(cf_mhz, color="cyan", linewidth=0.8, linestyle="--", label=f"CF {cf_mhz:.1f} MHz")
        self._figure.colorbar(mesh, ax=ax2, label="Power [dB]", fraction=0.046, pad=0.04)
        ax2.set_xlabel("Time [ms]")
        ax2.set_ylabel("Frequency [MHz]")
        ax2.set_title("Waterfall (Spectrogram)")
        ax2.legend(fontsize=8)

        self._figure.tight_layout()
        self._canvas.draw()
        self.statusBar().showMessage(
            f"Analysis done — CF: {cf_mhz:.3f} MHz  SR: {sr_mhz:.1f} MSps"
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_gui() -> None:
    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.show()
    app.exec()
