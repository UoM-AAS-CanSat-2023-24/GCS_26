"""
Unit tests for CanSat Ground Station.
Run with:  python -m pytest tests/ -v
Or:        python tests/test_all.py

Tests are grouped by module and cover:
  - data_parser: valid packets, field-level failures, range checks
  - logger: file creation, CSV content, raw log
  - sim_handler: CSV loading, row iteration (no Qt needed)
  - serial_handler: TX queue (no real serial port needed)
"""

import csv
import os
import sys
import tempfile
import unittest

# Make sure the parent directory is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from data_parser import parse_packet, packet_to_row


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# A complete valid raw packet string matching the FIELDS order
VALID_RAW = (
    "1059, 13:14:02, 1025, F, ASCENT, 427.3, 21.3, 101.3, 3.7, 1.31, "
    "186, 2.0, 0.5, 1.1, 0.3, 9.5, 21:49:53, 558.0, 63.4451, 10.9050, "
    "8, CXON, ARMED, 45, 0.377, 1234, 1, GLIDER"
)


def make_valid_packet() -> dict:
    return parse_packet(VALID_RAW)


# ---------------------------------------------------------------------------
# data_parser tests
# ---------------------------------------------------------------------------

class TestParsePacketValid(unittest.TestCase):

    def setUp(self):
        self.packet = make_valid_packet()

    def test_returns_dict(self):
        self.assertIsInstance(self.packet, dict)

    def test_all_fields_present(self):
        for field in config.FIELDS:
            self.assertIn(field, self.packet)

    def test_state_string(self):
        self.assertEqual(self.packet["STATE"], "ASCENT")

    def test_altitude_float(self):
        self.assertAlmostEqual(self.packet["ALTITUDE"], 427.3)

    def test_team_id_int(self):
        self.assertEqual(self.packet["TEAM_ID"], 1059)

    def test_packet_count_int(self):
        self.assertEqual(self.packet["PACKET_COUNT"], 1025)

    def test_gps_lat_float(self):
        self.assertAlmostEqual(self.packet["GPS_LATITUDE"], 63.4451, places=4)

    def test_sats_int(self):
        self.assertEqual(self.packet["GPS_SATS"], 8)

    def test_cmd_echo_string(self):
        self.assertEqual(self.packet["CMD_ECHO"], "CXON")

    def test_mission_time_string(self):
        self.assertEqual(self.packet["MISSION_TIME"], "13:14:02")


class TestParsePacketInvalid(unittest.TestCase):

    def test_none_on_empty_string(self):
        self.assertIsNone(parse_packet(""))

    def test_none_on_whitespace(self):
        self.assertIsNone(parse_packet("   "))

    def test_none_on_wrong_field_count_too_few(self):
        self.assertIsNone(parse_packet("1059, 13:14:02, 1025"))

    def test_none_on_wrong_field_count_too_many(self):
        extra = VALID_RAW + ", EXTRA, FIELDS"
        self.assertIsNone(parse_packet(extra))

    def test_none_on_none_input(self):
        self.assertIsNone(parse_packet(None))


class TestParsePacketFieldLevelFailures(unittest.TestCase):
    """
    Individual bad fields should produce None for that field
    but still return a dict (not None for the whole packet).
    """

    def _swap_field(self, field_name: str, new_value: str) -> str:
        """Replace one field in VALID_RAW with a new value."""
        parts = [p.strip() for p in VALID_RAW.split(",")]
        idx = config.FIELDS.index(field_name)
        parts[idx] = new_value
        return ", ".join(parts)

    def test_bad_altitude_gives_none_field(self):
        raw = self._swap_field("ALTITUDE", "NOT_A_NUMBER")
        packet = parse_packet(raw)
        self.assertIsNotNone(packet)
        self.assertIsNone(packet["ALTITUDE"])

    def test_bad_voltage_gives_none_field(self):
        raw = self._swap_field("VOLTAGE", "abc")
        packet = parse_packet(raw)
        self.assertIsNotNone(packet)
        self.assertIsNone(packet["VOLTAGE"])

    def test_other_fields_unaffected_by_single_bad_field(self):
        raw = self._swap_field("VOLTAGE", "abc")
        packet = parse_packet(raw)
        self.assertAlmostEqual(packet["ALTITUDE"], 427.3)
        self.assertEqual(packet["STATE"], "ASCENT")

    def test_empty_numeric_field_gives_none(self):
        raw = self._swap_field("CURRENT", "")
        packet = parse_packet(raw)
        self.assertIsNone(packet["CURRENT"])


class TestRangeChecks(unittest.TestCase):

    def _swap_field(self, field_name: str, new_value: str) -> str:
        parts = [p.strip() for p in VALID_RAW.split(",")]
        idx = config.FIELDS.index(field_name)
        parts[idx] = new_value
        return ", ".join(parts)

    def test_altitude_below_range(self):
        raw = self._swap_field("ALTITUDE", "-9999")
        packet = parse_packet(raw)
        self.assertIsNone(packet["ALTITUDE"])

    def test_altitude_above_range(self):
        raw = self._swap_field("ALTITUDE", "99999")
        packet = parse_packet(raw)
        self.assertIsNone(packet["ALTITUDE"])

    def test_altitude_in_range(self):
        raw = self._swap_field("ALTITUDE", "1000")
        packet = parse_packet(raw)
        self.assertAlmostEqual(packet["ALTITUDE"], 1000.0)

    def test_voltage_above_range(self):
        raw = self._swap_field("VOLTAGE", "999")
        packet = parse_packet(raw)
        self.assertIsNone(packet["VOLTAGE"])

    def test_gps_latitude_out_of_range(self):
        raw = self._swap_field("GPS_LATITUDE", "200")
        packet = parse_packet(raw)
        self.assertIsNone(packet["GPS_LATITUDE"])

    def test_sats_negative(self):
        raw = self._swap_field("GPS_SATS", "-1")
        packet = parse_packet(raw)
        self.assertIsNone(packet["GPS_SATS"])


class TestPacketToRow(unittest.TestCase):

    def test_row_length_matches_fields(self):
        packet = make_valid_packet()
        row = packet_to_row(packet)
        self.assertEqual(len(row), len(config.FIELDS))

    def test_none_field_becomes_empty_string(self):
        packet = make_valid_packet()
        packet["ALTITUDE"] = None
        row = packet_to_row(packet)
        idx = config.FIELDS.index("ALTITUDE")
        self.assertEqual(row[idx], "")

    def test_string_fields_preserved(self):
        packet = make_valid_packet()
        row = packet_to_row(packet)
        idx = config.FIELDS.index("STATE")
        self.assertEqual(row[idx], "ASCENT")


# ---------------------------------------------------------------------------
# logger tests
# ---------------------------------------------------------------------------

class TestDataLogger(unittest.TestCase):

    def setUp(self):
        from logger import DataLogger
        self.tmp_dir = tempfile.mkdtemp()
        self.dl = DataLogger(log_dir=self.tmp_dir)

    def tearDown(self):
        self.dl.close()

    def test_no_file_created_before_first_log(self):
        # CSV file should not exist until first log() call
        self.assertFalse(os.path.exists(self.dl.csv_path))

    def test_csv_created_on_first_log(self):
        packet = make_valid_packet()
        self.dl.log(packet)
        self.assertTrue(os.path.exists(self.dl.csv_path))

    def test_header_row_written(self):
        self.dl.log(make_valid_packet())
        with open(self.dl.csv_path, newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
        self.assertEqual(header, config.FIELDS)

    def test_data_row_written(self):
        packet = make_valid_packet()
        self.dl.log(packet)
        with open(self.dl.csv_path, newline="") as f:
            reader = csv.reader(f)
            next(reader)            # skip header
            data_row = next(reader)
        state_idx = config.FIELDS.index("STATE")
        self.assertEqual(data_row[state_idx], "ASCENT")

    def test_packet_count_increments(self):
        self.assertEqual(self.dl.packets_logged, 0)
        self.dl.log(make_valid_packet())
        self.dl.log(make_valid_packet())
        self.assertEqual(self.dl.packets_logged, 2)

    def test_raw_log_written(self):
        self.dl.log_raw("some raw data")
        self.assertTrue(os.path.exists(self.dl.raw_path))
        with open(self.dl.raw_path) as f:
            content = f.read()
        self.assertIn("some raw data", content)

    def test_none_fields_logged_as_empty(self):
        packet = make_valid_packet()
        packet["ALTITUDE"] = None
        self.dl.log(packet)
        with open(self.dl.csv_path, newline="") as f:
            reader = csv.reader(f)
            next(reader)
            row = next(reader)
        alt_idx = config.FIELDS.index("ALTITUDE")
        self.assertEqual(row[alt_idx], "")


# ---------------------------------------------------------------------------
# sim_handler tests (no Qt event loop needed)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# simp_sender tests
# ---------------------------------------------------------------------------

class TestLoadSimpFile(unittest.TestCase):

    def _write_simp(self, lines: list[str]) -> str:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        )
        tmp.write("\n".join(lines))
        tmp.close()
        return tmp.name

    HEADER = [
        "# CanSat SIMP file",
        "# Each line transmitted at 1 Hz",
        "",
    ]

    def test_basic_load(self):
        from simp_sender import load_simp_file
        path = self._write_simp(self.HEADER + [
            "CMD,$,SIMP,93948",
            "CMD,$,SIMP,93949",
        ])
        cmds = load_simp_file(path)
        self.assertEqual(len(cmds), 2)
        os.unlink(path)

    def test_dollar_replaced_with_team_id(self):
        from simp_sender import load_simp_file
        path = self._write_simp(["CMD,$,SIMP,93948"])
        cmds = load_simp_file(path)
        self.assertIn(str(config.TEAM_ID), cmds[0])
        self.assertNotIn("$", cmds[0])
        os.unlink(path)

    def test_inline_comments_stripped(self):
        from simp_sender import load_simp_file
        path = self._write_simp(["CMD,$,SIMP,93948 # this is a pressure glitch"])
        cmds = load_simp_file(path)
        self.assertEqual(len(cmds), 1)
        self.assertNotIn("#", cmds[0])
        self.assertEqual(cmds[0].strip(), f"CMD,{config.TEAM_ID},SIMP,93948")
        os.unlink(path)

    def test_blank_lines_skipped(self):
        from simp_sender import load_simp_file
        path = self._write_simp([
            "",
            "   ",
            "CMD,$,SIMP,93948",
            "",
            "CMD,$,SIMP,93949",
            "",
        ])
        cmds = load_simp_file(path)
        self.assertEqual(len(cmds), 2)
        os.unlink(path)

    def test_full_comment_lines_skipped(self):
        from simp_sender import load_simp_file
        path = self._write_simp([
            "# This whole line is a comment",
            "CMD,$,SIMP,93948",
        ])
        cmds = load_simp_file(path)
        self.assertEqual(len(cmds), 1)
        os.unlink(path)

    def test_raises_on_missing_file(self):
        from simp_sender import load_simp_file
        with self.assertRaises(FileNotFoundError):
            load_simp_file("/nonexistent/path/simp.txt")

    def test_raises_on_empty_file(self):
        from simp_sender import load_simp_file
        path = self._write_simp(["# only comments", "", "# nothing else"])
        with self.assertRaises(ValueError):
            load_simp_file(path)
        os.unlink(path)

    def test_realistic_file_format(self):
        """Test with the exact format from the competition spec."""
        from simp_sender import load_simp_file
        lines = [
            "################################################################################",
            "# CanSat 2023 Simulated Pressure Command File",
            "#",
            "# Notes:",
            "#   a) Contents are SIMP commands, where $ is to be replaced with the team id.",
            "#   b) Each line is to be transmitted @ 1 Hz by the ground station.",
            "#   c) All line text after a # character should be ignored as a comment.",
            "#   d) Blank lines are to be ignored.",
            "#   e) There may be intentional sensor glitches in this data.",
            "################################################################################",
            "",
            "CMD,$,SIMP,93948",
            "CMD,$,SIMP,93949",
            "CMD,$,SIMP,93948",
            "CMD,$,SIMP,93948",
        ]
        path = self._write_simp(lines)
        cmds = load_simp_file(path)
        self.assertEqual(len(cmds), 4)
        self.assertTrue(all(str(config.TEAM_ID) in c for c in cmds))
        self.assertTrue(all("SIMP" in c for c in cmds))
        os.unlink(path)


# ---------------------------------------------------------------------------
# config tests
# ---------------------------------------------------------------------------

class TestConfig(unittest.TestCase):

    def test_field_count(self):
        self.assertEqual(len(config.FIELDS), config.EXPECTED_FIELD_COUNT)

    def test_mech_codes_keys(self):
        self.assertEqual(set(config.MECH_CODES.keys()), {1, 2, 3, 4})

    def test_float_and_int_fields_disjoint(self):
        overlap = config.FLOAT_FIELDS & config.INT_FIELDS
        self.assertEqual(overlap, set())

    def test_range_check_fields_are_known(self):
        all_fields = set(config.FIELDS)
        for field in config.RANGE_CHECKS:
            self.assertIn(field, all_fields,
                          f"Range check for unknown field: {field}")

    def test_range_check_mins_less_than_maxs(self):
        for field, (lo, hi) in config.RANGE_CHECKS.items():
            self.assertLess(lo, hi, f"Bad range for {field}: [{lo}, {hi}]")


# ---------------------------------------------------------------------------
# Integration: parse -> log round-trip
# ---------------------------------------------------------------------------

class TestParseToLogRoundTrip(unittest.TestCase):

    def test_valid_packet_survives_parse_log_reread(self):
        from logger import DataLogger
        tmp_dir = tempfile.mkdtemp()
        dl = DataLogger(log_dir=tmp_dir)

        packet = parse_packet(VALID_RAW)
        dl.log(packet)
        dl.close()

        with open(dl.csv_path, newline="") as f:
            reader = csv.DictReader(f)
            row = next(reader)

        self.assertEqual(row["STATE"], "ASCENT")
        self.assertEqual(row["MISSION_TIME"], "13:14:02")
        self.assertAlmostEqual(float(row["ALTITUDE"]), 427.3)


if __name__ == "__main__":
    unittest.main(verbosity=2)