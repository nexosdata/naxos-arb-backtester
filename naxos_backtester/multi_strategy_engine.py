"""Multi-Strategy Simulation Engine for Quantitative Prediction Market Models.

Implements discrete event execution across historical L2 order book tapes for:
1. MARKET_MAKING (Avellaneda-Stoikov Passive L2 Market Making with Inventory Skew & Adverse Selection Filter)
2. ORDERFLOW_IMBALANCE (L2 Order Book Imbalance Top-5 & Momentum Breakout Scalper)
3. RESOLUTION_CARRY (Late-Stage High-Probability Tail Carry & Fee Harvester)
4. CUSTOM_STRATEGY (User-Defined Rule Matrix & Safe AST Expression Evaluator)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import math
import random
from typing import Any, Dict, List, Optional, Tuple

from .expression_evaluator import (
    SafeExpressionEvaluator,
    extract_l2_frame_context,
)
from .fee_models import calculate_venue_fee


class StrategyType(str, Enum):
    CROSS_VENUE_ARB = "CROSS_VENUE_ARB"
    MARKET_MAKING = "MARKET_MAKING"
    ORDERFLOW_IMBALANCE = "ORDERFLOW_IMBALANCE"
    RESOLUTION_CARRY = "RESOLUTION_CARRY"
    CUSTOM_STRATEGY = "CUSTOM_STRATEGY"


@dataclass
class SimulatedPosition:
    position_id: str
    symbol: str
    venue: str
    side: str  # "YES" or "NO"
    entry_price: float
    shares: float
    entry_ts_ms: int
    entry_fee: float
    peak_price: float
    strategy: str
    action_mode: str = "TAKER"


def _extract_best_levels(frame: Dict[str, Any], default_bid: float = 0.49, default_ask: float = 0.51) -> Tuple[float, float]:
    """Safely extract top bid and top ask without raising IndexError on empty order book sides."""
    leg_a = frame.get("leg_a") or {}
    bids = leg_a.get("bids") or frame.get("bids") or []
    asks = leg_a.get("asks") or frame.get("asks") or []

    raw_bid = frame.get("best_bid")
    if raw_bid is not None and float(raw_bid) > 0:
        best_bid = float(raw_bid)
    elif bids and len(bids[0]) > 0:
        best_bid = float(bids[0][0])
    else:
        best_bid = default_bid

    raw_ask = frame.get("best_ask")
    if raw_ask is not None and float(raw_ask) > 0:
        best_ask = float(raw_ask)
    elif asks and len(asks[0]) > 0:
        best_ask = float(asks[0][0])
    else:
        best_ask = default_ask

    return best_bid, best_ask


class BaseStrategySimulator:
    """Base class for modular strategy simulators."""

    def __init__(self, bankroll: float = 5000.0, latency_ms: float = 35.0, config: Optional[Dict[str, Any]] = None):
        self.bankroll = float(bankroll)
        self.cash = float(bankroll)
        self.latency_ms = float(latency_ms)
        self.config = config or {}
        self.open_positions: List[SimulatedPosition] = []
        self.closed_trades: List[Dict[str, Any]] = []

        # Telemetry metrics
        self.positions_opened = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.total_fees_paid = 0.0
        self.total_realized_pnl = 0.0
        self.equity_snapshots: List[Dict[str, Any]] = []

        # Peak equity for drawdown
        self.peak_equity = float(bankroll)
        self.max_drawdown_pct = 0.0

    def get_current_equity(self, current_price: float = 0.5) -> float:
        """Total equity = cash + locked market value of open positions."""
        locked_val = sum(pos.shares * current_price for pos in self.open_positions)
        return round(self.cash + locked_val, 2)

    def record_snapshot(self, ts_ms: int, current_price: float = 0.5) -> None:
        eq = self.get_current_equity(current_price)
        if eq > self.peak_equity:
            self.peak_equity = eq
        dd = round(((self.peak_equity - eq) / self.peak_equity) * 100.0, 2) if self.peak_equity > 0 else 0.0
        if dd > self.max_drawdown_pct:
            self.max_drawdown_pct = dd

        self.equity_snapshots.append({
            "timestamp_ms": ts_ms,
            "equity": round(eq, 2),
            "cash": round(self.cash, 2),
            "pnl": round(eq - self.bankroll, 2),
            "drawdown_pct": dd,
        })

    @property
    def equity(self) -> float:
        """Convenience property for current equity."""
        return self.get_current_equity()

    def on_frame(self, frame: Dict[str, Any], ts_ms: int) -> None:
        """Alias for process_frame."""
        return self.process_frame(frame, ts_ms)

    def process_frame(self, frame: Dict[str, Any], ts_ms: int) -> None:
        raise NotImplementedError


# =============================================================================
# 1. Avellaneda-Stoikov L2 Market Making Simulator
# =============================================================================

class MarketMakingSimulator(BaseStrategySimulator):
    """Quotes two-sided passive limit orders, capturing the bid-ask spread

    while skewing quotes dynamically based on net inventory (inventory_skew_gamma)
    and cancelling resting quotes when adverse selection risk (wire lag or OBI spike) spikes.
    """

    def __init__(self, bankroll: float = 5000.0, latency_ms: float = 35.0, config: Optional[Dict[str, Any]] = None):
        super().__init__(bankroll=bankroll, latency_ms=latency_ms, config=config)
        self.target_half_spread_bps = float(self.config.get("target_half_spread_bps", 60.0))
        self.max_inventory_usd = float(self.config.get("max_inventory_usd", 1000.0))
        self.inventory_skew_gamma = float(self.config.get("inventory_skew_gamma", 0.35))
        self.adverse_selection_cancel_ms = float(self.config.get("adverse_selection_cancel_ms", 35.0))

        # MM specific metrics
        self.maker_rebates_collected = 0.0
        self.quotes_placed = 0
        self.adverse_selection_cancellations = 0
        self.inventory_skew_adjustments = 0
        self.net_inventory_shares = 0.0
        self.last_quote_time_ms = 0

    def process_frame(self, frame: Dict[str, Any], ts_ms: int) -> None:
        context = extract_l2_frame_context(frame)
        mid_p = context["mid_price_cents"] / 100.0
        wire_lag = context["wire_lag_ms"]
        obi = context["obi_top5"]
        leg_a = frame.get("leg_a") or {}
        venue = leg_a.get("venue", "KALSHI")
        symbol = leg_a.get("symbol", "KX-MARKET")

        # 1. Check for Adverse Selection Spike (cancel resting quotes)
        if wire_lag > self.adverse_selection_cancel_ms or abs(obi) > 0.70:
            self.adverse_selection_cancellations += 1
            self.record_snapshot(ts_ms, mid_p)
            return

        # 2. Compute Avellaneda-Stoikov Reservation Price & Quote Skew
        # Reservation price: r(s, q) = mid - q * gamma * half_spread
        inv_usd = self.net_inventory_shares * mid_p
        half_spread = max(0.002, self.target_half_spread_bps / 10000.0)
        norm_inv = max(-1.0, min(1.0, inv_usd / self.max_inventory_usd)) if self.max_inventory_usd > 0 else 0.0
        skew = norm_inv * self.inventory_skew_gamma * half_spread
        reservation_p = mid_p - skew

        if abs(skew) > 0.001:
            self.inventory_skew_adjustments += 1

        my_bid = round(max(0.01, min(0.98, reservation_p - half_spread)), 3)
        my_ask = round(min(0.99, max(my_bid + 0.005, reservation_p + half_spread)), 3)
        self.quotes_placed += 2

        # 3. Simulate Passive Fill Execution Against Order Book Tape
        best_bid, best_ask = _extract_best_levels(frame, default_bid=0.49, default_ask=0.51)

        order_size_shares = 100.0
        order_cost = order_size_shares * my_bid

        # Check Bid Fill (tape trades down to our bid)
        if best_bid <= my_bid and self.cash >= order_cost and (inv_usd + order_cost) <= self.max_inventory_usd:
            fill_fee = calculate_venue_fee(venue, order_size_shares, my_bid)
            total_outlay = order_cost + fill_fee
            self.cash -= total_outlay
            self.total_fees_paid += fill_fee
            self.net_inventory_shares += order_size_shares
            self.positions_opened += 1
            self.open_positions.append(
                SimulatedPosition(
                    position_id=f"mm-bid-{ts_ms}",
                    symbol=symbol,
                    venue=venue,
                    side="YES",
                    entry_price=my_bid,
                    shares=order_size_shares,
                    entry_ts_ms=ts_ms,
                    entry_fee=fill_fee,
                    peak_price=my_bid,
                    strategy="MARKET_MAKING",
                    action_mode="MAKER",
                )
            )

        # Check Ask Fill / Inventory Unwind (tape trades up to our ask)
        if best_ask >= my_ask and self.open_positions:
            # Unwind the oldest open inventory position
            pos = self.open_positions.pop(0)
            proceeds = pos.shares * my_ask
            exit_fee = calculate_venue_fee(venue, pos.shares, my_ask)
            net_proceeds = proceeds - exit_fee
            self.cash += net_proceeds
            self.total_fees_paid += exit_fee
            self.net_inventory_shares = max(0.0, self.net_inventory_shares - pos.shares)

            trade_pnl = net_proceeds - (pos.shares * pos.entry_price + pos.entry_fee)
            self.total_realized_pnl += trade_pnl
            if trade_pnl >= 0:
                self.winning_trades += 1
            else:
                self.losing_trades += 1

            self.closed_trades.append({
                "position_id": pos.position_id,
                "entry_price": pos.entry_price,
                "exit_price": my_ask,
                "shares": pos.shares,
                "pnl": round(trade_pnl, 2),
                "duration_sec": (ts_ms - pos.entry_ts_ms) / 1000.0,
            })

        self.record_snapshot(ts_ms, mid_p)


# =============================================================================
# 2. L2 Order Book Imbalance & Momentum Scalper Simulator
# =============================================================================

class OrderflowImbalanceSimulator(BaseStrategySimulator):
    """Computes real-time Top-5 Rung Order Book Imbalance (OBI)

    Enters directional momentum positions when OBI exceeds threshold,
    exiting at take_profit_cents, stop_loss_cents, or max_hold_seconds.
    """

    def __init__(self, bankroll: float = 5000.0, latency_ms: float = 35.0, config: Optional[Dict[str, Any]] = None):
        super().__init__(bankroll=bankroll, latency_ms=latency_ms, config=config)
        self.obi_entry_threshold = float(self.config.get("obi_entry_threshold", 0.65))
        self.take_profit_cents = float(self.config.get("take_profit_cents", 3.0))
        self.stop_loss_cents = float(self.config.get("stop_loss_cents", 1.5))
        self.max_hold_seconds = float(self.config.get("max_hold_seconds", 120.0))

        self.take_profit_hits = 0
        self.stop_loss_hits = 0
        self.time_stop_hits = 0
        self.last_trade_ts_ms = -100_000

    def process_frame(self, frame: Dict[str, Any], ts_ms: int) -> None:
        context = extract_l2_frame_context(frame)
        mid_p = context["mid_price_cents"] / 100.0
        obi = context["obi_top5"]
        leg_a = frame.get("leg_a") or {}
        venue = leg_a.get("venue", "KALSHI")
        symbol = leg_a.get("symbol", "KX-OBI")
        best_bid, best_ask = _extract_best_levels(frame, default_bid=0.49, default_ask=0.51)

        # 1. Manage Existing Open Scalp Positions (Take Profit, Stop Loss, Time Stop)
        active_remaining = []
        for pos in self.open_positions:
            hold_sec = (ts_ms - pos.entry_ts_ms) / 1000.0
            cur_price = best_bid if pos.side == "YES" else (1.0 - best_ask)
            if cur_price > pos.peak_price:
                pos.peak_price = cur_price

            pnl_cents = (cur_price - pos.entry_price) * 100.0
            should_close = False
            exit_reason = ""

            if pnl_cents >= self.take_profit_cents:
                should_close = True
                exit_reason = "TAKE_PROFIT"
                self.take_profit_hits += 1
            elif pnl_cents <= -self.stop_loss_cents:
                should_close = True
                exit_reason = "STOP_LOSS"
                self.stop_loss_hits += 1
            elif hold_sec >= self.max_hold_seconds:
                should_close = True
                exit_reason = "TIME_STOP"
                self.time_stop_hits += 1

            if should_close:
                exit_fee = calculate_venue_fee(venue, pos.shares, cur_price)
                net_proceeds = (pos.shares * cur_price) - exit_fee
                self.cash += net_proceeds
                self.total_fees_paid += exit_fee
                trade_pnl = net_proceeds - (pos.shares * pos.entry_price + pos.entry_fee)
                self.total_realized_pnl += trade_pnl

                if trade_pnl >= 0:
                    self.winning_trades += 1
                else:
                    self.losing_trades += 1

                self.closed_trades.append({
                    "position_id": pos.position_id,
                    "entry_price": pos.entry_price,
                    "exit_price": cur_price,
                    "shares": pos.shares,
                    "pnl": round(trade_pnl, 2),
                    "exit_reason": exit_reason,
                    "duration_sec": round(hold_sec, 1),
                })
            else:
                active_remaining.append(pos)

        self.open_positions = active_remaining

        # 2. Check OBI Entry Signals (Cooldown: 15s between entries)
        if (ts_ms - self.last_trade_ts_ms) >= 15000 and len(self.open_positions) < 3:
            trade_shares = 200.0
            if obi >= self.obi_entry_threshold:
                # Heavy buying pressure -> Long YES
                entry_cost = trade_shares * best_ask
                fee = calculate_venue_fee(venue, trade_shares, best_ask)
                if self.cash >= (entry_cost + fee):
                    self.cash -= (entry_cost + fee)
                    self.total_fees_paid += fee
                    self.positions_opened += 1
                    self.last_trade_ts_ms = ts_ms
                    self.open_positions.append(
                        SimulatedPosition(
                            position_id=f"obi-yes-{ts_ms}",
                            symbol=symbol,
                            venue=venue,
                            side="YES",
                            entry_price=best_ask,
                            shares=trade_shares,
                            entry_ts_ms=ts_ms,
                            entry_fee=fee,
                            peak_price=best_ask,
                            strategy="ORDERFLOW_IMBALANCE",
                            action_mode="TAKER_IOC",
                        )
                    )
            elif obi <= -self.obi_entry_threshold:
                # Heavy selling pressure -> Long NO (cost is 1.0 - best_bid)
                no_price = round(1.0 - best_bid, 3)
                entry_cost = trade_shares * no_price
                fee = calculate_venue_fee(venue, trade_shares, no_price)
                if self.cash >= (entry_cost + fee):
                    self.cash -= (entry_cost + fee)
                    self.total_fees_paid += fee
                    self.positions_opened += 1
                    self.last_trade_ts_ms = ts_ms
                    self.open_positions.append(
                        SimulatedPosition(
                            position_id=f"obi-no-{ts_ms}",
                            symbol=symbol,
                            venue=venue,
                            side="NO",
                            entry_price=no_price,
                            shares=trade_shares,
                            entry_ts_ms=ts_ms,
                            entry_fee=fee,
                            peak_price=no_price,
                            strategy="ORDERFLOW_IMBALANCE",
                            action_mode="TAKER_IOC",
                        )
                    )

        self.record_snapshot(ts_ms, mid_p)


# =============================================================================
# 3. Resolution Carry & Fee Harvester Simulator
# =============================================================================

class ResolutionCarrySimulator(BaseStrategySimulator):
    """Exploits favorite-longshot bias and Kalshi quadratic tail fees

    Accumulates high-probability contracts (entry_prob_min_cents >= 92) and
    holds to $1.00 settlement unless emergency stop triggers.
    """

    def __init__(self, bankroll: float = 5000.0, latency_ms: float = 35.0, config: Optional[Dict[str, Any]] = None):
        super().__init__(bankroll=bankroll, latency_ms=latency_ms, config=config)
        self.entry_prob_min_cents = float(self.config.get("entry_prob_min_cents", 92.0))
        self.max_allocation_per_market_pct = float(self.config.get("max_allocation_per_market_pct", 25.0))
        self.emergency_stop_drop_cents = float(self.config.get("emergency_stop_drop_cents", 4.0))

        self.settlement_wins = 0
        self.emergency_stops = 0
        self.low_tail_fees_harvested = 0.0

    def process_frame(self, frame: Dict[str, Any], ts_ms: int) -> None:
        context = extract_l2_frame_context(frame)
        mid_p = context["mid_price_cents"] / 100.0
        leg_a = frame.get("leg_a") or {}
        venue = leg_a.get("venue", "KALSHI")
        symbol = leg_a.get("symbol", "KX-CARRY")
        best_bid, best_ask = _extract_best_levels(frame, default_bid=0.93, default_ask=0.95)

        # 1. Manage Existing Tail Carry Positions
        active_remaining = []
        for pos in self.open_positions:
            price_drop_cents = (pos.entry_price - best_bid) * 100.0
            if price_drop_cents >= self.emergency_stop_drop_cents:
                # Emergency Stop triggered: dispute or liquidity breakdown
                self.emergency_stops += 1
                exit_fee = calculate_venue_fee(venue, pos.shares, best_bid)
                net_proceeds = (pos.shares * best_bid) - exit_fee
                self.cash += net_proceeds
                self.total_fees_paid += exit_fee
                trade_pnl = net_proceeds - (pos.shares * pos.entry_price + pos.entry_fee)
                self.total_realized_pnl += trade_pnl
                self.losing_trades += 1
                self.closed_trades.append({
                    "position_id": pos.position_id,
                    "entry_price": pos.entry_price,
                    "exit_price": best_bid,
                    "pnl": round(trade_pnl, 2),
                    "exit_reason": "EMERGENCY_STOP",
                })
            elif best_bid >= 0.999 or (frame.get("expiration_utc") and ts_ms > pos.entry_ts_ms + 120000):
                # Settlement at $1.00
                self.settlement_wins += 1
                gross_proceeds = pos.shares * 1.00
                self.cash += gross_proceeds
                trade_pnl = gross_proceeds - (pos.shares * pos.entry_price + pos.entry_fee)
                self.total_realized_pnl += trade_pnl
                self.winning_trades += 1
                self.closed_trades.append({
                    "position_id": pos.position_id,
                    "entry_price": pos.entry_price,
                    "exit_price": 1.00,
                    "pnl": round(trade_pnl, 2),
                    "exit_reason": "SETTLEMENT_100",
                })
            else:
                active_remaining.append(pos)

        self.open_positions = active_remaining

        # 2. Carry Accumulation Entry
        min_p = self.entry_prob_min_cents / 100.0
        max_alloc_usd = (self.bankroll * self.max_allocation_per_market_pct) / 100.0
        curr_alloc = sum(p.shares * p.entry_price for p in self.open_positions)

        if best_ask >= min_p and best_ask < 0.99 and (curr_alloc < max_alloc_usd):
            order_shares = min(500.0, (max_alloc_usd - curr_alloc) / best_ask)
            if order_shares >= 10.0:
                cost = order_shares * best_ask
                tail_fee = calculate_venue_fee(venue, order_shares, best_ask)
                if self.cash >= (cost + tail_fee):
                    self.cash -= (cost + tail_fee)
                    self.total_fees_paid += tail_fee
                    self.low_tail_fees_harvested += tail_fee
                    self.positions_opened += 1
                    self.open_positions.append(
                        SimulatedPosition(
                            position_id=f"carry-{ts_ms}",
                            symbol=symbol,
                            venue=venue,
                            side="YES",
                            entry_price=best_ask,
                            shares=order_shares,
                            entry_ts_ms=ts_ms,
                            entry_fee=tail_fee,
                            peak_price=best_ask,
                            strategy="RESOLUTION_CARRY",
                            action_mode="TAIL_HARVESTER",
                        )
                    )

        self.record_snapshot(ts_ms, mid_p)


# =============================================================================
# 4. User-Defined Custom Strategy Simulator (Rule Matrix & AST Evaluator)
# =============================================================================

class CustomStrategySimulator(BaseStrategySimulator):
    """Safely evaluates user quantitative expressions and executes custom rules."""

    def __init__(self, bankroll: float = 5000.0, latency_ms: float = 35.0, config: Optional[Dict[str, Any]] = None):
        super().__init__(bankroll=bankroll, latency_ms=latency_ms, config=config)
        self.expression = str(self.config.get("entry_expression") or self.config.get("custom_expression") or self.config.get("expression") or "obi_top5 > 0.50 and spread_bps < 150")
        self.exit_expression = str(self.config.get("exit_expression") or "")
        self.action_mode = str(self.config.get("action_mode", "BUY_YES")).upper()
        self.take_profit_cents = float(self.config.get("take_profit_cents", 3.0))
        self.stop_loss_cents = float(self.config.get("stop_loss_cents", 2.0))
        self.trailing_stop_cents = float(self.config.get("trailing_stop_cents", 1.5))
        self.time_stop_seconds = float(self.config.get("time_stop_seconds", 300.0))
        self.order_size_pct_bankroll = float(self.config.get("order_size_pct_bankroll", 10.0))

        self.last_trigger_ts_ms = -100_000
        self.custom_signals_evaluated = 0
        self.custom_signals_triggered = 0
        self.trailing_stop_hits = 0

    def process_frame(self, frame: Dict[str, Any], ts_ms: int) -> None:
        context = extract_l2_frame_context(frame)
        mid_p = context["mid_price_cents"] / 100.0
        leg_a = frame.get("leg_a") or {}
        venue = leg_a.get("venue", "POLYMARKET")
        symbol = leg_a.get("symbol", "CUSTOM-MARKET")
        best_bid, best_ask = _extract_best_levels(frame, default_bid=0.49, default_ask=0.51)

        # 1. Manage Active Positions (TP, SL, Trailing Stop, Time Stop, Custom Exit Expression)
        active_remaining = []
        for pos in self.open_positions:
            hold_sec = (ts_ms - pos.entry_ts_ms) / 1000.0
            cur_price = best_bid if pos.side == "YES" else (1.0 - best_ask)

            if cur_price > pos.peak_price:
                pos.peak_price = cur_price

            pnl_cents = (cur_price - pos.entry_price) * 100.0
            pullback_cents = (pos.peak_price - cur_price) * 100.0

            should_close = False
            exit_reason = ""

            if self.exit_expression and SafeExpressionEvaluator.evaluate(self.exit_expression, context):
                should_close = True
                exit_reason = "CUSTOM_EXIT_SIGNAL"
            elif pnl_cents >= self.take_profit_cents:
                should_close = True
                exit_reason = "TAKE_PROFIT"
            elif pnl_cents <= -self.stop_loss_cents:
                should_close = True
                exit_reason = "STOP_LOSS"
            elif self.trailing_stop_cents > 0 and pullback_cents >= self.trailing_stop_cents and pnl_cents > 0:
                should_close = True
                exit_reason = "TRAILING_STOP"
                self.trailing_stop_hits += 1
            elif hold_sec >= self.time_stop_seconds:
                should_close = True
                exit_reason = "TIME_STOP"

            if should_close:
                exit_fee = calculate_venue_fee(venue, pos.shares, cur_price)
                net_proceeds = (pos.shares * cur_price) - exit_fee
                self.cash += net_proceeds
                self.total_fees_paid += exit_fee
                trade_pnl = net_proceeds - (pos.shares * pos.entry_price + pos.entry_fee)
                self.total_realized_pnl += trade_pnl

                if trade_pnl >= 0:
                    self.winning_trades += 1
                else:
                    self.losing_trades += 1

                self.closed_trades.append({
                    "position_id": pos.position_id,
                    "entry_price": pos.entry_price,
                    "exit_price": cur_price,
                    "pnl": round(trade_pnl, 2),
                    "exit_reason": exit_reason,
                    "duration_sec": round(hold_sec, 1),
                })
            else:
                active_remaining.append(pos)

        self.open_positions = active_remaining

        # 2. Evaluate User Expression Safely
        self.custom_signals_evaluated += 1
        is_triggered = SafeExpressionEvaluator.evaluate(self.expression, context)

        if is_triggered:
            self.custom_signals_triggered += 1
            # Cooldown of 10s and max 4 open positions
            if (ts_ms - self.last_trigger_ts_ms) >= 10000 and len(self.open_positions) < 4:
                target_alloc = (self.bankroll * self.order_size_pct_bankroll) / 100.0
                exec_price = best_ask if "YES" in self.action_mode else (1.0 - best_bid)
                exec_price = max(0.01, min(0.99, exec_price))
                shares = round(target_alloc / exec_price, 1)

                if shares >= 5.0:
                    cost = shares * exec_price
                    fee = calculate_venue_fee(venue, shares, exec_price)
                    if self.cash >= (cost + fee):
                        self.cash -= (cost + fee)
                        self.total_fees_paid += fee
                        self.positions_opened += 1
                        self.last_trigger_ts_ms = ts_ms
                        self.open_positions.append(
                            SimulatedPosition(
                                position_id=f"custom-{ts_ms}",
                                symbol=symbol,
                                venue=venue,
                                side="YES" if "YES" in self.action_mode else "NO",
                                entry_price=exec_price,
                                shares=shares,
                                entry_ts_ms=ts_ms,
                                entry_fee=fee,
                                peak_price=exec_price,
                                strategy="CUSTOM_STRATEGY",
                                action_mode=self.action_mode,
                            )
                        )

        self.record_snapshot(ts_ms, mid_p)
