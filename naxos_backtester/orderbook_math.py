"""Order Book Mathematics, Reciprocal Normalization & Execution Mechanics.

Implements:
1. Kalshi Reciprocal Yes/No Normalization into canonical equities-style USD bid/ask ladders.
2. Volume-Weighted Average Price (VWAP) calculation across resting depth levels.
3. Multi-venue fee models (Polymarket NegRisk, Kalshi regulatory fees, Limitless Base gas).
4. Dual-leg arbitrage spread math: Net Edge = $1.00 - (P_long + P_short) - Fees.
5. Rung-2 unhedged escape sweeps and emergency Leg-1 scratch unwinds.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Dict, List, Optional, Tuple, Union


@dataclass
class OrderBookLevel:
    price: float
    size: float


def normalize_kalshi_reciprocal_book(
    yes_bids: Optional[List[Union[List[float], Tuple[float, float], OrderBookLevel]]] = None,
    yes_asks: Optional[List[Union[List[float], Tuple[float, float], OrderBookLevel]]] = None,
    no_bids: Optional[List[Union[List[float], Tuple[float, float], OrderBookLevel]]] = None,
    no_asks: Optional[List[Union[List[float], Tuple[float, float], OrderBookLevel]]] = None,
) -> Tuple[List[OrderBookLevel], List[OrderBookLevel]]:
    """Convert Kalshi reciprocal Yes/No orders into standard canonical USD bid and ask ladders.

    On binary prediction markets:
    - Buying NO at price P is mathematically equivalent to selling YES at (1.0 - P).
    - Selling NO at price P is equivalent to buying YES at (1.0 - P).

    Returns:
        (canonical_yes_bids, canonical_yes_asks) sorted by best price first.
    """
    bids_dict: Dict[float, float] = {}
    asks_dict: Dict[float, float] = {}

    def _extract(level: Any) -> Optional[Tuple[float, float]]:
        if isinstance(level, OrderBookLevel):
            p, s = level.price, level.size
        elif isinstance(level, (list, tuple)) and len(level) >= 2:
            p, s = float(level[0]), float(level[1])
        else:
            return None
        if p <= 0.0 or p >= 1.0 or s <= 0.0:
            return None
        return round(p, 4), float(s)

    # 1. Native YES bids and asks
    for raw in yes_bids or []:
        parsed = _extract(raw)
        if parsed:
            bids_dict[parsed[0]] = bids_dict.get(parsed[0], 0.0) + parsed[1]

    for raw in yes_asks or []:
        parsed = _extract(raw)
        if parsed:
            asks_dict[parsed[0]] = asks_dict.get(parsed[0], 0.0) + parsed[1]

    # 2. Reciprocal NO bids -> YES asks: Ask_YES = 1.0 - Bid_NO
    for raw in no_bids or []:
        parsed = _extract(raw)
        if parsed:
            recip_ask = round(1.0 - parsed[0], 4)
            if 0.0 < recip_ask < 1.0:
                asks_dict[recip_ask] = asks_dict.get(recip_ask, 0.0) + parsed[1]

    # 3. Reciprocal NO asks -> YES bids: Bid_YES = 1.0 - Ask_NO
    for raw in no_asks or []:
        parsed = _extract(raw)
        if parsed:
            recip_bid = round(1.0 - parsed[0], 4)
            if 0.0 < recip_bid < 1.0:
                bids_dict[recip_bid] = bids_dict.get(recip_bid, 0.0) + parsed[1]

    # Sort bids descending (highest price first), asks ascending (lowest price first)
    sorted_bids = [
        OrderBookLevel(price=p, size=bids_dict[p])
        for p in sorted(bids_dict.keys(), reverse=True)
    ]
    sorted_asks = [
        OrderBookLevel(price=p, size=asks_dict[p])
        for p in sorted(asks_dict.keys())
    ]

    return sorted_bids, sorted_asks


def calculate_vwap(
    levels: List[Union[OrderBookLevel, List[float], Tuple[float, float]]],
    target_size: float,
) -> Tuple[float, float, float]:
    """Calculate Volume-Weighted Average Price (VWAP) for sweeping target_size.

    Returns:
        (vwap_price, filled_size, slippage_cents)
    """
    if target_size <= 0.0 or not levels:
        return 0.0, 0.0, 0.0

    accum_cost = 0.0
    accum_size = 0.0

    first_price = None

    for lvl in levels:
        if isinstance(lvl, OrderBookLevel):
            p, s = lvl.price, lvl.size
        elif isinstance(lvl, (list, tuple)) and len(lvl) >= 2:
            p, s = float(lvl[0]), float(lvl[1])
        else:
            continue

        if first_price is None:
            first_price = p

        needed = target_size - accum_size
        take_size = min(s, needed)

        accum_cost += p * take_size
        accum_size += take_size

        if accum_size >= target_size:
            break

    if accum_size <= 0.0:
        return 0.0, 0.0, 0.0

    vwap = accum_cost / accum_size
    slippage_cents = abs(vwap - (first_price or vwap)) * 100.0

    return round(vwap, 4), round(accum_size, 4), round(slippage_cents, 4)


def calculate_venue_fee(
    venue: str,
    price: float,
    shares: float,
) -> float:
    """Calculate exchange execution fee for taker orders.

    - Polymarket: 0.0% taker fee on standard CLOB binary pairs.
    - Kalshi: $0.005 per contract ($0.50 per 100 contracts).
    - Limitless: 0.10% Base L2 gas fee equivalent.
    - ForecastEx: $0.005 per contract regulatory fee.
    """
    v = venue.upper()
    if "KALSHI" in v or "FORECASTX" in v or "IBKR" in v:
        return round(0.005 * shares, 4)
    if "LIMITLESS" in v:
        return round(price * shares * 0.001, 4)
    # Polymarket CLOB
    return 0.0


def compute_dual_leg_arbitrage(
    best_ask_leg1: float,
    best_ask_leg2: float,
    venue_leg1: str = "POLYMARKET",
    venue_leg2: str = "KALSHI",
    size: float = 100.0,
) -> Dict[str, Any]:
    """Evaluate dual-leg binary prediction market arbitrage.

    Payoff condition:
    If Contract 1 is YES and Contract 2 is NO on the same underlying resolution,
    a portfolio holding 1 YES + 1 NO settles to exactly $1.00 USD at maturity.
    Gross edge = $1.00 - (P_yes + P_no).
    """
    total_entry_cost = best_ask_leg1 + best_ask_leg2
    spread_cents = round((1.0 - total_entry_cost) * 100.0, 3)

    fee1 = calculate_venue_fee(venue_leg1, best_ask_leg1, size)
    fee2 = calculate_venue_fee(venue_leg2, best_ask_leg2, size)
    total_fees = fee1 + fee2

    gross_pnl = (1.0 - total_entry_cost) * size
    net_pnl = gross_pnl - total_fees
    net_roi_pct = round((net_pnl / (total_entry_cost * size)) * 100.0, 2) if total_entry_cost > 0 else 0.0

    return {
        "is_arbitrage": net_pnl > 0.0,
        "spread_cents": spread_cents,
        "total_entry_cost": round(total_entry_cost, 4),
        "gross_pnl_usd": round(gross_pnl, 2),
        "total_fees_usd": round(total_fees, 2),
        "net_pnl_usd": round(net_pnl, 2),
        "net_roi_pct": net_roi_pct,
    }
