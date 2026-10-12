import io

import pytest

from qlob_tools import encode, framing


def _three_msgs() -> bytes:
    return b"".join(
        [
            encode.frame(encode.add(ref=1, side="B", shares=100, price=1_000_000, ts=1)),
            encode.frame(encode.add_mpid(ref=2, side="S", shares=50, price=1_010_000, ts=2, attribution="ABCD")),
            encode.frame(encode.delete(ref=1, ts=3)),
        ]
    )


def test_encoded_add_has_spec_length():
    assert len(encode.add(ref=1, side="B", shares=1, price=1)) == 36
    assert len(encode.add_mpid(ref=1, side="B", shares=1, price=1)) == 40
    assert len(encode.delete(ref=1)) == 19
    assert len(encode.system_event(code="O")) == 12


def test_frame_stream_yields_offsets_and_bodies():
    data = _three_msgs()
    frames = list(framing.FrameStream(io.BytesIO(data)))
    assert [chr(m[0]) for _, m in frames] == ["A", "F", "D"]
    assert [off for off, _ in frames] == [0, 38, 80]


def test_scan_counts_types():
    result = framing.scan(io.BytesIO(_three_msgs()))
    assert result == {
        "count_A": 1,
        "count_D": 1,
        "count_F": 1,
        "empty_frames": 0,
        "first_bad_offset": "none",
        "trailing_bytes": 0,
        "unknown_type": 0,
    }


def test_scan_counts_two_adds_one_delete():
    data = b"".join(
        [
            encode.frame(encode.add(ref=1, side="B", shares=100, price=1)),
            encode.frame(encode.add(ref=2, side="S", shares=100, price=2)),
            encode.frame(encode.delete(ref=1)),
        ]
    )
    result = framing.scan(io.BytesIO(data))
    assert {k: v for k, v in result.items() if k.startswith("count_")} == {"count_A": 2, "count_D": 1}


def test_short_add_is_length_mismatch():
    good = encode.frame(encode.delete(ref=9))
    short = encode.frame(encode.add(ref=1, side="B", shares=1, price=1)[:30])
    result = framing.scan(io.BytesIO(good + short))
    assert result["length_mismatch_A"] == 1
    assert result["first_bad_offset"] == len(good)


def test_unknown_type_counted():
    result = framing.scan(io.BytesIO(encode.frame(b"Z" + bytes(10))))
    assert result["unknown_type"] == 1
    assert result["first_bad_offset"] == 0


def test_truncated_body_is_trailing_bytes():
    full = encode.frame(encode.add(ref=1, side="B", shares=1, price=1))
    data = encode.frame(encode.delete(ref=1)) + full[:20]
    result = framing.scan(io.BytesIO(data))
    assert result["count_D"] == 1
    assert "count_A" not in result
    assert result["trailing_bytes"] == 20


def test_lone_length_byte_is_trailing():
    result = framing.scan(io.BytesIO(encode.frame(encode.delete(ref=1)) + b"\x00"))
    assert result["trailing_bytes"] == 1


def test_empty_frame_counted():
    data = b"\x00\x00" + encode.frame(encode.delete(ref=1))
    result = framing.scan(io.BytesIO(data))
    assert result["empty_frames"] == 1
    assert result["count_D"] == 1


def test_empty_input():
    result = framing.scan(io.BytesIO(b""))
    assert result == {"empty_frames": 0, "first_bad_offset": "none", "trailing_bytes": 0, "unknown_type": 0}


@pytest.mark.parametrize("chunk", [1, 2, 3, 7])
def test_chunk_size_does_not_change_result(chunk):
    data = (
        _three_msgs()
        + b"\x00\x00"
        + encode.frame(encode.system_event(code="O"))
        + encode.frame(encode.add(ref=5, side="B", shares=1, price=1)[:30])
        + encode.frame(encode.delete(ref=4))[:10]
    )
    default = framing.scan(io.BytesIO(data))
    assert framing.scan(io.BytesIO(data), chunk_size=chunk) == default
    assert list(framing.FrameStream(io.BytesIO(data), chunk_size=chunk)) == list(
        framing.FrameStream(io.BytesIO(data))
    )


def test_scan_accepts_path(tmp_path):
    p = tmp_path / "f.itch"
    p.write_bytes(_three_msgs())
    assert framing.scan(p)["count_A"] == 1
    assert framing.scan(str(p))["count_A"] == 1


def test_format_is_sorted_key_value():
    text = framing.format_result({"unknown_type": 0, "count_A": 2, "empty_frames": 0})
    assert text == "count_A=2\nempty_frames=0\nunknown_type=0\n"


def test_main_prints_scan(tmp_path, capsys):
    p = tmp_path / "f.itch"
    p.write_bytes(_three_msgs())
    assert framing.main([str(p)]) == 0
    assert capsys.readouterr().out == framing.format_result(framing.scan(p))


def test_unknown_type_also_counted_by_type_byte():
    result = framing.scan(io.BytesIO(encode.frame(b"Z" + bytes(10))))
    assert result["count_Z"] == 1
    assert result["unknown_type"] == 1


def test_empty_frame_is_first_bad():
    data = encode.frame(encode.delete(ref=1)) + b"\x00\x00" + encode.frame(b"Z" + bytes(3))
    assert framing.scan(io.BytesIO(data))["first_bad_offset"] == 21


def test_truncated_final_frame_does_not_set_first_bad():
    full = encode.frame(encode.add(ref=1, side="B", shares=1, price=1))
    result = framing.scan(io.BytesIO(encode.frame(encode.delete(ref=1)) + full[:20]))
    assert result["trailing_bytes"] == 20
    assert result["first_bad_offset"] == "none"
