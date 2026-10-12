"""ITCH 5.0 layout: expected message lengths and big-endian struct formats.

Offsets are from the type byte. Header: type(1) locate u16, tracking u16, timestamp u48.
"""

import struct

EXPECTED_LENGTH: dict[str, int] = {
    "S": 12, "R": 39, "H": 25, "Y": 20, "L": 26, "V": 35, "W": 12, "K": 28,
    "J": 35, "h": 21, "A": 36, "F": 40, "E": 31, "C": 36, "X": 23, "D": 19,
    "U": 35, "P": 44, "Q": 40, "B": 19, "I": 50, "N": 20, "O": 48,
}

LENGTH_PREFIX = struct.Struct(">H")

# The u48 timestamp is packed as u16 high + u32 low.
HEADER = struct.Struct(">cHHHI")
ADD = struct.Struct(">cHHHIQcI8sI")
ADD_MPID = struct.Struct(">cHHHIQcI8sI4s")
DELETE = struct.Struct(">cHHHIQ")
EXECUTED = struct.Struct(">cHHHIQIQ")
EXECUTED_WITH_PRICE = struct.Struct(">cHHHIQIQcI")
CANCEL = struct.Struct(">cHHHIQI")
REPLACE = struct.Struct(">cHHHIQQII")
SYSTEM_EVENT = struct.Struct(">cHHHIc")
STOCK_DIRECTORY = struct.Struct(">cHHHI8sccIcc2scccccIc")
CROSS_TRADE = struct.Struct(">cHHHIQ8sIQc")

assert ADD.size == EXPECTED_LENGTH["A"]
assert ADD_MPID.size == EXPECTED_LENGTH["F"]
assert DELETE.size == EXPECTED_LENGTH["D"]
assert EXECUTED.size == EXPECTED_LENGTH["E"]
assert EXECUTED_WITH_PRICE.size == EXPECTED_LENGTH["C"]
assert CANCEL.size == EXPECTED_LENGTH["X"]
assert REPLACE.size == EXPECTED_LENGTH["U"]
assert SYSTEM_EVENT.size == EXPECTED_LENGTH["S"]
assert STOCK_DIRECTORY.size == EXPECTED_LENGTH["R"]
assert CROSS_TRADE.size == EXPECTED_LENGTH["Q"]


def split_ts(ts: int) -> tuple[int, int]:
    return (ts >> 32) & 0xFFFF, ts & 0xFFFFFFFF


def join_ts(hi: int, lo: int) -> int:
    return (hi << 32) | lo
