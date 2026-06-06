"""
PlaybackWorker — reads a telemetry CSV and emits packets at 1 Hz.
Drop-in replacement for SerialWorker in main.py for log replay.

Emits the same Qt signals as SerialWorker so the dashboard needs
zero changes.  Speed can be increased for fast-forward.
"""

import csv
import logging
import time

from PyQt5.QtCore import QThread, pyqtSignal

from data_parser import parse_packet
from config import FIELDS

logger = logging.getLogger(__name__)

# CSV has 28 cols (CMD_ECHO_BLANK stripped). FIELDS has 29 (includes it).
# We need to map CSV headers → packet dict directly, then fill the blank.
CSV_FIELDS = [f for f in FIELDS if f != "CMD_ECHO_BLANK"]


class PlaybackWorker(QThread):
    """
    Reads a telemetry CSV row by row and emits one packet per second.

    Signals match SerialWorker exactly so GroundStation wiring is unchanged:
        packet_received(dict)
        raw_line_received(str)
        connection_status(bool)
        parse_error(str)

    Usage:
        worker = PlaybackWorker(csv_path="logs/fake_flight_....csv", speed=1.0)
        worker.packet_received.connect(dashboard.update_display)
        worker.start()
    """

    packet_received   = pyqtSignal(dict)
    raw_line_received = pyqtSignal(str)
    connection_status = pyqtSignal(bool)
    parse_error       = pyqtSignal(str)

    # Extra signal specific to playback — (current_row, total_rows)
    playback_progress = pyqtSignal(int, int)

    def __init__(self, csv_path: str, speed: float = 1.0, parent=None):
        super().__init__(parent)
        self.csv_path = csv_path
        self.speed    = speed       # 1.0 = realtime, 2.0 = 2x, etc.
        self._running = False

    def stop(self):
        self._running = False
        self.wait(3000)

    # Stub so GroundStation can call send_command without crashing
    def send_command(self, cmd: str) -> None:
        logger.debug("Playback: TX ignored: %s", cmd)

    def run(self):
        self._running = True

        try:
            rows = self._load_csv()
        except Exception as exc:
            logger.error("Playback: failed to load CSV: %s", exc)
            self.connection_status.emit(False)
            return

        if not rows:
            logger.error("Playback: CSV is empty")
            self.connection_status.emit(False)
            return

        total = len(rows)
        logger.info("Playback: loaded %d rows from %s", total, self.csv_path)
        self.connection_status.emit(True)

        interval = 1.0 / self.speed

        for i, row in enumerate(rows):
            if not self._running:
                break

            # Build the packet dict from CSV row
            packet = {}
            for field in CSV_FIELDS:
                packet[field] = row.get(field, "")

            # Re-insert the blank field (always empty in CSV)
            packet["CMD_ECHO_BLANK"] = ""

            # Run through the same type-casting as the real parser
            # by re-serialising to a comma string and calling parse_packet.
            # This ensures FLOAT_FIELDS / INT_FIELDS / RANGE_CHECKS all apply.
            raw_str = ",".join(str(packet.get(f, "")) for f in FIELDS)
            self.raw_line_received.emit(raw_str)

            parsed = parse_packet(raw_str)
            if parsed is not None:
                self.packet_received.emit(parsed)
            else:
                # Fall back to emitting the raw dict so display still updates
                # (can happen if a value is out of range and whole row fails)
                logger.warning("Playback: parse_packet returned None at row %d", i)
                self.parse_error.emit(raw_str)

            self.playback_progress.emit(i + 1, total)

            # Sleep until next packet, minus time spent processing
            time.sleep(interval)

        self.connection_status.emit(False)
        logger.info("Playback: finished")

    def _load_csv(self) -> list[dict]:
        with open(self.csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return [row for row in reader]