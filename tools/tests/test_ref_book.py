import io

import pytest

from qlob_tools import encode
from qlob_tools.ref_book import Cancel, Execute, Replace, RefBook, decode, replay


def _feed(*msgs: bytes) -> io.BytesIO:
    return io.BytesIO(b"".join(encode.frame(m) for m in msgs))


def _rows(*msgs: bytes, depth: int = 2):
    r = replay(_feed(*msgs), depth)
    lines = list(r)
    return lines[0], lines[1:], r.stats


def test_header_has_two_plus_four_n_columns():
    header, rows, _ = _rows(depth=3)
    cols = header.split(",")
    assert len(cols) == 2 + 4 * 3
    assert cols[:6] == ["seq", "ts_ns", "bid_px1", "bid_qty1", "ask_px1", "ask_qty1"]
    assert cols[-4:] == ["bid_px3", "bid_qty3", "ask_px3", "ask_qty3"]
    assert rows == []


def test_snapshot_aggregates_levels_best_first_with_padding():
    b = RefBook()
    b.add(1, "B", 100, 10)
    b.add(2, "B", 100, 5)
    b.add(3, "B", 101, 7)
    b.add(4, "S", 103, 4)
    b.add(5, "S", 102, 6)
    b.add(6, "S", 102, 1)
    assert b.snapshot(3) == [
        (101, 7, 102, 7),
        (100, 15, 103, 4),
        (0, 0, 0, 0),
    ]


def test_delete_removes_empty_level():
    b = RefBook()
    b.add(1, "B", 100, 10)
    b.add(2, "B", 99, 3)
    b.delete(1)
    assert b.snapshot(2) == [(99, 3, 0, 0), (0, 0, 0, 0)]
    assert 100 not in b.levels["B"]


def test_delete_leaves_level_with_remaining_orders():
    b = RefBook()
    b.add(1, "S", 100, 10)
    b.add(2, "S", 100, 4)
    b.delete(1)
    assert b.snapshot(1) == [(0, 0, 100, 4)]


def test_unknown_delete_counted_and_book_unchanged():
    b = RefBook()
    b.add(1, "B", 100, 10)
    b.delete(42)
    assert b.stats["unknown_order_refs"] == 1
    assert b.snapshot(1) == [(100, 10, 0, 0)]


def test_delete_twice_counts_second_as_unknown():
    b = RefBook()
    b.add(1, "B", 100, 10)
    b.delete(1)
    b.delete(1)
    assert b.stats["unknown_order_refs"] == 1


def test_duplicate_add_counted_and_ignored():
    b = RefBook()
    b.add(1, "B", 100, 10)
    b.add(1, "S", 200, 99)
    assert b.stats["duplicate_order_refs"] == 1
    assert b.snapshot(1) == [(100, 10, 0, 0)]


def test_zero_qty_add_counted_and_ignored():
    b = RefBook()
    b.add(1, "B", 100, 0)
    assert b.stats["zero_qty_adds"] == 1
    assert b.snapshot(1) == [(0, 0, 0, 0)]
    b.delete(1)
    assert b.stats["unknown_order_refs"] == 1


def test_zero_qty_add_on_live_id_counts_as_duplicate_only():
    b = RefBook()
    b.add(1, "B", 100, 10)
    b.add(1, "B", 100, 0)
    assert b.stats["duplicate_order_refs"] == 1
    assert b.stats["zero_qty_adds"] == 0


def test_ref_reusable_after_delete():
    b = RefBook()
    b.add(1, "B", 100, 10)
    b.delete(1)
    b.add(1, "S", 105, 2)
    assert b.stats["duplicate_order_refs"] == 0
    assert b.snapshot(1) == [(0, 0, 105, 2)]


def test_one_row_per_decoded_event_including_noops():
    header, rows, stats = _rows(
        encode.system_event(code="O", ts=1),
        encode.add(ref=1, side="B", shares=100, price=1_000_000, ts=10),
        encode.add_mpid(ref=2, side="S", shares=50, price=1_010_000, ts=20),
        encode.add(ref=1, side="B", shares=5, price=1_000_000, ts=30),  # duplicate
        encode.add(ref=3, side="B", shares=0, price=1_000_000, ts=40),  # zero qty
        encode.delete(ref=77, ts=50),  # unknown
        encode.delete(ref=1, ts=60),
    )
    assert rows == [
        "0,10,1000000,100,0,0,0,0,0,0",
        "1,20,1000000,100,1010000,50,0,0,0,0",
        "2,30,1000000,100,1010000,50,0,0,0,0",
        "3,40,1000000,100,1010000,50,0,0,0,0",
        "4,50,1000000,100,1010000,50,0,0,0,0",
        "5,60,0,0,1010000,50,0,0,0,0",
    ]
    assert stats == {
        "decode_rejects": 0,
        "duplicate_order_refs": 1,
        "events": 6,
        "excess_reductions": 0,
        "trailing_bytes": 0,
        "unknown_order_refs": 1,
        "zero_qty_adds": 1,
    }


def test_undecodable_book_messages_produce_no_row():
    bad_side = encode.add(ref=1, side="X", shares=10, price=100)
    short_add = encode.add(ref=2, side="B", shares=10, price=100)[:35]
    long_delete = encode.delete(ref=2) + b"\x00"
    _, rows, stats = _rows(bad_side, short_add, long_delete)
    assert rows == []
    assert stats["events"] == 0


def test_decode_rejects_counted_for_malformed_book_messages():
    short_add = encode.add(ref=1, side="B", shares=10, price=100)[:35]
    long_exec = encode.executed(ref=1, shares=1, match=1) + b"\x00"
    bad_side = encode.add(ref=2, side="Z", shares=10, price=100)
    _, rows, stats = _rows(short_add, long_exec, bad_side)
    assert rows == []
    assert stats["decode_rejects"] == 3
    assert stats["events"] == 0


def test_non_book_types_produce_no_row_and_are_not_decode_rejects():
    trade = b"P" + bytes(43)
    _, rows, stats = _rows(trade, encode.system_event(code="Q"), b"", b"Z" + bytes(5))
    assert rows == []
    assert stats["events"] == 0
    assert stats["decode_rejects"] == 0


def test_trailing_bytes_reported():
    data = encode.frame(encode.delete(ref=1)) + b"\x00\x24AB"
    r = replay(io.BytesIO(data), 1)
    list(r)
    assert r.stats["trailing_bytes"] == 4


def test_replay_accepts_path(tmp_path):
    p = tmp_path / "f.itch"
    p.write_bytes(encode.frame(encode.add(ref=1, side="S", shares=3, price=7, ts=5)))
    assert list(replay(p, 1))[1:] == ["0,5,0,0,7,3"]


# Header with distinct bytes per field: locate 0x0102, tracking 0x0304, ts 0x05060708090A.
HDR_TAIL = bytes([0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A])
HDR_TS = 0x05060708090A
REF = bytes(range(0x11, 0x19))  # 0x1112131415161718
SHARES = bytes([0x21, 0x22, 0x23, 0x24])
MATCH = bytes(range(0x31, 0x39))
PRICE = bytes([0x41, 0x42, 0x43, 0x44])
NEW_REF = bytes(range(0x51, 0x59))


def _int(b: bytes) -> int:
    return int.from_bytes(b, "big")


def test_decode_executed_fields_at_spec_offsets():
    raw = b"E" + HDR_TAIL + REF + SHARES + MATCH
    assert len(raw) == 31
    assert decode(raw) == Execute(ts=HDR_TS, ref=_int(REF), shares=_int(SHARES), match=_int(MATCH))


def test_decode_executed_with_price_fields_at_spec_offsets():
    raw = b"C" + HDR_TAIL + REF + SHARES + MATCH + b"Y" + PRICE
    assert len(raw) == 36
    assert decode(raw) == Execute(ts=HDR_TS, ref=_int(REF), shares=_int(SHARES), match=_int(MATCH),
                                  printable="Y", price=_int(PRICE))


def test_decode_cancel_fields_at_spec_offsets():
    raw = b"X" + HDR_TAIL + REF + SHARES
    assert len(raw) == 23
    assert decode(raw) == Cancel(ts=HDR_TS, ref=_int(REF), shares=_int(SHARES))


def test_decode_replace_fields_at_spec_offsets():
    raw = b"U" + HDR_TAIL + REF + NEW_REF + SHARES + PRICE
    assert len(raw) == 35
    assert decode(raw) == Replace(ts=HDR_TS, orig_ref=_int(REF), new_ref=_int(NEW_REF),
                                  shares=_int(SHARES), price=_int(PRICE))


def test_encoders_match_spec_bytes():
    kw = dict(ts=HDR_TS, locate=0x0102, tracking=0x0304)
    assert encode.executed(ref=_int(REF), shares=_int(SHARES), match=_int(MATCH), **kw) == (
        b"E" + HDR_TAIL + REF + SHARES + MATCH)
    assert encode.executed_with_price(ref=_int(REF), shares=_int(SHARES), match=_int(MATCH),
                                      printable="Y", price=_int(PRICE), **kw) == (
        b"C" + HDR_TAIL + REF + SHARES + MATCH + b"Y" + PRICE)
    assert encode.cancel(ref=_int(REF), shares=_int(SHARES), **kw) == b"X" + HDR_TAIL + REF + SHARES
    assert encode.replace(orig_ref=_int(REF), new_ref=_int(NEW_REF), shares=_int(SHARES),
                          price=_int(PRICE), **kw) == b"U" + HDR_TAIL + REF + NEW_REF + SHARES + PRICE


@pytest.mark.parametrize(
    "msg",
    [
        encode.executed(ref=1, shares=1, match=1),
        encode.executed_with_price(ref=1, shares=1, match=1, printable="Y", price=1),
        encode.cancel(ref=1, shares=1),
        encode.replace(orig_ref=1, new_ref=2, shares=1, price=1),
    ],
    ids=["E", "C", "X", "U"],
)
@pytest.mark.parametrize("mutate", [lambda m: m[:-1], lambda m: m + b"\x00"], ids=["short", "long"])
def test_wrong_length_not_decoded_and_no_row(msg, mutate):
    bad = mutate(msg)
    assert decode(bad) is None
    _, rows, stats = _rows(encode.add(ref=1, side="B", shares=10, price=100, ts=1), bad)
    assert len(rows) == 1
    assert stats["events"] == 1
    assert stats["decode_rejects"] == 1


def _book_with(*orders):
    b = RefBook()
    for ref, side, price, qty in orders:
        b.add(ref, side, price, qty)
    return b


def _counters(b):
    return {k: b.stats[k] for k in ("unknown_order_refs", "duplicate_order_refs", "zero_qty_adds", "excess_reductions")}


ZERO = {"unknown_order_refs": 0, "duplicate_order_refs": 0, "zero_qty_adds": 0, "excess_reductions": 0}


@pytest.mark.parametrize("op", ["execute", "cancel"])
def test_partial_reduces_order_and_level(op):
    b = _book_with((1, "B", 100, 10), (2, "B", 100, 5))
    getattr(b, op)(1, 4)
    assert b.orders[1] == ("B", 100, 6)
    assert b.snapshot(1) == [(100, 11, 0, 0)]
    assert _counters(b) == ZERO


@pytest.mark.parametrize("op", ["execute", "cancel"])
def test_exact_removes_order_without_excess_reduction(op):
    b = _book_with((1, "S", 100, 10), (2, "S", 101, 5))
    getattr(b, op)(1, 10)
    assert 1 not in b.orders
    assert 100 not in b.levels["S"]
    assert b.snapshot(1) == [(0, 0, 101, 5)]
    assert _counters(b) == ZERO


@pytest.mark.parametrize("op", ["execute", "cancel"])
def test_over_removes_order_and_counts_excess_reduction(op):
    b = _book_with((1, "B", 100, 10), (2, "B", 100, 3))
    getattr(b, op)(1, 11)
    assert 1 not in b.orders
    assert b.snapshot(1) == [(100, 3, 0, 0)]
    assert _counters(b) == {**ZERO, "excess_reductions": 1}


@pytest.mark.parametrize("op", ["execute", "cancel"])
def test_unknown_ref_counted_and_book_unchanged(op):
    b = _book_with((1, "B", 100, 10))
    getattr(b, op)(99, 5)
    assert b.orders == {1: ("B", 100, 10)}
    assert b.snapshot(1) == [(100, 10, 0, 0)]
    assert _counters(b) == {**ZERO, "unknown_order_refs": 1}


def test_replace_moves_to_new_id_price_qty_keeping_side():
    b = _book_with((1, "S", 100, 10), (2, "S", 100, 4))
    b.replace(1, 7, 102, 3)
    assert 1 not in b.orders
    assert b.orders[7] == ("S", 102, 3)
    assert b.snapshot(2) == [(0, 0, 100, 4), (0, 0, 102, 3)]
    assert _counters(b) == ZERO


def test_old_id_unknown_after_replace():
    b = _book_with((1, "B", 100, 10))
    b.replace(1, 2, 100, 10)
    b.delete(1)
    assert b.stats["unknown_order_refs"] == 1
    assert b.snapshot(1) == [(100, 10, 0, 0)]


def test_replace_unknown_original_adds_nothing():
    b = _book_with((1, "B", 100, 10))
    b.replace(99, 2, 105, 5)
    assert b.orders == {1: ("B", 100, 10)}
    assert _counters(b) == {**ZERO, "unknown_order_refs": 1}


def test_replace_unknown_original_with_live_new_id_counts_unknown_only():
    b = _book_with((1, "B", 100, 10))
    b.replace(99, 1, 105, 0)
    assert b.orders == {1: ("B", 100, 10)}
    assert _counters(b) == {**ZERO, "unknown_order_refs": 1}


def test_replace_onto_live_new_id_ignored_entirely():
    b = _book_with((1, "B", 100, 10), (2, "S", 200, 5))
    b.replace(1, 2, 101, 7)
    assert b.orders == {1: ("B", 100, 10), 2: ("S", 200, 5)}
    assert b.snapshot(1) == [(100, 10, 200, 5)]
    assert _counters(b) == {**ZERO, "duplicate_order_refs": 1}


def test_replace_onto_live_new_id_with_zero_qty_counts_duplicate_only():
    b = _book_with((1, "B", 100, 10), (2, "S", 200, 5))
    b.replace(1, 2, 101, 0)
    assert b.orders == {1: ("B", 100, 10), 2: ("S", 200, 5)}
    assert _counters(b) == {**ZERO, "duplicate_order_refs": 1}


def test_replace_same_id_counts_as_duplicate():
    b = _book_with((1, "B", 100, 10))
    b.replace(1, 1, 101, 7)
    assert b.orders == {1: ("B", 100, 10)}
    assert _counters(b) == {**ZERO, "duplicate_order_refs": 1}


def test_zero_qty_replace_ignored_entirely():
    b = _book_with((1, "B", 100, 10))
    b.replace(1, 2, 101, 0)
    assert b.orders == {1: ("B", 100, 10)}
    assert b.snapshot(1) == [(100, 10, 0, 0)]
    assert _counters(b) == {**ZERO, "zero_qty_adds": 1}


def test_replay_rows_for_execute_cancel_replace_including_noops():
    _, rows, stats = _rows(
        encode.add(ref=1, side="B", shares=100, price=1_000_000, ts=10),
        encode.add(ref=2, side="S", shares=50, price=1_010_000, ts=20),
        encode.executed(ref=1, shares=30, match=1, ts=30),
        encode.executed_with_price(ref=2, shares=10, match=2, printable="N", price=999, ts=40),
        encode.cancel(ref=1, shares=20, ts=50),
        encode.replace(orig_ref=2, new_ref=3, shares=60, price=1_005_000, ts=60),
        encode.executed(ref=2, shares=1, match=3, ts=70),  # unknown: replaced away
        encode.cancel(ref=3, shares=61, ts=80),  # excess reduction removes
        encode.replace(orig_ref=1, new_ref=4, shares=0, price=1, ts=90),  # zero qty
    )
    assert rows == [
        "0,10,1000000,100,0,0,0,0,0,0",
        "1,20,1000000,100,1010000,50,0,0,0,0",
        "2,30,1000000,70,1010000,50,0,0,0,0",
        "3,40,1000000,70,1010000,40,0,0,0,0",
        "4,50,1000000,50,1010000,40,0,0,0,0",
        "5,60,1000000,50,1005000,60,0,0,0,0",
        "6,70,1000000,50,1005000,60,0,0,0,0",
        "7,80,1000000,50,0,0,0,0,0,0",
        "8,90,1000000,50,0,0,0,0,0,0",
    ]
    assert stats == {
        "decode_rejects": 0,
        "duplicate_order_refs": 0,
        "events": 9,
        "excess_reductions": 1,
        "trailing_bytes": 0,
        "unknown_order_refs": 1,
        "zero_qty_adds": 1,
    }
