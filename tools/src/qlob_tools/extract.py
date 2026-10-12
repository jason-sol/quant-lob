"""Single-pass, multi-symbol Extract from an ITCH day file.

An Extract keeps every `S` system event, the symbol's `R` stock directory message,
and every later frame carrying the locate that `R` assigned. Frames are copied
byte-for-byte, length prefix included.
"""

import argparse
import gzip
import os
import re
import sys
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from qlob_tools import layout
from qlob_tools.framing import DEFAULT_CHUNK, FrameStream

_S, _R = ord("S"), ord("R")
_NASDAQ_NAME = re.compile(r"^(\d{2})(\d{2})(\d{4})\.")


@dataclass
class SymbolStats:
    locate: int | None = None
    frames: int = 0


@dataclass
class ExtractResult:
    symbols: dict[str, SymbolStats] = field(default_factory=dict)
    trailing_bytes: int = 0


def extract(src: BinaryIO, outs: dict[str, BinaryIO], chunk_size: int = DEFAULT_CHUNK) -> ExtractResult:
    result = ExtractResult({sym: SymbolStats() for sym in outs})
    wanted = {sym.encode().ljust(8): sym for sym in outs}
    by_locate: dict[int, str] = {}
    frames = FrameStream(src, chunk_size)
    for off, msg in frames:
        if not msg:
            raise ValueError(f"empty frame at offset {off}")
        t = msg[0]
        if t == _R and len(msg) != layout.STOCK_DIRECTORY.size:
            raise ValueError(f"R frame at offset {off} has length {len(msg)}")
        if t == _S:
            targets = outs.keys()
        elif t == _R and msg[11:19] in wanted:
            sym = wanted[msg[11:19]]
            if result.symbols[sym].locate is not None:
                raise ValueError(f"second R for {sym} at offset {off}")
            locate = int.from_bytes(msg[1:3], "big")
            result.symbols[sym].locate = locate
            by_locate[locate] = sym
            targets = (sym,)
        else:
            sym = by_locate.get(int.from_bytes(msg[1:3], "big"))
            if sym is None:
                continue
            targets = (sym,)
        framed = layout.LENGTH_PREFIX.pack(len(msg)) + msg
        for sym in targets:
            outs[sym].write(framed)
            result.symbols[sym].frames += 1
    result.trailing_bytes = frames.trailing_bytes
    return result


def output_name(src: str | Path, symbol: str) -> str:
    m = _NASDAQ_NAME.match(Path(src).name)
    if not m:
        raise ValueError(f"expected an MMDDYYYY.* Nasdaq file name, got {Path(src).name}")
    mm, dd, yyyy = m.groups()
    return f"{symbol}-{yyyy}{mm}{dd}.itch"


def _open_input(path: Path) -> BinaryIO:
    return gzip.open(path, "rb") if path.suffix == ".gz" else open(path, "rb")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m qlob_tools.extract")
    p.add_argument("src", type=Path)
    p.add_argument("symbols", nargs="+")
    p.add_argument("--out", type=Path, default=Path("."))
    p.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK)
    args = p.parse_args(argv)

    paths = {sym: args.out / output_name(args.src, sym) for sym in args.symbols}
    temps = {sym: path.with_name(path.name + ".tmp") for sym, path in paths.items()}
    # Outputs are all-or-nothing: a failed run must not leave a plausible-looking partial Extract.
    try:
        with ExitStack() as stack:
            src = stack.enter_context(_open_input(args.src))
            outs = {sym: stack.enter_context(open(tmp, "wb")) for sym, tmp in temps.items()}
            result = extract(src, outs, args.chunk_size)

        ok = result.trailing_bytes == 0
        for sym, st in result.symbols.items():
            ok &= st.locate is not None
            print(f"{sym} locate={st.locate} frames={st.frames} bytes={temps[sym].stat().st_size} -> {paths[sym]}")
        print(f"trailing_bytes={result.trailing_bytes}")
        if ok:
            for sym, tmp in temps.items():
                os.replace(tmp, paths[sym])
    finally:
        for tmp in temps.values():
            tmp.unlink(missing_ok=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
