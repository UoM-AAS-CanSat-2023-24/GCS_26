"""
SIMP Sender - reads the competition SIMP pressure command file and transmits
one command per second over serial during simulation mode.

The CanSat receives these pressure values and responds with normal telemetry
packets. SerialWorker continues reading RX entirely unchanged.

File format (from competition spec):
  - Lines starting with or containing # are comments - strip everything after #
  - Blank lines are ignored
  - $ is replaced with TEAM_ID
  - Each remaining line is a complete CMD string e.g. CMD,$,SIMP,93948

This worker does NOT touch received data at all - it only writes to the
serial TX queue provided by SerialWorker.
"""

import logging
import time

from config import TEAM_ID

# Guard Qt import so tests work without a display
try:
    from PyQt5.QtCore import QThread, pyqtSignal
    _QT_AVAILABLE = True
except ImportError:
    import threading
    class QThread(threading.Thread):  # type: ignore
        def start(self): threading.Thread.start(self)
        def wait(self, ms=0): self.join(ms / 1000)
    def pyqtSignal(*args):  # type: ignore
        return None
    _QT_AVAILABLE = False

logger = logging.getLogger(__name__)


def load_simp_file(filepath: str) -> list[str]:
    """
    Parse a SIMP command file into a list of ready-to-send command strings.

    Rules applied:
      - Strip everything after # (comments)
      - Skip blank lines
      - Replace $ with TEAM_ID
      - Return only non-empty lines after processing

    Args:
        filepath: Path to the .txt SIMP command file

    Returns:
        List of command strings ready to transmit, e.g.
        ["CMD,1059,SIMP,93948", "CMD,1059,SIMP,93949", ...]

    Raises:
        FileNotFoundError: if filepath does not exist
        ValueError: if no valid commands found in file

    Examples:
        >>> cmds = load_simp_file("cansat_2023_simp.txt")
        >>> cmds[0]
        'CMD,1059,SIMP,93948'
    """
    commands = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line_num, raw_line in enumerate(f, start=1):
            # Strip comment - everything from # onwards
            if "#" in raw_line:
                raw_line = raw_line[:raw_line.index("#")]

            line = raw_line.strip()

            # Skip blank lines
            if not line:
                continue

            # Replace $ placeholder with team ID
            line = line.replace("$", str(TEAM_ID))

            commands.append(line)
            logger.debug("SIMP file line %d: %s", line_num, line)

    if not commands:
        raise ValueError(f"No valid SIMP commands found in {filepath}")

    logger.info("Loaded %d SIMP commands from %s", len(commands), filepath)
    return commands


class SimpSender(QThread):
    """
    Transmits SIMP pressure commands at 1 Hz by pushing them into
    SerialWorker's TX queue.

    Does not interact with RX data at all - SerialWorker handles that
    independently and continues operating normally during sim mode.

    Signals:
        progress(int, int): (current_index, total) emitted after each send
        finished():         emitted when all commands have been sent
        started_sig():      emitted when transmission begins

    Usage:
        commands = load_simp_file("cansat_2023_simp.txt")
        sender = SimpSender(commands, serial_worker)
        sender.progress.connect(my_progress_slot)
        sender.finished.connect(my_finished_slot)
        sender.start()
        ...
        sender.stop()   # can be called at any time to abort
    """

    progress    = pyqtSignal(int, int)   # (sent_count, total)
    finished    = pyqtSignal()
    started_sig = pyqtSignal()

    def __init__(self, commands: list[str], serial_worker, interval_ms: int = 1000, parent=None):
        super().__init__(parent)
        self._commands = commands
        self._serial_worker = serial_worker
        self._interval_ms = interval_ms
        self._running = False

    def stop(self) -> None:
        """Abort transmission. Safe to call from any thread."""
        self._running = False
        self.wait(3000)

    def run(self) -> None:
        self._running = True
        total = len(self._commands)
        self.started_sig.emit()
        logger.info("SimpSender starting: %d commands at %d ms interval", total, self._interval_ms)

        for index, cmd in enumerate(self._commands):
            if not self._running:
                logger.info("SimpSender aborted at command %d / %d", index, total)
                return

            self._serial_worker.send_command(cmd)
            logger.debug("SIMP TX [%d/%d]: %s", index + 1, total, cmd)

            if _QT_AVAILABLE:
                self.progress.emit(index + 1, total)

            # Interruptible sleep
            interval_s = self._interval_ms / 1000.0
            deadline = time.monotonic() + interval_s
            while self._running and time.monotonic() < deadline:
                time.sleep(0.05)

        logger.info("SimpSender finished: all %d commands sent", total)
        if _QT_AVAILABLE:
            self.finished.emit()
        self._running = False
