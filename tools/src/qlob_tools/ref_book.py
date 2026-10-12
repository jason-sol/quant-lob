"""Reference Book: a deliberately naive Python Book used as the correctness oracle.

Simplicity over speed: plain dicts, and top-N levels recomputed from scratch per Snapshot.
"""

import heapq
from collections.abc import Iterator

from qlob_tools import layout
from qlob_tools.framing import DEFAULT_CHUNK, iter_frames, open_source

STAT_KEYS = ("duplicate_order_refs", "events", "overfills", "trailing_bytes",
             "unknown_order_refs", "zero_qty_adds")


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
        order = self.orders.pop(ref, None)
        if order is None:
            self.stats["unknown_order_refs"] += 1
            return
        side, price, qty = order
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


def _timestamp(msg: bytes) -> int:
    _, _, _, hi, lo = layout.HEADER.unpack_from(msg)
    return layout.join_ts(hi, lo)


def _apply(book: RefBook, msg: bytes) -> bool:
    """Apply one message; returns True if it decoded as a book Event."""
    t = msg[0:1]
    if t in (b"A", b"F"):
        fmt = layout.ADD if t == b"A" else layout.ADD_MPID
        if len(msg) != fmt.size:
            return False
        fields = fmt.unpack(msg)
        ref, side, shares, price = fields[5], fields[6], fields[7], fields[9]
        if side not in (b"B", b"S"):
            return False
        book.add(ref, side.decode(), price, shares)
        return True
    if t == b"D":
        if len(msg) != layout.DELETE.size:
            return False
        book.delete(layout.DELETE.unpack(msg)[5])
        return True
    return False


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
            frames = iter_frames(f, self.chunk_size)
            for _, msg in frames:
                if not msg or not _apply(self.book, msg):
                    continue
                self.stats["events"] += 1
                cells = [str(seq), str(_timestamp(msg))]
                for level in self.book.snapshot(self.depth):
                    cells += map(str, level)
                yield ",".join(cells)
                seq += 1
            self.stats["trailing_bytes"] = frames.trailing_bytes
