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
    if sep and key in ref_book.STAT_KEYS and value.isdigit():
        return key, int(value)
    return None


def parse_counters(text: str) -> dict[str, int]:
    return dict(sorted(kv for line in text.splitlines() if (kv := _counter(line))))


def other_stderr_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip() and _counter(line) is None]


def run(path, depth: int, replay_bin: str) -> dict:
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
    counters_equal = cpp_counters == ref_counters
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
        "ok": mismatches == 0 and counters_equal and header_match and returncode == 0,
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
        lines.append(f"counter {k}: ref={r} cpp={c}{'' if r == c else '  DIFF'}")
    lines += [f"crossed_{b}={result['crossed'][b]}" for b in BUCKETS]
    lines.append("GATE PASS" if result["ok"] else "GATE FAIL")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m qlob_tools.gate")
    ap.add_argument("file")
    ap.add_argument("--depth", type=int, required=True)
    ap.add_argument("--replay", required=True)
    args = ap.parse_args(argv)
    result = run(args.file, args.depth, args.replay)
    sys.stdout.write(format_summary(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
