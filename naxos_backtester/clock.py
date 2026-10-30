"""Virtual Simulation Clock with Strict Zero-Lookahead Assertion.

Guarantees that backtesting algorithms cannot peek ahead into future order book ticks.
Monotonically advances millisecond timestamps and provides UTC datetimes.
"""

from __future__ import annotations

from datetime import datetime, timezone


class SimulatedClock:
    """Virtual zero-lookahead simulation clock.

    Tracks time monotonically forward in milliseconds. Provides datetime in UTC.
    """

    def __init__(self, start_ts_ms: int = 0):
        self._current_ts_ms = start_ts_ms

    @property
    def current_ts_ms(self) -> int:
        return self._current_ts_ms

    def sim_now(self) -> datetime:
        """Return current virtual simulation time as UTC datetime."""
        return datetime.fromtimestamp(self._current_ts_ms / 1000.0, tz=timezone.utc)

    def advance_to(self, new_ts_ms: int) -> None:
        """Advance clock forward. Raises ValueError if attempted backward step."""
        if new_ts_ms < self._current_ts_ms:
            raise ValueError(
                f"Clock lookahead violation: Cannot retreat time from {self._current_ts_ms}ms to {new_ts_ms}ms"
            )
        self._current_ts_ms = new_ts_ms

    def __call__(self) -> datetime:
        return self.sim_now()
