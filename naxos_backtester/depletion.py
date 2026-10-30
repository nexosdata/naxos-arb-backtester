"""Shadow Liquidity Depletion Ledger.

Prevents backtesters from repeatedly filling against identical resting order book levels
across consecutive ticks when the exchange tape has not refreshed that price level.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class DepletionEntry:
    price: float
    depleted_size: float
    original_tape_size: float
    last_update_ts_ms: int


class BookDepletionLedger:
    """Tracks simulated consumption of resting order book liquidity.

    Subsequent frames within TTL (e.g. 300s) have their available size reduced
    by the volume filled in earlier frames.
    """

    def __init__(self, ttl_sec: float = 300.0):
        self.ttl_ms = int(ttl_sec * 1000)
        # key: (venue, symbol, side) -> dict: price -> DepletionEntry
        self._depletions: Dict[Tuple[str, str, str], Dict[float, DepletionEntry]] = {}

    def _clean_expired(self, key: Tuple[str, str, str], current_ts_ms: int) -> None:
        if key not in self._depletions:
            return
        entries = self._depletions[key]
        expired = [p for p, e in entries.items() if current_ts_ms - e.last_update_ts_ms > self.ttl_ms]
        for p in expired:
            del entries[p]

    def record_fill(
        self,
        venue: str,
        symbol: str,
        side: str,
        price: float,
        filled_size: float,
        original_size: float,
        current_ts_ms: int,
    ) -> None:
        """Record consumed volume at price level."""
        key = (venue.upper(), symbol, side.upper())
        self._clean_expired(key, current_ts_ms)
        if key not in self._depletions:
            self._depletions[key] = {}

        p_round = round(price, 4)
        if p_round in self._depletions[key]:
            entry = self._depletions[key][p_round]
            entry.depleted_size += filled_size
            entry.last_update_ts_ms = current_ts_ms
        else:
            self._depletions[key][p_round] = DepletionEntry(
                price=p_round,
                depleted_size=filled_size,
                original_tape_size=original_size,
                last_update_ts_ms=current_ts_ms,
            )

    def get_effective_size(
        self,
        venue: str,
        symbol: str,
        side: str,
        price: float,
        tape_size: float,
        current_ts_ms: int,
    ) -> float:
        """Get remaining available liquidity at price level after previous fills."""
        key = (venue.upper(), symbol, side.upper())
        self._clean_expired(key, current_ts_ms)
        if key not in self._depletions:
            return tape_size

        p_round = round(price, 4)
        entry = self._depletions[key].get(p_round)
        if not entry:
            return tape_size

        # If tape size changed significantly, assume market maker refreshed quotes
        if abs(tape_size - entry.original_tape_size) > 1e-4:
            del self._depletions[key][p_round]
            return tape_size

        remaining = max(0.0, tape_size - entry.depleted_size)
        return round(remaining, 4)
