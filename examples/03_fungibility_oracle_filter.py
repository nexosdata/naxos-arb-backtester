#!/usr/bin/env python3
"""Example 3: Settlement Fungibility Oracle Filter.

Demonstrates filtering cross-venue candidate pairs using institutional settlement
fungibility equivalence scores (0-100). Protects execution capital by rejecting
toxic pairs with divergent resolution criteria (fungibility_score < 85).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class MarketPairAudit:
    pair_id: str
    venue_a: str
    venue_b: str
    question_a: str
    question_b: str
    oracle_a: str
    oracle_b: str
    expiry_diff_hours: float
    fungibility_score: int
    rejection_reason: str = ""


def audit_pair_fungibility(pair: MarketPairAudit) -> bool:
    """Evaluate whether candidate pair meets institutional fungibility standard (score >= 85)."""
    return pair.fungibility_score >= 85


def main() -> None:
    print(f"\n{'='*88}")
    print(" NAXOSDATA SETTLEMENT FUNGIBILITY ORACLE FILTER")
    print(" Filtering cross-venue pairs to eliminate toxic resolution risk (Threshold >= 85/100)")
    print(f"{'='*88}\n")

    candidates: List[MarketPairAudit] = [
        MarketPairAudit(
            pair_id="FED-25BPS-NOV26",
            venue_a="POLYMARKET",
            venue_b="KALSHI",
            question_a="Fed cuts Federal Funds Target Rate by 25bps at Nov 2026 FOMC",
            question_b="Fed Interest Rate Cut 25bps in November 2026",
            oracle_a="Federal Reserve FOMC Statement & Release",
            oracle_b="Federal Reserve Board of Governors Release",
            expiry_diff_hours=0.0,
            fungibility_score=96,
        ),
        MarketPairAudit(
            pair_id="CPI-YOY-OCT26",
            venue_a="KALSHI",
            venue_b="POLYMARKET",
            question_a="US Headline CPI Year-over-Year >= 2.8% for October 2026",
            question_b="October 2026 Annual CPI inflation rate at or above 2.8%",
            oracle_a="US Bureau of Labor Statistics (BLS) CPI News Release",
            oracle_b="BLS Seasonally Adjusted Consumer Price Index",
            expiry_diff_hours=0.0,
            fungibility_score=94,
        ),
        MarketPairAudit(
            pair_id="BTC-100K-DEC26",
            venue_a="POLYMARKET",
            venue_b="LIMITLESS",
            question_a="Will Bitcoin reach $100,000 on or before Dec 31, 2026?",
            question_b="Bitcoin touches $100k before 2027",
            oracle_a="Binance BTC/USDT 1-minute candle high",
            oracle_b="CoinGecko BTC aggregate benchmark index",
            expiry_diff_hours=0.0,
            fungibility_score=88,
        ),
        MarketPairAudit(
            pair_id="ECB-RATE-DEC26-TOXIC",
            venue_a="KALSHI",
            venue_b="POLYMARKET",
            question_a="ECB cuts Deposit Facility Rate by 25bps at December 2026 meeting",
            question_b="ECB cuts Main Refinancing Operations Rate in December 2026",
            oracle_a="ECB Governing Council Policy Decision (Deposit Facility)",
            oracle_b="ECB Press Release (Main Refinancing Rate)",
            expiry_diff_hours=4.0,
            fungibility_score=72,
            rejection_reason="Underlying benchmark mismatch (Deposit Rate vs Refinancing Rate)",
        ),
        MarketPairAudit(
            pair_id="WEATHER-NYC-SNOW-TOXIC",
            venue_a="POLYMARKET",
            venue_b="KALSHI",
            question_a="Will Central Park record measurable snowfall in Dec 2026?",
            question_b="Snowfall > 0.1 inches in New York City in December 2026",
            oracle_a="National Weather Service Central Park Station",
            oracle_b="NOAA Daily Climate Report (LaGuardia + JFK + Central Park avg)",
            expiry_diff_hours=24.0,
            fungibility_score=64,
            rejection_reason="Geographic reporting station variance (Central Park only vs 3-airport aggregate)",
        ),
    ]

    accepted = []
    rejected = []

    for c in candidates:
        if audit_pair_fungibility(c):
            accepted.append(c)
        else:
            rejected.append(c)

    print(f"ACCEPTED INSTITUTIONAL PAIRS ({len(accepted)} approved for automated HFT):")
    for a in accepted:
        print(f"  [SCORE: {a.fungibility_score}/100] {a.pair_id:<22} | {a.venue_a} <-> {a.venue_b}")
        print(f"    Resolution: {a.oracle_a} vs. {a.oracle_b}")

    print(f"\nREJECTED TOXIC CANDIDATES ({len(rejected)} blocked by risk guard):")
    for r in rejected:
        print(f"  [SCORE: {r.fungibility_score}/100 - REJECTED] {r.pair_id:<22} | {r.venue_a} <-> {r.venue_b}")
        print(f"    Risk Trigger: {r.rejection_reason}")

    print(f"\n{'='*88}")
    print(f"Summary: {len(accepted)} pairs passed strict fungibility standard (score >= 85).")
    print(f"         {len(rejected)} toxic pairs filtered out, preventing adverse settlement loss.")
    print("SUCCESS: Settlement fungibility oracle filter completed cleanly.")


if __name__ == "__main__":
    main()
