"""Streaming ITCH 5.0 framing: 2-byte big-endian length prefix, then the message."""

import os
import sys
from collections import Counter
from collections.abc import Iterator
from contextlib import nullcontext
from typing import BinaryIO

from qlob_tools import layout

DEFAULT_CHUNK = 1 << 20


class FrameStream:
    """Yields (offset, msg) per complete frame; offset is where the length prefix starts.

    After exhaustion, `trailing_bytes` holds the size of any incomplete final frame
    and `trailing_offset` its start (None when the input ended on a frame boundary).
    """

    def __init__(self, fileobj: BinaryIO, chunk_size: int = DEFAULT_CHUNK) -> None:
        self._f = fileobj
        self._chunk = chunk_size
        self.trailing_bytes = 0
        self.trailing_offset: int | None = None

    def __iter__(self) -> Iterator[tuple[int, bytes]]:
        buf = bytearray()
        base = 0  # file offset of buf[0]
        pos = 0
        while True:
            data = self._f.read(self._chunk)
            if not data:
                break
            if pos:
                del buf[:pos]
                base += pos
                pos = 0
            buf += data
            while len(buf) - pos >= 2:
                (n,) = layout.LENGTH_PREFIX.unpack_from(buf, pos)
                end = pos + 2 + n
                if end > len(buf):
                    break
                yield base + pos, bytes(memoryview(buf)[pos + 2 : end])
                pos = end
        remaining = len(buf) - pos
        if remaining:
            self.trailing_bytes = remaining
            self.trailing_offset = base + pos


def open_source(src):
    if isinstance(src, (str, os.PathLike)):
        return open(src, "rb")
    return nullcontext(src)


def scan(src, chunk_size: int = DEFAULT_CHUNK) -> dict[str, int | str]:
    counts: Counter[str] = Counter()
    mismatches: Counter[str] = Counter()
    empty = unknown = 0
    first_bad: int | None = None
    with open_source(src) as f:
        frames = FrameStream(f, chunk_size)
        for off, msg in frames:
            if not msg:
                empty += 1
                bad = True
            else:
                t = chr(msg[0])
                counts[t] += 1
                expected = layout.EXPECTED_LENGTH.get(t)
                if expected is None:
                    unknown += 1
                    bad = True
                else:
                    bad = len(msg) != expected
                    if bad:
                        mismatches[t] += 1
            if bad and first_bad is None:
                first_bad = off
    result: dict[str, int | str] = {f"count_{t}": n for t, n in counts.items()}
    result.update({f"length_mismatch_{t}": n for t, n in mismatches.items()})
    result["empty_frames"] = empty
    result["first_bad_offset"] = "none" if first_bad is None else first_bad
    result["trailing_bytes"] = frames.trailing_bytes
    result["unknown_type"] = unknown
    return dict(sorted(result.items()))


def format_result(result: dict) -> str:
    return "".join(f"{k}={result[k]}\n" for k in sorted(result))


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: python -m qlob_tools.framing <file>", file=sys.stderr)
        return 2
    sys.stdout.write(format_result(scan(argv[0])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
