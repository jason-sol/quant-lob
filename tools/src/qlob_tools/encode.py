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


def system_event(*, code: str, ts: int = 0, locate: int = 0, tracking: int = 0) -> bytes:
    return layout.SYSTEM_EVENT.pack(*_hdr("S", locate, tracking, ts), code.encode())


def frame(msg: bytes) -> bytes:
    return layout.LENGTH_PREFIX.pack(len(msg)) + msg
