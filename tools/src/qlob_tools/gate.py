"""Streaming differential gate: C++ qlob_replay Snapshots vs the Reference Book, row by row."""

import argparse
import subprocess
import sys
import threading
from itertools import zip_longest

from qlob_tools import ref_book

NS = 1_000_000_000
OPEN_NS = (9 * 3600 + 30 * 60) * NS
CLOSE_NS = 16 * 3600 * NS
BUCKETS = ("pre_open", "regular", "post_close")
STRICT_CPP_KEYS = ("exec_not_at_front",)
INFO_CPP_KEYS = ("exec_with_price_not_at_front",)
CPP_ONLY_KEYS = STRICT_CPP_KEYS + INFO_CPP_KEYS
COUNTER_KEYS = frozenset(ref_book.STAT_KEYS) | frozenset(CPP_ONLY_KEYS)
ANOMALY_KEYS = ("unknown_order_refs", "duplicate_order_refs", "zero_qty_adds", "excess_reductions",
                "decode_rejects", "trailing_bytes")


def session_bucket(ts_ns: int) -> str:
    if ts_ns < OPEN_NS:
        return "pre_open"
    if ts_ns < CLOSE_NS:
        return "regular"
    return "post_close"


def is_crossed(row: str) -> bool:
    cells = row.split(",", 6)
    bid, ask = int(cells[2]), int(cells[4])
    return bid != 0 and ask != 0 and bid >= ask


def _counter(line: str) -> tuple[str, int] | None:
    key, sep, value = line.partition("=")
    if sep and key in COUNTER_KEYS and value.isdigit():
        return key, int(value)
    return None


def parse_counters(text: str) -> dict[str, int]:
    return dict(sorted(kv for line in text.splitlines() if (kv := _counter(line))))


def other_stderr_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip() and _counter(line) is None]


def strict_failures(ref_counters: dict[str, int], cpp_counters: dict[str, int], crossed: dict[str, int]) -> list[str]:
    """Strict criteria that a byte-identical replay can still fail: anomalies the data must not contain."""
    failures = [f"{k}={ref_counters[k]}" for k in ANOMALY_KEYS if ref_counters.get(k)]
    if crossed["regular"]:
        failures.append(f"crossed_regular={crossed['regular']}")
    failures += [f"{k}={cpp_counters[k]}" for k in STRICT_CPP_KEYS if cpp_counters.get(k)]
    return failures


def run(path, depth: int, replay_bin: str, allow_anomalies: bool = False) -> dict:
    proc = subprocess.Popen(
        [str(replay_bin), str(path), "--depth", str(depth), "--snapshots", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    stderr_chunks: list[str] = []
    drain = threading.Thread(target=lambda: stderr_chunks.append(proc.stderr.read()), daemon=True)
    drain.start()
    try:
        ref = ref_book.replay(path, depth)
        ref_iter = iter(ref)
        cpp_iter = (line.rstrip("\n") for line in proc.stdout)

        ref_header = next(ref_iter)
        cpp_header = next(cpp_iter, None)

        rows_ref = rows_cpp = mismatches = 0
        first_mismatch = None
        crossed = dict.fromkeys(BUCKETS, 0)
        for seq, (r, c) in enumerate(zip_longest(ref_iter, cpp_iter)):
            rows_ref += r is not None
            rows_cpp += c is not None
            if r != c:
                mismatches += 1
                if first_mismatch is None:
                    first_mismatch = {"seq": seq, "ref": r, "cpp": c}
            if r is not None and is_crossed(r):
                crossed[session_bucket(int(r.split(",", 2)[1]))] += 1
    except BaseException:
        proc.kill()
        raise
    finally:
        proc.stdout.close()
        returncode = proc.wait()
        drain.join()

    stderr_text = "".join(stderr_chunks)
    cpp_counters = parse_counters(stderr_text)
    ref_counters = dict(sorted(ref.stats.items()))
    header_match = ref_header == cpp_header
    shared_cpp = {k: v for k, v in cpp_counters.items() if k not in CPP_ONLY_KEYS}
    counters_equal = shared_cpp == ref_counters
    identical = mismatches == 0 and counters_equal and header_match and returncode == 0
    strict = strict_failures(ref_counters, cpp_counters, crossed)
    missing = [k for k in STRICT_CPP_KEYS if k not in cpp_counters]
    return {
        "rows_ref": rows_ref,
        "rows_cpp": rows_cpp,
        "mismatches": mismatches,
        "first_mismatch": first_mismatch,
        "ref_header": ref_header,
        "cpp_header": cpp_header,
        "header_match": header_match,
        "ref_counters": ref_counters,
        "cpp_counters": cpp_counters,
        "cpp_stderr_other": other_stderr_lines(stderr_text),
        "counters_equal": counters_equal,
        "crossed": crossed,
        "returncode": returncode,
        "strict_failures": strict,
        "missing_cpp_keys": missing,
        "allow_anomalies": allow_anomalies,
        "ok": identical and not missing and (allow_anomalies or not strict),
    }


def format_summary(result: dict) -> str:
    lines = [
        f"rows_ref={result['rows_ref']}",
        f"rows_cpp={result['rows_cpp']}",
        f"mismatches={result['mismatches']}",
        f"header_match={result['header_match']}",
        f"returncode={result['returncode']}",
    ]
    if result["returncode"] != 0 or not result["header_match"]:
        lines += [f"ref_header: {result['ref_header']}", f"cpp_header: {result['cpp_header']}"]
        lines += [f"cpp_stderr: {line}" for line in result["cpp_stderr_other"]]
    fm = result["first_mismatch"]
    if fm:
        lines += [f"first_mismatch_seq={fm['seq']}", f"  ref: {fm['ref']}", f"  cpp: {fm['cpp']}"]
    keys = sorted(set(result["ref_counters"]) | set(result["cpp_counters"]))
    for k in keys:
        r, c = result["ref_counters"].get(k), result["cpp_counters"].get(k)
        if k in INFO_CPP_KEYS:
            lines.append(f"counter {k}: cpp={c} (C++ only, info)")
        elif k in CPP_ONLY_KEYS:
            lines.append(f"counter {k}: cpp={c} (C++ only)")
        else:
            lines.append(f"counter {k}: ref={r} cpp={c}{'' if r == c else '  DIFF'}")
    lines += [f"crossed_{b}={result['crossed'][b]}" for b in BUCKETS]
    label = "anomaly_allowed" if result["allow_anomalies"] else "strict_fail"
    lines += [f"{label}: {f}" for f in result["strict_failures"]]
    lines += [f"missing_cpp_key: {k}" for k in result["missing_cpp_keys"]]
    lines.append("GATE PASS" if result["ok"] else "GATE FAIL")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m qlob_tools.gate")
    ap.add_argument("file")
    ap.add_argument("--depth", type=int, required=True)
    ap.add_argument("--replay", required=True)
    ap.add_argument("--allow-anomalies", action="store_true",
                    help="relaxes: anomaly counters (unknown/duplicate refs, zero-qty adds, excess reductions, "
                         "decode rejects, trailing bytes), crossed regular-hours rows, the exec_not_at_front value. "
                         "Never relaxes: row mismatches, shared-counter disagreement, missing C++ keys.")
    args = ap.parse_args(argv)
    result = run(args.file, args.depth, args.replay, allow_anomalies=args.allow_anomalies)
    sys.stdout.write(format_summary(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
