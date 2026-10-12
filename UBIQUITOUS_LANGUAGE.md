# Ubiquitous language

## Market data

| **Term** | **Definition** | **Avoid** |
|---|---|---|
| Feed | A source of normalised market Events (Nasdaq ITCH 5.0). | data, stream |
| Event | One normalised feed message: add, cancel, delete, replace, or execution. | message, tick |
| Replay day | One symbol's full trading day of Events, played back in sequence. | session, run |
| Feed order | A resting order placed by another market participant, as seen in the Feed. | order (unqualified) |
| Order reference | The exchange-assigned id of a Feed order, unique within a day; also the key that ranks orders within a Price level. | order id, order number |
| Frame | One length-prefixed ITCH message as it appears on the wire: a 2-byte big-endian length, then the message. | packet, record |
| Execution | An Event reporting that a Feed order traded. | fill, trade |

**Relationships:**
- A **Replay day** has many **Events** (1:N)
- An **Event** refers to exactly one **Feed order** (N:1)
- A **Feed order** has exactly one **Order reference** (1:1); a replace gives the new order a new one
- An **Event** is decoded from exactly one **Frame**; most Frames are not Events

## Book

| **Term** | **Definition** | **Avoid** |
|---|---|---|
| Book | The limit order book reconstructed from Events; it never matches orders itself. | matching engine, LOB (in code) |
| Price level | All resting orders on one side at one price, queued by Order reference. | bucket, tier |
| BBO | The best bid and best offer with their sizes. | top of book, TOB |
| Snapshot | The state of the top N Price levels at a given Event. | depth |
| Excess reduction | An Execution or cancel for more shares than the Feed order has resting; the order is removed. | overfill (Fill is for Own orders) |

**Relationships:**
- A **Book** has many **Price levels** per side (1:N)
- A **Price level** holds many **Feed orders** and **Own orders** (1:N)

## Simulation

| **Term** | **Definition** | **Avoid** |
|---|---|---|
| SimExchange | The layer that places Own orders alongside the Book and decides when they fill. | exchange, simulator |
| Matching engine | Price-time FIFO matching for orders injected into the SimExchange. | (never used for the Book) |
| Own order | An order placed by the strategy into the SimExchange. | sim order, my order |
| Queue position | An order's rank among the displayed orders at its Price level, ordered by Order reference. | queue, priority |
| Fill | A trade of an Own order. | execution |

**Relationships:**
- An **Own order** has exactly one **Queue position** (1:1) and zero or more **Fills** (1:N)
- A **SimExchange** wraps exactly one **Book** (1:1)

## Market making

| **Term** | **Definition** | **Avoid** |
|---|---|---|
| Inventory | The strategy's signed net position (q). | position, holdings |
| Reservation price | The mid price shifted against Inventory; the centre of the quotes. | fair value, skewed mid |
| Half-spread (δ) | The distance from the Reservation price to each quote. | spread (unqualified) |
| Markout | The mid-price change at a fixed horizon after a Fill, signed by the Fill's side. | slippage |

## P&L attribution

| **Term** | **Definition** | **Avoid** |
|---|---|---|
| Spread capture | P&L from the Fill price versus the mid at Fill time. | edge |
| Adverse selection | P&L lost to negative Markout after Fills. | toxicity |
| Inventory P&L | Mark-to-market change on Inventory held. | carry |

**Relationships:**
- Total P&L = **Spread capture** + **Adverse selection** + **Inventory P&L**

## Cross-repo

| **Term** | **Definition** | **Avoid** |
|---|---|---|
| Harness | The walk-forward / DSR / PBO validation code in the companion repository [strategy-promotion-gate](https://github.com/jason-sol/strategy-promotion-gate). | validator, backtester |
| Trial | One evaluated parameter set; the count DSR deflates for. | run, config |
| Latency | Time to process one Event in the Book or SimExchange, excluding network. | speed, wire-to-wire |
| Reference Book | A deliberately simple Python Book that the C++ Book is checked against. | golden |
| Extract | A single-symbol subset of an ITCH day file, framing preserved. | sample, slice |

## Flagged ambiguities

| **Term** | **Conflict** | **Resolution** |
|---|---|---|
| Matching engine | Used for both book reconstruction and order matching. | **Book** = reconstructed from the Feed; **Matching engine** = matching inside the SimExchange. |
| Fill vs Execution | Both mean "traded". | **Execution** = someone else's trade, from the Feed; **Fill** = an Own order's trade. |
| FIFO | Arrival order of Add messages vs Order reference order. | Queues follow **Order reference**. The two differ after the Opening Cross, when pre-open orders are published late but keep their earlier references. |
| Spread | Quoted spread vs Half-spread vs Spread capture. | Always qualify. |
| Markout horizon | Adverse selection depends on the horizon. | Unresolved — default proposal: report 1s / 10s / 60s; decide in milestone 4. |

## Example dialogue

> **Developer:** "When the Book processes an Execution, does the strategy get a Fill?"
> **Domain expert:** "Only if an Own order sat at that Price level and the Execution reached it in Queue position."
> **Developer:** "So the Book never matches anything — the SimExchange decides Fills?"
> **Domain expert:** "Right. The Book mirrors the exchange; the Matching engine only handles Own orders injected into the SimExchange."
> **Developer:** "And the loss after a Fill when the mid moves against us?"
> **Domain expert:** "That's Adverse selection, measured by Markout — not slippage, which we don't model."
