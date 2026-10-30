"""Canonical Exchange Fee Engine for Prediction Markets.

Provides exact price-dependent fee calculations for:
1. Kalshi: Nonlinear quadratic taker fee curve:
   Fee_Kalshi(C, P) = ceil_cents(0.07 * C * P * (1 - P))
   where C is contract count and P in (0, 1) is contract price in dollars.
2. Polymarket: 0 bps maker/taker CLOB fee + Polygon L2 gas estimate (~$0.008/tx).
3. Limitless: 10 bps taker fee + Base L2 gas estimate (~$0.004/tx).
4. ForecastEx (IBKR): Flat threshold fee of $0.005 per contract.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Dict, List, Optional, Tuple, Union


# Gas and flat fee constants
POLYGON_L2_GAS_USD: float = 0.008
BASE_L2_GAS_USD: float = 0.004
FORECASTEX_FEE_PER_CONTRACT_USD: float = 0.005
LIMITLESS_TAKER_BPS: float = 10.0


def ceil_cents(val_dollars: float) -> float:
    """Round up value in dollars to the next whole cent ($0.01)."""
    if val_dollars <= 0.0:
        return 0.0
    # Use round(..., 6) before ceil to prevent IEEE 754 precision artifacts (e.g. 1.7500000000000002)
    cents = round(val_dollars * 100.0, 6)
    return math.ceil(cents) / 100.0


def calculate_kalshi_taker_fee(
    contracts: Union[int, float],
    price: float,
    round_to_cents: bool = True,
) -> float:
    """Calculate Kalshi taker fee for C contracts at price P.

    Formula: Fee = ceil_cents(0.07 * C * P * (1 - P))
    """
    if contracts <= 0 or price <= 0.0 or price >= 1.0:
        return 0.0

    raw_fee = 0.07 * float(contracts) * price * (1.0 - price)
    if round_to_cents:
        return ceil_cents(raw_fee)
    return raw_fee


def get_kalshi_per_contract_fee(price: float) -> float:
    """Get the unrounded per-contract Kalshi taker fee in dollars at price P."""
    if price <= 0.0 or price >= 1.0:
        return 0.0
    return 0.07 * price * (1.0 - price)


def calculate_polymarket_fee(
    contracts: Union[int, float],
    price: float,
    include_gas: bool = True,
) -> float:
    """Calculate Polymarket fee: 0 bps CLOB fee + optional Polygon L2 gas estimate."""
    if contracts <= 0 or price <= 0.0:
        return 0.0
    return POLYGON_L2_GAS_USD if include_gas else 0.0


def calculate_limitless_fee(
    contracts: Union[int, float],
    price: float,
    include_gas: bool = True,
) -> float:
    """Calculate Limitless fee: 10 bps taker fee on volume + optional Base L2 gas."""
    if contracts <= 0 or price <= 0.0:
        return 0.0
    notional = float(contracts) * price
    clob_fee = (notional * LIMITLESS_TAKER_BPS) / 10000.0
    gas_fee = BASE_L2_GAS_USD if include_gas else 0.0
    return clob_fee + gas_fee


def calculate_forecastex_fee(
    contracts: Union[int, float],
    price: float,
) -> float:
    """Calculate ForecastEx fee: $0.005 per contract ($0.50 per 100 contracts)."""
    if contracts <= 0 or price <= 0.0:
        return 0.0
    return float(contracts) * FORECASTEX_FEE_PER_CONTRACT_USD


@dataclass
class ExchangeFeeBreakdown:
    venue: str
    contracts: float
    price: float
    notional_usd: float
    clob_fee_usd: float
    gas_usd: float
    total_fee_usd: float
    fee_cents: float
    per_contract_fee_cents: float
    effective_bps_on_payout: float
    effective_bps_on_price: float
    formula_description: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "venue": self.venue,
            "contracts": self.contracts,
            "price": self.price,
            "notional_usd": round(self.notional_usd, 4),
            "clob_fee_usd": round(self.clob_fee_usd, 4),
            "gas_usd": round(self.gas_usd, 4),
            "total_fee_usd": round(self.total_fee_usd, 4),
            "fee_cents": round(self.fee_cents, 2),
            "per_contract_fee_cents": round(self.per_contract_fee_cents, 4),
            "effective_bps_on_payout": round(self.effective_bps_on_payout, 2),
            "effective_bps_on_price": round(self.effective_bps_on_price, 2),
            "formula_description": self.formula_description,
        }


def calculate_exchange_fee(
    venue: str,
    contracts: Union[int, float],
    price: float,
    include_gas: bool = True,
) -> ExchangeFeeBreakdown:
    """Compute complete dynamic fee breakdown for an order on any supported venue."""
    v = venue.upper()
    c = max(0.0, float(contracts))
    p = max(0.001, min(0.999, float(price)))
    notional = c * p

    if v == "KALSHI":
        clob_fee = calculate_kalshi_taker_fee(c, p, round_to_cents=True)
        gas = 0.0
        per_contract_cents = (0.07 * p * (1.0 - p)) * 100.0
        desc = f"Kalshi quadratic taker fee: ceil(0.07 * C * P * (1-P)) = {clob_fee:.4f} USD"
    elif v == "POLYMARKET":
        clob_fee = 0.0
        gas = POLYGON_L2_GAS_USD if include_gas else 0.0
        per_contract_cents = (gas / c) * 100.0 if c > 0 else 0.0
        desc = "Polymarket 0 bps CLOB maker/taker + Polygon L2 gas (~$0.008)"
    elif v == "LIMITLESS":
        clob_fee = (notional * LIMITLESS_TAKER_BPS) / 10000.0
        gas = BASE_L2_GAS_USD if include_gas else 0.0
        per_contract_cents = ((clob_fee + gas) / c) * 100.0 if c > 0 else 0.0
        desc = "Limitless 10 bps CLOB taker + Base L2 gas (~$0.004)"
    elif v in ("FORECASTEX", "IBKR"):
        clob_fee = c * FORECASTEX_FEE_PER_CONTRACT_USD
        gas = 0.0
        per_contract_cents = FORECASTEX_FEE_PER_CONTRACT_USD * 100.0
        desc = "ForecastEx / IBKR $0.005 per contract exchange fee"
    else:
        # Default 20 bps fallback
        clob_fee = notional * 0.0020
        gas = 0.0
        per_contract_cents = (clob_fee / c) * 100.0 if c > 0 else 0.0
        desc = f"{venue} standard 20 bps taker fee"

    total_fee = clob_fee + gas
    fee_cents = total_fee * 100.0
    effective_bps_payout = (total_fee / c * 10000.0) if c > 0 else 0.0
    effective_bps_price = (total_fee / notional * 10000.0) if notional > 0 else 0.0

    return ExchangeFeeBreakdown(
        venue=v,
        contracts=c,
        price=p,
        notional_usd=notional,
        clob_fee_usd=clob_fee,
        gas_usd=gas,
        total_fee_usd=total_fee,
        fee_cents=fee_cents,
        per_contract_fee_cents=per_contract_cents,
        effective_bps_on_payout=effective_bps_payout,
        effective_bps_on_price=effective_bps_price,
        formula_description=desc,
    )


def calculate_kalshi_breakeven_spread(
    poly_yes_price: float,
    target_roi_pct: float = 0.0,
    contracts: float = 100.0,
) -> Dict[str, Any]:
    """Calculate the maximum Kalshi NO price to break even or hit target ROI.

    A dual-leg arbitrage buys Polymarket YES at poly_yes_price and Kalshi NO at kalshi_no_price.
    Settlement payout is $1.00 per paired contract.
    Total cost = poly_yes_price + kalshi_no_price + poly_fee + kalshi_fee.
    To break even:
        Total Outlay <= 1.00 / (1 + target_roi_pct / 100)
    Kalshi NO is priced at P_no, where Kalshi fee is ceil_cents(0.07 * C * P_no * (1 - P_no)).

    Solves the exact quadratic equation:
        0.07 * P_no^2 - 1.07 * P_no + K >= 0
    where K = 1.0 / (1 + target_roi / 100) - poly_p - poly_fee.
    The exact analytical root is:
        P_no = (1.07 - sqrt(1.1449 - 0.28 * K)) / 0.14
    """
    c = max(1.0, float(contracts))
    poly_p = max(0.01, min(0.99, float(poly_yes_price)))
    poly_fee_per_contract = POLYGON_L2_GAS_USD / c
    target_multiple = 1.0 + (target_roi_pct / 100.0)
    max_total_outlay_per_contract = 1.0 / target_multiple

    k = max_total_outlay_per_contract - poly_p - poly_fee_per_contract
    best_kalshi_no = 0.0

    if k > 0.0:
        disc = 1.1449 - 0.28 * k
        if disc >= 0.0:
            p_no_analytic = (1.07 - math.sqrt(disc)) / 0.14
            test_no = min(0.99, max(0.001, p_no_analytic))
            test_no = math.floor(test_no * 10000.0) / 10000.0
            while test_no >= 0.001:
                fee_usd = calculate_kalshi_taker_fee(c, test_no, round_to_cents=True)
                fee_per_contract = fee_usd / c
                outlay = poly_p + test_no + poly_fee_per_contract + fee_per_contract
                if outlay <= max_total_outlay_per_contract + 1e-7:
                    best_kalshi_no = test_no
                    break
                test_no = round(test_no - 0.0001, 4)

    kalshi_fee_usd = calculate_kalshi_taker_fee(c, best_kalshi_no, round_to_cents=True) if best_kalshi_no > 0 else 0.0
    kalshi_fee_contract = kalshi_fee_usd / c if best_kalshi_no > 0 else 0.0
    combined_cost = poly_p + best_kalshi_no + poly_fee_per_contract + kalshi_fee_contract
    gross_edge_cents = (1.0 - (poly_p + best_kalshi_no)) * 100.0 if best_kalshi_no > 0 else 0.0
    net_edge_cents = (1.0 - combined_cost) * 100.0 if best_kalshi_no > 0 else 0.0

    return {
        "poly_yes_price": round(poly_p, 4),
        "target_roi_pct": round(target_roi_pct, 2),
        "max_kalshi_no_price": round(best_kalshi_no, 4),
        "kalshi_fee_cents": round(kalshi_fee_contract * 100.0, 3),
        "poly_fee_cents": round(poly_fee_per_contract * 100.0, 3),
        "gross_edge_cents": round(gross_edge_cents, 2),
        "net_edge_cents": round(net_edge_cents, 2),
        "total_cost_per_pair": round(combined_cost, 4),
    }


def generate_fee_breakeven_matrix(
    step: float = 0.05,
    contracts: float = 100.0,
) -> List[Dict[str, Any]]:
    """Generate visual matrix points for Poly YES 0.05 to 0.95."""
    matrix = []
    p = 0.05
    while p <= 0.9501:
        p_round = round(p, 2)
        kalshi_at_p_fee = 0.07 * p_round * (1.0 - p_round)
        be = calculate_kalshi_breakeven_spread(p_round, target_roi_pct=0.0, contracts=contracts)
        roi15 = calculate_kalshi_breakeven_spread(p_round, target_roi_pct=1.5, contracts=contracts)
        roi30 = calculate_kalshi_breakeven_spread(p_round, target_roi_pct=3.0, contracts=contracts)

        matrix.append({
            "poly_yes_price": p_round,
            "kalshi_fee_cents": round(kalshi_at_p_fee * 100.0, 2),
            "kalshi_fee_bps": round(kalshi_at_p_fee * 10000.0, 1),
            "breakeven_kalshi_no": be["max_kalshi_no_price"],
            "roi_15_kalshi_no": roi15["max_kalshi_no_price"],
            "roi_30_kalshi_no": roi30["max_kalshi_no_price"],
            "min_gross_spread_cents": be["gross_edge_cents"],
        })
        p += step
    return matrix


def calculate_venue_fee(
    venue: str,
    contracts: Union[int, float],
    price: float,
    include_gas: bool = True,
) -> float:
    """Convenience helper returning the total fee in USD for a given venue, contract count, and price."""
    return calculate_exchange_fee(venue, contracts, price, include_gas=include_gas).total_fee_usd
