"""NaxosData Multi-Venue Prediction Market Arbitrage & Multi-Strategy Backtester (`naxos-arb-backtester`).

Institutional-grade discrete event-driven backtesting engine with:
- 5 Strategy Archetypes: CROSS_VENUE_ARB, MARKET_MAKING, ORDERFLOW_IMBALANCE, RESOLUTION_CARRY, CUSTOM_STRATEGY
- Safe AST Expression Evaluator (Zero-eval runtime for quantitative rules)
- Exact Kalshi Quadratic Fee Engine (0.07 * C * P * (1 - P))
- 4-Stage execution latency modeling (35ms ± 15ms)
- Kalshi reciprocal binary mathematics
- Shadow liquidity depletion ledger
- Rung-2 unhedged escape sweeps and Leg-1 scratch exits
- Automated cross-chain USDC rebalancing
"""

from .clock import SimulatedClock
from .depletion import BookDepletionLedger, DepletionEntry
from .engine import BacktestResult, BacktestSummary, EventDrivenBacktester, TradeRecord
from .expression_evaluator import (
    ALLOWED_MICROSTRUCTURE_VARS,
    SafeExpressionEvaluator,
    extract_l2_frame_context,
)
from .fee_models import (
    ExchangeFeeBreakdown,
    calculate_exchange_fee,
    calculate_kalshi_breakeven_spread,
    calculate_kalshi_taker_fee,
    calculate_limitless_fee,
    calculate_polymarket_fee,
    calculate_venue_fee as calculate_exact_venue_fee,
    generate_fee_breakeven_matrix,
    get_kalshi_per_contract_fee,
)
from .fetch_and_backtest import fetch_and_backtest
from .latency import NetworkLatencyConfig
from .multi_strategy_engine import (
    CustomStrategySimulator,
    MarketMakingSimulator,
    OrderflowImbalanceSimulator,
    ResolutionCarrySimulator,
    SimulatedPosition,
    StrategyType,
)
from .orderbook_math import (
    OrderBookLevel,
    calculate_venue_fee,
    calculate_vwap,
    compute_dual_leg_arbitrage,
    normalize_kalshi_reciprocal_book,
)
from .rebalancer import CrossChainRebalancer, RebalanceTransfer

__version__ = "1.5.0"

__all__ = [
    # Core Engine
    "BacktestResult",
    "BacktestSummary",
    "BookDepletionLedger",
    "CrossChainRebalancer",
    "DepletionEntry",
    "EventDrivenBacktester",
    "NetworkLatencyConfig",
    "OrderBookLevel",
    "RebalanceTransfer",
    "SimulatedClock",
    "TradeRecord",
    "calculate_venue_fee",
    "calculate_vwap",
    "compute_dual_leg_arbitrage",
    "fetch_and_backtest",
    "normalize_kalshi_reciprocal_book",
    # 5 Strategies
    "StrategyType",
    "MarketMakingSimulator",
    "OrderflowImbalanceSimulator",
    "ResolutionCarrySimulator",
    "CustomStrategySimulator",
    "SimulatedPosition",
    # AST Evaluator
    "SafeExpressionEvaluator",
    "ALLOWED_MICROSTRUCTURE_VARS",
    "extract_l2_frame_context",
    # Fee Models
    "ExchangeFeeBreakdown",
    "calculate_exchange_fee",
    "calculate_exact_venue_fee",
    "calculate_kalshi_taker_fee",
    "get_kalshi_per_contract_fee",
    "calculate_polymarket_fee",
    "calculate_limitless_fee",
    "calculate_kalshi_breakeven_spread",
    "generate_fee_breakeven_matrix",
]
