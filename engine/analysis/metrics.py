"""
Post-backtest metrics calculator.

Takes a list of TradeRecord objects and computes comprehensive
performance statistics. Populates a BacktestResult dataclass.
"""

from typing import List

import numpy as np

from core.types import BacktestResult, TradeRecord


def calculate_metrics(
    trades: List[TradeRecord],
    initial_balance: float,
) -> BacktestResult:
    """Compute all performance metrics from a list of trades.

    Args:
        trades: List of completed TradeRecord objects.
        initial_balance: Starting account balance.

    Returns:
        BacktestResult with all stats populated.
    """
    result = BacktestResult(
        trades=trades,
        total_trades=len(trades),
        start_equity=initial_balance,
    )

    if not trades:
        result.end_equity = initial_balance
        return result

    # Separate winners and losers
    winners = [t for t in trades if t.is_winner]
    losers = [t for t in trades if not t.is_winner]

    result.winning_trades = len(winners)
    result.losing_trades = len(losers)
    result.win_rate = len(winners) / len(trades) if trades else 0.0

    # P&L
    winner_pnls = [t.net_pnl for t in winners]
    loser_pnls = [t.net_pnl for t in losers]

    result.gross_profit = sum(winner_pnls) if winner_pnls else 0.0
    result.gross_loss = sum(loser_pnls) if loser_pnls else 0.0
    result.net_profit = sum(t.net_pnl for t in trades)
    result.total_costs = sum(t.total_costs for t in trades)

    result.avg_winner = np.mean(winner_pnls) if winner_pnls else 0.0
    result.avg_loser = np.mean(loser_pnls) if loser_pnls else 0.0
    result.largest_winner = max(winner_pnls) if winner_pnls else 0.0
    result.largest_loser = min(loser_pnls) if loser_pnls else 0.0

    # Profit factor
    if result.gross_loss != 0:
        result.profit_factor = abs(result.gross_profit / result.gross_loss)
    else:
        result.profit_factor = float("inf") if result.gross_profit > 0 else 0.0

    # Average R:R
    rr_values = [t.risk_reward_actual for t in trades if t.risk_reward_actual is not None]
    result.avg_rr = np.mean(rr_values) if rr_values else 0.0

    # Equity curve for drawdown calculation
    equity = [initial_balance]
    for t in trades:
        equity.append(equity[-1] + t.net_pnl)

    result.end_equity = equity[-1]
    result.return_percent = ((result.end_equity - initial_balance) / initial_balance) * 100

    # Max drawdown
    peak = initial_balance
    max_dd = 0.0
    max_dd_pct = 0.0
    for eq in equity:
        if eq > peak:
            peak = eq
        dd = peak - eq
        dd_pct = (dd / peak) * 100 if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = dd_pct

    result.max_drawdown = max_dd
    result.max_drawdown_percent = max_dd_pct

    # Sharpe ratio (simplified — using trade returns)
    if len(trades) > 1:
        trade_returns = [t.net_pnl for t in trades]
        mean_return = np.mean(trade_returns)
        std_return = np.std(trade_returns, ddof=1)
        if std_return > 0:
            # Annualized assuming ~252 trading days
            result.sharpe_ratio = (mean_return / std_return) * np.sqrt(252)
        else:
            result.sharpe_ratio = 0.0
    else:
        result.sharpe_ratio = 0.0

    # Consecutive win/loss streaks
    max_wins, max_losses, cur_wins, cur_losses = 0, 0, 0, 0
    for t in trades:
        if t.is_winner:
            cur_wins += 1
            cur_losses = 0
        else:
            cur_losses += 1
            cur_wins = 0
        max_wins = max(max_wins, cur_wins)
        max_losses = max(max_losses, cur_losses)
    result.max_consecutive_wins = max_wins
    result.max_consecutive_losses = max_losses

    # Duration stats
    durations = [t.duration_seconds for t in trades if t.duration_seconds is not None]
    winner_durations = [t.duration_seconds for t in winners if t.duration_seconds is not None]
    loser_durations = [t.duration_seconds for t in losers if t.duration_seconds is not None]

    if durations:
        result.avg_trade_duration_min = np.mean(durations) / 60.0
    if winner_durations:
        result.avg_winner_duration_min = np.mean(winner_durations) / 60.0
    if loser_durations:
        result.avg_loser_duration_min = np.mean(loser_durations) / 60.0

    # Long/Short breakdown
    from core.types import Direction
    longs = [t for t in trades if t.direction == Direction.LONG]
    shorts = [t for t in trades if t.direction == Direction.SHORT]
    long_wins = [t for t in longs if t.is_winner]
    short_wins = [t for t in shorts if t.is_winner]

    result.long_trades = len(longs)
    result.short_trades = len(shorts)
    result.long_win_rate = len(long_wins) / len(longs) if longs else 0.0
    result.short_win_rate = len(short_wins) / len(shorts) if shorts else 0.0
    result.long_net_pnl = sum(t.net_pnl for t in longs)
    result.short_net_pnl = sum(t.net_pnl for t in shorts)

    # Expectancy (average $ per trade)
    result.expectancy = result.net_profit / len(trades) if trades else 0.0

    # Equity curve for charting
    eq = initial_balance
    result.equity_curve = [(0, initial_balance)]  # (trade_id, equity)
    for t in trades:
        eq += t.net_pnl
        result.equity_curve.append((t.trade_id, eq))

    return result


def format_results(result: BacktestResult) -> str:
    """Format a BacktestResult into a human-readable string.

    Args:
        result: Computed BacktestResult.

    Returns:
        Formatted summary string.
    """
    lines = [
        "=" * 60,
        "BACKTEST RESULTS",
        "=" * 60,
        "",
        f"  Total Trades:        {result.total_trades}",
        f"  Winners:             {result.winning_trades}",
        f"  Losers:              {result.losing_trades}",
        f"  Win Rate:            {result.win_rate:.1%}",
        "",
        "--- P&L ---",
        f"  Net Profit:          ${result.net_profit:,.2f}",
        f"  Gross Profit:        ${result.gross_profit:,.2f}",
        f"  Gross Loss:          ${result.gross_loss:,.2f}",
        f"  Total Costs:         ${result.total_costs:,.2f}",
        f"  Expectancy:          ${result.expectancy:,.2f}/trade",
        "",
        "--- Risk ---",
        f"  Max Drawdown:        ${result.max_drawdown:,.2f} ({result.max_drawdown_percent:.1f}%)",
        f"  Sharpe Ratio:        {result.sharpe_ratio:.2f}",
        f"  Profit Factor:       {result.profit_factor:.2f}",
        f"  Max Win Streak:      {result.max_consecutive_wins}",
        f"  Max Loss Streak:     {result.max_consecutive_losses}",
        "",
        "--- Trade Stats ---",
        f"  Avg Winner:          ${result.avg_winner:,.2f}",
        f"  Avg Loser:           ${result.avg_loser:,.2f}",
        f"  Largest Winner:      ${result.largest_winner:,.2f}",
        f"  Largest Loser:       ${result.largest_loser:,.2f}",
        f"  Avg R:R:             {result.avg_rr:.2f}",
        "",
        "--- Long vs Short ---",
        f"  Long:   {result.long_trades} trades, {result.long_win_rate:.1%} WR, ${result.long_net_pnl:,.2f}",
        f"  Short:  {result.short_trades} trades, {result.short_win_rate:.1%} WR, ${result.short_net_pnl:,.2f}",
        "",
        "--- Equity ---",
        f"  Starting Balance:    ${result.start_equity:,.2f}",
        f"  Ending Balance:      ${result.end_equity:,.2f}",
        f"  Return:              {result.return_percent:.2f}%",
        "=" * 60,
    ]
    return "\n".join(lines)
