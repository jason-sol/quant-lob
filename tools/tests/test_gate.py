import io
import os
import random
import subprocess
import sys
import textwrap

import pytest

from qlob_tools import encode, framing, gate

NS = 1_000_000_000
OPEN = 9 * 3600 * NS + 30 * 60 * NS
CLOSE = 16 * 3600 * NS

REPLAY = os.environ.get("QLOB_REPLAY")
needs_replay = pytest.mark.skipif(not REPLAY, reason="QLOB_REPLAY not set")


def build_fixture(seed: int = 1, n_events: int = 200) -> bytes:
    rng = random.Random(seed)
    live: list[int] = []
    next_ref = 1
    ts = 8 * 3600 * NS
    step = (17 * 3600 * NS - ts) // n_events
    out = [encode.frame(encode.system_event(code="O", ts=ts))]
    for i in range(n_events):
        ts += rng.randint(1, 2 * step - 1)
        roll = rng.random()
        if live and roll < 0.30:
            ref = live.pop(rng.randrange(len(live)))
            out.append(encode.frame(encode.delete(ref=ref, ts=ts)))
        elif roll < 0.34:
            out.append(encode.frame(encode.delete(ref=900_000 + i, ts=ts)))
        elif live and roll < 0.38:
            ref = rng.choice(live)
            out.append(encode.frame(encode.add(ref=ref, side="B", shares=rng.randint(0, 9), price=990_000, ts=ts)))
        elif roll < 0.42:
            out.append(encode.frame(encode.add(ref=800_000 + i, side="S", shares=0, price=1_010_000, ts=ts)))
        else:
            side = rng.choice("BS")
            offset = rng.randint(-2, 8) * 100
            price = 1_000_000 - offset if side == "B" else 1_000_000 + offset
            shares = rng.choice([1, 100, 200, 500, rng.randint(1, 10_000)])
            ref = next_ref
            next_ref += 1
            live.append(ref)
            if rng.random() < 0.3:
                msg = encode.add_mpid(ref=ref, side=side, shares=shares, price=price, ts=ts, attribution="GSCO")
            else:
                msg = encode.add(ref=ref, side=side, shares=shares, price=price, ts=ts)
            out.append(encode.frame(msg))
        if i % 50 == 0:
            out.append(encode.frame(encode.system_event(code="Q", ts=ts)))
    return b"".join(out)


# rng.sample never yields new_ref == orig_ref, so self-replaces are placed explicitly.
SELF_REPLACE_LIVE_AT = (1234, 3456)
SELF_REPLACE_UNKNOWN_AT = (2345, 4567)


def build_full_fixture(seed: int = 2, n_events: int = 5000) -> bytes:
    """All seven book types; refs drawn from live ids; ~1% unknown/duplicate/zero-qty Events."""
    rng = random.Random(seed)
    live: dict[int, tuple[str, int]] = {}  # ref -> (side, qty), as the fixture expects the Book to hold
    next_ref = 1
    unknown_ref = 900_000_000
    ts = 8 * 3600 * NS
    step = (17 * 3600 * NS - ts) // n_events
    out = [encode.frame(encode.system_event(code="O", ts=ts))]

    def price_for(side: str) -> int:
        offset = rng.randint(-2, 8) * 100
        return 1_000_000 - offset if side == "B" else 1_000_000 + offset

    def reduce_shares(qty: int) -> int:
        r = rng.random()
        if r < 0.45:
            return qty
        if r < 0.47:
            return qty + rng.randint(1, 50)
        return rng.randint(1, max(1, qty - 1))

    for i in range(n_events):
        ts += rng.randint(1, 2 * step - 1)
        roll = rng.random()
        if i in SELF_REPLACE_LIVE_AT and live:
            ref = rng.choice(list(live))
            out.append(encode.frame(encode.replace(orig_ref=ref, new_ref=ref, shares=rng.randint(1, 9),
                                                   price=1_000_000, ts=ts)))
        elif i in SELF_REPLACE_UNKNOWN_AT:
            unknown_ref += 1
            out.append(encode.frame(encode.replace(orig_ref=unknown_ref, new_ref=unknown_ref, shares=5,
                                                   price=1_000_000, ts=ts)))
        elif roll < 0.01:
            kind = rng.choice(["E", "C", "X", "D", "U", "dupA", "dupU", "zeroA", "zeroU"])
            unknown_ref += 1
            any_live = rng.choice(list(live)) if live else None
            if kind == "E":
                msg = encode.executed(ref=unknown_ref, shares=10, match=i, ts=ts)
            elif kind == "C":
                msg = encode.executed_with_price(ref=unknown_ref, shares=10, match=i, printable="Y", price=1, ts=ts)
            elif kind == "X":
                msg = encode.cancel(ref=unknown_ref, shares=10, ts=ts)
            elif kind == "D":
                msg = encode.delete(ref=unknown_ref, ts=ts)
            elif kind == "U":
                msg = encode.replace(orig_ref=unknown_ref, new_ref=next_ref, shares=10, price=1_000_000, ts=ts)
            elif kind == "dupA" and live:
                msg = encode.add(ref=any_live, side="S", shares=rng.randint(0, 9), price=1_010_000, ts=ts)
            elif kind == "dupU" and len(live) >= 2:
                orig, new = rng.sample(list(live), 2)
                msg = encode.replace(orig_ref=orig, new_ref=new, shares=rng.randint(0, 9), price=1_000_000, ts=ts)
            elif kind == "zeroU" and live:
                msg = encode.replace(orig_ref=any_live, new_ref=next_ref, shares=0, price=1_000_000, ts=ts)
            else:
                msg = encode.add(ref=next_ref, side="B", shares=0, price=990_000, ts=ts)
            out.append(encode.frame(msg))
        elif not live or roll < 0.35:
            side = rng.choice("BS")
            shares = rng.choice([1, 100, 200, 500, rng.randint(1, 10_000)])
            ref = next_ref
            next_ref += 1
            live[ref] = (side, shares)
            if rng.random() < 0.3:
                msg = encode.add_mpid(ref=ref, side=side, shares=shares, price=price_for(side), ts=ts,
                                      attribution="GSCO")
            else:
                msg = encode.add(ref=ref, side=side, shares=shares, price=price_for(side), ts=ts)
            out.append(encode.frame(msg))
        else:
            ref = rng.choice(list(live))
            side, qty = live[ref]
            kind = rng.choices("ECXDU", weights=[25, 10, 25, 20, 20])[0]
            if kind in "ECX":
                shares = reduce_shares(qty)
                if kind == "E":
                    msg = encode.executed(ref=ref, shares=shares, match=i, ts=ts)
                elif kind == "C":
                    msg = encode.executed_with_price(ref=ref, shares=shares, match=i, printable=rng.choice("YN"),
                                                     price=rng.randint(1, 2_000_000), ts=ts)
                else:
                    msg = encode.cancel(ref=ref, shares=shares, ts=ts)
                if shares >= qty:
                    del live[ref]
                else:
                    live[ref] = (side, qty - shares)
            elif kind == "D":
                msg = encode.delete(ref=ref, ts=ts)
                del live[ref]
            else:
                new_qty = rng.choice([1, 100, 300, rng.randint(1, 5_000)])
                msg = encode.replace(orig_ref=ref, new_ref=next_ref, shares=new_qty, price=price_for(side), ts=ts)
                del live[ref]
                live[next_ref] = (side, new_qty)
                next_ref += 1
            out.append(encode.frame(msg))
        if i % 50 == 0:
            out.append(encode.frame(encode.system_event(code="Q", ts=ts)))
    return b"".join(out)


def test_full_fixture_is_deterministic_and_exercises_every_type_and_counter(tmp_path):
    data = build_full_fixture()
    assert data == build_full_fixture()
    p = tmp_path / "full.itch"
    p.write_bytes(data)
    counts = framing.scan(p)
    for t in "AFECXDU":
        assert counts[f"count_{t}"] > 0, t
    r = gate.ref_book.replay(p, 5)
    rows = list(r)[1:]
    stats = r.stats
    assert stats["events"] == len(rows) == 5000
    anomalies = stats["unknown_order_refs"] + stats["duplicate_order_refs"] + stats["zero_qty_adds"]
    assert 20 <= anomalies <= 100
    for k in ("unknown_order_refs", "duplicate_order_refs", "zero_qty_adds", "excess_reductions"):
        assert stats[k] > 0, k
    assert _self_replaces(data) == {"live": 2, "unknown": 2}


def _self_replaces(data: bytes) -> dict[str, int]:
    """Count Replaces with new_ref == orig_ref, split by whether the original was live at that point."""
    book = gate.ref_book.RefBook()
    seen = {"live": 0, "unknown": 0}
    with framing.open_source(io.BytesIO(data)) as f:
        for _, msg in framing.FrameStream(f):
            ev = gate.ref_book.decode(msg)
            if ev is None:
                continue
            if isinstance(ev, gate.ref_book.Replace) and ev.new_ref == ev.orig_ref:
                seen["live" if ev.orig_ref in book.orders else "unknown"] += 1
            gate.ref_book._apply(book, ev)
    return seen


def test_fixture_is_deterministic_and_exercises_edge_cases(tmp_path):
    data = build_fixture()
    assert data == build_fixture()
    p = tmp_path / "f.itch"
    p.write_bytes(data)
    r = gate.ref_book.replay(p, 3)
    list(r)
    stats = r.stats
    assert stats["events"] == 200
    assert stats["unknown_order_refs"] > 0
    assert stats["duplicate_order_refs"] > 0
    assert stats["zero_qty_adds"] > 0


@pytest.mark.parametrize(
    ("ts", "bucket"),
    [(0, "pre_open"), (OPEN - 1, "pre_open"), (OPEN, "regular"), (CLOSE - 1, "regular"), (CLOSE, "post_close")],
)
def test_session_bucket(ts, bucket):
    assert gate.session_bucket(ts) == bucket


@pytest.mark.parametrize(
    ("row", "crossed"),
    [
        ("0,1,100,5,100,5", True),
        ("0,1,101,5,100,5", True),
        ("0,1,99,5,100,5", False),
        ("0,1,0,0,100,5", False),
        ("0,1,100,5,0,0", False),
    ],
)
def test_is_crossed(row, crossed):
    assert gate.is_crossed(row) is crossed


def test_parse_counters():
    assert gate.parse_counters("zero_qty_adds=2\nevents=1\n\n") == {"events": 1, "zero_qty_adds": 2}


def test_parse_counters_accepts_full_cpp_key_set():
    text = ("decode_rejects=1\nduplicate_order_refs=2\nevents=3\nexcess_reductions=5\nexec_not_at_front=4\n"
            "exec_with_price_not_at_front=9\ntrailing_bytes=6\nunknown_order_refs=7\nzero_qty_adds=8\n")
    assert gate.parse_counters(text) == {
        "decode_rejects": 1, "duplicate_order_refs": 2, "events": 3, "excess_reductions": 5,
        "exec_not_at_front": 4, "exec_with_price_not_at_front": 9, "trailing_bytes": 6,
        "unknown_order_refs": 7, "zero_qty_adds": 8,
    }


def test_parse_counters_rejects_retired_overfills_key():
    assert gate.parse_counters("overfills=1\nevents=2\n") == {"events": 2}


def test_parse_counters_ignores_unknown_keys_and_non_int_values():
    text = "error: bad arg=--depth\nevents=x\nfoo=3\nevents=4\n"
    assert gate.parse_counters(text) == {"events": 4}


def test_other_stderr_lines_kept():
    assert gate.other_stderr_lines("events=1\nerror: open failed=yes\n\n") == ["error: open failed=yes"]


def _fake_replay(tmp_path, rows: list[str], stderr: str, exit_code: int = 0):
    return _fake_script(
        tmp_path,
        f"""\
        import sys
        sys.stdout.write({"".join(r + chr(10) for r in rows)!r})
        sys.stderr.write({stderr!r})
        sys.exit({exit_code})
        """,
    )


def _fake_script(tmp_path, body: str):
    script = tmp_path / "fake_replay.py"
    script.write_text(textwrap.dedent(body))
    wrapper = tmp_path / "fake_replay"
    wrapper.write_text(f"#!/bin/sh\nexec {sys.executable} {script} \"$@\"\n")
    wrapper.chmod(0o755)
    return str(wrapper)


def _fixture_file(tmp_path):
    p = tmp_path / "f.itch"
    p.write_bytes(
        b"".join(
            encode.frame(m)
            for m in [
                encode.add(ref=1, side="B", shares=10, price=100, ts=OPEN - 5),
                encode.add(ref=2, side="S", shares=10, price=100, ts=OPEN + 5),
                encode.delete(ref=1, ts=CLOSE + 5),
            ]
        )
    )
    return p


REF_STDERR = ("decode_rejects=0\nduplicate_order_refs=0\nevents=3\nexcess_reductions=0\nexec_not_at_front=0\n"
              "exec_with_price_not_at_front=0\ntrailing_bytes=0\nunknown_order_refs=0\nzero_qty_adds=0\n")


def test_run_against_matching_fake(tmp_path):
    p = _fixture_file(tmp_path)
    expected = list(gate.ref_book.replay(p, 1))
    fake = _fake_replay(tmp_path, expected, REF_STDERR)
    result = gate.run(p, 1, fake, allow_anomalies=True)
    assert result["rows_ref"] == result["rows_cpp"] == 3
    assert result["mismatches"] == 0
    assert result["first_mismatch"] is None
    assert result["counters_equal"] is True
    assert result["crossed"] == {"pre_open": 0, "regular": 1, "post_close": 0}
    assert result["ok"] is True


def test_run_reports_first_mismatch(tmp_path):
    p = _fixture_file(tmp_path)
    expected = list(gate.ref_book.replay(p, 1))
    bad = expected[:2] + ["1,999,0,0,0,0", "2,999,0,0,0,0"]
    result = gate.run(p, 1, _fake_replay(tmp_path, bad, REF_STDERR))
    assert result["mismatches"] == 2
    assert result["first_mismatch"]["seq"] == 1
    assert result["first_mismatch"]["ref"] == expected[2]
    assert result["first_mismatch"]["cpp"] == "1,999,0,0,0,0"
    assert result["ok"] is False


def test_run_counts_missing_rows_and_counter_drift(tmp_path):
    p = _fixture_file(tmp_path)
    expected = list(gate.ref_book.replay(p, 1))
    result = gate.run(p, 1, _fake_replay(tmp_path, expected[:-1], REF_STDERR.replace("events=3", "events=2")))
    assert result["mismatches"] == 1
    assert result["first_mismatch"]["cpp"] is None
    assert result["counters_equal"] is False
    assert result["ok"] is False


def test_main_exit_code_follows_gate(tmp_path, capsys):
    p = _fixture_file(tmp_path)
    expected = list(gate.ref_book.replay(p, 1))
    args = [str(p), "--depth", "1", "--allow-anomalies", "--replay"]
    assert gate.main(args + [_fake_replay(tmp_path, expected, REF_STDERR)]) == 0
    assert "mismatches=0" in capsys.readouterr().out
    assert gate.main(args + [_fake_replay(tmp_path, expected[:-1], REF_STDERR)]) == 1


@needs_replay
def test_gate_against_cpp_replay(tmp_path):
    p = tmp_path / "fixture.itch"
    p.write_bytes(build_fixture())
    result = gate.run(p, 5, REPLAY, allow_anomalies=True)
    assert result["rows_ref"] == result["rows_cpp"] == 200
    assert result["mismatches"] == 0, result["first_mismatch"]
    assert result["counters_equal"] is True
    assert result["ok"] is True


@needs_replay
def test_gate_full_message_set_against_cpp_replay(tmp_path):
    p = tmp_path / "full.itch"
    p.write_bytes(build_full_fixture())
    result = gate.run(p, 5, REPLAY, allow_anomalies=True)
    assert result["rows_ref"] == result["rows_cpp"] == 5000
    assert result["mismatches"] == 0, result["first_mismatch"]
    assert result["counters_equal"] is True
    assert result["ok"] is True


@needs_replay
def test_count_matches_cpp(tmp_path):
    p = tmp_path / "fixture.itch"
    p.write_bytes(build_fixture())
    cpp = subprocess.run([REPLAY, str(p), "--count"], capture_output=True, text=True, check=True)
    assert framing.format_result(framing.scan(p)) == cpp.stdout


def build_malformed_fixture() -> bytes:
    return b"".join(
        [
            encode.frame(encode.add(ref=1, side="B", shares=10, price=100, ts=1)),
            encode.frame(encode.add(ref=2, side="S", shares=10, price=200, ts=2)[:30]),
            b"\x00\x00",
            encode.frame(b"Z" + bytes(5)),
            encode.frame(encode.delete(ref=1, ts=3)),
            encode.frame(encode.add(ref=3, side="B", shares=1, price=1))[:20],
        ]
    )


@needs_replay
def test_malformed_count_matches_cpp(tmp_path):
    p = tmp_path / "malformed.itch"
    p.write_bytes(build_malformed_fixture())
    cpp = subprocess.run([REPLAY, str(p), "--count"], capture_output=True, text=True, check=True)
    assert framing.format_result(framing.scan(p)) == cpp.stdout


def test_run_reports_row_counts_per_side(tmp_path):
    p = _fixture_file(tmp_path)
    expected = list(gate.ref_book.replay(p, 1))
    result = gate.run(p, 1, _fake_replay(tmp_path, expected[:-1], REF_STDERR))
    assert result["rows_ref"] == 3
    assert result["rows_cpp"] == 2


def test_truncated_cpp_row_fails_gate_without_traceback(tmp_path):
    p = _fixture_file(tmp_path)
    expected = list(gate.ref_book.replay(p, 1))
    result = gate.run(p, 1, _fake_replay(tmp_path, expected[:2] + ["1,5"] + expected[3:], REF_STDERR))
    assert result["ok"] is False
    assert result["first_mismatch"] == {"seq": 1, "ref": expected[2], "cpp": "1,5"}
    assert result["crossed"] == {"pre_open": 0, "regular": 1, "post_close": 0}


def test_nonzero_exit_summary_shows_stderr_and_headers(tmp_path):
    p = _fixture_file(tmp_path)
    fake = _fake_replay(tmp_path, ["bogus,header"], "error: cannot open file=f.itch\n", exit_code=3)
    result = gate.run(p, 1, fake)
    assert result["ok"] is False
    assert result["returncode"] == 3
    assert result["cpp_counters"] == {}
    summary = gate.format_summary(result)
    assert "error: cannot open file=f.itch" in summary
    assert "bogus,header" in summary
    assert gate.ref_book.header(1) in summary


def test_child_is_reaped_when_gate_aborts(tmp_path, monkeypatch):
    spawned = []

    class RecordingPopen(subprocess.Popen):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            spawned.append(self)

    monkeypatch.setattr(gate.subprocess, "Popen", RecordingPopen)
    endless = _fake_script(
        tmp_path,
        """\
        import sys
        while True:
            sys.stdout.write("0,0,0,0,0,0\\n")
        """,
    )
    with pytest.raises(FileNotFoundError):
        gate.run(tmp_path / "missing.itch", 1, endless)
    assert len(spawned) == 1
    assert spawned[0].poll() is not None


def _write(tmp_path, msgs, tail: bytes = b"", name: str = "s.itch"):
    p = tmp_path / name
    p.write_bytes(b"".join(encode.frame(m) for m in msgs) + tail)
    return p


def _clean_msgs():
    return [
        encode.add(ref=1, side="B", shares=10, price=99, ts=OPEN + 1),
        encode.add(ref=2, side="S", shares=10, price=101, ts=OPEN + 2),
    ]


def _mirror_replay(tmp_path, p, depth: int = 1,
                   cpp_extra: str = "exec_not_at_front=0\nexec_with_price_not_at_front=0\n"):
    """Fake C++ binary that reproduces the Reference Book exactly, plus C++-only counters."""
    r = gate.ref_book.replay(p, depth)
    rows = list(r)
    stderr = "".join(f"{k}={v}\n" for k, v in r.stats.items()) + cpp_extra
    return _fake_replay(tmp_path, rows, stderr)


def test_clean_fixture_passes_strict_gate(tmp_path):
    p = _write(tmp_path, _clean_msgs())
    result = gate.run(p, 1, _mirror_replay(tmp_path, p))
    assert result["strict_failures"] == []
    assert result["ok"] is True


@pytest.mark.parametrize(
    ("extra", "tail", "failure"),
    [
        ([encode.delete(ref=99, ts=OPEN + 3)], b"", "unknown_order_refs=1"),
        ([encode.add(ref=1, side="B", shares=5, price=98, ts=OPEN + 3)], b"", "duplicate_order_refs=1"),
        ([encode.add(ref=3, side="B", shares=0, price=98, ts=OPEN + 3)], b"", "zero_qty_adds=1"),
        ([encode.cancel(ref=1, shares=11, ts=OPEN + 3)], b"", "excess_reductions=1"),
        ([encode.add(ref=3, side="Z", shares=5, price=98, ts=OPEN + 3)], b"", "decode_rejects=1"),
        ([], b"\x00\x24AB", "trailing_bytes=4"),
    ],
    ids=["unknown", "duplicate", "zero_qty", "excess", "decode_reject", "trailing"],
)
def test_anomaly_fails_strict_gate_and_passes_with_allow_anomalies(tmp_path, extra, tail, failure):
    p = _write(tmp_path, _clean_msgs() + extra, tail)
    fake = _mirror_replay(tmp_path, p)
    strict = gate.run(p, 1, fake)
    assert strict["mismatches"] == 0
    assert strict["counters_equal"] is True
    assert strict["strict_failures"] == [failure]
    assert strict["ok"] is False
    assert gate.run(p, 1, fake, allow_anomalies=True)["ok"] is True


def test_crossed_regular_hours_row_fails_strict_gate(tmp_path):
    p = _fixture_file(tmp_path)
    fake = _mirror_replay(tmp_path, p)
    result = gate.run(p, 1, fake)
    assert result["strict_failures"] == ["crossed_regular=1"]
    assert result["ok"] is False
    assert gate.run(p, 1, fake, allow_anomalies=True)["ok"] is True


def test_crossed_rows_outside_regular_hours_do_not_fail_strict_gate(tmp_path):
    p = _write(tmp_path, [
        encode.add(ref=1, side="B", shares=10, price=100, ts=OPEN - 2),
        encode.add(ref=2, side="S", shares=10, price=100, ts=OPEN - 1),
        encode.delete(ref=2, ts=OPEN),
        encode.add(ref=3, side="S", shares=10, price=100, ts=CLOSE),
    ])
    result = gate.run(p, 1, _mirror_replay(tmp_path, p))
    assert result["crossed"] == {"pre_open": 1, "regular": 0, "post_close": 1}
    assert result["strict_failures"] == []
    assert result["ok"] is True


def test_cpp_exec_not_at_front_is_not_compared_but_fails_strict_gate(tmp_path):
    p = _write(tmp_path, _clean_msgs())
    fake = _mirror_replay(tmp_path, p, cpp_extra="exec_not_at_front=2\n")
    result = gate.run(p, 1, fake)
    assert result["cpp_counters"]["exec_not_at_front"] == 2
    assert "exec_not_at_front" not in result["ref_counters"]
    assert result["counters_equal"] is True
    assert result["strict_failures"] == ["exec_not_at_front=2"]
    assert result["ok"] is False
    assert gate.run(p, 1, fake, allow_anomalies=True)["ok"] is True


@pytest.mark.parametrize("allow_anomalies", [False, True])
def test_missing_exec_not_at_front_fails_gate_even_with_allow_anomalies(tmp_path, allow_anomalies):
    p = _write(tmp_path, _clean_msgs())
    fake = _mirror_replay(tmp_path, p, cpp_extra="exec_with_price_not_at_front=0\n")
    result = gate.run(p, 1, fake, allow_anomalies=allow_anomalies)
    assert result["counters_equal"] is True
    assert result["missing_cpp_keys"] == ["exec_not_at_front"]
    assert result["ok"] is False
    assert "missing_cpp_key: exec_not_at_front" in gate.format_summary(result)


def test_strict_mode_does_not_rescue_a_mismatch(tmp_path):
    p = _write(tmp_path, _clean_msgs())
    rows = list(gate.ref_book.replay(p, 1))
    fake = _fake_replay(tmp_path, rows[:-1] + ["1,999,0,0,0,0"], REF_STDERR.replace("events=3", "events=2"))
    assert gate.run(p, 1, fake, allow_anomalies=True)["ok"] is False


def test_cli_names_failed_strict_criterion(tmp_path, capsys):
    p = _fixture_file(tmp_path)
    fake = _mirror_replay(tmp_path, p)
    assert gate.main([str(p), "--depth", "1", "--replay", fake]) == 1
    out = capsys.readouterr().out
    assert "strict_fail: crossed_regular=1" in out
    assert "GATE FAIL" in out
    assert gate.main([str(p), "--depth", "1", "--replay", fake, "--allow-anomalies"]) == 0
    out = capsys.readouterr().out
    assert "anomaly_allowed: crossed_regular=1" in out
    assert "GATE PASS" in out


@needs_replay
def test_clean_fixture_passes_strict_gate_against_cpp_replay(tmp_path):
    p = _write(tmp_path, _clean_msgs() + [
        encode.executed(ref=1, shares=4, match=1, ts=OPEN + 3),
        encode.cancel(ref=2, shares=10, ts=OPEN + 4),
        encode.replace(orig_ref=1, new_ref=5, shares=7, price=98, ts=OPEN + 5),
        encode.delete(ref=5, ts=OPEN + 6),
    ])
    result = gate.run(p, 3, REPLAY)
    assert result["strict_failures"] == []
    assert result["ok"] is True


@needs_replay
def test_decode_rejects_match_cpp_replay(tmp_path):
    p = _write(tmp_path, [
        encode.add(ref=1, side="B", shares=10, price=99, ts=OPEN + 1),
        encode.add(ref=2, side="S", shares=10, price=101, ts=OPEN + 2)[:35],
        encode.executed(ref=1, shares=1, match=1, ts=OPEN + 3) + b"\x00",
        encode.add(ref=3, side="Z", shares=10, price=100, ts=OPEN + 4),
        encode.delete(ref=1, ts=OPEN + 5),
    ])
    result = gate.run(p, 2, REPLAY, allow_anomalies=True)
    assert result["mismatches"] == 0, result["first_mismatch"]
    assert result["rows_cpp"] == 2
    assert result["cpp_counters"]["decode_rejects"] == 3
    assert result["counters_equal"] is True
    assert result["strict_failures"] == ["decode_rejects=3"]
    assert result["ok"] is True


def test_summary_reports_cpp_only_counter_without_diff(tmp_path):
    p = _write(tmp_path, _clean_msgs())
    summary = gate.format_summary(gate.run(p, 1, _mirror_replay(tmp_path, p)))
    assert "counter exec_not_at_front: cpp=0 (C++ only)" in summary
    assert "DIFF" not in summary


def test_exec_with_price_not_at_front_is_info_only(tmp_path):
    p = _write(tmp_path, _clean_msgs())
    fake = _mirror_replay(tmp_path, p, cpp_extra="exec_not_at_front=0\nexec_with_price_not_at_front=7\n")
    result = gate.run(p, 1, fake)
    assert result["cpp_counters"]["exec_with_price_not_at_front"] == 7
    assert result["counters_equal"] is True
    assert result["strict_failures"] == []
    assert result["ok"] is True
    summary = gate.format_summary(result)
    assert "counter exec_with_price_not_at_front: cpp=7 (C++ only, info)" in summary
    assert "DIFF" not in summary


def test_missing_exec_with_price_not_at_front_does_not_fail_strict_gate(tmp_path):
    p = _write(tmp_path, _clean_msgs())
    result = gate.run(p, 1, _mirror_replay(tmp_path, p, cpp_extra="exec_not_at_front=0\n"))
    assert result["strict_failures"] == []
    assert result["ok"] is True
