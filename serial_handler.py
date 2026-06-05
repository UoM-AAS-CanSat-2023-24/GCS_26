"""
Serial I/O worker running in a background QThread.
Emits parsed packets and raw lines as Qt signals.
TX commands are queued thread-safely and drained on each loop iteration.
"""

import logging
import queue
import time

from PyQt5.QtCore import QThread, pyqtSignal

from data_parser import parse_packet

logger = logging.getLogger(__name__)

# Guard import so the module can be imported in unit tests without pyserial
try:
    import serial
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False
    logger.warning("pyserial not installed - SerialWorker will not function")


class SerialWorker(QThread):
    """
    Background thread that:
      - Reads lines from a serial port at BAUD_RATE
      - Parses each line with data_parser.parse_packet()
      - Emits packet_received for valid packets
      - Emits raw_line_received for every line (valid or not)
      - Emits connection_status when the port opens/closes/errors
      - Drains a send queue on each loop so TX is thread-safe

    Usage:
        worker = SerialWorker(port="COM3", baud=9600)
        worker.packet_received.connect(my_slot)
        worker.start()
        ...
        worker.send_command("CMD,1059,CX,ON")
        worker.stop()
    """

    packet_received    = pyqtSignal(dict)
    raw_line_received  = pyqtSignal(str)
    connection_status  = pyqtSignal(bool)   # True = connected, False = disconnected
    parse_error        = pyqtSignal(str)    # raw line that failed to parse

    def __init__(self, port: str, baud: int, parent=None):
        super().__init__(parent)
        self.port = port
        self.baud = baud
        self._running = False
        self._tx_queue: queue.Queue[str] = queue.Queue()
        self._serial = None

    # ------------------------------------------------------------------
    # Public API (called from main thread)
    # ------------------------------------------------------------------

    def send_command(self, cmd: str) -> None:
        """
        Queue a command string for transmission.
        Thread-safe - can be called from any thread.
        A newline is appended automatically.
        """
        self._tx_queue.put(cmd)
        logger.debug("TX queued: %s", cmd)

    def stop(self) -> None:
        """Signal the thread to stop and wait for it to finish."""
        self._running = False
        self.wait(3000)   # wait up to 3 s

    # ------------------------------------------------------------------
    # QThread entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        self._running = True

        if not SERIAL_AVAILABLE:
            logger.error("pyserial not available, SerialWorker cannot run")
            self.connection_status.emit(False)
            return

        while self._running:
            try:
                self._serial = serial.Serial(
                    self.port,
                    self.baud,
                    timeout=2,
                )
                logger.info("Serial port %s opened at %d baud", self.port, self.baud)
                self.connection_status.emit(True)
                self._loop()

            except serial.SerialException as exc:
                logger.error("Serial error: %s", exc)
                self.connection_status.emit(False)
                # Retry after a short delay rather than crashing
                time.sleep(2)

            finally:
                if self._serial and self._serial.is_open:
                    self._serial.close()
                self.connection_status.emit(False)

    # ------------------------------------------------------------------
    # Internal read/write loop
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        """Main read loop - runs until _running is False or port errors."""
        while self._running:
            # --- Drain TX queue first ---
            while not self._tx_queue.empty():
                try:
                    cmd = self._tx_queue.get_nowait()
                    self._write(cmd)
                except queue.Empty:
                    break

            # --- Read one line ---
            try:
                raw_bytes = self._serial.readline()
                if not raw_bytes:
                    # Timeout - no data, loop again
                    continue

                raw = raw_bytes.decode("utf-8", errors="replace").strip()
                if not raw:
                    continue

                self.raw_line_received.emit(raw)

                packet = parse_packet(raw)
                if packet is not None:
                    self.packet_received.emit(packet)
                else:
                    self.parse_error.emit(raw)

            except serial.SerialException as exc:
                logger.error("Read error: %s", exc)
                break   # Exit loop; outer while will attempt reconnect

    def _write(self, cmd: str) -> None:
        """Write a command to serial. Newline appended."""
        try:
            data = (cmd + "\n").encode("utf-8")
            self._serial.write(data)
            logger.info("TX sent: %s", cmd)
        except serial.SerialException as exc:
            logger.error("Write error: %s", exc)
