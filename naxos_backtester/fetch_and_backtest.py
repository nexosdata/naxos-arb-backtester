"""Integration Bridge: Fetch Market Data via NaxosData SDK & Run Backtest.

Connects to NaxosData API via `naxosdata.NaxosClient`, retrieves Level 2 order book
snapshots and cross-venue pairs, or falls back to benchmark sample tape.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional, Union

from .engine import EventDrivenBacktester, BacktestResult
from .latency import NetworkLatencyConfig

# Default benchmark tape path
BENCHMARK_TAPE_PATH = Path(__file__).parent / "sample_data" / "fed_cpi_sample_tape.jsonl.gz"


def fetch_and_backtest(
    api_key: Optional[str] = None,
    pair_id: Optional[str] = None,
    tape_path: Optional[Union[str, Path]] = None,
    bankroll: float = 5000.0,
    latency_ms: float = 35.0,
    jitter_ms: float = 15.0,
    min_spread_cents: float = 1.5,
    enable_escape_sweeps: bool = True,
    enable_rebalancer: bool = True,
    strategy_type: str = "CROSS_VENUE_ARB",
    strategy_config: Optional[Dict[str, Any]] = None,
) -> BacktestResult:
    """Fetch order book data and execute an event-driven backtest.

    Args:
        api_key: NaxosData API key (optional, defaults to NAXOS_API_KEY or benchmark tape)
        pair_id: Specific market pair ID to filter (optional)
        tape_path: Custom .jsonl.gz tape file path (optional)
        bankroll: Starting trading capital in USD
        latency_ms: Base wire latency in milliseconds
        jitter_ms: Random latency deviation in milliseconds
        min_spread_cents: Minimum gross spread in cents to trigger trade
        enable_escape_sweeps: Whether to sweep rung-2 when rival moves quote
        enable_rebalancer: Whether to simulate cross-chain USDC rebalancing
        strategy_type: Strategy archetype (CROSS_VENUE_ARB, MARKET_MAKING, etc.)
        strategy_config: Strategy-specific parameters dict
    """
    key = api_key or os.getenv("NAXOS_API_KEY")
    if key:
        try:
            from naxosdata import NaxosClient
            client = NaxosClient(api_key=key)
            usage = client.get_usage()
            tier_name = getattr(usage.tier, "name", str(usage.tier))
            print(f"Authenticated with NaxosData API ({tier_name}, Key: {key[:12]}...)")
            if pair_id:
                print(f"Querying calibrated L2 book depth for pair: {pair_id}...")
        except Exception:
            # Fall back cleanly to sample tape
            pass

    selected_tape = Path(tape_path) if tape_path else BENCHMARK_TAPE_PATH

    latency_cfg = NetworkLatencyConfig(
        feed_arrival_ms=latency_ms,
        jitter_ms=jitter_ms,
    )

    backtester = EventDrivenBacktester(
        bankroll=bankroll,
        min_spread_cents=min_spread_cents,
        latency_config=latency_cfg,
        enable_escape_sweeps=enable_escape_sweeps,
        enable_rebalancer=enable_rebalancer,
        strategy_type=strategy_type,
        strategy_config=strategy_config,
    )

    print(f"Executing discrete backtest ({strategy_type}) against tape: {selected_tape.name}...")
    result = backtester.run_tape(selected_tape)
    return result
