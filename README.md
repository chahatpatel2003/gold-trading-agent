# Gold Trading Agent (XAUUSD): Risk-First Paper Trading with a Continuous-Learning Loop

A paper-trading system for **gold (XAUUSD)**. It is built around one constraint: **live trading is disabled by default** and can only be enabled after a strategy passes explicit deployment gates.

It has two layers:

1. **Strategy research.** 16 rule-based strategies run through a backtester with realistic costs, walk-forward testing and Monte-Carlo resampling. They are ranked by *robustness*, not raw return.
2. **A continuous-learning agent.** It watches the market on five timeframes and streams ticks from a broker practice feed. It makes and grades its own predictions, keeps a journal and writes a daily report, all without placing real orders.

| | |
|---|---|
| **Market** | XAUUSD spot gold (TradingView / OANDA practice feeds; yfinance and CSV supported) |
| **Stack** | Python, pandas, NumPy, SciPy, `ta`, Click CLI, structlog, Matplotlib; a small read-only web dashboard (HTML/JS) |
| **Scale** | ~21k lines of Python · 16 strategies · 8 market-intelligence modules · 18 learning-loop modules |
| **Tests** | 30 pytest tests, all passing |
| **Status** | Paper trading and research only; the live path is gated and off |

---

## Architecture

```
main.py                     CLI: backtest · paper-trade · gate-check · report · tournament · learn · learn-deep · learn-live · live (gated)
config/                     default.yaml (master configuration) + loader (environment overrides)
data/                       providers (TradingView, yfinance, CSV, OANDA), chronological splitter, regime + session labels, indicators
strategies/                 base interface + 16 strategies: trend following, mean reversion, Asian-range breakout, momentum, momentum-trend,
                            Ichimoku, multi-timeframe, RSI divergence, session momentum, smart money, stochastic RSI, triple EMA,
                            volatility breakout, volume-price, cross-market, ensemble (voting / weighted consensus)
backtest/                   bar-by-bar engine with costs · metrics · walk-forward · Monte-Carlo trade resampling
risk/                       position sizing, drawdown limits, kill switches
broker/                     broker interface · simulated paper broker · OANDA practice-account adapter
paper_trade/                paper-trading loop
live_trade_disabled/gate.py live trading blocked unless every deployment gate passes
reports/                    strategy comparison reports + deployment-gate checker
intelligence/               COT positioning, economic calendar, ICT concepts, cross-market universe with random-matrix cleaning,
                            news, order flow, seasonality
learn/                      the learning agent: market observer (5m/15m/1h/4h/1d snapshots), tick streamer, prediction engine,
                            strategy lab and evolver, self-optimiser, mental-trade tracker, risk manager, journals, daily reports
dashboard/                  read-only status dashboard (server + static page)
tournament.py               strategy tournament
run_learner.sh              runs the two learning services with automatic restart
```

## Results

**Backtest comparison** ([`reports/`](reports/), 2026-05-21, ranked by robustness score):

| Strategy | Robustness | Sharpe | Max DD | Profit factor | Trades |
|---|---:|---:|---:|---:|---:|
| Trend following | 0.838 | 1.34 | 2.09 % | 2.19 | 294 |
| Mean reversion | 0.468 | 0.33 | 2.28 % | 1.32 | 103 |
| Ensemble | 0.154 | −1.07 | 1.90 % | 0.00 | 8 |
| Momentum | 0.151 | −0.90 | 3.24 % | 0.33 | 24 |

Each report also lists **why each strategy may fail**: whipsaws in ranging markets, indicator lag, regime change, and data-feed problems. These are hypothetical backtests, and the deployment gate was built so that a good backtest alone can never switch on live trading.

**Learning loop, live paper observation** (3–8 June 2026, from the agent's own state files in `learn/data/`):

- The agent made and graded **27 directional predictions**: 11 correct, 4 partial, 12 wrong.
- All 7 mental trades expired without reaching target or stop.

Over that window the agent did not show a usable edge, and the journals record the lessons it drew.

## Running it

```bash
git clone https://github.com/chahatpatel2003/gold-trading-agent.git
cd gold-trading-agent
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # add practice-account credentials only if you use the OANDA / TradingView feeds
python main.py backtest           # walk-forward + Monte Carlo
python main.py paper-trade
python main.py gate-check
pytest tests/ -v
```

Learning services: `bash run_learner.sh`. The script now finds its own folder. `PYTHON`, `GOLD_BOT_DIR` and `LOGDIR` can be overridden with environment variables; the defaults reproduce the original setup.

## What is not included

- **Recorded broker tick streams and price captures**, including the 500-snapshot observation log. These are broker / TradingView data and are kept private.
- **Paper-signal logs and run logs.** They contain feed prices and account identifiers.
- **`.env`.** Credentials.
- **A third-party MetaTrader expert advisor (`.ex5`) and its settings files.** These are not this project's code.
- **The original `gold_trading_bot.zip` snapshot.** `main.py`, `requirements.txt` and `run_learner.sh` existed only inside that archive and have been restored here. The archive itself is kept privately.

## Third-party material

- **CFTC Commitments of Traders data** cached in `learn/data/` is public U.S. government data and is not claimed.
- **Analyst views** summarised in `learn/data/fundamentals.json` are attributed to the institutions named there.
- **Method:** `intelligence/rmt_cleaner.py` implements the random-matrix cleaning of Ledoit and Péché (2011, arXiv:0911.3010).
- **Trading concepts:** ICT-style concepts in `intelligence/ict_concepts.py` are publicly taught ideas, implemented independently.
- **Data and broker services** (TradingView via the third-party `tvdatafeed` package, OANDA, yfinance) are used under their own terms. Their raw data is not redistributed here; the agent's own prediction records and one analysis chart contain a few feed prices.
- **Open-source libraries** are installed as dependencies under their own licences; none are copied into this repository.

## Notes

- Assembled on 2026-10-14. File contents are byte-identical to that snapshot (SHA-256 verified). The one exception is `run_learner.sh`, whose hardcoded home folder of the original machine was replaced by the portable settings above, without changing what the script runs.
- `.env.example` contains variable names only, no values.
- Research and paper trading only. Nothing here is investment advice.

© Chahat Patel. All rights reserved. This notice covers the original code, documentation and research results in this repository. It does not extend to the third-party material listed above, which belongs to its respective owners. No license to reuse this code is granted; it is published for review.
