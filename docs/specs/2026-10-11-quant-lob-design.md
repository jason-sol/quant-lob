# quant-lob — design

Status: approved 2026-10-11. Terms follow `UBIQUITOUS_LANGUAGE.md`.

## Decision

Build a C++20 Book that replays real Nasdaq data, a SimExchange where Own orders fill against the replayed flow, and an Avellaneda–Stoikov market maker whose parameters are evaluated by an external Python backtest Harness (walk-forward, DSR, PBO).

Driving constraint: a market-making simulator is only as credible as the order book under it. The Book must therefore be checked for correctness against real exchange data first, and measurably fast second, with every performance claim traceable to a reproducible benchmark.

## Goals

1. For a full Nasdaq ITCH 5.0 Replay day, the C++ Book's Snapshots match an independent Python reference Book exactly (differential test), with zero Events referencing unknown orders.
2. The ITCH parser decodes every message in a public day file; per-type message counts reconcile with an independent framing-only count.
3. Published Latency (p50 / p99 / p99.9 per Event) measured on Linux x86 with stated hardware, plus a `perf` flame graph and a design write-up.
4. SimExchange fills Own orders only when Executions/cancels consume their Queue position.
5. Market maker P&L decomposes into Spread capture + Adverse selection + Inventory P&L, summing to total P&L.
6. Market-maker Trials evaluated through the Harness (walk-forward, DSR, PBO) via pybind11.

## Non-goals

Pro-rata matching, multi-symbol Books, kernel-bypass networking, live or paper trading, ML signals, Windows support.

## Components

| Unit | Responsibility | Depends on |
|---|---|---|
| `feed/itch` | Zero-copy ITCH 5.0 binary parser → `Event` | — |
| `tools/` (Python) | Single-symbol extract from a day file; reference Book; Snapshot diff | — |
| `book` | Price levels with intrusive FIFO lists, O(1) cancel via order-id map, memory pool | `Event` |
| `engine` | Price-time FIFO Matching engine for injected orders; self-trade prevention | `book` |
| `sim` | SimExchange: Own orders, Queue position tracking, Fill generation | `book`, `engine` |
| `mm` | Avellaneda–Stoikov quoting (Reservation price, Half-spread), Inventory limits, P&L attribution, Markout | `sim` |
| `bench` | Google Benchmark harness, Latency percentiles, reproducible run script | `book`, `feed/*` |
| `py` | pybind11 bindings exposing a Replay day run with parameters → Fills and P&L | `mm` |

Data flow: `Feed → Event → Book → (SimExchange ← Own orders from mm) → Fills → P&L attribution → py → Harness`.

## Milestones

| # | Scope | Est. | Exit |
|---|---|---|---|
| 1 | Repo skeleton (CMake + Ninja, GoogleTest, ASan/UBSan, GitHub Actions) + `feed/itch` + baseline `book` (std containers) + Python reference + differential gate | 3–4 wk | Goals 1–2 |
| 2 | Optimised `book` (flat price levels, memory pool, custom hash) benchmarked against the M1 baseline + `bench` + design post | 2–3 wk | Goal 3 |
| 3 | `engine` + `sim` | 2 wk | Goal 4 |
| 4 | `mm` + `py` + Harness integration + second post | 3–4 wk | Goals 5–6 |

## Testing

- `book`: property tests on invariants after every Event (never crossed, sizes ≥ 0, level totals equal the sum of their orders); exact Snapshot comparison against the Python reference Book.
- `feed/itch`: unit tests from hand-encoded messages; per-type counts reconcile with a framing-only Python count over a full day file.
- `engine`/`sim`: hand-written scenarios (partial fills, cancel ahead of us, price-level depletion, self-trade).
- `mm`: closed-form checks (zero Inventory → symmetric quotes; Reservation price shift sign); P&L components sum to total.
- Sanitisers on all test runs in CI; benchmarks are not run in CI.

## Error handling

- Feed parsers reject malformed records with a counted, typed error and the byte offset; a Replay day reports totals rather than aborting on the first bad record.
- Book treats an Event for an unknown order id as a counted anomaly. ITCH starts before the pre-market, so any non-zero count is a bug, not missing data.

## Environment

- Develop on macOS (Apple Silicon). Published benchmarks run on a short-lived Linux x86 cloud instance with a dedicated core; hardware, compiler, and flags recorded with each result.
- Workflow: spec → plan → test-first implementation; each milestone's plan lives in `docs/plans/`.

## Open questions

- Markout horizon(s) for Adverse selection — default proposal 1s / 10s / 60s; decide in milestone 4.
- Resolved 2026-10-12: LOBSTER samples are no longer freely downloadable; Nasdaq still hosts public ITCH 5.0 day files at `emi.nasdaq.com/ITCH/Nasdaq ITCH/`. Correctness reference is a Python reference Book (differential testing) instead of LOBSTER.
