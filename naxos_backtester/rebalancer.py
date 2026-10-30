"""Cross-Chain Automated USDC & Fiat Ledger Rebalancer.

Manages cash distribution across venues:
- Polymarket: Polygon PoS USDC
- Limitless: Base L2 USDC
- Kalshi / ForecastEx: USD ACH/Wire Cash Ledger

Triggers automated rebalancing transfers when venue cash drops below threshold,
preventing execution starvation while accurately simulating flight times and bridge fees.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from .clock import SimulatedClock


@dataclass
class RebalanceTransfer:
    id: str
    from_venue: str
    to_venue: str
    amount: float
    fee: float
    start_ts_ms: int
    settlement_ts_ms: int
    settled: bool = False


class CrossChainRebalancer:
    """Simulates automated capital rebalancing between prediction market venues."""

    def __init__(
        self,
        clock: SimulatedClock,
        min_reserve_usd: float = 300.0,
        target_allocation_usd: float = 1000.0,
        bridge_delay_sec: float = 120.0,
        bridge_fee_usd: float = 1.50,
    ):
        self.clock = clock
        self.min_reserve_usd = min_reserve_usd
        self.target_allocation_usd = target_allocation_usd
        self.bridge_delay_ms = int(bridge_delay_sec * 1000)
        self.bridge_fee_usd = bridge_fee_usd

        # Venue cash balances
        self.balances: Dict[str, float] = {
            "POLYMARKET": 2500.0,
            "KALSHI": 2500.0,
            "LIMITLESS": 1000.0,
            "FORECASTX": 1000.0,
        }

        self.transfers: List[RebalanceTransfer] = []
        self._tx_counter = 0

    def check_and_rebalance(self) -> List[RebalanceTransfer]:
        """Check venue cash balances and initiate transfers if any venue is starved."""
        now_ms = self.clock.current_ts_ms

        # 1. Settle completed transfers
        for tx in self.transfers:
            if not tx.settled and now_ms >= tx.settlement_ts_ms:
                self.balances[tx.to_venue] = self.balances.get(tx.to_venue, 0.0) + tx.amount
                tx.settled = True

        initiated: List[RebalanceTransfer] = []

        # 2. Check for depleted venues
        for venue, cash in list(self.balances.items()):
            if cash < self.min_reserve_usd:
                # Find wealthiest venue to source capital
                source_venue = max(self.balances.keys(), key=lambda v: self.balances[v])
                source_cash = self.balances[source_venue]

                if source_cash >= self.min_reserve_usd * 2.5:
                    transfer_amt = min(
                        self.target_allocation_usd - cash,
                        (source_cash - self.min_reserve_usd) * 0.5,
                    )
                    if transfer_amt > 50.0:
                        self.balances[source_venue] -= (transfer_amt + self.bridge_fee_usd)
                        self._tx_counter += 1
                        tx = RebalanceTransfer(
                            id=f"tx-rebal-{self._tx_counter}",
                            from_venue=source_venue,
                            to_venue=venue,
                            amount=transfer_amt,
                            fee=self.bridge_fee_usd,
                            start_ts_ms=now_ms,
                            settlement_ts_ms=now_ms + self.bridge_delay_ms,
                        )
                        self.transfers.append(tx)
                        initiated.append(tx)

        return initiated
