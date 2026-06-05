# CanSat Ground Station

PyQt5 dashboard for receiving, displaying, logging, and commanding a CanSat
over a 9600-baud serial link.

---

## File Structure

```
cansat/
├── main.py            # Entry point
├── dashboard.py       # GUI (DashboardGUI)
├── serial_handler.py  # Background QThread for serial RX/TX
├── sim_handler.py     # Background QThread that replays a CSV as fake packets
├── data_parser.py     # Parses raw packet strings → dicts
├── logger.py          # Writes validated packets to CSV log files
├── config.py          # Constants: TEAM_ID, port, field names, ranges
└── tests/
    └── test_all.py    # Unit tests 
```

---

## Dependencies

Install with pip:

```bash
pip install PyQt5 PyQtWebEngine pyqtgraph folium pyserial numpy
```

On Linux you may also need:

```bash
sudo apt install python3-pyqt5 python3-pyqt5.qtwebengine
```

---

## Running the Application

```bash
cd cansat
python main.py
```

A startup dialog will appear asking for:
- **Serial Port** — select from the dropdown or type manually (e.g. `COM3`, `/dev/ttyUSB0`)
- **Sim CSV** — optional, browse to a pre-recorded telemetry CSV for sim mode

---

## Running Unit Tests

The tests cover `data_parser`, `logger`, `sim_handler`, and `config`.
They do **not** require a serial port, display, or Qt event loop.

### With pytest (recommended)

```bash
cd cansat
pip install pytest
python -m pytest tests/ -v
```

Expected output:

```
tests/test_all.py::TestParsePacketValid::test_all_fields_present       PASSED
tests/test_all.py::TestParsePacketValid::test_altitude_float           PASSED
tests/test_all.py::TestParsePacketValid::test_cmd_echo_string          PASSED
...
tests/test_all.py::TestParseToLogRoundTrip::test_valid_packet...       PASSED

28 passed in 0.4s
```

### With unittest (no extra install)

```bash
cd cansat
python tests/test_all.py
```

### Running a specific test class

```bash
python -m pytest tests/test_all.py::TestRangeChecks -v
python -m pytest tests/test_all.py::TestDataLogger -v
```

---

## Testing the Dashboard Statically (No Serial Port)

You can run the dashboard and feed it fake data without any hardware.

### Option 1 — Sim mode via the UI

1. Create a sim CSV file (see format below)
2. `python main.py` → pick any port → browse to your sim CSV
3. In the dashboard, press **SIM ENABLE** then **SIM ACTIVATE**
4. The dashboard will display packets at 1 Hz from the CSV

### Option 2 — Static test script (no GUI event loop required)

Create `tests/static_test.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PyQt5.QtWidgets import QApplication
from dashboard import DashboardGUI
from data_parser import parse_packet

SAMPLE = (
    "1059, 13:14:02, 1025, F, ASCENT, 427.3, 21.3, 101.3, 3.7, 1.31, "
    "186, 2.0, 0.5, 1.1, 0.3, 9.5, 21:49:53, 558.0, 63.4451, 10.9050, "
    "8, CXON, ARMED, 45, 0.377, 1234, 1, GLIDER"
)

app = QApplication(sys.argv)
window = DashboardGUI()
window.show()

# Feed 10 packets with incrementing altitude
for i in range(10):
    parts = SAMPLE.split(",")
    parts[5] = f" {400 + i * 10}"   # increment ALTITUDE
    parts[2] = f" {1025 + i}"       # increment PACKET_COUNT
    packet = parse_packet(",".join(parts))
    if packet:
        window.update_display(packet)

sys.exit(app.exec_())
```

Run with:
```bash
python tests/static_test.py
```

---

## Sim CSV Format

The sim CSV must have either:
- A **header row** with field names matching `config.FIELDS` (in any order)
- **No header**, with columns in exactly the same order as `config.FIELDS`

Example row (no header):
```
1059, 13:14:02, 1025, F, ASCENT, 427.3, 21.3, 101.3, 3.7, 1.31, 186, 2.0, 0.5, 1.1, 0.3, 9.5, 21:49:53, 558.0, 63.4451, 10.9050, 8, CXON, ARMED, 45, 0.377, 1234, 1, GLIDER
```

The sim worker loops back to the start when it reaches the end of the file.

---

## Offline Map Tiles

Download tiles before launch day using one of these tools:

- **MOBAC** (Mobile Atlas Creator) — https://mobac.sourceforge.io/
  Select OpenStreetMap or a satellite provider, draw a bounding box around
  your launch/landing area, export as "OSMDroid ZIP" or raw tiles.
  Unzip so tiles are at `tiles/{z}/{x}/{y}.png`.

- **wget** (command line):
  ```bash
  # Example: download zoom levels 10-16 for a bounding box
  # Use a tile downloader script - see: https://github.com/geopandas/tilemapbase
  ```

Set `TILE_PATH` in `config.py` to the absolute path of your tile directory:
```python
TILE_PATH = "/home/user/cansat/tiles/{z}/{x}/{y}.png"
```

Recommended zoom levels to download: **10 to 16**
(16 is street-level detail; higher zoom = many more tiles)
Cover at least 10 km radius around your expected launch site.

---

## Log Files

On each run, two files are created in the `logs/` directory:

- `telemetry_YYYYMMDD_HHMMSS.csv` — validated packets, one row each, with header
- `raw_YYYYMMDD_HHMMSS.txt` — every raw serial line with timestamps,
  including lines that failed to parse

---p

## TX Commands Reference

| Button        | Command sent                          |
|---------------|---------------------------------------|
| TX (on)       | `CMD,{TEAM_ID},CX,ON`                |
| TX (off)      | `CMD,{TEAM_ID},CX,OFF`               |
| SET UTC       | `CMD,{TEAM_ID},ST,<time>` (prompted) |
| SET ALT       | `CMD,{TEAM_ID},CAL`                  |
| SIM ENABLE    | `CMD,{TEAM_ID},SIM,ENABLE/DISABLE`   |
| SIM ACTIVATE  | `CMD,{TEAM_ID},SIMP,<pressure>`      |
| ARM (on)      | `CMD,{TEAM_ID},ARM,ON`               |
| ARM (off)     | `CMD,{TEAM_ID},ARM,OFF`              |
| MECH 1        | `CMD,{TEAM_ID},MEC,1000,ON/OFF`      |
| MECH 2        | `CMD,{TEAM_ID},MEC,0200,ON/OFF`      |
| MECH 3        | `CMD,{TEAM_ID},MEC,0030,ON/OFF`      |
| MECH 4        | `CMD,{TEAM_ID},MEC,0004,ON/OFF`      |

---

## Editing TEAM_ID or Port

Edit `config.py`:
```python
TEAM_ID = 1059       # your team number
PORT    = "COM3"     # default port (can be overridden at startup dialog)
```
