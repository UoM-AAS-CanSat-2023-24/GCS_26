"""
CanSat Ground Station - entry point.
Wires together: DashboardGUI, SerialWorker, SimWorker, DataLogger.
"""

import logging
import sys
import os

from PyQt5.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QFileDialog, QMessageBox,
)
from PyQt5.QtGui import QFont, QPalette, QColor
from PyQt5.QtCore import Qt

# Guard so tests can import main without Qt crashing
if __name__ == "__main__":
    from dashboard import DashboardGUI
    from serial_handler import SerialWorker
    from playback_worker import PlaybackWorker
    from simp_sender import SimpSender, load_simp_file
    from logger import DataLogger
    import config

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("groundstation.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Port selection dialog
# ---------------------------------------------------------------------------

class StartupDialog(QDialog):
    """
    Simple dialog shown at startup to select serial port and optional sim file.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ground Station Setup")
        self.setFixedSize(400, 200)
        self.selected_port = None
        self.selected_simp = None

        layout = QVBoxLayout(self)

        # Port selection
        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("Serial Port:"))
        self.port_combo = QComboBox()
        self.port_combo.addItems(self._list_ports())
        self.port_combo.setEditable(True)
        port_row.addWidget(self.port_combo)
        layout.addLayout(port_row)

        # Playback CSV (optional - leave blank for live serial)
        pb_row = QHBoxLayout()
        self.pb_label = QLabel("Playback CSV: (none — use live serial)")
        pb_row.addWidget(self.pb_label)
        btn_pb = QPushButton("Browse…")
        btn_pb.clicked.connect(self._browse_csv)
        pb_row.addWidget(btn_pb)
        btn_pb_clear = QPushButton("Clear")
        btn_pb_clear.clicked.connect(self._clear_csv)
        pb_row.addWidget(btn_pb_clear)
        layout.addLayout(pb_row)

        # Speed selector (only relevant for playback)
        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("Playback speed:"))
        self.speed_combo = QComboBox()
        self.speed_combo.addItems(["1×", "2×", "5×", "10×"])
        speed_row.addWidget(self.speed_combo)
        layout.addLayout(speed_row)

        # SIMP file selection (optional - can also be selected when SIM ACTIVATE is pressed)
        sim_row = QHBoxLayout()
        self.sim_label = QLabel("SIMP File: (none - select later)")
        sim_row.addWidget(self.sim_label)
        btn_sim = QPushButton("Browse…")
        btn_sim.clicked.connect(self._browse_simp)
        sim_row.addWidget(btn_sim)
        layout.addLayout(sim_row)

        # Buttons
        btn_row = QHBoxLayout()
        btn_start = QPushButton("Start")
        btn_start.clicked.connect(self.accept)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_start)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

    def accept(self):
        self.selected_port = self.port_combo.currentText().strip()
        self.selected_csv  = getattr(self, "_csv_path", None)
        speed_map = {"1×": 1.0, "2×": 2.0, "5×": 5.0, "10×": 10.0}
        self.selected_speed = speed_map.get(self.speed_combo.currentText(), 1.0)
        super().accept()

    def _browse_csv(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Telemetry CSV", "logs", "CSV Files (*.csv);;All Files (*)"
        )
        if path:
            self._csv_path = path
            self.pb_label.setText(f"Playback CSV: {os.path.basename(path)}")

    def _clear_csv(self):
        self._csv_path = None
        self.pb_label.setText("Playback CSV: (none — use live serial)")

    def _browse_simp(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select SIMP Command File", "", "Text Files (*.txt);;All Files (*)"
        )
        if path:
            self.selected_simp = path
            self.sim_label.setText(f"SIMP File: {os.path.basename(path)}")

    @staticmethod
    def _list_ports() -> list[str]:
        """Return available serial port names."""
        try:
            import serial.tools.list_ports
            return [p.device for p in serial.tools.list_ports.comports()] or ["COM3"]
        except ImportError:
            return ["COM3", "/dev/ttyUSB0", "/dev/ttyACM0"]


# ---------------------------------------------------------------------------
# Application controller
# ---------------------------------------------------------------------------

class GroundStation:
    """
    Top-level controller.  Owns all workers and connects signals.

    Sim mode explanation:
      - SerialWorker runs the entire time, reading real telemetry from the CanSat
      - SIM ENABLE sends CMD,TEAM_ID,SIM,ENABLE to the CanSat over serial
      - SIM ACTIVATE starts SimpSender which sends SIMP pressure commands at 1 Hz
        via the same SerialWorker TX queue - RX is completely unaffected
      - The CanSat responds to SIMP commands with normal telemetry packets
      - SIM DISABLE stops SimpSender and sends CMD,TEAM_ID,SIM,DISABLE
    """

    def __init__(self, app: QApplication, port: str, simp_file: str | None,
                 playback_csv: str | None = None, playback_speed: float = 1.0):
        self.app = app
        self.port = port
        self.simp_file = simp_file
        self.playback_csv   = playback_csv
        self.playback_speed = playback_speed

        self.dashboard     = DashboardGUI()
        self.data_logger   = DataLogger(log_dir="logs")
        self.serial_worker: SerialWorker | None = None
        self.simp_sender:   SimpSender   | None = None
        self._sim_enabled  = False

        self._connect_dashboard_signals()
        self._start_serial()

        self.dashboard.show()

    # -----------------------------------------------------------------------
    # Signal wiring
    # -----------------------------------------------------------------------

    def _connect_dashboard_signals(self):
        self.dashboard.command_send.connect(self._on_command_send)
        self.dashboard._btn_sim_enable.toggled.connect(self._on_sim_enable_toggle)
        self.dashboard._btn_sim_activate.clicked.connect(self._on_sim_activate)

    def _connect_serial_signals(self, worker: SerialWorker):
        worker.packet_received.connect(self.dashboard.update_display)
        worker.packet_received.connect(self.data_logger.log)
        worker.raw_line_received.connect(self.data_logger.log_raw)
        worker.connection_status.connect(self.dashboard.set_connected)
        worker.parse_error.connect(self._on_parse_error)

    # -----------------------------------------------------------------------
    # Serial - runs the entire session, including during sim mode
    # -----------------------------------------------------------------------

    def _start_serial(self):
        if self.playback_csv:
            logger.info("Playback mode: loading %s at %.0fx", self.playback_csv, self.playback_speed)
            self.serial_worker = PlaybackWorker(
                csv_path=self.playback_csv, speed=self.playback_speed
            )
        else:
            self.serial_worker = SerialWorker(port=self.port, baud=config.BAUD_RATE)
        self._connect_serial_signals(self.serial_worker)
        self.serial_worker.start()
        logger.info("Worker started (%s)", type(self.serial_worker).__name__)

    def _stop_serial(self):
        if self.serial_worker:
            self.serial_worker.stop()
            self.serial_worker = None

    # -----------------------------------------------------------------------
    # Sim mode: SIM ENABLE toggle
    # -----------------------------------------------------------------------

    def _on_sim_enable_toggle(self, enabled: bool):
        """
        SIM ENABLE button toggled.
        Sends SIM,ENABLE or SIM,DISABLE to the CanSat.
        Does NOT start SIMP transmission - that is SIM ACTIVATE.
        """
        mode = "ENABLE" if enabled else "DISABLE"
        self._on_command_send(f"CMD,{config.TEAM_ID},SIM,{mode}")
        self._sim_enabled = enabled
        self.dashboard.set_sim_mode(enabled)

        if not enabled:
            # Also stop any running SIMP transmission
            self._stop_simp()

    # -----------------------------------------------------------------------
    # Sim mode: SIM ACTIVATE - starts sending SIMP pressure commands
    # -----------------------------------------------------------------------

    def _on_sim_activate(self):
        """
        SIM ACTIVATE button pressed.
        Loads the SIMP file and starts sending pressure commands at 1 Hz.
        SerialWorker RX is completely unaffected.
        """
        if not self._sim_enabled:
            QMessageBox.warning(
                self.dashboard, "Sim Not Enabled",
                "Enable simulation mode first (SIM ENABLE), then activate."
            )
            return

        if self.simp_sender and self.simp_sender.isRunning():
            QMessageBox.information(
                self.dashboard, "Already Active",
                "SIMP transmission is already running."
            )
            return

        # Resolve SIMP file path
        if not self.simp_file:
            path, _ = QFileDialog.getOpenFileName(
                self.dashboard, "Select SIMP Command File", "",
                "Text Files (*.txt);;All Files (*)"
            )
            if not path:
                return
            self.simp_file = path

        # Load and validate the file
        try:
            commands = load_simp_file(self.simp_file)
        except (FileNotFoundError, ValueError) as exc:
            QMessageBox.critical(
                self.dashboard, "SIMP File Error", str(exc)
            )
            return

        # Start sender
        self.simp_sender = SimpSender(
            commands=commands,
            serial_worker=self.serial_worker,
            interval_ms=1000,
        )
        self.simp_sender.progress.connect(self._on_simp_progress)
        self.simp_sender.finished.connect(self._on_simp_finished)
        self.simp_sender.start()

        total = len(commands)
        self.dashboard.set_simp_status(f"SIMP TX: 0 / {total}")
        logger.info("SimpSender started: %d commands from %s", total, self.simp_file)

    def _stop_simp(self):
        if self.simp_sender:
            self.simp_sender.stop()
            self.simp_sender = None
        self.dashboard.set_simp_status("")

    def _on_simp_progress(self, sent: int, total: int):
        self.dashboard.set_simp_status(f"SIMP TX: {sent} / {total}")

    def _on_simp_finished(self):
        self.dashboard.set_simp_status("SIMP TX: COMPLETE")
        self.simp_sender = None
        logger.info("SimpSender finished all commands")

    # -----------------------------------------------------------------------
    # TX routing - all button commands go through here to SerialWorker
    # -----------------------------------------------------------------------

    def _on_command_send(self, cmd: str):
        logger.info("TX: %s", cmd)
        if self.serial_worker:
            self.serial_worker.send_command(cmd)
        else:
            logger.warning("TX dropped - no serial worker active: %s", cmd)

    # -----------------------------------------------------------------------
    # Error handling
    # -----------------------------------------------------------------------

    def _on_parse_error(self, raw: str):
        logger.warning("Parse error: %s", raw)

    # -----------------------------------------------------------------------
    # Shutdown
    # -----------------------------------------------------------------------

    def shutdown(self):
        logger.info("Shutting down...")
        self._stop_simp()
        self._stop_serial()
        self.data_logger.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.Window,          QColor(255, 68, 68))
    palette.setColor(QPalette.WindowText,      Qt.black)
    palette.setColor(QPalette.Base,            QColor(255, 255, 255))
    palette.setColor(QPalette.AlternateBase,   QColor(255, 255, 255))
    palette.setColor(QPalette.Text,            Qt.black)
    palette.setColor(QPalette.Button,          QColor(204, 204, 204))
    palette.setColor(QPalette.ButtonText,      Qt.black)
    palette.setColor(QPalette.Highlight,       QColor(255, 68, 68))
    palette.setColor(QPalette.HighlightedText, Qt.white)
    app.setPalette(palette)

    dialog = StartupDialog()
    if dialog.exec_() != QDialog.Accepted:
        sys.exit(0)

    port      = dialog.selected_port or config.PORT
    simp_file = dialog.selected_simp
    csv_file  = getattr(dialog, "selected_csv", None)
    speed     = getattr(dialog, "selected_speed", 1.0)

    station = GroundStation(app, port=port, simp_file=simp_file,
                            playback_csv=csv_file, playback_speed=speed)
    app.aboutToQuit.connect(station.shutdown)

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()