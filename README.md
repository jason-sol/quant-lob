# quant-lob

A C++20 order Book that replays Nasdaq ITCH 5.0, differential-tested against an independent Python Reference Book on three symbols (AAPL, MSFT, SPY) across a full trading day. After every Book Event the two must produce identical top-10 Snapshots. Their counters must match, every anomaly counter must be zero, every E execution must hit the order at the front of its queue, and no row may be crossed during regular hours. The closing-cross price in the feed is also checked against the official close published elsewhere.

Status: M1 differential gate passed; optimisation and benchmarks are next.

## Reproduce the gate

Requires CMake ≥ 3.25, Ninja, a C++20 compiler, and [uv](https://docs.astral.sh/uv/). The download is 4.76 GB, and it decompresses to 11.2 GB.

```sh
curl -fL -C - -o data/01302019.NASDAQ_ITCH50.gz --create-dirs \
  "https://emi.nasdaq.com/ITCH/Nasdaq%20ITCH/01302019.NASDAQ_ITCH50.gz"
uv run --project tools python -m qlob_tools.extract data/01302019.NASDAQ_ITCH50.gz --out data/ AAPL MSFT SPY
cmake --preset release && cmake --build --preset release
uv run --project tools python -m qlob_tools.gate data/AAPL-20190130.itch --depth 10 --replay build/release/qlob_replay
uv run --project tools python -m qlob_tools.anchor data/AAPL-20190130.itch
```

To reproduce the full-day frame count, decompress with `gunzip -k`. Then run `uv run --project tools python -m qlob_tools.framing data/01302019.NASDAQ_ITCH50` and `build/release/qlob_replay data/01302019.NASDAQ_ITCH50 --count`, and diff the two outputs. `build/release/qlob_replay data/01302019.NASDAQ_ITCH50` decodes every book message in the day file and prints its counters.

## Results

| Strict gate check | AAPL | MSFT | SPY |
|---|---|---|---|
| Snapshot mismatches (depth 10) | 0 of 1,656,597 | 0 of 1,642,525 | 0 of 3,055,956 |
| Counters equal, Reference Book vs C++ | yes | yes | yes |
| Anomaly counters (unknown and duplicate refs, excess reductions, zero-share adds, decode rejects, trailing bytes) | all 0 | all 0 | all 0 |
| E executions not at the front of the queue (`exec_not_at_front`) | 0 | 0 | 0 |
| Crossed rows, 09:30–16:00 | 0 | 0 | 0 |
| Closing cross vs official close | 165.25 = 165.25 | 106.38 = 106.38 | n/a (Arca-listed) |

Queues are ordered by Order Reference Number rather than message arrival, because orders left over from the Opening Cross are published after it but keep their earlier references; see [Queue priority](docs/results/m1-gate-2019-01-30.md#queue-priority).

Full-day frame count: Python and C++ agree on all 368,366,634 frames, with zero malformed frames. Full-day decode: all 363,118,215 book messages decode into Events, with zero decode rejects or order-reference anomalies.

Full report: [docs/results/m1-gate-2019-01-30.md](docs/results/m1-gate-2019-01-30.md).

## Layout

- `include/qlob/`, `src/`: ITCH decoder, Book, `qlob_replay`
- `tests/`: GoogleTest unit and property tests
- `tools/`: Python Extract, framing count, Reference Book, differential gate, price anchor
- `docs/`: design spec, plan, results
