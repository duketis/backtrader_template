"""
Core types and dataclasses for the Backtest Engine.

These are the shared data structures used across all modules.
Defined in one place to avoid circular imports and ensure consistency.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


# ==============================================================================
# Enums
# ==============================================================================

class Direction(Enum):
    """Trade direction."""
    LONG = "long"
    SHORT = "short"


class PositionSizingMethod(Enum):
    """How to calculate trade size.

    - fixed_lot:      Always trade the same lot size
    - fixed_risk:     Size the position so the dollar risk to SL is constant
    - percent_equity: Size so the risk to SL is a % of current equity
    - fixed_dollar:   Allocate a fixed notional dollar value per trade
    """
    FIXED_LOT = "fixed_lot"
    FIXED_RISK = "fixed_risk"
    PERCENT_EQUITY = "percent_equity"
    FIXED_DOLLAR = "fixed_dollar"


class TradeStatus(Enum):
    """Lifecycle of a trade."""
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class Timeframe(Enum):
    """Supported data timeframes.

    Values are pandas-compatible frequency strings for resampling.
    """
    TICK = "tick"
    ONE_MIN = "1min"
    FIVE_MIN = "5min"
    ONE_HOUR = "1hour"
    FOUR_HOUR = "4hour"

    @property
    def pandas_freq(self) -> str:
        """Return pandas-compatible frequency string for resampling."""
        mapping = {
            Timeframe.ONE_MIN: "1min",
            Timeframe.FIVE_MIN: "5min",
            Timeframe.ONE_HOUR: "1h",
            Timeframe.FOUR_HOUR: "4h",
        }
        if self == Timeframe.TICK:
            raise ValueError("Cannot resample to tick — tick is the base data")
        return mapping[self]

    @property
    def display_name(self) -> str:
        """Human-readable name for chart titles etc."""
        mapping = {
            Timeframe.TICK: "Tick",
            Timeframe.ONE_MIN: "1 Minute",
            Timeframe.FIVE_MIN: "5 Minute",
            Timeframe.ONE_HOUR: "1 Hour",
            Timeframe.FOUR_HOUR: "4 Hour",
        }
        return mapping[self]

    @classmethod
    def from_string(cls, value: str) -> "Timeframe":
        """Parse a timeframe from config string like '1min', '5min', '1hour', '4hour'."""
        mapping = {
            "tick": cls.TICK,
            "1min": cls.ONE_MIN,
            "5min": cls.FIVE_MIN,
            "1hour": cls.ONE_HOUR,
            "4hour": cls.FOUR_HOUR,
        }
        if value not in mapping:
            raise ValueError(
                f"Unknown timeframe '{value}'. Valid: {list(mapping.keys())}"
            )
        return mapping[value]


# ==============================================================================
# Dataclasses
# ==============================================================================

@dataclass
class TradeRecord:
    """Complete record of a single trade for logging and visualization.

    This is the central data structure passed from the trade logger
    to the analysis and visualization modules. It captures everything
    needed to reconstruct and verify a trade.
    """
    # Identification
    trade_id: int
    direction: Direction

    # Timing
    entry_time: datetime
    exit_time: Optional[datetime] = None

    # Prices
    entry_price: float = 0.0
    exit_price: float = 0.0
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None

    # Sizing
    size: float = 0.0               # Lot/contract size
    notional_value: float = 0.0     # Dollar value of position

    # Costs
    spread_cost: float = 0.0        # Cost from spread
    commission_cost: float = 0.0    # Cost from commission
    slippage_cost: float = 0.0      # Cost from slippage

    # P&L
    gross_pnl: float = 0.0          # P&L before costs
    net_pnl: float = 0.0            # P&L after all costs
    total_costs: float = 0.0        # Sum of all costs

    # State
    status: TradeStatus = TradeStatus.OPEN

    # Metadata
    entry_reason: str = ""          # Why the trade was entered
    exit_reason: str = ""           # Why the trade was exited
    notes: str = ""                 # Additional notes
    metadata: dict = field(default_factory=dict)  # Strategy-specific data (e.g. {"confluence": "FVG"})

    @property
    def is_winner(self) -> bool:
        """Trade was profitable after costs."""
        return self.net_pnl > 0

    @property
    def risk_reward_actual(self) -> Optional[float]:
        """Actual R:R achieved. Returns None if no SL was set."""
        if self.stop_loss is None or self.entry_price == 0:
            return None
        risk = abs(self.entry_price - self.stop_loss)
        if risk == 0:
            return None
        reward = abs(self.exit_price - self.entry_price)
        return reward / risk

    @property
    def duration_seconds(self) -> Optional[float]:
        """Trade duration in seconds. None if still open."""
        if self.exit_time is None:
            return None
        return (self.exit_time - self.entry_time).total_seconds()


@dataclass
class SessionWindow:
    """Defines a trading session window in a specific timezone.

    Used by the session filter to determine if a given UTC timestamp
    falls within the active trading window.
    """
    timezone: str                    # e.g. "America/New_York"
    start_time: str                  # e.g. "08:00"
    end_time: str                    # e.g. "16:30"
    dst_aware: bool = True


@dataclass
class CostModel:
    """All trading costs applied to each trade.

    Spread is applied as half-spread on each side of the fill price.
    Commission can be per-trade (flat) or per-lot.
    Slippage is additional adverse price movement beyond spread.
    """
    spread_points: float = 1.14     # Full spread in index points
    commission_per_trade: float = 0.0
    commission_per_lot: float = 0.0
    slippage_points: float = 0.0

    @property
    def half_spread(self) -> float:
        """Half the spread — applied to fill price on entry/exit."""
        return self.spread_points / 2.0

    def total_entry_cost_per_unit(self) -> float:
        """Points of adverse cost on entry (half spread + slippage)."""
        return self.half_spread + self.slippage_points

    def total_exit_cost_per_unit(self) -> float:
        """Points of adverse cost on exit (half spread + slippage)."""
        return self.half_spread + self.slippage_points

    def commission_for_trade(self, lot_size: float) -> float:
        """Total commission for one side of a trade."""
        return self.commission_per_trade + (self.commission_per_lot * lot_size)


@dataclass
class BacktestResult:
    """Summary of a completed backtest run."""
    # Trade list
    trades: list = field(default_factory=list)  # List[TradeRecord]

    # Summary stats (populated by metrics module)
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0

    gross_profit: float = 0.0
    gross_loss: float = 0.0
    net_profit: float = 0.0
    total_costs: float = 0.0

    max_drawdown: float = 0.0
    max_drawdown_percent: float = 0.0
    sharpe_ratio: float = 0.0
    profit_factor: float = 0.0
    avg_winner: float = 0.0
    avg_loser: float = 0.0
    avg_rr: float = 0.0
    largest_winner: float = 0.0
    largest_loser: float = 0.0

    start_equity: float = 0.0
    end_equity: float = 0.0
    return_percent: float = 0.0

    # Streaks
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0

    # Duration stats (in minutes)
    avg_trade_duration_min: float = 0.0
    avg_winner_duration_min: float = 0.0
    avg_loser_duration_min: float = 0.0

    # Long/Short breakdown
    long_trades: int = 0
    short_trades: int = 0
    long_win_rate: float = 0.0
    short_win_rate: float = 0.0
    long_net_pnl: float = 0.0
    short_net_pnl: float = 0.0

    # Expectancy
    expectancy: float = 0.0  # avg $ per trade

    # Equity curve (for charting)
    equity_curve: list = field(default_factory=list)  # [(trade_id, equity)]
