"""Closing-cross price anchor: decode ITCH `Q` cross trade messages from an Extract."""

import sys
from dataclasses import dataclass

from qlob_tools import layout
from qlob_tools.framing import DEFAULT_CHUNK, iter_frames, open_source

_Q = ord("Q")


@dataclass(frozen=True)
class CrossTrade:
    ts: int
    locate: int
    stock: str
    shares: int
    price: int
    match: int
    cross_type: str


def cross_trades(src, chunk_size: int = DEFAULT_CHUNK) -> list[CrossTrade]:
    found = []
    with open_source(src) as f:
        for off, msg in iter_frames(f, chunk_size):
            if not msg:
                raise ValueError(f"empty frame at offset {off}")
            if msg[0] != _Q:
                continue
            if len(msg) != layout.CROSS_TRADE.size:
                raise ValueError(f"Q frame at offset {off} has length {len(msg)}")
            _, locate, _, ts_hi, ts_lo, shares, stock, price, match, kind = layout.CROSS_TRADE.unpack(msg)
            found.append(CrossTrade(ts=layout.join_ts(ts_hi, ts_lo), locate=locate,
                                    stock=stock.decode().rstrip(), shares=shares, price=price,
                                    match=match, cross_type=kind.decode()))
    return found


def closing_cross(crosses: list[CrossTrade]) -> CrossTrade | None:
    return next((c for c in crosses if c.cross_type == "C"), None)


def format_price(price: int) -> str:
    return f"{price // 10_000}.{price % 10_000:04d}"


def format_time(ts: int) -> str:
    secs, ns = divmod(ts, 1_000_000_000)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}.{ns:09d}"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: python -m qlob_tools.anchor <extract>", file=sys.stderr)
        return 2
    for c in cross_trades(argv[0]):
        print(f"type={c.cross_type} ts={c.ts} time={format_time(c.ts)} stock={c.stock} "
              f"shares={c.shares} price={format_price(c.price)} match={c.match}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
