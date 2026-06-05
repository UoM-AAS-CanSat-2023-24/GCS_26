"""
Parses raw RX packet strings into validated dictionaries.
No Qt dependency - pure logic, fully unit-testable.
"""

import logging
from config import (
    FIELDS, EXPECTED_FIELD_COUNT,
    FLOAT_FIELDS, INT_FIELDS, RANGE_CHECKS,
)

logger = logging.getLogger(__name__)


def parse_packet(raw: str) -> dict | None:
    """
    Parse a raw comma-separated packet string into a dict.

    Returns:
        dict with FIELDS as keys.  Individual fields that failed type-casting
        or range checks are set to None rather than discarding the whole packet.
        Returns None only if the packet is structurally invalid (wrong field
        count, completely empty, etc.).

    Examples:
        >>> p = parse_packet("1059, 13:14:02, 1025, F, LAUNCH_PAD, 427.3, 21.3, "
        ...                   "101.3, 3.7, 1.31, 186, 2.0, 0.5, 1.1, 0.3, "
        ...                   "9.5, 21:49:53, 558.0, 63.4451, 10.9050, 8, "
        ...                   "CXON, ARMED, 45, 0.377, 1234, 1, GLIDER")
        >>> p["STATE"]
        'LAUNCH_PAD'
        >>> p["ALTITUDE"]
        427.3
    """
    if not raw or not raw.strip():
        logger.debug("Empty packet received")
        return None

    raw = raw.strip()
    parts = [p.strip() for p in raw.split(",")]

    if len(parts) != EXPECTED_FIELD_COUNT:
        logger.warning(
            "Field count mismatch: expected %d, got %d | raw: %s",
            EXPECTED_FIELD_COUNT, len(parts), raw,
        )
        return None

    packet = {}
    for field, value in zip(FIELDS, parts):
        packet[field] = _cast_field(field, value)

    return packet


def _cast_field(field: str, raw_value: str):
    """
    Attempt to cast a single field value to the correct type.
    Returns None on failure or out-of-range.
    """
    if raw_value == "" or raw_value.upper() in ("N/A", "NODATA", "NO DATA", "NONE"):
        logger.debug("Field %s has no data value: '%s'", field, raw_value)
        return None

    # String fields - return as-is (strip already applied)
    if field not in FLOAT_FIELDS and field not in INT_FIELDS:
        return raw_value

    # Numeric cast
    try:
        if field in FLOAT_FIELDS:
            value = float(raw_value)
        else:
            # INT_FIELDS - some may arrive as floats e.g. "45.0"
            value = int(float(raw_value))
    except (ValueError, TypeError):
        logger.warning("Type cast failed for field %s: '%s'", field, raw_value)
        return None

    # Range check
    if field in RANGE_CHECKS:
        lo, hi = RANGE_CHECKS[field]
        if not (lo <= value <= hi):
            logger.warning(
                "Range check failed for field %s: %s not in [%s, %s]",
                field, value, lo, hi,
            )
            return None

    return value


def packet_to_row(packet: dict) -> list:
    """
    Convert a packet dict to an ordered list suitable for CSV writing.
    None values become empty string.
    """
    return ["" if packet.get(f) is None else str(packet[f]) for f in FIELDS]