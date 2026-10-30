# NaxosData Arbitrage Backtester (`naxos-arb-backtester`)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![NaxosData](https://img.shields.io/badge/Powered%20By-NaxosData.com-00DC82.svg)](https://naxosdata.com)

A high-performance, discrete event-driven backtesting engine engineered specifically for cross-venue prediction market arbitrage across **Polymarket**, **Kalshi**, **Limitless**, **PredictIt**, **Drift BET**, and **Smarkets**.

Standard equities and crypto backtesters fail on prediction markets because they ignore physical wire transit windows, reciprocal order book inversions, cross-chain bridge flight times, and adverse execution sweeps. **`naxos-arb-backtester`** replaces naive price-matching with realistic institutional microstructure simulation.

---

## Core Quantitative Architecture

### 1. 4-Stage Execution Latency Model (`35ms ± 15ms`)
In cross-venue arbitrage, fills are never instantaneous. An arbitrage bot observing a mispriced spread must undergo four discrete stages:

$$\begin{aligned}
t_{\text{bot}} &= t_{\text{exchange}} + \Delta t_{\text{feed}} \quad (35\text{ms} \pm 15\text{ms}) \\
t_{\text{leg1}} &= t_{\text{bot}} + \Delta t_{\text{compute}} + \Delta t_{\text{order, leg1}} \\
t_{\text{ack}} &= t_{\text{leg1}} + \Delta t_{\text{ack, leg1}} \\
t_{\text{leg2}} &= t_{\text{ack}} + \Delta t_{\text{order, leg2}}
\end{aligned}$$

During the round-trip flight window between Leg 1 execution and Leg 2 matching ($t_{\text{leg2}} - t_{\text{leg1}}$), rival market makers may lift the resting quote, leaving Leg 2 exposed.

### 2. Kalshi Reciprocal Binary Mathematics
Kalshi natively streams Yes/No bids, where buying NO at price $P_{\text{NO}}$ is mathematically equivalent to selling YES at $1.00 - P_{\text{NO}}$. The backtester reconstructs normalized equities-style USD order book ladders so trading algorithms can sweep standard bid/ask queues.

$$\text{Canonical Ask}_{\text{YES}} = 1.00 - \text{Bid}_{\text{NO}}, \quad \text{Canonical Bid}_{\text{YES}} = 1.00 - \text{Ask}_{\text{NO}}$$

Dual-leg risk-free payoff condition:

$$\text{Gross Spread} = 1.00 - (P_{\text{leg1}} + P_{\text{leg2}})$$

### 3. Shadow Liquidity Depletion (`BookDepletionLedger`)
Backtesters that do not track liquidity consumption repeatedly fill against identical historical resting depth across consecutive ticks. The `BookDepletionLedger` decrements resting volume at price $P$ until market makers refresh their quotes or a configurable Time-To-Live (e.g. 300s) elapses.

### 4. Rung-2 Unhedged Escape Sweeps & Emergency Scratch Unwinds
If rival HFT sweeps consume Leg 2 liquidity during the wire flight window, the engine evaluates two emergency risk protocols:
- **Rung-2 Escape Sweep**: If Leg 2 ask slipped but the combined dual-leg cost remains $\le \$1.005$, the bot sweeps the second price rung to complete the hedge with minimal slippage.
- **Emergency Scratch Unwind**: If Leg 2 depth evaporated or slipped beyond acceptable tolerance, the bot immediately executes an IOC sell of Leg 1 back to the resting bid, taking a fractional scratch loss rather than maintaining dangerous directional tail exposure.

### 5. Multi-Venue Automated Cash Rebalancing
Arbitrage continuously depletes cash on the buying venue and accumulates proceeds on the selling venue. The engine models multi-venue cash ledgers across Polygon PoS (Polymarket), Base L2 (Limitless), Solana (Drift BET), and USD settlement (Kalshi, PredictIt, Smarkets).

---

## Production Tiers & Data Access

To run backtests against real historical order book archives, get an API key from [NaxosData.com](https://naxosdata.com):

- **Hobbyist ($0/mo)**: `30 req/min`, `24h` historical lookback, `50,000` historical L2 rows/day, open-source SDK access.
- **Quant Pro ($30/mo)**: `180 req/min`, `90d` historical lookback, `1,000,000` historical L2 rows/day, real-time WebSocket streams & cross-venue pair scanner.
- **Institutional ($100/mo)**: `600 req/min`, unlimited all-time historical lookback, `10,000,000` historical L2 rows/day, priority endpoints & instant Telegram/Discord webhook alerts.

Set your API key:
```bash
export NAXOS_API_KEY="nx_live_..."
```

---

## Installation

```bash
git clone https://github.com/naxosdata/naxos-arb-backtester.git
cd naxos-arb-backtester
pip install -e .
```

With Pandas analysis support:
```bash
pip install -e ".[analysis]"
```

---

## 5 Strategy Archetypes

The backtester supports five discrete simulation archetypes engineered for prediction market microstructure:

1. **`CROSS_VENUE_ARB`**: Dual-leg basis divergence capture between venues with 4-stage latency modeling, shadow liquidity depletion, Rung-2 unhedged escape sweeps, and cross-chain USDC rebalancing.
2. **`MARKET_MAKING`**: Avellaneda-Stoikov high-frequency market making with inventory skew penalties ($r(s, q) = s - q\gamma\sigma^2$) and an adverse selection filter that cancels resting maker quotes during toxic book sweeps.
3. **`ORDERFLOW_IMBALANCE` ($OBI$)**: Top-5 Level 2 book imbalance momentum scalper ($OBI = \frac{V_b - V_a}{V_b + V_a}$) with dynamic take-profit, trailing stop, and time-stop exits.
4. **`RESOLUTION_CARRY`**: Late-stage tail carry harvester exploiting Kalshi's quadratic fee decay near boundaries ($P \ge \$0.90$ or $P \le \$0.10$) to capture low-volatility settlement yield.
5. **`CUSTOM_STRATEGY`**: Safe AST Quantitative Rule Matrix. Users write Pythonic arithmetic expressions (e.g. `obi_top5 > 0.45 and spread_bps < 120 and net_arb_cents > 0.5`) parsed into an immutable AST without `eval()` or arbitrary code execution risks.

---

## Exact Kalshi Quadratic Fee Engine

Prediction market fee structures are nonlinear. While Polymarket charges 0 bps maker/taker, Kalshi levies an exact quadratic taker fee:

$$\text{Fee}_{\text{Kalshi}}(C, P) = \left\lceil 0.07 \cdot C \cdot P \cdot (1 - P) \right\rceil_{\text{cents}}$$

where $C$ is contract volume and $P \in (0, 1)$ is dollar contract price.
- **At $P = \$0.50$**: Fee reaches its theoretical maximum of $1.75¢$ per contract (175 bps on $\$1.00$ payout).
- **At $P = \$0.92$**: Fee drops to $0.52¢$ per contract (52 bps on $\$1.00$ payout).

The engine includes exact analytical breakeven solvers (`calculate_kalshi_breakeven_spread`) solving:
$$0.07 P_{\text{NO}}^2 - 1.07 P_{\text{NO}} + K \ge 0$$
to determine the maximum counterpart leg price for target net ROIs.

---

## Running Examples

The repository includes four self-contained quantitative examples that run out of the box:

### 1. Dual-Leg Kalshi vs. Polymarket Arbitrage
Replays synchronized L2 depth against benchmark tape, executing dual-leg fills through the 4-stage latency pipeline:

```bash
python examples/01_kalshi_vs_polymarket_arb.py
```

### 2. Network Latency Sensitivity Sweep
Evaluates how wire transit times from `10ms` (co-located cross-connect) to `100ms` (public residential internet) impact arbitrage capture, slippage rate, and realized Sharpe ratio:

```bash
python examples/02_latency_sensitivity_sweep.py
```

### 3. Settlement Fungibility Oracle Filter
Demonstrates filtering out toxic or ambiguous market pairs with resolution discrepancies (`fungibility_score < 85`):

```bash
python examples/03_fungibility_oracle_filter.py
```

### 4. Custom Strategy AST Formula Backtest
Compiles custom AST microstructure expressions, models exact Kalshi quadratic fee curves, and executes the `CUSTOM_STRATEGY` simulator against tick data:

```bash
python examples/04_custom_strategy_ast_backtest.py
```

---

## License

MIT © [NaxosData.com](https://naxosdata.com)
