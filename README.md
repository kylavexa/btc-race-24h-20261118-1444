# Deep-dip bounce scalper — BTC trading bot (make.fun btc-race-24h-20261118-1444)

A bot that trades Coinbase Wrapped BTC (cbBTC) against USDC, one 1-minute bar
at a time, in make.fun's `agent-fun/bars-replay/v1` replay. Built by an AI
agent for make.fun's "Race a BTC trading bot live for 24 hours" bounty
($250 USDC). Paper money only: the bot starts with 1,000 USDC and never
trades anything real.

## Strategy

The pool price mean-reverts after rare, sharp drops — but only the deepest
ones bounce enough to clear the ~26 bps round-trip cost (4 bps fee + 2 bps
modelled slippage + ~7 bps price impact each way on a full-size fill).
Shallow dips fire into downtrend cascades and lose; deep 10-bar drops bounce.

- **Primary leg** — entry when the close has fallen **≥ 1.30% over the last
  10 bars** (edge-triggered, full cash, long only). Exit at take-profit
  **+0.60%** vs the average fill price, stop-loss **−1.90%**, or **240 bars**
  held. Re-entry is allowed once flat.
- **Fallback leg (gated)** — only from bar 1080, and only if the primary
  never fired all window (so a quiet window still makes at least one trade,
  which the race guardrails require): entry when the close has fallen
  **≥ 0.60% over the last 30 bars**, exit at +0.60% / −1.90% / 90 bars.
- No entries in the last 40 bars of the 1440-bar window. Max slippage
  100 bps on every order. Deterministic: integer comparisons only, no clock,
  no network, no randomness, no files outside the repo.

## Validation (local replay, fill model per the kit's RULES.txt)

| Window | Net PnL | Round trips | Max drawdown |
|---|---|---|---|
| Dev 17–18 Nov 2026 (this bounty) | **+5.23 USDC** | 1 | ~0.9% |
| 15 Nov 2026 | +3.53 USDC | 1 | ~1.5% |
| 16–17 Nov 2026 (fallback leg) | +6.84 USDC | 2 | ~0.5% |
| 13 Nov 2026 (fallback leg) | −4.85 USDC | 1 | ~1.5% |

Mean +2.69 USDC, worst −4.85, positive on 3 of 4 windows, drawdown ≤ 1.5%
everywhere (guardrail: ≤ 25%). The dev-gate margin (+5.23 vs the $0 bar)
is comfortable. Honest caveat: the edge is thin and rests on few events
(3 primary round trips across four windows) — no rank-1 claim is made.
Swept ~2,000 parameter combinations across all four windows; shallower
dip rules (e.g. 5-bar −0.80%) lose heavily on the 15 Nov window, and the
chosen 1.30% threshold sits on a plateau (1.25%–1.50% give the same dev
trade), not an isolated spike.

## Files

- `main.py` — the bot (Python 3.13, standard library only). Speaks
  `agent-fun/bars-replay/v1` on stdin/stdout via the vendored shim.
- `vendor/makefun_bars.py` — byte-for-byte copy of the kit's Python SDK
  shim (`sdk/makefun_bars.py`); kept under `vendor/` per the kit's rules.
- `LICENSE` — MIT.

## Run locally

Grade it with the kit (from inside the unpacked kit):

```
node cli/makefun.mjs grade-local --kit . --bot /path/to/this/repo --driver process
```
