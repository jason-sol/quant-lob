import io

import pytest

from qlob_tools import anchor, encode, framing

NS = 1_000_000_000
CLOSE = 16 * 3600 * NS


def _day() -> bytes:
    return b"".join([
        encode.frame(encode.system_event(code="O", ts=1)),
        encode.frame(encode.add(ref=1, side="B", shares=100, price=1_650_000, stock="AAPL", locate=14, ts=2)),
        encode.frame(encode.cross_trade(shares=500, stock="AAPL", price=1_651_200, match=7,
                                        cross_type="O", locate=14, ts=9 * 3600 * NS + 30 * 60 * NS)),
        encode.frame(encode.delete(ref=1, locate=14, ts=3)),
        encode.frame(encode.cross_trade(shares=4_321_000, stock="AAPL", price=1_655_100, match=9,
                                        cross_type="C", locate=14, ts=CLOSE)),
        encode.frame(encode.system_event(code="C", ts=CLOSE + 5)),
    ])


def test_cross_trade_has_spec_layout():
    msg = encode.cross_trade(shares=2**40, stock="AAPL", price=1_655_100, match=2**33,
                             cross_type="C", locate=14, tracking=3, ts=CLOSE)
    assert len(msg) == 40
    assert msg[0:1] == b"Q"
    assert int.from_bytes(msg[1:3], "big") == 14
    assert int.from_bytes(msg[5:11], "big") == CLOSE
    assert int.from_bytes(msg[11:19], "big") == 2**40
    assert msg[19:27] == b"AAPL    "
    assert int.from_bytes(msg[27:31], "big") == 1_655_100
    assert int.from_bytes(msg[31:39], "big") == 2**33
    assert msg[39:40] == b"C"


@pytest.mark.parametrize("chunk", [1, 7, framing.DEFAULT_CHUNK])
def test_cross_trades_decodes_every_q_in_file_order(chunk):
    crosses = anchor.cross_trades(io.BytesIO(_day()), chunk_size=chunk)
    assert crosses == [
        anchor.CrossTrade(ts=9 * 3600 * NS + 30 * 60 * NS, locate=14, stock="AAPL", shares=500,
                          price=1_651_200, match=7, cross_type="O"),
        anchor.CrossTrade(ts=CLOSE, locate=14, stock="AAPL", shares=4_321_000,
                          price=1_655_100, match=9, cross_type="C"),
    ]


def test_cross_trades_empty_when_no_q():
    data = encode.frame(encode.system_event(code="O"))
    assert anchor.cross_trades(io.BytesIO(data)) == []


def test_cross_trades_rejects_wrong_length_q():
    bad = encode.frame(encode.cross_trade(shares=1, stock="AAPL", price=1, match=1, cross_type="C")[:39])
    with pytest.raises(ValueError, match="Q frame at offset 0 has length 39"):
        anchor.cross_trades(io.BytesIO(bad))


def test_cross_trades_rejects_empty_frame():
    data = encode.frame(encode.system_event(code="O")) + b"\x00\x00"
    with pytest.raises(ValueError, match="empty frame at offset 14"):
        anchor.cross_trades(io.BytesIO(data))


def test_closing_cross_picks_type_c():
    crosses = anchor.cross_trades(io.BytesIO(_day()))
    assert anchor.closing_cross(crosses).match == 9


def test_closing_cross_none_when_absent():
    assert anchor.closing_cross([]) is None


def test_format_price_uses_four_implied_decimals():
    assert anchor.format_price(1_655_100) == "165.5100"
    assert anchor.format_price(1) == "0.0001"


def test_main_prints_each_cross(tmp_path, capsys):
    src = tmp_path / "AAPL-20190130.itch"
    src.write_bytes(_day())
    assert anchor.main([str(src)]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out == [
        "type=O ts=34200000000000 time=09:30:00.000000000 stock=AAPL shares=500 price=165.1200 match=7",
        "type=C ts=57600000000000 time=16:00:00.000000000 stock=AAPL shares=4321000 price=165.5100 match=9",
    ]
