"""
Trade logger: captures every trade during a backtest with full detail.

Integrates with backtrader's notification system (Observer pattern) to
record trade entries, exits, costs, and P&L. The resulting TradeRecord
objects are passed to the analysis and visualization modules.
"""

from datetime import datetime
from typing import Dict, List, Optional

import backtrader as bt

from core.types import CostModel, Direction, TradeRecord, TradeStatus


class TradeLogger(bt.Analyzer):
    """Backtrader analyzer that captures detailed trade records.

    Hooks into backtrader's notify_trade and notify_order events to
    build complete TradeRecord objects for every trade taken.

    Usage:
        cerebro.addanalyzer(TradeLogger, _name="trade_logger",
                            cost_model=cost_model)
        results = cerebro.run()
        trades = results[0].analyzers.trade_logger.get_trades()
    """

    params = (
        ("cost_model", None),  # CostModel instance for cost tracking
    )

    def __init__(self):
        self._trades: List[TradeRecord] = []
        self._open_trades: Dict[int, TradeRecord] = {}  # ref -> TradeRecord
        self._trade_counter = 0
        self._cost_model: CostModel = self.p.cost_model or CostModel()
        self._sl_tp_registry: Dict[int, Dict] = {}  # order_ref -> {sl_price, tp_price}
        self._order_to_trade: Dict[int, int] = {}    # order_ref -> trade_ref

    def register_sl_tp(
        self,
        order_ref: int,
        sl_price: Optional[float],
        tp_price: Optional[float],
    ) -> None:
        """Register SL/TP prices for a bracket order.

        Called by OrderManager after submitting a bracket order so that
        TradeLogger can populate the SL/TP fields on the TradeRecord.

        Args:
            order_ref: Main order reference from buy_bracket/sell_bracket.
            sl_price: Stop loss price.
            tp_price: Take profit price (None if no TP).
        """
        self._sl_tp_registry[order_ref] = {
            "sl_price": sl_price,
            "tp_price": tp_price,
        }

    def link_trade_to_order(self, trade_ref: int, order_ref: int) -> None:
        """Link a backtrader trade.ref to the main order.ref.

        Called by the strategy in notify_trade() when a trade just opens,
        so that _on_trade_opened can look up SL/TP by order_ref.

        Args:
            trade_ref: The Trade.ref assigned by backtrader.
            order_ref: The main Order.ref used in register_sl_tp.
        """
        self._order_to_trade[order_ref] = trade_ref

    def notify_trade(self, trade: bt.Trade) -> None:
        """Called by backtrader whenever a trade changes state.

        We track the trade lifecycle:
        - justopened: Record entry details
        - isclosed: Record exit details, compute P&L
        """
        if trade.justopened:
            self._on_trade_opened(trade)
        elif trade.isclosed:
            self._on_trade_closed(trade)

    def _on_trade_opened(self, trade: bt.Trade) -> None:
        """Record a new trade entry."""
        self._trade_counter += 1

        direction = Direction.LONG if trade.size > 0 else Direction.SHORT

        record = TradeRecord(
            trade_id=self._trade_counter,
            direction=direction,
            entry_time=bt.num2date(trade.dtopen),
            entry_price=trade.price,
            size=abs(trade.size),
        )

        # Populate SL/TP from registry if available.
        # The registry is keyed by order_ref (from register_sl_tp).
        # Find the order_ref that was linked to this trade.ref.
        order_ref = None
        for oref, tref in self._order_to_trade.items():
            if tref == trade.ref:
                order_ref = oref
                break

        if order_ref is not None:
            sl_tp = self._sl_tp_registry.pop(order_ref, None)
            self._order_to_trade.pop(order_ref, None)
        else:
            # Fallback: try trade.ref directly (single-order, non-bracket)
            sl_tp = self._sl_tp_registry.pop(trade.ref, None)

        if sl_tp is not None:
            record.stop_loss = sl_tp["sl_price"]
            record.take_profit = sl_tp["tp_price"]

        self._open_trades[trade.ref] = record

    def _on_trade_closed(self, trade: bt.Trade) -> None:
        """Record trade exit, compute final P&L.

        Cost accounting:
          - trade.pnl:     P&L based on actual fill prices. Slippage is already
                           baked in because set_slippage_fixed moves fill prices.
          - trade.pnlcomm: trade.pnl minus broker-applied commission.

        We use these directly so there is NO double-counting.
        The spread/slippage cost fields are informational only — they
        show what the CostModel *estimates* but are NOT subtracted again.
        """
        record = self._open_trades.pop(trade.ref, None)
        if record is None:
            return

        record.exit_time = bt.num2date(trade.dtclose)

        # trade.price is always the weighted entry price, NOT exit.
        # Derive exit price from pnl and known entry/size.
        if record.direction == Direction.LONG:
            record.exit_price = record.entry_price + trade.pnl / record.size
        else:
            record.exit_price = record.entry_price - trade.pnl / record.size

        # ---- P&L from backtrader (single source of truth) ----
        record.gross_pnl = trade.pnl        # includes slippage, excludes commission
        record.net_pnl = trade.pnlcomm      # includes slippage AND commission
        record.total_costs = trade.pnl - trade.pnlcomm  # commission only

        # ---- Informational cost breakdown (for reporting only) ----
        record.spread_cost = self._cost_model.half_spread * record.size * 2
        record.slippage_cost = self._cost_model.slippage_points * record.size * 2
        record.commission_cost = (
            self._cost_model.commission_for_trade(record.size) * 2  # both sides
        )

        record.status = TradeStatus.CLOSED
        self._trades.append(record)

    def get_trades(self) -> List[TradeRecord]:
        """Return all completed trade records."""
        return self._trades.copy()

    def get_open_trades(self) -> List[TradeRecord]:
        """Return any trades still open at backtest end."""
        return list(self._open_trades.values())

    def get_analysis(self) -> dict:
        """Required by backtrader Analyzer interface. Returns trade summary."""
        return {
            "total_trades": len(self._trades),
            "open_trades": len(self._open_trades),
            "trades": self._trades,
        }
