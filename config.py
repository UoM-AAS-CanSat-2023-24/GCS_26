"""
Central configuration for CanSat Ground Station.
Edit TEAM_ID and PORT before use.
"""

TEAM_ID = 1059
BAUD_RATE = 9600
PORT = "COM3"          # Windows: "COM3" etc.  Linux/Mac: "/dev/ttyUSB0"
READ_TIMEOUT = 2       # seconds before serial readline times out

# Rolling graph buffer length (number of packets)
GRAPH_BUFFER = 300

# Map: how many packets between full HTML reloads (only used as fallback)
# Normal updates use JS injection so this should rarely trigger
MAP_RELOAD_INTERVAL = 60

# Tile path for offline folium map - edit to match your tile directory
# Tiles should be in {z}/{x}/{y}.png format
TILE_PATH = "tiles/{z}/{x}/{y}.png"
TILE_ATTRIBUTION = "Offline Tiles"

# Default location shown before first GPS fix (Stonehenge area for testing)
DEFAULT_LAT = 51.18325
DEFAULT_LON = -1.82139

# Ordered list of fields in the RX packet, exactly matching transmission order
FIELDS = [
    "TEAM_ID",
    "MISSION_TIME",
    "PACKET_COUNT",
    "MODE",
    "STATE",
    "ALTITUDE",
    "TEMPERATURE",
    "PRESSURE",
    "VOLTAGE",
    "CURRENT",
    "GYRO_R",
    "GYRO_P",
    "GYRO_Y",
    "ACCEL_R",
    "ACCEL_P",
    "ACCEL_Y",
    "GPS_TIME",
    "GPS_ALTITUDE",
    "GPS_LATITUDE",
    "GPS_LONGITUDE",
    "GPS_SATS",
    "CMD_ECHO",
    "SUBSTATE",
    "MAIN_SOC",
    "BUS_POWER",
    "ACTIVE_MECHS",
    "ACTIVE_CAMERA",
    "MATEK",
]

EXPECTED_FIELD_COUNT = len(FIELDS)

# Fields that should be cast to float
FLOAT_FIELDS = {
    "ALTITUDE", "TEMPERATURE", "PRESSURE", "VOLTAGE", "CURRENT",
    "GYRO_R", "GYRO_P", "GYRO_Y", "ACCEL_R", "ACCEL_P", "ACCEL_Y",
    "GPS_ALTITUDE", "GPS_LATITUDE", "GPS_LONGITUDE", "BUS_POWER",
}

# Fields that should be cast to int
INT_FIELDS = {
    "TEAM_ID", "PACKET_COUNT", "GPS_SATS", "MAIN_SOC",
    "ACTIVE_MECHS", "ACTIVE_CAMERA",
}

# Sanity range checks: field -> (min, max).  Out-of-range values become None.
RANGE_CHECKS = {
    "ALTITUDE":      (-500,  50000),
    "TEMPERATURE":   (-80,   120),
    "PRESSURE":      (0,     200000),
    "VOLTAGE":       (0,     25),
    "CURRENT":       (-50,   50),
    "GYRO_R":        (-2000, 2000),
    "GYRO_P":        (-2000, 2000),
    "GYRO_Y":        (-2000, 2000),
    "ACCEL_R":       (-160,  160),
    "ACCEL_P":       (-160,  160),
    "ACCEL_Y":       (-160,  160),
    "GPS_ALTITUDE":  (-500,  50000),
    "GPS_LATITUDE":  (-90,   90),
    "GPS_LONGITUDE": (-180,  180),
    "GPS_SATS":      (0,     50),
    "MAIN_SOC":      (0,     100),
    "BUS_POWER":     (0,     1000),
}

# Mechanism device codes keyed by button number 1-4
MECH_CODES = {
    1: "1000",   # Servo 1 - Payload release servo
    2: "0200",   # Servo 2 - Port steering servo
    3: "0030",   # Servo 3 - Starboard steering servo
    4: "0004",   # Servo 4 - Egg release servo
}
