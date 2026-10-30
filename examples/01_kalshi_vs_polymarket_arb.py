#!/usr/bin/env python3
"""Example 1: Dual-Leg Kalshi vs. Polymarket Arbitrage Backtest.

Demonstrates running the discrete event-driven backtester against the 3-day
benchmark tape (or live NaxosData API archive), simulating the 4-stage latency
pipeline (35ms ± 15ms), shadow liquidity depletion, and Rung-2 escape sweeps.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure local naxos_backtester and parent naxosdata SDK are importable
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from naxos_backtester import (
    EventDrivenBacktester,
    NetworkLatencyConfig,
    fetch_and_backtest,
)


def main() -> None:
    print(f"\n{'='*72}")
    print(" NAXOSDATA DISCRETE ARBITRAGE BACKTESTER: KALSHI VS POLYMARKET")
    print(f"{'='*72}")

    bankroll = 10000.0
    min_spread_cents = 1.5
    latency_ms = 35.0
    jitter_ms = 15.0

    print(f"Parameters:")
    print(f"  Starting Bankroll:      ${bankroll:,.2f} USD")
    print(f"  Minimum Spread Filter:  +{min_spread_cents:.1f}¢")
    print(f"  Wire Latency:           {latency_ms:.1f}ms (±{jitter_ms:.1f}ms jitter)")
    print(f"  Rung-2 Escape Sweeps:   ENABLED (<= $1.005 limit sweep)")
    print(f"  Cross-Chain Rebalancer: ENABLED (Polygon USDC <-> Kalshi USD)")

    tape_path = repo_root / "naxos_backtester" / "sample_data" / "fed_cpi_sample_tape.jsonl.gz"

    # Execute backtest
    result = fetch_and_backtest(
        tape_path=tape_path,
        bankroll=bankroll,
        latency_ms=latency_ms,
        jitter_ms=jitter_ms,
        min_spread_cents=min_spread_cents,
        enable_escape_sweeps=True,
        enable_rebalancer=True,
    )

    # Print institutional performance summary
    print(result.summary())

    # Inspect sample trades
    if result.trades:
        print("Sample Executed Arbitrage Trades:")
        for t in result.trades[:5]:
            print(
                f"  [{t.execution_type:<14}] {t.venue_long:<10} (${t.price_long:.3f}) + "
                f"{t.venue_short:<10} (${t.price_short:.3f}) | "
                f"Size: {t.shares:>6.0f} | Spread: +{t.spread_cents:.1f}¢ | Net PnL: +${t.net_pnl:.2f}"
            )
        print()

    print("SUCCESS: Dual-leg arbitrage backtest completed cleanly.")


if __name__ == "__main__":
    main()
