"""Fixture encoder for ITCH 5.0 messages."""

from qlob_tools import layout


def _hdr(type_: str, locate: int, tracking: int, ts: int) -> tuple:
    return (type_.encode(), locate, tracking, *layout.split_ts(ts))


def header(type_: str, *, locate: int = 1, tracking: int = 0, ts: int = 0) -> bytes:
    return layout.HEADER.pack(*_hdr(type_, locate, tracking, ts))


def add(*, ref: int, side: str, shares: int, price: int, ts: int = 0,
        stock: str = "TEST", locate: int = 1, tracking: int = 0) -> bytes:
    return layout.ADD.pack(*_hdr("A", locate, tracking, ts), ref, side.encode(),
                           shares, stock.encode().ljust(8), price)


def add_mpid(*, ref: int, side: str, shares: int, price: int, ts: int = 0,
             stock: str = "TEST", attribution: str = "MPID", locate: int = 1,
             tracking: int = 0) -> bytes:
    return layout.ADD_MPID.pack(*_hdr("F", locate, tracking, ts), ref, side.encode(),
                                shares, stock.encode().ljust(8), price,
                                attribution.encode().ljust(4))


def delete(*, ref: int, ts: int = 0, locate: int = 1, tracking: int = 0) -> bytes:
    return layout.DELETE.pack(*_hdr("D", locate, tracking, ts), ref)


def executed(*, ref: int, shares: int, match: int, ts: int = 0, locate: int = 1,
             tracking: int = 0) -> bytes:
    return layout.EXECUTED.pack(*_hdr("E", locate, tracking, ts), ref, shares, match)


def executed_with_price(*, ref: int, shares: int, match: int, printable: str, price: int,
                        ts: int = 0, locate: int = 1, tracking: int = 0) -> bytes:
    return layout.EXECUTED_WITH_PRICE.pack(*_hdr("C", locate, tracking, ts), ref, shares, match,
                                           printable.encode(), price)


def cancel(*, ref: int, shares: int, ts: int = 0, locate: int = 1, tracking: int = 0) -> bytes:
    return layout.CANCEL.pack(*_hdr("X", locate, tracking, ts), ref, shares)


def replace(*, orig_ref: int, new_ref: int, shares: int, price: int, ts: int = 0,
            locate: int = 1, tracking: int = 0) -> bytes:
    return layout.REPLACE.pack(*_hdr("U", locate, tracking, ts), orig_ref, new_ref, shares, price)


def system_event(*, code: str, ts: int = 0, locate: int = 0, tracking: int = 0) -> bytes:
    return layout.SYSTEM_EVENT.pack(*_hdr("S", locate, tracking, ts), code.encode())


def stock_directory(*, stock: str, locate: int, ts: int = 0, tracking: int = 0) -> bytes:
    return layout.STOCK_DIRECTORY.pack(*_hdr("R", locate, tracking, ts), stock.encode().ljust(8),
                                       b"Q", b"N", 100, b"N", b"C", b"Z ", b"P", b"N", b"N",
                                       b"1", b"N", 0, b"N")


def cross_trade(*, shares: int, stock: str, price: int, match: int, cross_type: str,
                ts: int = 0, locate: int = 1, tracking: int = 0) -> bytes:
    return layout.CROSS_TRADE.pack(*_hdr("Q", locate, tracking, ts), shares, stock.encode().ljust(8),
                                   price, match, cross_type.encode())


def frame(msg: bytes) -> bytes:
    return layout.LENGTH_PREFIX.pack(len(msg)) + msg
