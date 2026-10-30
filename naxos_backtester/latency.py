"""4-Stage Network Latency & Packet Pipeline Simulation.

Simulates physical cross-connect and transit latencies:
1. Feed Arrival:     t_bot_sees = t_exchange + feed_arrival_ms (35ms ± 15ms)
2. Leg 1 Order Send: t_leg1_match = t_bot_sees + compute_ms + leg1_order_latency_ms
3. Leg 1 Exchange Ack: t_leg1_ack = t_leg1_match + leg1_ack_latency_ms
4. Leg 2 Order Send: t_leg2_match = t_leg1_ack + leg2_order_latency_ms

Simulates adverse selection when rival HFT sweeps consume Leg 2 liquidity during the round-trip wire window.
"""

from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Tuple


@dataclass
class NetworkLatencyConfig:
    """Network and compute latency parameters (in milliseconds)."""
    feed_arrival_ms: float = 35.0      # Wire lag from exchange to trading bot
    leg1_order_latency_ms: float = 25.0 # Round-trip wire lag to Leg 1 venue
    leg1_ack_latency_ms: float = 20.0   # Wire lag from Leg 1 venue ack to bot
    leg2_order_latency_ms: float = 25.0 # Round-trip wire lag to Leg 2 venue
    compute_overhead_ms: float = 2.0    # Local bot strategy compute time
    jitter_ms: float = 15.0             # Gaussian / uniform jitter deviation
    seed: int = 42

    def sample_feed_lag(self, rng: random.Random) -> int:
        """Sample feed arrival latency with jitter."""
        noise = rng.uniform(-self.jitter_ms, self.jitter_ms)
        return max(1, int(round(self.feed_arrival_ms + noise)))

    def sample_leg1_flight(self, rng: random.Random) -> int:
        """Sample Leg 1 wire + compute latency."""
        noise = rng.uniform(-self.jitter_ms * 0.5, self.jitter_ms * 0.5)
        return max(1, int(round(self.leg1_order_latency_ms + self.compute_overhead_ms + noise)))

    def sample_leg1_ack_flight(self, rng: random.Random) -> int:
        """Sample Leg 1 acknowledgement wire latency."""
        noise = rng.uniform(-self.jitter_ms * 0.3, self.jitter_ms * 0.3)
        return max(1, int(round(self.leg1_ack_latency_ms + noise)))

    def sample_leg2_flight(self, rng: random.Random) -> int:
        """Sample Leg 2 wire latency after Leg 1 ack."""
        noise = rng.uniform(-self.jitter_ms * 0.5, self.jitter_ms * 0.5)
        return max(1, int(round(self.leg2_order_latency_ms + noise)))

    def compute_pipeline_timestamps(
        self,
        exchange_ts_ms: int,
        rng: random.Random,
    ) -> Tuple[int, int, int, int]:
        """Compute the 4 discrete timestamps for order execution.

        Returns:
            (t_bot_sees, t_leg1_match, t_leg1_ack, t_leg2_match)
        """
        t_bot = exchange_ts_ms + self.sample_feed_lag(rng)
        t_leg1 = t_bot + self.sample_leg1_flight(rng)
        t_ack = t_leg1 + self.sample_leg1_ack_flight(rng)
        t_leg2 = t_ack + self.sample_leg2_flight(rng)
        return t_bot, t_leg1, t_ack, t_leg2
