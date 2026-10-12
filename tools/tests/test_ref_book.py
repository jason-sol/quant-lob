import io

from qlob_tools import encode
from qlob_tools.ref_book import RefBook, replay


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
        "duplicate_order_refs": 1,
        "events": 6,
        "overfills": 0,
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


def test_non_book_types_produce_no_row():
    execute = b"E" + bytes(30)
    _, rows, stats = _rows(execute, encode.system_event(code="Q"))
    assert rows == []
    assert stats["events"] == 0


def test_trailing_bytes_reported():
    data = encode.frame(encode.delete(ref=1)) + b"\x00\x24AB"
    r = replay(io.BytesIO(data), 1)
    list(r)
    assert r.stats["trailing_bytes"] == 4


def test_replay_accepts_path(tmp_path):
    p = tmp_path / "f.itch"
    p.write_bytes(encode.frame(encode.add(ref=1, side="S", shares=3, price=7, ts=5)))
    assert list(replay(p, 1))[1:] == ["0,5,0,0,7,3"]
