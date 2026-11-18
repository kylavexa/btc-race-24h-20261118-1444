"""Deep-dip bounce scalper for make.fun "Race a BTC trading bot live for 24 hours"
(btc-race-24h-20261118-1444). Written in-session 18 Nov 2026.

Design (from the written brief, validated on four 24h cbBTC windows):
  The pool price mean-reverts after rare, sharp drops, but only the deepest
  ones bounce enough to clear the ~26 bps round-trip cost (4 bps fee + 2 bps
  modelled slippage + ~7 bps impact each way on a full-size fill). Shallow
  dips fire into downtrend cascades and lose; deep 10-bar drops bounce.

  PRIMARY (the only leg that trades on a normal window):
    - Entry: the close has fallen >= 1.30% over the last 10 bars, edge
      triggered (fires once when the condition first becomes true), full
      cash, long only.
    - Exit: take profit +0.60% vs the average fill price, stop loss -1.90%,
      or 240 bars held, whichever comes first.
    - Re-entry is allowed after the position is flat.
  FALLBACK (gated: only from bar 1080, and only if the primary never fired
  all window -- it exists so a quiet window still makes at least one trade,
  which the race guardrails require):
    - Entry: the close has fallen >= 0.60% over the last 30 bars, edge
      triggered, full cash.
    - Exit: take profit +0.60%, stop loss -1.90%, or 90 bars held.
  No entries in the last 40 bars of the 1440-bar window.

  Validation (local replay, fill model per kit RULES.txt: fee 4 bps, slippage
  2 bps, constant-product impact vs the fill bar's open depth):
    dev window 17-18 Nov (this bounty): +5.23 USDC, 1 round trip, max DD ~0.9%
    15 Nov window: +3.53 USDC, 1 round trip
    16-17 Nov window: +6.84 USDC, 2 round trips (fallback leg)
    13 Nov window: -4.85 USDC, 1 round trip (fallback leg)
  Mean +2.69, worst -4.85, max drawdown <= 1.5% on every window. The edge is
  thin and rests on few events (3 primary round trips across four windows);
  the dev-gate margin (+5.23 vs the $0 bar) is comfortable, but no rank-1
  claim is made -- see README.md.

  Determinism: integer comparisons only, no clock, no network, no random
  numbers, no files outside the repo. Two runs on the same data give the
  same orders byte for byte.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"

# Primary leg: deep 10-bar dip, quick take-profit, wide stop, long hold.
P_WINDOW = 10
P_DROP_BPS = 130
P_TP_BPS = 60
P_SL_BPS = 190
P_HOLD_BARS = 240

# Fallback leg: gated, late-window, shallower 30-bar dip.
F_FROM_BAR = 1080
F_WINDOW = 30
F_DROP_BPS = 60
F_TP_BPS = 60
F_SL_BPS = 190
F_HOLD_BARS = 90

MAX_SLIPPAGE_BPS = 100
LAST_ENTRY_BAR = 1400  # 1440-bar window: no entries in the last 40 bars.

# --- bot state (all derived from hello / batches only) ---
_closes = []            # closes, oldest first, ints (price_scale units)
_prev_primary = False   # primary condition on the previous bar
_prev_fallback = False  # fallback condition on the previous bar
_primary_fired = False  # a primary buy was ever decided this run
_leg_fallback = False   # the open position came from the fallback leg
_entry_bar = -1         # bar index whose open filled the open position
_avg_price = 0          # average fill price of the open position (int)
_px_qty_sum = 0         # sum(price * qty) of the fills building the position
_position_qty = 0       # qty of the open position


def _drop(window, drop_bps):
    """True when the latest close is down >= drop_bps vs `window` bars ago."""
    if len(_closes) <= window:
        return False
    now = _closes[-1]
    then = _closes[-1 - window]
    return now * 10000 <= then * (10000 - drop_bps)


def _fold_fills(batch):
    """Fold this batch's fills into the tracked average fill price."""
    global _avg_price, _px_qty_sum, _position_qty
    for fill in batch.get("fills", []):
        if fill.get("symbol") != SYMBOL or fill.get("status") != "filled":
            continue
        price = int(fill["price"])
        qty = int(fill["qty"])
        if fill.get("side") == "buy":
            _px_qty_sum += price * qty
            _position_qty += qty
            if _position_qty > 0:
                _avg_price = _px_qty_sum // _position_qty
        elif fill.get("side") == "sell":
            _position_qty -= qty
            if _position_qty <= 0:
                _position_qty = 0
                _px_qty_sum = 0
                _avg_price = 0


def on_batch(state, batch):
    """The orders decided on this bar (the bar that just closed)."""
    global _prev_primary, _prev_fallback, _primary_fired, _leg_fallback
    global _entry_bar
    bar = state.latest.get(SYMBOL)
    if bar is None:
        return []
    _closes.append(int(bar["c"]))
    _fold_fills(batch)
    # bar index on the scored window (0-based); warm-up batches do not count.
    idx = state.seq - state.warmup_bars
    close = int(bar["c"])
    holding = state.positions.get(SYMBOL)
    qty = holding.qty if holding is not None else 0

    if qty > 0 and _avg_price > 0:
        # Exit the open position: take profit, stop loss, or max hold.
        if _leg_fallback:
            tp, sl, hold = F_TP_BPS, F_SL_BPS, F_HOLD_BARS
        else:
            tp, sl, hold = P_TP_BPS, P_SL_BPS, P_HOLD_BARS
        take_profit = close * 10000 >= _avg_price * (10000 + tp)
        stop_loss = close * 10000 <= _avg_price * (10000 - sl)
        timed_out = _entry_bar >= 0 and (idx - _entry_bar) >= hold
        if take_profit or stop_loss or timed_out:
            return [{"side": "sell", "symbol": SYMBOL, "qty": qty,
                     "max_slippage_bps": MAX_SLIPPAGE_BPS}]
        return []

    if idx >= LAST_ENTRY_BAR or state.warming_up:
        return []

    # Primary: 10-bar drop >= 1.30%, edge triggered.
    cond_primary = _drop(P_WINDOW, P_DROP_BPS)
    if cond_primary and not _prev_primary:
        _primary_fired = True
        _leg_fallback = False
        _entry_bar = idx + 1  # the buy fills at the next bar's open
        _prev_primary = cond_primary
        return [{"side": "buy", "symbol": SYMBOL,
                 "notional_quote_units": state.cash,
                 "max_slippage_bps": MAX_SLIPPAGE_BPS}]
    _prev_primary = cond_primary

    # Fallback: from bar 1080, only if the primary never fired.
    if idx >= F_FROM_BAR and not _primary_fired:
        cond_fallback = _drop(F_WINDOW, F_DROP_BPS)
        if cond_fallback and not _prev_fallback:
            _leg_fallback = True
            _entry_bar = idx + 1  # the buy fills at the next bar's open
            _prev_fallback = cond_fallback
            return [{"side": "buy", "symbol": SYMBOL,
                     "notional_quote_units": state.cash,
                     "max_slippage_bps": MAX_SLIPPAGE_BPS}]
        _prev_fallback = cond_fallback
    return []


makefun_bars.run(on_batch)
