"""Shared Futu OpenAPI adapter bound to an exact CN or US simulator account."""

from __future__ import annotations

from typing import Any
from datetime import datetime
from decimal import Decimal, InvalidOperation
import time
import re
from zoneinfo import ZoneInfo

from .audit import AuditRecorder
from .channel import FUTU_SIMULATE_CN_CHANNEL_ID, ChannelAccountConfig, channel_profile

from .broker import (
    BrokerAccount,
    BrokerOrder,
    BrokerOrderRejectedError,
    BrokerPosition,
    BrokerSnapshot,
    BrokerSubmissionUncertainError,
    OrderIntent,
    PaperTradingSafetyError,
    KNOWN_ORDER_STATUSES,
)


class FutuGatewayError(RuntimeError):
    pass


_DEFINITE_REJECTION_MARKERS = (
    "报单价格",
    "涨跌停",
    "购买力不足",
    "持仓不足",
    "交易权限",
    "市场未开放",
    "参数错误",
    "invalid price",
    "insufficient",
    "not tradable",
    "rejected",
)


def _submission_error(operation: str, value: object) -> RuntimeError:
    message = f"{operation} failed: {value}"
    lowered = str(value).lower()
    if any(marker in lowered for marker in _DEFINITE_REJECTION_MARKERS):
        return BrokerOrderRejectedError(message)
    return BrokerSubmissionUncertainError(message)


def _records(value: object) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(item) for item in value]
    if hasattr(value, "to_dict"):
        records = value.to_dict("records")
        return [dict(item) for item in records]
    raise FutuGatewayError(f"unexpected Futu table type: {type(value).__name__}")


def _broker_code(symbol: str) -> str:
    code, market = symbol.upper().split(".", 1)
    return f"{market}.{code}"


def _project_symbol(code: str) -> str:
    market, symbol = code.upper().split(".", 1)
    return f"{symbol}.{market}"


def _number(value: object, name: str) -> Decimal:
    if isinstance(value, bool):
        raise FutuGatewayError(f"{name} must be finite and non-negative")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise FutuGatewayError(f"{name} must be numeric") from exc
    if not result.is_finite() or result < 0:
        raise FutuGatewayError(f"{name} must be finite and non-negative")
    return result


def _quantity(value: object, name: str) -> int:
    result = _number(value, name)
    if result != result.to_integral_value():
        raise FutuGatewayError(f"{name} must contain integer shares")
    return int(result)


class FutuGateway:
    channel_id = FUTU_SIMULATE_CN_CHANNEL_ID

    def __init__(
        self,
        *,
        symbol: str | None = None,
        host: str = "127.0.0.1",
        port: int = 11111,
        sdk: object | None = None,
        trade_context: object | None = None,
        audit: AuditRecorder | None = None,
        config: ChannelAccountConfig | None = None,
    ) -> None:
        if config is not None and type(config) is not ChannelAccountConfig:
            raise TypeError("gateway config requires ChannelAccountConfig")
        self.config = config
        self.profile = config.profile if config else channel_profile(FUTU_SIMULATE_CN_CHANNEL_ID)
        self.channel_id = self.profile.channel_id
        self.channel_account_id = config.channel_account_id if config else ""
        if sdk is None:
            import futu as sdk_module

            sdk = sdk_module
        self.sdk = sdk
        self.sdk.SysConfig.enable_console_log(False)
        self.symbol = symbol.upper() if symbol else None
        self.trade_context = trade_context or sdk.OpenSecTradeContext(
            filter_trdmarket=getattr(sdk.TrdMarket, self.profile.market), host=host, port=port
        )
        self._account_id: int | None = None
        self.audit = audit

    def _audit_mutation(
        self, operation: str, started: float, *, correlation_id: str,
        order_id: str | None = None, account_id: str | None = None,
        error: Exception | None = None,
        symbol: str | None = None,
    ) -> None:
        if self.audit is None:
            return
        self.audit.record(
            "EXTERNAL_CALL_FAILED" if error else "EXTERNAL_CALL_SUCCEEDED",
            source="futu_gateway", outcome="FAILURE" if error else "SUCCESS",
            actor_type="EXTERNAL", actor_id="futu", correlation_id=correlation_id,
            account_id=account_id, symbol=symbol or self.symbol, channel=self.channel_id, order_id=order_id,
            details={
                "service": "futu", "operation": operation,
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                "channel_account_id": self.channel_account_id,
                **({"error_type": type(error).__name__, "error": str(error)} if error else {}),
            },
        )

    def _ok(self, operation: str, result: tuple[object, object]) -> object:
        code, value = result
        if code != self.sdk.RET_OK:
            raise FutuGatewayError(f"{operation} failed: {value}")
        return value

    def _account(self) -> int:
        if self._account_id is not None:
            return self._account_id
        rows = _records(self._ok("get_acc_list", self.trade_context.get_acc_list()))
        if self.config is not None:
            matches = [row for row in rows
                       if row.get("acc_id") == self.config.broker_account_id
                       and row.get("trd_env") == self.sdk.TrdEnv.SIMULATE
                       and row.get("acc_status") == "ACTIVE"]
            if len(matches) != 1:
                raise FutuGatewayError("configured simulator account is missing, inactive or ambiguous")
            row = matches[0]
            authorization = row.get("trdmarket_auth")
            if not isinstance(authorization, (tuple, list)) or self.profile.market not in authorization:
                raise FutuGatewayError("configured simulator account lacks the declared market authorization")
            if row.get("trd_market", self.profile.market) != self.profile.market:
                raise FutuGatewayError("configured simulator account has a different market")
            if self.profile.market == "US" and (row.get("sim_acc_type") != "STOCK_AND_OPTION"
                                                or row.get("acc_type") != "MARGIN"):
                raise FutuGatewayError("US simulation requires the stock-and-option margin simulator")
            self._account_id = self.config.broker_account_id
            return self._account_id
        # OpenD account-list rows on the live simulator omit ``trd_market``.
        # The adapter itself creates the context with filter_trdmarket=CN, so
        # that fixed constructor contract is the explicit market authority;
        # a returned market, when present, must still agree with it.
        matches = [
            row for row in rows
            if row.get("trd_env") == self.sdk.TrdEnv.SIMULATE
            and row.get("trd_market", self.sdk.TrdMarket.CN) == self.sdk.TrdMarket.CN
        ]
        if len(matches) != 1:
            raise FutuGatewayError(f"expected one CN SIMULATE account, found {len(matches)}")
        self._account_id = int(matches[0]["acc_id"])
        return self._account_id

    def _broker_symbol(self, symbol: str) -> str:
        if self.profile.market == "CN":
            if re.fullmatch(r"[0-9]{6}\.(SH|SZ)", symbol) is None:
                raise PaperTradingSafetyError("order symbol is not a supported China-market code")
            return _broker_code(symbol)
        if (not isinstance(symbol, str) or re.fullmatch(r"[A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)*", symbol) is None
                or symbol.startswith("US.") or symbol.endswith(".US")):
            raise PaperTradingSafetyError("US symbol must be a canonical ticker without market prefix")
        return "US." + symbol

    def _symbol(self, code: object) -> str:
        value = str(code)
        if self.profile.market == "US":
            if not value.startswith("US."):
                raise FutuGatewayError("foreign-market instrument in US simulator response")
            symbol = value[3:]
        else:
            symbol = _project_symbol(value)
        self._broker_symbol(symbol)
        return symbol

    def _timestamp(self, value: object) -> str:
        text = str(value)
        if not text or self.config is None:
            return text
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise FutuGatewayError("invalid broker order timestamp") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo(self.profile.timezone))
        return parsed.isoformat()

    def snapshot(self) -> BrokerSnapshot:
        account = self.account_snapshot()
        return BrokerSnapshot(
            account.account,
            account.positions,
            self.order_snapshot(),
        )

    def account_snapshot(self) -> BrokerSnapshot:
        account_id = self._account()
        common = {
            "trd_env": self.sdk.TrdEnv.SIMULATE,
            "acc_id": account_id,
            "refresh_cache": True,
        }
        funds_args = dict(common)
        # Futu exposes CNH, not CNY. CN uses its native market cash query;
        # US explicitly requests USD and consumes us_cash only.
        if self.profile.market == "US":
            funds_args["currency"] = getattr(self.sdk.Currency, self.profile.currency)
        account_rows = _records(self._ok("accinfo_query", self.trade_context.accinfo_query(**funds_args)))
        if len(account_rows) != 1:
            raise FutuGatewayError("accinfo_query did not return exactly one account")
        account_row = account_rows[0]
        cash_field = "us_cash" if self.profile.market == "US" else "cash"
        if self.config is not None:
            for field in (cash_field, "total_assets", "frozen_cash", "market_val"):
                _number(account_row.get(field), field)
            if account_row.get("currency") not in (None, "N/A", self.profile.currency):
                raise FutuGatewayError("broker account currency differs from configured currency")
        position_rows = _records(
            self._ok(
                "position_list_query",
                self.trade_context.position_list_query(**common),
            )
        )
        return BrokerSnapshot(
            account=BrokerAccount(
                environment="SIMULATE",
                market=self.profile.market,
                cash=float(account_row.get(cash_field, 0.0)),
                total_assets=float(account_row.get("total_assets", 0.0)),
                frozen_cash=float(account_row.get("frozen_cash", 0.0)),
                market_value=float(account_row.get("market_val", 0.0)),
                currency=self.profile.currency,
                channel_account_id=self.channel_account_id,
            ),
            positions=tuple(
                self._position(row)
                for row in position_rows
            ),
            orders=(),
        )

    def _position(self, row):
        quantity = _quantity(row["qty"], "position quantity")
        sellable = row.get("can_sell_qty")
        if sellable is None and self.config is not None:
            raise FutuGatewayError("configured account position lacks sellable quantity")
        sellable = None if sellable is None else _quantity(sellable, "sellable quantity")
        if sellable is not None and sellable > quantity:
            raise FutuGatewayError("sellable quantity exceeds long holdings")
        if quantity and row.get("position_side", "LONG") != "LONG":
            raise FutuGatewayError("long-only simulation account contains a short position")
        return BrokerPosition(self._symbol(row["code"]), quantity, sellable)

    def order_snapshot(self) -> tuple[BrokerOrder, ...]:
        rows = _records(
            self._ok(
                "order_list_query",
                self.trade_context.order_list_query(
                    trd_env=self.sdk.TrdEnv.SIMULATE,
                    acc_id=self._account(),
                    refresh_cache=True,
                ),
            )
        )
        return tuple(self._map_order(row) for row in rows)

    def historical_order_snapshot(self, start: str, end: str) -> tuple[BrokerOrder, ...]:
        rows = _records(
            self._ok(
                "history_order_list_query",
                self.trade_context.history_order_list_query(
                    start=start,
                    end=end,
                    trd_env=self.sdk.TrdEnv.SIMULATE,
                    acc_id=self._account(),
                ),
            )
        )
        return tuple(self._map_order(row) for row in rows)

    def _map_order(self, row: dict[str, Any]) -> BrokerOrder:
        raw_order_type = str(row.get("order_type", "NORMAL")).upper()
        types = {"NORMAL": "LIMIT", "ABSOLUTE_LIMIT": "LIMIT", "MARKET": "MARKET"}
        if raw_order_type not in types:
            raise FutuGatewayError(f"unsupported broker order type: {raw_order_type}")
        order_type = types[raw_order_type]
        if row["order_status"] not in KNOWN_ORDER_STATUSES:
            raise FutuGatewayError("unknown broker order status")
        if row["trd_side"] not in {"BUY", "SELL"}:
            raise FutuGatewayError("unsupported broker order side")
        quantity = _quantity(row["qty"], "order quantity")
        filled = _quantity(row.get("dealt_qty", 0), "cumulative filled quantity")
        average = _number(row.get("dealt_avg_price", 0), "cumulative average price")
        if not quantity or filled > quantity or (filled and not average):
            raise FutuGatewayError("invalid cumulative broker fill")
        price = _number(row["price"], "order price")
        session = str(row.get("session", "RTH"))
        if self.profile.market == "US" and session not in {"RTH", "ETH"}:
            raise FutuGatewayError("unsupported US order session")
        return BrokerOrder(
            channel_order_id=str(row["order_id"]),
            symbol=self._symbol(row["code"]),
            side=str(row["trd_side"]),
            quantity=quantity,
            limit_price=float(price),
            status=str(row["order_status"]),
            cumulative_filled_quantity=filled,
            average_fill_price=float(average),
            remark=str(row.get("remark", "")),
            last_error=str(row.get("last_err_msg", "")),
            created_at=self._timestamp(row.get("create_time", "")),
            updated_at=self._timestamp(row.get("updated_time", "")),
            order_type=order_type,
            session=session if self.profile.market == "US" else "RTH",
            channel_account_id=self.channel_account_id,
            cumulative_notional=average * filled if self.config is not None else None,
        )

    def place_order(self, intent: OrderIntent) -> BrokerOrder:
        code_symbol = self._broker_symbol(intent.symbol)
        step = self.profile.quantity_step
        if type(intent.full_liquidation) is not bool or (intent.full_liquidation and intent.side != 'SELL'):
            raise PaperTradingSafetyError('full liquidation requires an explicit SELL intent')
        if (type(intent.quantity) is not int or intent.quantity <= 0
                or (intent.quantity % step and not intent.full_liquidation)):
            raise PaperTradingSafetyError(f"order quantity must use positive {step}-share lots")
        if self.config is not None:
            if intent.channel_account_id != self.channel_account_id:
                raise PaperTradingSafetyError("order belongs to a different channel account")
            if intent.session != self.config.session:
                raise PaperTradingSafetyError("order session differs from channel account policy")
        price = _number(intent.limit_price, "order price")
        if intent.order_type == "LIMIT" and not price:
            raise PaperTradingSafetyError("limit order requires a positive price")
        if self.profile.market == "US":
            tick = Decimal("0.01") if price >= 1 else Decimal("0.0001")
            if intent.order_type == "LIMIT" and price % tick:
                raise PaperTradingSafetyError("US limit price differs from its price tick")
            if intent.session == "ETH" and intent.order_type != "LIMIT":
                raise PaperTradingSafetyError("ETH permits limit orders only")
        if intent.side not in {"BUY", "SELL"}:
            raise PaperTradingSafetyError("order side must be BUY or SELL")
        if intent.time_in_force != "DAY":
            raise PaperTradingSafetyError("gateway accepts DAY orders only")
        if (intent.side, intent.order_type) not in {
            ("BUY", "LIMIT"), ("SELL", "LIMIT"), ("SELL", "MARKET"),
        }:
            raise PaperTradingSafetyError(
                "gateway requires LIMIT buys and LIMIT or MARKET sells"
            )
        side = self.sdk.TrdSide.BUY if intent.side == "BUY" else self.sdk.TrdSide.SELL
        order_type = (
            self.sdk.OrderType.NORMAL
            if intent.order_type == "LIMIT"
            else self.sdk.OrderType.MARKET
        )
        started = time.perf_counter()
        try:
            session_args = {}
            if self.profile.market == "US":
                session_args = {"session": getattr(self.sdk.Session, intent.session)}
            code, value = self.trade_context.place_order(
                price=intent.limit_price,
                qty=intent.quantity,
                code=code_symbol,
                trd_side=side,
                order_type=order_type,
                adjust_limit=0,
                trd_env=self.sdk.TrdEnv.SIMULATE,
                acc_id=self._account(),
                remark=intent.intent_id,
                time_in_force=self.sdk.TimeInForce.DAY,
                **session_args,
            )
            if code != self.sdk.RET_OK:
                raise _submission_error("place_order", value)
            rows = _records(value)
            if len(rows) != 1:
                raise FutuGatewayError("place_order did not return exactly one order")
            order = self._map_order(rows[0])
        except Exception as exc:
            self._audit_mutation(
                "place_order", started, correlation_id=intent.decision_id,
                account_id=intent.account_id, error=exc, symbol=intent.symbol,
            )
            raise
        self._audit_mutation(
            "place_order", started, correlation_id=intent.decision_id,
            order_id=order.channel_order_id, account_id=intent.account_id,
            symbol=intent.symbol,
        )
        return order

    def cancel_order(self, channel_order_id: str) -> None:
        started = time.perf_counter()
        try:
            self._ok(
                "modify_order",
                self.trade_context.modify_order(
                    modify_order_op=self.sdk.ModifyOrderOp.CANCEL,
                    order_id=channel_order_id,
                    qty=0,
                    price=0,
                    adjust_limit=0,
                    trd_env=self.sdk.TrdEnv.SIMULATE,
                    acc_id=self._account(),
                ),
            )
        except Exception as exc:
            self._audit_mutation(
                "cancel_order", started, correlation_id=channel_order_id,
                order_id=channel_order_id, error=exc,
            )
            raise
        self._audit_mutation(
            "cancel_order", started, correlation_id=channel_order_id,
            order_id=channel_order_id,
        )

    def close(self) -> None:
        self.trade_context.close()
