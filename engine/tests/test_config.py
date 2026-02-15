"""
Tests for the configuration loader.

Validates that YAML config files are parsed correctly into
typed Python objects, and that missing/invalid values raise
clear errors.
"""

import tempfile
from pathlib import Path

import pytest
import yaml

from core.config import load_config
from core.types import PositionSizingMethod


def _write_config(tmpdir: Path, config_dict: dict) -> Path:
    """Helper: write a config dict to a YAML file in a temp directory."""
    config_dir = tmpdir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "backtest.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config_dict, f)
    return config_path


def _make_valid_config() -> dict:
    """Return a minimal valid config dictionary."""
    return {
        "account": {"initial_balance": 100000, "currency": "USD", "leverage": 50},
        "position_sizing": {
            "method": "fixed_risk",
            "fixed_lot_size": 1.0,
            "risk_per_trade_dollars": 1000,
            "risk_per_trade_percent": 1.0,
            "fixed_dollar_amount": 5000,
        },
        "risk_management": {
            "max_positions": 1,
            "max_daily_loss_dollars": 5000,
            "max_daily_loss_percent": 5.0,
        },
        "costs": {
            "spread_points": 1.14,
            "commission_per_trade": 0.0,
            "commission_per_lot": 0.0,
            "slippage_points": 0.0,
        },
        "session": {
            "timezone": "America/New_York",
            "start_time": "08:00",
            "end_time": "16:30",
            "dst_aware": True,
        },
        "data": {
            "instrument": "USATECHIDXUSD",
            "tick_data_dir": "../data/usatech",
            "parquet_dir": "../data/usatech_parquet",
            "timeframes": ["1min", "5min", "1hour", "4hour"],
        },
        "backtest": {
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
        },
        "visualization": {
            "enabled": True,
            "output_dir": "outputs/runs",
            "plot_format": "html",
            "timeframes": ["1min", "5min", "1hour", "4hour"],
            "candles_before_trade": 50,
            "candles_after_trade": 20,
        },
        "logging": {
            "level": "INFO",
            "log_dir": "logs",
            "console": True,
            "structured": True,
        },
    }


class TestConfigLoading:
    """Test config file loading and parsing."""

    def test_load_valid_config(self, tmp_path):
        config_path = _write_config(tmp_path, _make_valid_config())
        config = load_config(config_path)

        assert config.initial_balance == 100000
        assert config.currency == "USD"
        assert config.position_sizing.method == PositionSizingMethod.FIXED_RISK
        assert config.costs.spread_points == 1.14
        assert config.session.timezone == "America/New_York"
        assert config.session.start_time == "08:00"
        assert config.session.end_time == "16:30"

    def test_position_sizing_methods(self, tmp_path):
        """All position sizing methods should parse correctly."""
        for method in ["fixed_lot", "fixed_risk", "percent_equity", "fixed_dollar"]:
            raw = _make_valid_config()
            raw["position_sizing"]["method"] = method
            config_path = _write_config(tmp_path, raw)
            config = load_config(config_path)
            assert config.position_sizing.method == PositionSizingMethod(method)

    def test_timeframes_parsed(self, tmp_path):
        config_path = _write_config(tmp_path, _make_valid_config())
        config = load_config(config_path)

        from core.types import Timeframe
        assert Timeframe.ONE_MIN in config.data.timeframes
        assert Timeframe.FIVE_MIN in config.data.timeframes
        assert Timeframe.ONE_HOUR in config.data.timeframes
        assert Timeframe.FOUR_HOUR in config.data.timeframes

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/path/config.yaml")

    def test_missing_key_raises(self, tmp_path):
        raw = _make_valid_config()
        del raw["account"]  # Remove required key
        config_path = _write_config(tmp_path, raw)

        with pytest.raises(KeyError):
            load_config(config_path)

    def test_invalid_position_sizing_method(self, tmp_path):
        raw = _make_valid_config()
        raw["position_sizing"]["method"] = "invalid_method"
        config_path = _write_config(tmp_path, raw)

        with pytest.raises(ValueError):
            load_config(config_path)


class TestConfigValues:
    """Test that config values are correctly typed."""

    def test_costs_are_floats(self, tmp_path):
        config_path = _write_config(tmp_path, _make_valid_config())
        config = load_config(config_path)

        assert isinstance(config.costs.spread_points, float)
        assert isinstance(config.costs.commission_per_trade, float)
        assert isinstance(config.costs.slippage_points, float)

    def test_paths_are_path_objects(self, tmp_path):
        config_path = _write_config(tmp_path, _make_valid_config())
        config = load_config(config_path)

        assert isinstance(config.data.tick_data_dir, Path)
        assert isinstance(config.data.parquet_dir, Path)
        assert isinstance(config.visualization.output_dir, Path)

    def test_booleans_are_bool(self, tmp_path):
        config_path = _write_config(tmp_path, _make_valid_config())
        config = load_config(config_path)

        assert isinstance(config.session.dst_aware, bool)
        assert isinstance(config.visualization.enabled, bool)
        assert isinstance(config.logging.console, bool)
