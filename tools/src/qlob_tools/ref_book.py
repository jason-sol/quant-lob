"""Reference Book: a deliberately naive Python Book the C++ Book is checked against.

Simplicity over speed: plain dicts, and top-N levels recomputed from scratch per Snapshot.
"""

import heapq
from collections.abc import Iterator
from typing import NamedTuple

from qlob_tools import layout
from qlob_tools.framing import DEFAULT_CHUNK, FrameStream, open_source

STAT_KEYS = ("decode_rejects", "duplicate_order_refs", "events", "excess_reductions",
             "trailing_bytes", "unknown_order_refs", "zero_qty_adds")


class Add(NamedTuple):
    ts: int
    ref: int
    side: str
    shares: int
    price: int


class Delete(NamedTuple):
    ts: int
    ref: int


class Execute(NamedTuple):
    ts: int
    ref: int
    shares: int
    match: int
    printable: str | None = None
    price: int | None = None


class Cancel(NamedTuple):
    ts: int
    ref: int
    shares: int


class Replace(NamedTuple):
    ts: int
    orig_ref: int
    new_ref: int
    shares: int
    price: int


Event = Add | Delete | Execute | Cancel | Replace


class RefBook:
    def __init__(self) -> None:
        self.orders: dict[int, tuple[str, int, int]] = {}
        self.levels: dict[str, dict[int, int]] = {"B": {}, "S": {}}
        self.stats: dict[str, int] = dict.fromkeys(STAT_KEYS, 0)

    def add(self, ref: int, side: str, price: int, qty: int) -> None:
        if ref in self.orders:
            self.stats["duplicate_order_refs"] += 1
            return
        if qty == 0:
            self.stats["zero_qty_adds"] += 1
            return
        self.orders[ref] = (side, price, qty)
        level = self.levels[side]
        level[price] = level.get(price, 0) + qty

    def delete(self, ref: int) -> None:
        if ref not in self.orders:
            self.stats["unknown_order_refs"] += 1
            return
        self._remove(ref)

    def execute(self, ref: int, shares: int) -> None:
        self._reduce(ref, shares)

    def cancel(self, ref: int, shares: int) -> None:
        self._reduce(ref, shares)

    def replace(self, orig_ref: int, new_ref: int, price: int, qty: int) -> None:
        order = self.orders.get(orig_ref)
        if order is None:
            self.stats["unknown_order_refs"] += 1
            return
        if new_ref in self.orders:
            self.stats["duplicate_order_refs"] += 1
            return
        if qty == 0:
            self.stats["zero_qty_adds"] += 1
            return
        self._remove(orig_ref)
        self.add(new_ref, order[0], price, qty)

    def _reduce(self, ref: int, shares: int) -> None:
        order = self.orders.get(ref)
        if order is None:
            self.stats["unknown_order_refs"] += 1
            return
        side, price, qty = order
        if shares >= qty:
            self.stats["excess_reductions"] += shares > qty
            self._remove(ref)
            return
        self.orders[ref] = (side, price, qty - shares)
        self.levels[side][price] -= shares

    def _remove(self, ref: int) -> None:
        side, price, qty = self.orders.pop(ref)
        level = self.levels[side]
        level[price] -= qty
        if level[price] == 0:
            del level[price]

    def snapshot(self, depth: int) -> list[tuple[int, int, int, int]]:
        bids = self.levels["B"]
        asks = self.levels["S"]
        bid_px = heapq.nlargest(depth, bids)
        ask_px = heapq.nsmallest(depth, asks)
        out = []
        for i in range(depth):
            bp = bid_px[i] if i < len(bid_px) else 0
            ap = ask_px[i] if i < len(ask_px) else 0
            out.append((bp, bids.get(bp, 0), ap, asks.get(ap, 0)))
        return out


def header(depth: int) -> str:
    cols = ["seq", "ts_ns"]
    for i in range(1, depth + 1):
        cols += [f"bid_px{i}", f"bid_qty{i}", f"ask_px{i}", f"ask_qty{i}"]
    return ",".join(cols)


def decode(msg: bytes) -> Event | None:
    """Decode one book message; None for non-book types, wrong lengths or a bad side."""
    t = msg[0:1]
    fmt = _FORMATS.get(t)
    if fmt is None or len(msg) != fmt.size:
        return None
    _, _, _, hi, lo, *body = fmt.unpack(msg)
    ts = layout.join_ts(hi, lo)
    if t in (b"A", b"F"):
        ref, side, shares, _stock, price = body[:5]
        if side not in (b"B", b"S"):
            return None
        return Add(ts, ref, side.decode(), shares, price)
    if t == b"D":
        return Delete(ts, *body)
    if t == b"E":
        return Execute(ts, *body)
    if t == b"C":
        ref, shares, match, printable, price = body
        return Execute(ts, ref, shares, match, printable.decode("latin-1"), price)
    if t == b"X":
        return Cancel(ts, *body)
    return Replace(ts, *body)


_FORMATS = {
    b"A": layout.ADD, b"F": layout.ADD_MPID, b"D": layout.DELETE, b"E": layout.EXECUTED,
    b"C": layout.EXECUTED_WITH_PRICE, b"X": layout.CANCEL, b"U": layout.REPLACE,
}


def _apply(book: RefBook, ev: Event) -> None:
    match ev:
        case Add():
            book.add(ev.ref, ev.side, ev.price, ev.shares)
        case Delete():
            book.delete(ev.ref)
        case Execute():
            book.execute(ev.ref, ev.shares)
        case Cancel():
            book.cancel(ev.ref, ev.shares)
        case Replace():
            book.replace(ev.orig_ref, ev.new_ref, ev.price, ev.shares)


class replay:
    """Iterate to get the CSV header then one Snapshot row per decoded book Event.

    `stats` is complete once iteration finishes.
    """

    def __init__(self, src, depth: int, chunk_size: int = DEFAULT_CHUNK) -> None:
        self.src = src
        self.depth = depth
        self.chunk_size = chunk_size
        self.book = RefBook()
        self.stats = self.book.stats

    def __iter__(self) -> Iterator[str]:
        yield header(self.depth)
        seq = 0
        with open_source(self.src) as f:
            frames = FrameStream(f, self.chunk_size)
            for _, msg in frames:
                ev = decode(msg)
                if ev is None:
                    self.stats["decode_rejects"] += msg[:1] in _FORMATS
                    continue
                _apply(self.book, ev)
                self.stats["events"] += 1
                cells = [str(seq), str(ev.ts)]
                for level in self.book.snapshot(self.depth):
                    cells += map(str, level)
                yield ",".join(cells)
                seq += 1
            self.stats["trailing_bytes"] = frames.trailing_bytes
