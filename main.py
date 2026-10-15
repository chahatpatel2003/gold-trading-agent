#!/usr/bin/env python3
"""
Gold Trading Bot — Main CLI Entry Point.
Commands: backtest, paper-trade, report, gate-check
Live trading is DISABLED by default and gated behind strict checks.
"""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

import click

from backtest.engine import BacktestEngine
from backtest.monte_carlo import monte_carlo_test
from backtest.walk_forward import walk_forward_test
from config.loader import load_config
from data.provider import get_data
from data.splitter import chronological_split, label_market_regime, label_trading_session
from live_trade_disabled.gate import block_live_trading, check_live_trading_gate
from logs.logger import get_logger, setup_logging
from paper_trade.runner import PaperTradeRunner, build_strategies
from reports.deployment_gate import check_deployment_gates, print_gate_report
from reports.generator import generate_comparison_report
from strategies.breakout import BreakoutStrategy
from strategies.ensemble import EnsembleStrategy
from strategies.ichimoku_cloud import IchimokuCloudStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.momentum import MomentumStrategy
from strategies.momentum_trend import MomentumTrendStrategy
from strategies.multi_timeframe import MultiTimeframeStrategy
from strategies.rsi_divergence import RSIDivergenceStrategy
from strategies.session_momentum import SessionMomentumStrategy
from strategies.smart_money import SmartMoneyStrategy
from strategies.stochastic_rsi import StochasticRSIStrategy
from strategies.trend_following import TrendFollowingStrategy
from strategies.triple_ema import TripleEMAStrategy
from strategies.volatility_breakout import VolatilityBreakoutStrategy
from strategies.volume_price import VolumePriceStrategy


@click.group()
@click.option("--config", default=None, help="Path to config YAML file")
@click.pass_context
def cli(ctx, config):
    """Gold Trading Bot — XAUUSD Paper Trading System"""
    ctx.ensure_object(dict)
    cfg = load_config(config)
    setup_logging(
        log_dir=cfg.get("logging", {}).get("dir", "./logs"),
        level=cfg.get("logging", {}).get("level", "INFO"),
    )
    ctx.obj["cfg"] = cfg


@cli.command()
@click.option("--strategy", default="all", help="Strategy to backtest (all, trend, mean_rev, breakout, momentum, ensemble)")
@click.option("--walk-forward/--no-walk-forward", default=True, help="Run walk-forward analysis")
@click.option("--monte-carlo/--no-monte-carlo", default=True, help="Run Monte Carlo stress test")
@click.pass_context
def backtest(ctx, strategy, walk_forward, monte_carlo):
    """Run backtests on historical data with full metrics."""
    cfg = ctx.obj["cfg"]
    log = get_logger("cli")

    click.echo("=" * 60)
    click.echo("GOLD TRADING BOT — BACKTESTING")
    click.echo("=" * 60)

    # Fetch data
    click.echo("\n[1/5] Fetching historical data...")
    df = get_data(cfg)
    click.echo(f"      Loaded {len(df)} bars from {df.index[0]} to {df.index[-1]}")

    # Split data
    click.echo("\n[2/5] Splitting data (train/val/test)...")
    split = chronological_split(
        df,
        cfg["data"]["train_pct"],
        cfg["data"]["val_pct"],
        cfg["data"]["test_pct"],
    )
    click.echo(f"      Train: {split.split_info['train_bars']} bars")
    click.echo(f"      Val:   {split.split_info['val_bars']} bars")
    click.echo(f"      Test:  {split.split_info['test_bars']} bars")

    # Label regimes
    df = label_market_regime(df)
    df = label_trading_session(df)

    # Build strategies
    click.echo("\n[3/5] Running backtests...")
    strategies = _get_strategies(cfg, strategy)
    engine = BacktestEngine(cfg)

    bt_results = []
    wf_results = []
    mc_results = []

    for strat in strategies:
        click.echo(f"\n  --- {strat.name} ---")

        # Backtest on full dataset for overall metrics
        # Walk-forward below provides unbiased OOS evaluation
        result = engine.run(strat, df)
        bt_results.append(result)

        m = result.metrics
        click.echo(f"  Return: {m.total_return_pct}%  |  Sharpe: {m.sharpe_ratio}")
        click.echo(f"  Max DD: {m.max_drawdown_pct}%  |  Win Rate: {m.win_rate_pct}%")
        click.echo(f"  Trades: {m.num_trades}  |  PF: {m.profit_factor}")
        click.echo(f"  Stability: {m.stability}  |  Expectancy: ${m.expectancy_per_trade}/trade")

        # Walk-forward
        if walk_forward:
            click.echo(f"  Running walk-forward analysis...")
            try:
                wf = walk_forward_test(strat, df, cfg)
                wf_results.append(wf)
                click.echo(f"  WF OOS Sharpe: {wf.combined_metrics.sharpe_ratio}")
            except ValueError as e:
                click.echo(f"  Walk-forward skipped: {e}")

        # Monte Carlo
        if monte_carlo and result.trades:
            click.echo(f"  Running Monte Carlo ({cfg['backtest']['monte_carlo']['n_simulations']} sims)...")
            mc = monte_carlo_test(
                result.trades,
                cfg["backtest"]["initial_equity"],
                n_simulations=cfg["backtest"]["monte_carlo"]["n_simulations"],
                strategy_name=strat.name,
            )
            mc_results.append(mc)
            click.echo(f"  MC Sharpe CI: {mc.sharpe_ci}")
            click.echo(f"  MC Max DD CI: {mc.max_dd_ci}")
            click.echo(f"  P(20% ruin): {mc.prob_ruin_20pct:.4f}")

    # Generate report
    click.echo("\n[4/5] Generating comparison report...")
    report_path = generate_comparison_report(
        bt_results,
        wf_results if wf_results else None,
        mc_results if mc_results else None,
    )
    click.echo(f"      Report saved: {report_path}")

    # Summary ranking
    click.echo("\n[5/5] STRATEGY RANKING (by robustness, not raw return):")
    click.echo("-" * 50)
    sorted_results = sorted(bt_results, key=lambda r: r.metrics.sharpe_ratio, reverse=True)
    for i, r in enumerate(sorted_results, 1):
        click.echo(f"  #{i}  {r.strategy_name:20s}  Sharpe={r.metrics.sharpe_ratio:6.3f}  DD={r.metrics.max_drawdown_pct:5.1f}%")

    click.echo("\nDone. Review the full report for detailed analysis.")


@cli.command(name="paper-trade")
@click.option("--strategy", default="all", help="Strategy to paper trade")
@click.pass_context
def paper_trade(ctx, strategy):
    """Run paper trading simulation."""
    cfg = ctx.obj["cfg"]

    click.echo("=" * 60)
    click.echo("GOLD TRADING BOT — PAPER TRADING")
    click.echo("=" * 60)
    click.echo("\nNOTE: This is paper trading. No real money is at risk.\n")

    # Fetch data
    click.echo("[1/3] Fetching data...")
    df = get_data(cfg)

    # Use the test split for paper trading simulation
    split = chronological_split(
        df,
        cfg["data"]["train_pct"],
        cfg["data"]["val_pct"],
        cfg["data"]["test_pct"],
    )

    strategies = _get_strategies(cfg, strategy)

    click.echo(f"\n[2/3] Running paper trading with {len(strategies)} strategies...")
    runner = PaperTradeRunner(cfg, strategies)
    results = runner.run_on_historical(split.test)

    click.echo("\n[3/3] Paper Trading Results:")
    click.echo("-" * 60)
    for name, r in results.items():
        click.echo(f"\n  {name}:")
        click.echo(f"    Final Equity:  ${r['final_equity']:,.2f}")
        click.echo(f"    Return:        {r['total_return_pct']}%")
        click.echo(f"    Total Trades:  {r['total_trades']}")
        click.echo(f"    Win/Loss:      {r['winning_trades']}/{r['losing_trades']}")
        click.echo(f"    Signals:       {r['signal_count']} generated, {r['rejections']} rejected")

    # Save logs
    runner.save_logs()
    click.echo("\nSignal logs saved to ./logs/")
    click.echo("Run 'python main.py gate-check' to check deployment readiness.")


@cli.command(name="gate-check")
@click.option("--strategy", default="trend_following", help="Strategy to check")
@click.pass_context
def gate_check(ctx, strategy):
    """Check if a strategy passes all deployment gates."""
    cfg = ctx.obj["cfg"]

    click.echo("=" * 60)
    click.echo("DEPLOYMENT GATE CHECK")
    click.echo("=" * 60)

    # Run backtest
    df = get_data(cfg)
    split = chronological_split(
        df,
        cfg["data"]["train_pct"],
        cfg["data"]["val_pct"],
        cfg["data"]["test_pct"],
    )

    strategies = _get_strategies(cfg, strategy)
    if not strategies:
        click.echo("No matching strategy found.")
        return

    strat = strategies[0]
    engine = BacktestEngine(cfg)
    bt_result = engine.run(strat, split.test)

    # Walk-forward
    try:
        wf_result = walk_forward_test(strat, df, cfg)
    except ValueError:
        wf_result = None

    # Monte Carlo
    mc_result = None
    if bt_result.trades:
        mc_result = monte_carlo_test(
            bt_result.trades,
            cfg["backtest"]["initial_equity"],
            strategy_name=strat.name,
        )

    # Check gates
    all_passed, checks = check_deployment_gates(
        bt_result, wf_result, mc_result, cfg=cfg
    )

    click.echo(print_gate_report(checks))

    if not all_passed:
        click.echo("\nLive trading should remain DISABLED.")
    else:
        click.echo("\nGates passed, but proceed with extreme caution.")
        click.echo("Start with reduced position sizes (25-50% of target).")


@cli.command()
@click.pass_context
def report(ctx):
    """Generate strategy comparison report from latest backtest."""
    ctx.invoke(backtest, strategy="all", walk_forward=True, monte_carlo=True)


@cli.command(name="live")
@click.pass_context
def live_trade(ctx):
    """DISABLED — Live trading is not enabled."""
    cfg = ctx.obj["cfg"]
    allowed, failures = check_live_trading_gate(cfg)
    if not allowed:
        block_live_trading(f"Failed gates: {', '.join(failures)}")
    else:
        click.echo("Live trading gate passed but not implemented yet.")
        click.echo("This is intentional — build confidence with paper trading first.")


@cli.command(name="tournament")
@click.pass_context
def tournament(ctx):
    """Run strategy tournament — backtest all strategies and pick the best."""
    from tournament import run_tournament
    run_tournament()


@cli.command(name="learn")
@click.option("--continuous", is_flag=True, help="Keep running and re-fetch every interval")
@click.option("--interval", default=300, help="Seconds between data refreshes (default 300 = 5 min)")
@click.pass_context
def learn(ctx, continuous, interval):
    """Watch live gold market on ALL timeframes and learn patterns (no money at risk)."""
    import time
    from learn.market_observer import MarketObserver

    cfg = ctx.obj["cfg"]

    click.echo("=" * 75)
    click.echo("GOLD TRADING BOT — MULTI-TIMEFRAME LIVE LEARNING MODE")
    click.echo("  Timeframes: 5M | 15M | 1H | 4H | 1D")
    click.echo("=" * 75)
    click.echo("\nNO MONEY AT RISK. Observing and learning only.\n")

    observer = MarketObserver()
    symbol = cfg["data"].get("tradingview_symbol", "XAUUSD")
    exchange = cfg["data"].get("tradingview_exchange", "OANDA")

    while True:
        try:
            click.echo(f"[{time.strftime('%H:%M:%S')}] Fetching ALL timeframes (5M, 15M, 1H, 4H, 1D)...")
            all_data = observer.fetch_all_timeframes(symbol=symbol, exchange=exchange)

            fetched = {tf: len(df) for tf, df in all_data.items() if df is not None}
            click.echo(f"  Fetched: {fetched}")

            report = observer.generate_multi_tf_report(all_data)
            click.echo(report)

            observer.save_knowledge()
            click.echo(f"\nKnowledge saved to {observer.data_dir}/")

        except Exception as e:
            click.echo(f"  Error: {e}")

        if not continuous:
            break

        click.echo(f"\nNext update in {interval}s... (Ctrl+C to stop)")
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            click.echo("\nStopping learning mode.")
            observer.save_knowledge()
            break


@cli.command(name="learn-deep")
@click.option("--interval", default=300, help="Seconds between learning cycles (default 300 = 5 min)")
@click.option("--once", is_flag=True, help="Run one cycle and exit")
@click.pass_context
def learn_deep(ctx, interval, once):
    """Deep learning mode — observe, predict, discover correlations, invent strategies.

    Runs TradingView (all timeframes) + OANDA (live ticks) in parallel.
    Makes predictions, tracks outcomes, finds patterns, mentally tests strategies.
    NO MONEY AT RISK.
    """
    from learn.brain import LearningBrain

    cfg = ctx.obj["cfg"]
    brain = LearningBrain(cfg)
    brain.start(interval=interval, continuous=not once)


@cli.command(name="learn-live")
@click.pass_context
def learn_live(ctx):
    """Stream real-time tick data from OANDA and learn from every price change."""
    import os
    from learn.tick_streamer import TickStreamer

    cfg = ctx.obj["cfg"]
    token = cfg["data"].get("oanda_token") or os.getenv("OANDA_TOKEN")
    account_id = cfg["data"].get("oanda_account_id") or os.getenv("OANDA_ACCOUNT_ID")

    if not token or not account_id:
        click.echo("=" * 70)
        click.echo("OANDA CREDENTIALS REQUIRED FOR LIVE TICK STREAMING")
        click.echo("=" * 70)
        click.echo("")
        click.echo("  To stream real-time ticks, you need a free OANDA practice account:")
        click.echo("")
        click.echo("  1. Sign up at https://www.oanda.com (choose Practice/Demo)")
        click.echo("  2. Log in → Account → Manage API Access → Generate Token")
        click.echo("  3. Copy your Account ID from the account page")
        click.echo("  4. Add to your .env file:")
        click.echo("")
        click.echo("     OANDA_TOKEN=your-api-token-here")
        click.echo("     OANDA_ACCOUNT_ID=your-account-id-here")
        click.echo("")
        click.echo("  It's 100% free. No money needed. Practice account = live prices.")
        return

    click.echo("=" * 70)
    click.echo("GOLD TRADING BOT — REAL-TIME TICK STREAMING")
    click.echo("  Source: OANDA Live Price Stream")
    click.echo("  Building: 10-second, 1-minute, and 5-minute candles from ticks")
    click.echo("=" * 70)
    click.echo("\nNO MONEY AT RISK. Observing every price tick in real time.\n")

    streamer = TickStreamer(
        token=token,
        account_id=account_id,
        practice=True,
    )
    streamer.start()


def _get_strategies(cfg, strategy_name):
    """Build strategy list based on CLI argument."""
    all_strats = build_strategies(cfg)
    if strategy_name == "all":
        return all_strats
    return [s for s in all_strats if strategy_name in s.name]


if __name__ == "__main__":
    cli()
