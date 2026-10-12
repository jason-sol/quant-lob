import gzip
import io

import pytest

from qlob_tools import encode, extract, framing

AAPL, MSFT = 7, 9


def _day() -> list[bytes]:
    """Frames of a two-symbol day, in file order."""
    return [
        encode.frame(encode.system_event(code="O", ts=1)),
        encode.frame(encode.add(ref=99, side="B", shares=1, price=1, stock="AAPL", locate=AAPL, ts=2)),
        encode.frame(encode.stock_directory(stock="AAPL", locate=AAPL, ts=3)),
        encode.frame(encode.stock_directory(stock="MSFT", locate=MSFT, ts=4)),
        encode.frame(encode.stock_directory(stock="AAPLW", locate=11, ts=5)),
        encode.frame(encode.system_event(code="S", ts=6)),
        encode.frame(encode.add(ref=1, side="B", shares=100, price=1_500_000, stock="AAPL", locate=AAPL, ts=7)),
        encode.frame(encode.add(ref=2, side="S", shares=50, price=1_050_000, stock="MSFT", locate=MSFT, ts=8)),
        encode.frame(encode.add(ref=3, side="S", shares=10, price=1, stock="AAPLW", locate=11, ts=9)),
        encode.frame(encode.executed(ref=1, shares=40, match=1, locate=AAPL, ts=10)),
        encode.frame(encode.executed(ref=2, shares=50, match=2, locate=MSFT, ts=11)),
        encode.frame(encode.delete(ref=1, locate=AAPL, ts=12)),
        encode.frame(encode.system_event(code="Q", ts=13)),
        encode.frame(encode.delete(ref=3, locate=11, ts=14)),
        encode.frame(encode.system_event(code="C", ts=15)),
    ]


def _expected(frames: list[bytes], symbol: str, locate: int) -> bytes:
    seen_r = False
    kept = []
    for fr in frames:
        msg = fr[2:]
        t = chr(msg[0])
        loc = int.from_bytes(msg[1:3], "big")
        if t == "R" and msg[11:19] == symbol.encode().ljust(8):
            seen_r = True
            kept.append(fr)
        elif t == "S" or (seen_r and loc == locate):
            kept.append(fr)
    return b"".join(kept)


def test_stock_directory_has_spec_length_and_padded_stock():
    msg = encode.stock_directory(stock="AAPL", locate=AAPL)
    assert len(msg) == 39
    assert msg[0:1] == b"R"
    assert int.from_bytes(msg[1:3], "big") == AAPL
    assert msg[11:19] == b"AAPL    "


@pytest.mark.parametrize("chunk", [1, 3, 7, framing.DEFAULT_CHUNK])
def test_extract_keeps_system_events_directory_and_own_locate(chunk):
    frames = _day()
    out = io.BytesIO()
    stats = extract.extract(io.BytesIO(b"".join(frames)), {"AAPL": out}, chunk_size=chunk)
    assert out.getvalue() == _expected(frames, "AAPL", AAPL)
    assert stats.symbols["AAPL"].locate == AAPL
    assert stats.symbols["AAPL"].frames == 8  # 4 S + R + A + E + D; the pre-R add is dropped


def test_extract_drops_non_system_frames_before_directory():
    frames = _day()
    out = io.BytesIO()
    extract.extract(io.BytesIO(b"".join(frames)), {"AAPL": out})
    assert frames[1] not in out.getvalue()


def test_prefix_symbol_does_not_match_longer_symbol():
    out = io.BytesIO()
    extract.extract(io.BytesIO(b"".join(_day())), {"AAPL": out})
    assert b"AAPLW" not in out.getvalue()


@pytest.mark.parametrize("chunk", [1, 3, 7, framing.DEFAULT_CHUNK])
def test_multi_symbol_single_pass(chunk):
    frames = _day()
    outs = {"AAPL": io.BytesIO(), "MSFT": io.BytesIO()}
    stats = extract.extract(io.BytesIO(b"".join(frames)), outs, chunk_size=chunk)
    assert outs["AAPL"].getvalue() == _expected(frames, "AAPL", AAPL)
    assert outs["MSFT"].getvalue() == _expected(frames, "MSFT", MSFT)
    assert (stats.symbols["MSFT"].locate, stats.symbols["MSFT"].frames) == (MSFT, 7)


def test_unresolved_symbol_has_no_locate_and_only_system_events():
    out = io.BytesIO()
    stats = extract.extract(io.BytesIO(b"".join(_day())), {"SPY": out})
    assert stats.symbols["SPY"].locate is None
    assert stats.symbols["SPY"].frames == 4


def test_trailing_bytes_reported():
    data = b"".join(_day()) + encode.frame(encode.delete(ref=1, locate=AAPL))[:10]
    stats = extract.extract(io.BytesIO(data), {"AAPL": io.BytesIO()})
    assert stats.trailing_bytes == 10


def test_output_name_uses_iso_date_from_nasdaq_filename():
    assert extract.output_name("data/01302019.NASDAQ_ITCH50.gz", "AAPL") == "AAPL-20190130.itch"
    assert extract.output_name("01302019.NASDAQ_ITCH50", "SPY") == "SPY-20190130.itch"


def test_main_reads_gzip_and_writes_one_file_per_symbol(tmp_path, capsys):
    frames = _day()
    src = tmp_path / "01302019.NASDAQ_ITCH50.gz"
    with gzip.open(src, "wb") as f:
        f.write(b"".join(frames))
    assert extract.main([str(src), "--out", str(tmp_path), "AAPL", "MSFT"]) == 0
    assert (tmp_path / "AAPL-20190130.itch").read_bytes() == _expected(frames, "AAPL", AAPL)
    assert (tmp_path / "MSFT-20190130.itch").read_bytes() == _expected(frames, "MSFT", MSFT)
    out = capsys.readouterr().out
    assert "AAPL locate=7 frames=8" in out
    assert "MSFT locate=9 frames=7" in out


def test_main_reads_raw_file(tmp_path):
    frames = _day()
    src = tmp_path / "01302019.NASDAQ_ITCH50"
    src.write_bytes(b"".join(frames))
    assert extract.main([str(src), "--out", str(tmp_path), "AAPL"]) == 0
    assert (tmp_path / "AAPL-20190130.itch").read_bytes() == _expected(frames, "AAPL", AAPL)


def test_main_fails_when_symbol_unresolved(tmp_path):
    src = tmp_path / "01302019.NASDAQ_ITCH50"
    src.write_bytes(b"".join(_day()))
    assert extract.main([str(src), "--out", str(tmp_path), "SPY"]) == 1


def test_main_fails_on_trailing_bytes(tmp_path):
    src = tmp_path / "01302019.NASDAQ_ITCH50"
    src.write_bytes(b"".join(_day()) + b"\x00")
    assert extract.main([str(src), "--out", str(tmp_path), "AAPL"]) == 1


def test_empty_frame_is_rejected():
    data = encode.frame(encode.system_event(code="O")) + b"\x00\x00"
    with pytest.raises(ValueError, match="empty frame at offset 14"):
        extract.extract(io.BytesIO(data), {"AAPL": io.BytesIO()})


def test_short_stock_directory_is_rejected_before_slicing():
    short_r = encode.stock_directory(stock="AAPL", locate=AAPL)[:20]
    data = encode.frame(encode.system_event(code="O")) + encode.frame(short_r)
    with pytest.raises(ValueError, match="R frame at offset 14 has length 20"):
        extract.extract(io.BytesIO(data), {"AAPL": io.BytesIO()})


def test_long_stock_directory_is_rejected():
    long_r = encode.stock_directory(stock="AAPL", locate=AAPL) + b"\x00"
    with pytest.raises(ValueError, match="R frame at offset 0 has length 40"):
        extract.extract(io.BytesIO(encode.frame(long_r)), {"AAPL": io.BytesIO()})


def _outputs(tmp_path) -> set[str]:
    return {p.name for p in tmp_path.iterdir() if not p.name.startswith("01302019")}


def test_main_leaves_no_partial_outputs_when_extract_raises(tmp_path):
    src = tmp_path / "01302019.NASDAQ_ITCH50"
    src.write_bytes(b"".join(_day()) + b"\x00\x00")
    with pytest.raises(ValueError, match="empty frame"):
        extract.main([str(src), "--out", str(tmp_path), "AAPL", "MSFT"])
    assert _outputs(tmp_path) == set()


@pytest.mark.parametrize("symbols, suffix", [(["AAPL", "SPY"], b""), (["AAPL"], b"\x00")])
def test_main_leaves_no_outputs_when_result_is_not_ok(tmp_path, symbols, suffix):
    src = tmp_path / "01302019.NASDAQ_ITCH50"
    src.write_bytes(b"".join(_day()) + suffix)
    assert extract.main([str(src), "--out", str(tmp_path), *symbols]) == 1
    assert _outputs(tmp_path) == set()


def test_main_failure_keeps_existing_output_untouched(tmp_path):
    src = tmp_path / "01302019.NASDAQ_ITCH50"
    src.write_bytes(b"".join(_day()) + b"\x00")
    existing = tmp_path / "AAPL-20190130.itch"
    existing.write_bytes(b"previous run")
    assert extract.main([str(src), "--out", str(tmp_path), "AAPL"]) == 1
    assert existing.read_bytes() == b"previous run"
    assert _outputs(tmp_path) == {"AAPL-20190130.itch"}


def test_main_success_leaves_no_temp_files(tmp_path):
    src = tmp_path / "01302019.NASDAQ_ITCH50"
    src.write_bytes(b"".join(_day()))
    assert extract.main([str(src), "--out", str(tmp_path), "AAPL", "MSFT"]) == 0
    assert _outputs(tmp_path) == {"AAPL-20190130.itch", "MSFT-20190130.itch"}
