#!/usr/bin/env python3
"""Example 04: Custom Strategy Backtest with Safe AST Microstructure Formula.

Demonstrates:
1. Validating and parsing user-defined quantitative rules using SafeExpressionEvaluator (zero eval()).
2. Replaying historical Level 2 tick tape against the CustomStrategySimulator engine.
3. Calculating exact nonlinear Kalshi quadratic taker fees (0.07 * C * P * (1 - P)).
4. Generating institutional performance reports with equity curve and trade logs.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure local naxos_backtester package is importable
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from naxos_backtester import (
    EventDrivenBacktester,
    NetworkLatencyConfig,
    SafeExpressionEvaluator,
    StrategyType,
    calculate_exchange_fee,
    calculate_kalshi_breakeven_spread,
    fetch_and_backtest,
)


def main() -> None:
    print(f"\n{'='*72}")
    print(" NAXOSDATA DISCRETE BACKTESTER: CUSTOM STRATEGY & SAFE AST ENGINE")
    print(f"{'='*72}")

    # 1. Define quantitative AST entry & exit expressions
    entry_rule = "obi_top5 >= 0.15 and spread_bps <= 250 and net_arb_cents >= 0.0"
    exit_rule = "obi_top5 < -0.20 or vwap_divergence_cents > 1.2"

    print("Validating Quantitative Microstructure Expressions:")
    is_entry_valid, err_entry = SafeExpressionEvaluator.validate(entry_rule)
    is_exit_valid, err_exit = SafeExpressionEvaluator.validate(exit_rule)
    print(f"  • Entry Rule: '{entry_rule}' -> {'VALID (AST compiled)' if is_entry_valid else f'REJECTED: {err_entry}'}")
    print(f"  • Exit Rule:  '{exit_rule}' -> {'VALID (AST compiled)' if is_exit_valid else f'REJECTED: {err_exit}'}")

    if not is_entry_valid or not is_exit_valid:
        print("AST validation failed. Aborting.")
        return

    # 2. Inspect Exact Quadratic Fee Curve for sample Kalshi trade
    sample_price = 0.50
    sample_contracts = 100
    fee_breakdown = calculate_exchange_fee("KALSHI", contracts=sample_contracts, price=sample_price)
    be_spread = calculate_kalshi_breakeven_spread(poly_yes_price=0.50, target_roi_pct=2.0, contracts=100)

    print(f"\nExact Kalshi Quadratic Fee Model (0.07 * C * P * (1 - P)):")
    print(f"  • Contract Size:    {sample_contracts} contracts @ ${sample_price:.2f}")
    print(f"  • Effective Fee:    ${fee_breakdown.total_fee_usd:.2f} USD ({fee_breakdown.effective_bps_on_payout:.1f} bps on $1.00 payout)")
    print(f"  • Breakeven Spread: Min gross spread {be_spread['gross_edge_cents']:.2f}¢ for +{be_spread['target_roi_pct']}% ROI")

    # 3. Execute Custom Strategy Backtest against Historical Tape
    tape_path = repo_root / "naxos_backtester" / "sample_data" / "fed_cpi_sample_tape.jsonl.gz"

    bankroll = 10000.0
    custom_config = {
        "entry_expression": entry_rule,
        "exit_expression": exit_rule,
        "take_profit_cents": 2.5,
        "stop_loss_cents": 1.5,
        "trailing_stop_cents": 0.8,
        "position_size_shares": 500.0,
    }

    print(f"\nExecuting Custom AST Strategy Backtest against tape: {tape_path.name}...")
    result = fetch_and_backtest(
        tape_path=tape_path,
        bankroll=bankroll,
        latency_ms=25.0,
        jitter_ms=10.0,
        min_spread_cents=1.0,
        enable_escape_sweeps=True,
        enable_rebalancer=True,
        strategy_type=StrategyType.CUSTOM_STRATEGY,
        strategy_config=custom_config,
    )

    # 4. Print Institutional Performance Summary
    print(result.summary())

    if result.trades:
        print(f"Executed Trades Sample (Total: {len(result.trades)}):")
        for t in result.trades[:5]:
            print(f"  • [{t.timestamp_ms}] {t.execution_type:<15} {t.shares:,.0f} shs @ ${t.price_long:.3f} -> Net PnL: ${t.net_pnl:+,.2f}")

    print("\nCustom AST Formula Backtest completed with 100% exit code 0.")


if __name__ == "__main__":
    main()
