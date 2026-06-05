# CanSat Ground Station — Getting Started

This is the ground station dashboard for your CanSat. It receives telemetry
over a serial XBee link, displays live data and graphs, logs everything to
CSV, and lets you send commands back to the CanSat.

---

## What you need before starting

- A Windows, Mac, or Linux laptop
- Python 3.10 or newer — download from https://www.python.org/downloads/
  - **Windows:** tick "Add Python to PATH" during installation
- The ground station XBee plugged into your laptop via a USB adapter
- This folder of files

---

## Step 1 — Install Python packages

Open a terminal (Windows: search "cmd" or "PowerShell", Mac/Linux: Terminal).

Navigate to this folder:

```
cd path/to/cansat
```

Install everything in one command:

```
pip install PyQt5 PyQtWebEngine pyqtgraph folium pyserial numpy
```

This only needs to be done once. It takes a minute or two.

If you get a "pip not found" error on Mac/Linux, try `pip3` instead of `pip`.

---

## Step 2 — Set your Team ID

Open `config.py` in any text editor (Notepad is fine) and change the team ID:

```python
TEAM_ID = 1079    # <-- change this to your team number
```

Save the file. That's the only thing you need to change before launch.

---

## Step 3 — Download offline map tiles

The map works offline using pre-downloaded tiles. You need to do this on a
laptop with internet **before** you go to the launch site.

1. Download MOBAC (Mobile Atlas Creator) from https://mobac.sourceforge.io/
2. Open MOBAC and select **OpenStreetMap** as the map source
3. Navigate to your launch site on the map
4. Draw a bounding box covering at least 10 km around the site
5. Set zoom levels **10 to 16**
6. Export as **"OSMDroid ZIP"**, then unzip it
7. Copy the tile folders into a folder called `tiles/` inside this cansat folder

The tile folder structure should look like:
```
cansat/
└── tiles/
    └── 15/
        └── 16123/
            └── 10987.png
```

Then open `config.py` and set the path:
```python
TILE_PATH = "tiles/{z}/{x}/{y}.png"
```

If you are somewhere with internet on the day, you can skip this step — the
map will fall back to loading tiles live from OpenStreetMap.

---

## Step 4 — Run the ground station

In your terminal, make sure you are in the cansat folder, then run:

```
python main.py
```

A small setup window appears asking for two things:

**Serial Port** — this is the COM port your XBee USB adapter is on.
- Windows: looks like `COM3`, `COM4`, etc. Check Device Manager if unsure.
- Mac/Linux: looks like `/dev/ttyUSB0` or `/dev/tty.usbserial-XXXX`

**SIMP File** — only needed for simulation mode. Leave it blank for a
normal flight. See the Simulation section below if you need it.

Click **Start**. The dashboard opens.

---

## Step 5 — Before launch checklist

Work through these in order on the day:

### 1. Enable telemetry
Press the **TX** button. It turns red when active.
The CanSat will start transmitting and you should see the RX counter
incrementing at the top of the dashboard. If nothing arrives after
10 seconds, check the XBee connection and that the CanSat is powered.

### 2. Set the UTC time
Press **SET UTC**. This reads your laptop's current UTC clock and sends it
to the CanSat automatically. The CanSat's RTC is now synchronised.

### 3. Calibrate altitude
Make sure the CanSat is sitting on the launch pad and is powered and
transmitting. Press **SET ALT**. This zeros the altitude to the launch pad
elevation. You can only do this before the CanSat is armed — the button
does nothing in any other state.

### 4. Arm the CanSat
Press **ARM**. A confirmation dialog appears — click Yes to confirm.
Once armed, individual mechanism buttons are locked out for safety.
The state machine takes over from here.

### 5. Launch
The CanSat handles everything automatically from this point:
- Detects ascent, apogee, and descent from altitude data
- Releases the container at 80% of apogee altitude
- Releases the egg at 2 m above ground
- The dashboard state label colour changes at each transition

---

## Simulation mode (pre-launch testing)

Simulation mode lets you test the full system without launching. The ground
station sends simulated pressure values to the CanSat, which runs its state
machine as if it were flying and responds with real telemetry.

You need a SIMP command file — this is a `.txt` file provided by the
competition, or you can use the example one in this folder.

1. Press **SIM ENABLE** — sends the enable command to the CanSat
2. Press **SIM ACTIVATE** — a file browser opens, select your SIMP `.txt` file
3. The ground station sends one pressure command per second
4. Watch the dashboard — the state label should cycle through all flight states
5. The SIMP progress counter shows `SIMP TX: 1 / 120` etc.
6. Press **SIM ENABLE** again to disable sim mode when done

---

## What the dashboard shows

| Panel | What it displays |
|---|---|
| Large state label | Current flight state, colour-coded |
| MISSION TIME | UTC time from the CanSat's RTC |
| RX / LOST / LAST | Packets received, packets lost, seconds since last packet |
| ALT / GPS | Current altitude AGL and GPS coordinates |
| Graphs (left) | Live altitude, acceleration, rotation, voltage, current |
| Map (top right) | Live position with flight path trail |
| Data panel (right) | All raw telemetry values |

**State colours:**
- Blue = LAUNCH_PAD
- Orange = ASCENT or DESCENT
- Purple = APOGEE
- Red = PROBE_RELEASE or PAYLOAD_RELEASE
- Green = LANDED

---

## Log files

Every session automatically saves two files in the `logs/` folder:

- `telemetry_YYYYMMDD_HHMMSS.csv` — every valid packet, one row per second
- `raw_YYYYMMDD_HHMMSS.txt` — every raw line received, timestamped

These are created the moment the first packet arrives. If no data is
received, no files are created.

---

## Troubleshooting

**Dashboard opens but RX stays at 0**
- Check the XBee USB adapter is plugged in
- Check you selected the right COM port — try the others in the dropdown
- Check the CanSat is powered and TX is enabled

**"No module named PyQt5" error**
- Run the pip install command from Step 1 again

**Map shows grey tiles**
- You are offline and tiles are not downloaded, or the TILE_PATH in
  config.py is wrong. Check the tiles folder exists and the path matches.

**SET ALT button does nothing**
- The CanSat must be in LAUNCH_PAD state and transmitting for CAL to work.
  Check the state label on the dashboard.

**Python not found**
- Make sure Python was installed with "Add to PATH" ticked.
  Try typing `python --version` in the terminal to check.

---

## Files in this folder

| File | What it does |
|---|---|
| `main.py` | Run this to start the dashboard |
| `config.py` | Your team ID, port default, field definitions |
| `dashboard.py` | The GUI layout and display logic |
| `serial_handler.py` | Reads and writes to the XBee serial port |
| `simp_sender.py` | Sends SIMP pressure commands during sim mode |
| `data_parser.py` | Parses incoming telemetry strings |
| `logger.py` | Saves telemetry to CSV files |
| `tests/` | Automated tests — run with `python -m pytest tests/` |