"""
Logs received packets to a timestamped CSV file.
Also maintains a separate debug log for raw unparsed lines.
No Qt dependency.
"""

import csv
import logging
import os
from datetime import datetime
from config import FIELDS

logger = logging.getLogger(__name__)


class DataLogger:
    """
    Writes validated packet dicts to a CSV file, one row per packet.
    Opens files on first write so no empty files are created if nothing
    is ever received.

    Usage:
        dl = DataLogger(log_dir="logs")
        dl.log(packet_dict)
        dl.close()
    """

    def __init__(self, log_dir: str = "logs"):
        self.log_dir = log_dir
        self._ensure_dir(log_dir)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.csv_path = os.path.join(log_dir, f"telemetry_{timestamp}.csv")
        self.raw_path = os.path.join(log_dir, f"raw_{timestamp}.txt")

        self._csv_file = None
        self._csv_writer = None
        self._raw_file = None
        self._packet_count = 0

        logger.info("DataLogger initialised. CSV: %s | Raw: %s",
                    self.csv_path, self.raw_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log(self, packet: dict) -> None:
        """Write a validated packet dict to the CSV log."""
        if self._csv_file is None:
            self._open_csv()

        row = [
            "" if packet.get(f) is None else str(packet[f])
            for f in FIELDS
        ]
        self._csv_writer.writerow(row)
        # Flush every write - we can't afford to lose data at landing
        self._csv_file.flush()
        self._packet_count += 1

    def log_raw(self, raw_line: str) -> None:
        """
        Write a raw serial line to the debug log regardless of whether
        parsing succeeded.  Useful for post-flight diagnostics.
        """
        if self._raw_file is None:
            self._raw_file = open(self.raw_path, "a", encoding="utf-8")

        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._raw_file.write(f"[{timestamp}] {raw_line}\n")
        self._raw_file.flush()

    def close(self) -> None:
        """Flush and close all open log files."""
        if self._csv_file:
            self._csv_file.close()
            self._csv_file = None
            logger.info("CSV log closed. %d packets written.", self._packet_count)
        if self._raw_file:
            self._raw_file.close()
            self._raw_file = None

    @property
    def packets_logged(self) -> int:
        return self._packet_count

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _open_csv(self) -> None:
        self._csv_file = open(
            self.csv_path, "a", newline="", encoding="utf-8"
        )
        self._csv_writer = csv.writer(self._csv_file)
        # Write header only if file is new/empty
        if os.path.getsize(self.csv_path) == 0:
            self._csv_writer.writerow(FIELDS)

    @staticmethod
    def _ensure_dir(path: str) -> None:
        os.makedirs(path, exist_ok=True)
