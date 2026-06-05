"""
Flight Control Dashboard GUI.
Receives packet dicts via update_display() - no serial/sim logic here.
All TX commands are emitted as the command_send signal so main.py
can route them to the active worker.
"""

import io
import logging
import time
from datetime import datetime, timezone
from collections import deque

import folium
import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QPalette, QColor
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QInputDialog,
    QLabel, QMainWindow, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
    QFileDialog, QMessageBox,
)

import config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stylesheet constants
# ---------------------------------------------------------------------------

MAIN_STYLE = """
QMainWindow { background-color: #ff4444; }
QLabel      { color: #000000; font-size: 14px; }
QPushButton {
    background-color: #cccccc; color: #000000;
    border: 2px solid #000000; padding: 8px;
    border-radius: 4px; font-size: 18px; font-weight: bold;
}
QPushButton:hover   { background-color: #bbbbbb; }
QPushButton:pressed { background-color: #ff4444; }
QPushButton:checked { background-color: #ff4444; color: #000000; border: 2px solid #000000; }
QFrame { background-color: #ffffff; border: 2px solid #000000; border-radius: 6px; }
"""

BTN_STYLE = """
QPushButton {
    background-color: #cccccc; color: #000000;
    border: 2px solid #000000; padding: 12px;
    border-radius: 4px; font-size: 18px; font-weight: bold;
}
QPushButton:hover   { background-color: #bbbbbb; }
QPushButton:pressed { background-color: #ff4444; }
QPushButton:checked { background-color: #ff4444; color: #000000; border: 2px solid #000000; }
"""

MINI_BTN_STYLE = """
QPushButton {
    background-color: #cccccc; color: #000000;
    border: 2px solid #000000; padding: 6px;
    border-radius: 4px; font-size: 16px; font-weight: bold; min-width: 40px;
}
QPushButton:hover   { background-color: #bbbbbb; }
QPushButton:pressed { background-color: #ff4444; }
QPushButton:checked { background-color: #ff4444; color: #000000; border: 2px solid #000000; }
"""


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

class DashboardGUI(QMainWindow):
    """
    Main window.  Data flows in via update_display(packet_dict).
    TX commands flow out via the command_send signal.
    """

    # Emitted whenever a button wants to send a TX command
    command_send = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("CanSat Ground Station")
        self.setGeometry(100, 100, 1400, 900)
        self.setStyleSheet(MAIN_STYLE)

        # --- Internal state ---
        self._last_packet_count: int | None = None
        self._lost_packets = 0
        self._rx_packets = 0
        self._last_rx_time: float | None = None
        self._mission_start_time: str | None = None

        # Graph buffers: deque of (elapsed_seconds, value)
        self._graph_buffers = {
            "ALTITUDE":    (deque(maxlen=config.GRAPH_BUFFER), deque(maxlen=config.GRAPH_BUFFER)),
            "ACCEL_R":     (deque(maxlen=config.GRAPH_BUFFER), deque(maxlen=config.GRAPH_BUFFER)),
            "GYRO_R":      (deque(maxlen=config.GRAPH_BUFFER), deque(maxlen=config.GRAPH_BUFFER)),
            "VOLTAGE":     (deque(maxlen=config.GRAPH_BUFFER), deque(maxlen=config.GRAPH_BUFFER)),
            "CURRENT":     (deque(maxlen=config.GRAPH_BUFFER), deque(maxlen=config.GRAPH_BUFFER)),
        }

        # Map state
        self._current_lat = config.DEFAULT_LAT
        self._current_lon = config.DEFAULT_LON
        self._map_initialised = False
        self._flight_path: list[list[float]] = []

        # Data dump label references: field_name -> QLabel (value column)
        self._data_labels: dict[str, QLabel] = {}

        # Build UI
        self._build_ui()

        # Timer: update "LAST: Xs" display every second
        self._last_rx_timer = QTimer(self)
        self._last_rx_timer.timeout.connect(self._tick_last_rx)
        self._last_rx_timer.start(1000)

    # -----------------------------------------------------------------------
    # Public API called by main.py
    # -----------------------------------------------------------------------

    def update_display(self, packet: dict) -> None:
        """
        Called from the main thread (via signal) for every valid received packet.
        Updates all GUI elements.
        """
        self._rx_packets += 1
        self._last_rx_time = time.monotonic()

        # Packet loss tracking
        pcount = packet.get("PACKET_COUNT")
        if pcount is not None and self._last_packet_count is not None:
            gap = pcount - self._last_packet_count - 1
            if gap > 0:
                self._lost_packets += gap
        if pcount is not None:
            self._last_packet_count = pcount

        # Mission time reference
        if self._mission_start_time is None and packet.get("MISSION_TIME"):
            self._mission_start_time = packet["MISSION_TIME"]

        # Elapsed seconds for graphs (based on packet count as proxy)
        elapsed = self._rx_packets  # seconds at ~1 Hz

        # --- Centre info labels ---
        state = packet.get("STATE") or "---"
        self._state_label.setText(state)
        self._state_label.setStyleSheet(
            f"color: {self._state_colour(state)}; font-weight: bold;"
        )

        mission_time = packet.get("MISSION_TIME") or "hh:mm:ss"
        self._time_label.setText(f"MISSION TIME: {mission_time}")

        self._update_rx_label()

        alt = packet.get("ALTITUDE")
        lat = packet.get("GPS_LATITUDE")
        lon = packet.get("GPS_LONGITUDE")
        alt_str = f"{alt:.1f} m" if alt is not None else "---"
        lat_str = f"{lat:.4f}" if lat is not None else "---"
        lon_str = f"{lon:.4f}" if lon is not None else "---"
        self._telemetry_label.setText(f"ALT: {alt_str}    GPS: {lat_str}, {lon_str}")

        accel_r = packet.get("ACCEL_R")
        current = packet.get("CURRENT")
        accel_str = f"{accel_r:.2f} m/s²" if accel_r is not None else "---"
        current_str = f"{current:.2f} A" if current is not None else "---"
        self._speed_accel_label.setText(f"ACCEL: {accel_str}    CURRENT: {current_str}")

        # --- Data dump panel ---
        self._update_data_labels(packet)

        # --- Graphs ---
        self._push_graph("ALTITUDE", elapsed, packet.get("ALTITUDE"))
        self._push_graph("ACCEL_R",  elapsed, packet.get("ACCEL_R"))
        self._push_graph("GYRO_R",   elapsed, packet.get("GYRO_R"))
        self._push_graph("VOLTAGE",  elapsed, packet.get("VOLTAGE"))
        self._push_graph("CURRENT",  elapsed, packet.get("CURRENT"))
        self._redraw_graphs()

        # --- Map ---
        if lat is not None and lon is not None:
            self._current_lat = lat
            self._current_lon = lon
            self._flight_path.append([lat, lon])
            self._update_map_js(lat, lon)

    def set_simp_status(self, text: str) -> None:
        """Show SIMP TX progress in the connection label area."""
        if text:
            self._simp_label.setText(text)
            self._simp_label.setVisible(True)
        else:
            self._simp_label.setVisible(False)

    def set_sim_mode(self, active: bool) -> None:
        """Called by main.py when sim mode changes."""
        if active:
            self.setWindowTitle("CanSat Ground Station  [SIM MODE]")
        else:
            self.setWindowTitle("CanSat Ground Station")

    def set_connected(self, connected: bool) -> None:
        """Called by main.py when serial connection status changes."""
        status = "CONNECTED" if connected else "DISCONNECTED"
        color = "#008800" if connected else "#cc0000"
        self._connection_label.setText(status)
        self._connection_label.setStyleSheet(f"color: {color}; font-weight: bold;")

    # -----------------------------------------------------------------------
    # UI construction
    # -----------------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QGridLayout(central)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        for col in range(4):
            main_layout.setColumnStretch(col, 1)
        main_layout.setRowStretch(0, 1)
        main_layout.setRowStretch(1, 1)

        self._create_left_graphs(main_layout)
        self._create_map_panel(main_layout)

        # Bottom right: centre info + buttons stacked left, data dump right
        bottom = QWidget()
        bl = QHBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(10)

        left_stack = QWidget()
        ls_layout = QVBoxLayout(left_stack)
        ls_layout.setContentsMargins(0, 0, 0, 0)
        ls_layout.setSpacing(10)

        self._center_frame   = self._create_center_info_widget()
        self._buttons_frame  = self._create_control_buttons_widget()
        self._data_frame     = self._create_data_dump_widget()

        ls_layout.addWidget(self._center_frame)
        ls_layout.addWidget(self._buttons_frame)

        bl.addWidget(left_stack)
        bl.addWidget(self._data_frame)

        main_layout.addWidget(bottom, 1, 2, 1, 2)

    # --- Graphs ---

    def _create_left_graphs(self, main_layout):
        frame, layout = self._make_section_frame("Flight Data Graphs")

        def make_graph():
            g = pg.PlotWidget()
            g.setBackground("#ffffff")
            g.showGrid(x=True, y=True, alpha=0.2)
            for axis in ("left", "bottom"):
                g.getAxis(axis).setPen(pg.mkPen(color="#000000", width=2))
                g.getAxis(axis).setTextPen(pg.mkPen(color="#000000"))
            return g

        self._graph_alt     = make_graph()
        self._graph_accel   = make_graph()
        self._graph_gyro    = make_graph()
        self._graph_voltage = make_graph()
        self._graph_current = make_graph()

        self._graph_alt.setLabel("left", "Altitude (m)")
        self._graph_accel.setLabel("left", "Accel (m/s²)")
        self._graph_gyro.setLabel("left", "Rotation (°/s)")
        self._graph_voltage.setLabel("left", "Voltage (V)")
        self._graph_current.setLabel("left", "Current (A)")
        self._graph_current.setLabel("bottom", "Time (s)")

        # Shared x-axis
        for g in (self._graph_accel, self._graph_gyro,
                  self._graph_voltage, self._graph_current):
            g.setXLink(self._graph_alt)

        # Hide x tick labels on all except bottom graph
        for g in (self._graph_alt, self._graph_accel,
                  self._graph_gyro, self._graph_voltage):
            g.getAxis("bottom").setStyle(showValues=False)

        # Plot data items (so we update in-place rather than re-plotting)
        pen = pg.mkPen(color="#ff4444", width=2)
        self._plot_alt     = self._graph_alt.plot([], [], pen=pen)
        self._plot_accel   = self._graph_accel.plot([], [], pen=pen)
        self._plot_gyro    = self._graph_gyro.plot([], [], pen=pen)
        self._plot_voltage = self._graph_voltage.plot([], [], pen=pen)
        self._plot_current = self._graph_current.plot([], [], pen=pen)

        for g in (self._graph_alt, self._graph_accel, self._graph_gyro,
                  self._graph_voltage, self._graph_current):
            layout.addWidget(g)

        main_layout.addWidget(frame, 0, 0, 2, 2)

    # --- Map ---

    def _create_map_panel(self, main_layout):
        frame, layout = self._make_section_frame("Map")
        self._map_view = QWebEngineView()
        self._map_view.setMinimumHeight(350)
        self._init_map()
        layout.addWidget(self._map_view)
        main_layout.addWidget(frame, 0, 2, 1, 2)

    def _init_map(self):
        """Build initial folium map and load it once into the WebEngineView."""
        m = folium.Map(
            location=[self._current_lat, self._current_lon],
            zoom_start=15,
            tiles=config.TILE_PATH,
            attr=config.TILE_ATTRIBUTION,
        )

        # Marker - we'll move it via JS
        folium.Marker(
            [self._current_lat, self._current_lon],
            popup="Current Position",
            icon=folium.Icon(color="red", icon="info-sign"),
        ).add_to(m)

        # Give the map and marker JS variable names so we can update them
        # Inject JS after the map is built to expose `map` and `marker`
        map_js = """
        <script>
        // Wait for Leaflet to initialise then expose globals
        window.addEventListener('load', function() {
            // The folium map object is stored on the first map div
            var mapDivId = Object.keys(window).find(k => k.startsWith('map_'));
            if (mapDivId) {
                window._cansatMap = window[mapDivId];
            }
            // Find the marker layer (first CircleMarker/Marker)
            window._cansatMap.eachLayer(function(layer) {
                if (layer instanceof L.Marker) {
                    window._cansatMarker = layer;
                }
            });
            // Create flight path polyline
            window._cansatPath = L.polyline([], {color: 'red', weight: 2}).addTo(window._cansatMap);
        });
        </script>
        """

        data = io.BytesIO()
        m.save(data, close_file=False)
        html = data.getvalue().decode()
        # Inject our JS just before </body>
        html = html.replace("</body>", map_js + "</body>")
        self._map_view.setHtml(html)
        self._map_initialised = True

    def _update_map_js(self, lat: float, lon: float):
        """Update marker and flight path via JavaScript - no full reload."""
        if not self._map_initialised:
            return

        js = f"""
        if (window._cansatMarker) {{
            window._cansatMarker.setLatLng([{lat}, {lon}]);
        }}
        if (window._cansatMap) {{
            window._cansatMap.setView([{lat}, {lon}]);
        }}
        if (window._cansatPath) {{
            window._cansatPath.addLatLng([{lat}, {lon}]);
        }}
        """
        self._map_view.page().runJavaScript(js)

    # --- Centre info ---

    def _create_center_info_widget(self):
        frame = QFrame()
        frame.setStyleSheet("""
            QFrame { background-color: #ffffff; border: 0px; border-radius: 6px; }
        """)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        self._state_label = QLabel("---")
        self._state_label.setFont(QFont("Arial", 48, QFont.Bold))
        self._state_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._state_label)

        self._time_label = QLabel("MISSION TIME: hh:mm:ss")
        self._time_label.setFont(QFont("Arial", 24, QFont.Bold))
        self._time_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._time_label)

        self._rx_label = QLabel("RX: 0     LOST: 0     LAST: ---")
        self._rx_label.setFont(QFont("Arial", 16))
        self._rx_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._rx_label)

        self._telemetry_label = QLabel("ALT: ---    GPS: ---, ---")
        self._telemetry_label.setFont(QFont("Arial", 16))
        self._telemetry_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._telemetry_label)

        self._speed_accel_label = QLabel("ACCEL: ---    CURRENT: ---")
        self._speed_accel_label.setFont(QFont("Arial", 16))
        self._speed_accel_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._speed_accel_label)

        self._connection_label = QLabel("DISCONNECTED")
        self._connection_label.setFont(QFont("Arial", 14, QFont.Bold))
        self._connection_label.setStyleSheet("color: #cc0000; font-weight: bold;")
        self._connection_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._connection_label)

        self._simp_label = QLabel("")
        self._simp_label.setFont(QFont("Arial", 13, QFont.Bold))
        self._simp_label.setStyleSheet("color: #ff8800; font-weight: bold;")
        self._simp_label.setAlignment(Qt.AlignCenter)
        self._simp_label.setVisible(False)
        layout.addWidget(self._simp_label)

        layout.addStretch()
        return frame

    # --- Data dump ---

    def _create_data_dump_widget(self):
        frame = QFrame()
        layout = QGridLayout(frame)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)
        for c in range(4):
            layout.setColumnStretch(c, 1)

        sections_left = [
            ("IMU", [
                ("ACCEL R", "ACCEL_R"), ("ACCEL P", "ACCEL_P"), ("ACCEL Y", "ACCEL_Y"),
                ("GYRO R",  "GYRO_R"),  ("GYRO P",  "GYRO_P"),  ("GYRO Y",  "GYRO_Y"),
            ]),
            ("GPS", [
                ("TIME",  "GPS_TIME"), ("ALT",  "GPS_ALTITUDE"), ("LAT", "GPS_LATITUDE"),
                ("LONG",  "GPS_LONGITUDE"), ("SATS", "GPS_SATS"),
            ]),
        ]

        sections_right = [
            ("POWER", [
                ("SOC",     "MAIN_SOC"), ("POWER",   "BUS_POWER"),
                ("VOLTAGE", "VOLTAGE"),  ("CURRENT", "CURRENT"),
            ]),
            ("DEVICES", [
                ("CAM",   "ACTIVE_CAMERA"), ("MATEK", "MATEK"),
            ]),
            ("SENSOR", [
                ("TEMP",  "TEMPERATURE"), ("PRESS", "PRESSURE"), ("ALT", "ALTITUDE"),
            ]),
            ("FLIGHT", [
                ("STATE",  "STATE"), ("SUBSTATE", "SUBSTATE"), ("MODE", "MODE"),
                ("MECHS",  "ACTIVE_MECHS"), ("PKT", "PACKET_COUNT"),
            ]),
        ]

        header_style = (
            "background-color: #ffcccc; color: #000000; "
            "padding: 4px; border-radius: 3px;"
        )

        def add_section(sections, col_offset, row_start=0):
            row = row_start
            for title, items in sections:
                lbl = QLabel(title)
                lbl.setFont(QFont("Arial", 9, QFont.Bold))
                lbl.setStyleSheet(header_style)
                layout.addWidget(lbl, row, col_offset, 1, 2)
                row += 1
                for display_name, field_key in items:
                    name_lbl = QLabel(display_name)
                    name_lbl.setFont(QFont("Arial", 8, QFont.Bold))
                    name_lbl.setStyleSheet("color: #000000;")

                    val_lbl = QLabel("---")
                    val_lbl.setFont(QFont("Arial", 8))
                    val_lbl.setStyleSheet("color: #666666;")
                    val_lbl.setAlignment(Qt.AlignRight)

                    layout.addWidget(name_lbl, row, col_offset)
                    layout.addWidget(val_lbl, row, col_offset + 1)
                    self._data_labels[field_key] = val_lbl
                    row += 1
            return row

        add_section(sections_left,  col_offset=0)
        add_section(sections_right, col_offset=2)

        return frame

    # --- Control buttons ---

    def _create_control_buttons_widget(self):
        frame = QFrame()
        layout = QGridLayout(frame)
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)

        btn_tx          = self._make_btn("TX",           checkable=True)
        btn_sleep       = self._make_btn("SLEEP",        checkable=True)
        btn_set_utc     = self._make_btn("SET UTC",      checkable=False)
        btn_set_alt     = self._make_btn("SET ALT",      checkable=False)
        btn_sim_enable  = self._make_btn("SIM\nENABLE",  checkable=True)
        btn_sim_act     = self._make_btn("SIM\nACTIVATE", checkable=False)
        btn_arm         = self._make_btn("ARM",           checkable=True)

        # --- TX toggle ---
        def on_tx(checked):
            state = "ON" if checked else "OFF"
            self.command_send.emit(f"CMD,{config.TEAM_ID},CX,{state}")

        btn_tx.toggled.connect(on_tx)

        # --- SLEEP (CX OFF) ---
        def on_sleep(checked):
            self.command_send.emit(f"CMD,{config.TEAM_ID},CX,OFF")

        btn_sleep.toggled.connect(on_sleep)

        # --- SET UTC ---
        def on_set_utc():
            utc_now = datetime.now(timezone.utc).strftime("%H:%M:%S")
            self.command_send.emit(f"CMD,{config.TEAM_ID},ST,{utc_now}")
            logger.info("SET UTC sent: %s", utc_now)

        btn_set_utc.clicked.connect(on_set_utc)

        # --- SET ALT (calibrate to zero) ---
        def on_set_alt():
            self.command_send.emit(f"CMD,{config.TEAM_ID},CAL")

        btn_set_alt.clicked.connect(on_set_alt)

        # --- SIM ENABLE ---
        def on_sim_enable(checked):
            mode = "ENABLE" if checked else "DISABLE"
            self.command_send.emit(f"CMD,{config.TEAM_ID},SIM,{mode}")
            # Signal main.py to start/stop SimWorker via a second emit
            # main.py connects this button's toggled signal directly
            # (see main.py wiring)

        btn_sim_enable.toggled.connect(on_sim_enable)
        self._btn_sim_enable   = btn_sim_enable   # exposed for main.py
        self._btn_sim_activate = btn_sim_act      # exposed for main.py

        # SIM ACTIVATE handled entirely by main.py via _btn_sim_activate reference

        # --- ARM ---
        def on_arm(checked):
            state = "ON" if checked else "OFF"
            reply = QMessageBox.question(
                self, "Confirm ARM",
                f"Are you sure you want to ARM {'ON' if checked else 'OFF'}?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self.command_send.emit(f"CMD,{config.TEAM_ID},ARM,{state}")
            else:
                btn_arm.setChecked(not checked)   # revert toggle

        btn_arm.toggled.connect(on_arm)

        # Grid layout: 2-wide
        for i, btn in enumerate([btn_tx, btn_sleep, btn_set_utc,
                                  btn_set_alt, btn_sim_enable, btn_sim_act]):
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            layout.addWidget(btn, i // 2, i % 2)

        next_row = 3
        btn_arm.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(btn_arm, next_row, 0, 1, 2)

        # --- MECH tile ---
        mech_frame = self._create_mech_widget()
        layout.addWidget(mech_frame, next_row + 1, 0, 1, 2)

        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)
        return frame

    def _create_mech_widget(self):
        frame = QFrame()
        ml = QVBoxLayout(frame)
        ml.setContentsMargins(6, 6, 6, 6)
        ml.setSpacing(6)

        title = QLabel("MECH")
        title.setFont(QFont("Arial", 12, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        ml.addWidget(title)

        row_layout = QHBoxLayout()
        row_layout.setSpacing(6)

        for num in range(1, 5):
            btn = QPushButton(str(num))
            btn.setStyleSheet(MINI_BTN_STYLE)
            btn.setCheckable(True)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

            def on_mech(checked, n=num):
                code  = config.MECH_CODES[n]
                state = "ON" if checked else "OFF"
                self.command_send.emit(
                    f"CMD,{config.TEAM_ID},MEC,{code},{state}"
                )

            btn.toggled.connect(on_mech)
            row_layout.addWidget(btn)

        ml.addLayout(row_layout)
        return frame

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _state_colour(self, state: str) -> str:
        """Return a colour hex string for each flight state."""
        return {
            "LAUNCH_PAD":      "#0055cc",   # blue    - sitting on pad
            "ASCENT":          "#cc6600",   # orange  - climbing
            "APOGEE":          "#cc00cc",   # purple  - peak
            "DESCENT":         "#cc6600",   # orange  - falling
            "PROBE_RELEASE":   "#cc0000",   # red     - container released
            "PAYLOAD_RELEASE": "#cc0000",   # red     - egg released
            "LANDED":          "#008800",   # green   - safe on ground
        }.get(state, "#000000")             # black   - unknown / ---

    def _make_btn(self, text: str, checkable: bool = False) -> QPushButton:
        btn = QPushButton(text)
        btn.setStyleSheet(BTN_STYLE)
        btn.setCheckable(checkable)
        return btn

    def _make_section_frame(self, title: str):
        frame = QFrame()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 10, 10, 10)
        lbl = QLabel(title)
        lbl.setFont(QFont("Arial", 13, QFont.Bold))
        lbl.setStyleSheet("color: #000000; margin-bottom: 5px;")
        layout.addWidget(lbl)
        return frame, layout

    def _update_rx_label(self):
        if self._last_rx_time is not None:
            since = int(time.monotonic() - self._last_rx_time)
            last_str = f"{since}s"
        else:
            last_str = "---"
        self._rx_label.setText(
            f"RX: {self._rx_packets}     "
            f"LOST: {self._lost_packets}     "
            f"LAST: {last_str}"
        )

    def _tick_last_rx(self):
        """Called by QTimer every second to keep LAST: Xs display current."""
        self._update_rx_label()

    def _update_data_labels(self, packet: dict):
        for field, label in self._data_labels.items():
            val = packet.get(field)
            if val is None:
                label.setText("---")
                label.setStyleSheet("color: #cc0000;")   # red for missing
            else:
                label.setText(str(val))
                label.setStyleSheet("color: #006600;")   # green for present

    def _push_graph(self, key: str, x: float, y):
        """Push a value to a graph buffer, skipping None."""
        if y is None:
            return
        xs, ys = self._graph_buffers[key]
        xs.append(x)
        ys.append(y)

    def _redraw_graphs(self):
        mapping = {
            "ALTITUDE": self._plot_alt,
            "ACCEL_R":  self._plot_accel,
            "GYRO_R":   self._plot_gyro,
            "VOLTAGE":  self._plot_voltage,
            "CURRENT":  self._plot_current,
        }
        for key, plot_item in mapping.items():
            xs, ys = self._graph_buffers[key]
            if xs:
                plot_item.setData(list(xs), list(ys))