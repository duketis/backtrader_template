"""
Configuration loader for Backtest Engine.

Loads and validates YAML configuration files, returning typed Python objects.
Single source of truth for all config access across the application.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List

import yaml

from core.types import (
    CostModel,
    PositionSizingMethod,
    SessionWindow,
    Timeframe,
)


@dataclass
class PositionSizingConfig:
    """Position sizing configuration parsed from YAML."""
    method: PositionSizingMethod
    fixed_lot_size: float
    risk_per_trade_dollars: float
    risk_per_trade_percent: float
    fixed_dollar_amount: float


@dataclass
class RiskConfig:
    """Risk management limits."""
    max_positions: int
    max_daily_loss_dollars: float
    max_daily_loss_percent: float


@dataclass
class DataConfig:
    """Data source paths and timeframe settings."""
    instrument: str
    tick_data_dir: Path
    parquet_dir: Path
    timeframes: List[Timeframe]


@dataclass
class BacktestPeriodConfig:
    """Backtest date range."""
    start_date: str
    end_date: str


@dataclass
class VisualizationConfig:
    """Trade visualization settings."""
    enabled: bool
    output_dir: Path
    plot_format: str
    timeframes: List[Timeframe]
    candles_before_trade: int
    candles_after_trade: int


@dataclass
class LoggingConfig:
    """Logging configuration."""
    level: str
    log_dir: Path
    console: bool
    structured: bool


@dataclass
class AppConfig:
    """Top-level application configuration. Everything in one place."""
    initial_balance: float
    currency: str
    leverage: float
    position_sizing: PositionSizingConfig
    risk: RiskConfig
    costs: CostModel
    session: SessionWindow
    data: DataConfig
    backtest: BacktestPeriodConfig
    visualization: VisualizationConfig
    logging: LoggingConfig


def load_config(config_path: str | Path) -> AppConfig:
    """Load and parse a backtest YAML config file into an AppConfig.

    Args:
        config_path: Path to the backtest.yaml file.

    Returns:
        Fully parsed AppConfig dataclass.

    Raises:
        FileNotFoundError: If config file does not exist.
        KeyError: If a required config key is missing.
        ValueError: If a config value is invalid.
    """
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r") as f:
        raw = yaml.safe_load(f)

    # Resolve paths relative to the config file's directory
    config_dir = config_path.parent.parent.resolve()  # engine/ root (absolute)

    return AppConfig(
        initial_balance=raw["account"]["initial_balance"],
        currency=raw["account"]["currency"],
        leverage=float(raw["account"].get("leverage", 1.0)),
        position_sizing=PositionSizingConfig(
            method=PositionSizingMethod(raw["position_sizing"]["method"]),
            fixed_lot_size=raw["position_sizing"]["fixed_lot_size"],
            risk_per_trade_dollars=raw["position_sizing"]["risk_per_trade_dollars"],
            risk_per_trade_percent=raw["position_sizing"]["risk_per_trade_percent"],
            fixed_dollar_amount=raw["position_sizing"]["fixed_dollar_amount"],
        ),
        risk=RiskConfig(
            max_positions=raw["risk_management"]["max_positions"],
            max_daily_loss_dollars=raw["risk_management"]["max_daily_loss_dollars"],
            max_daily_loss_percent=raw["risk_management"]["max_daily_loss_percent"],
        ),
        costs=CostModel(
            spread_points=raw["costs"]["spread_points"],
            commission_per_trade=raw["costs"]["commission_per_trade"],
            commission_per_lot=raw["costs"]["commission_per_lot"],
            slippage_points=raw["costs"]["slippage_points"],
        ),
        session=SessionWindow(
            timezone=raw["session"]["timezone"],
            start_time=raw["session"]["start_time"],
            end_time=raw["session"]["end_time"],
            dst_aware=raw["session"]["dst_aware"],
        ),
        data=DataConfig(
            instrument=raw["data"]["instrument"],
            tick_data_dir=config_dir / raw["data"]["tick_data_dir"],
            parquet_dir=config_dir / raw["data"]["parquet_dir"],
            timeframes=[Timeframe.from_string(tf) for tf in raw["data"]["timeframes"]],
        ),
        backtest=BacktestPeriodConfig(
            start_date=raw["backtest"]["start_date"],
            end_date=raw["backtest"]["end_date"],
        ),
        visualization=VisualizationConfig(
            enabled=raw["visualization"]["enabled"],
            output_dir=config_dir / raw["visualization"]["output_dir"],
            plot_format=raw["visualization"]["plot_format"],
            timeframes=[
                Timeframe.from_string(tf) for tf in raw["visualization"]["timeframes"]
            ],
            candles_before_trade=raw["visualization"]["candles_before_trade"],
            candles_after_trade=raw["visualization"]["candles_after_trade"],
        ),
        logging=LoggingConfig(
            level=raw["logging"]["level"],
            log_dir=config_dir / raw["logging"]["log_dir"],
            console=raw["logging"]["console"],
            structured=raw["logging"]["structured"],
        ),
    )
