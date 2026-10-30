"""Market-neutral monetary postings, with no execution model or I/O.

The caller authenticates fills/events and owns policy, ordering, idempotency and
transaction boundaries. Posting arithmetic deliberately retains the existing
float operation order; budget validation remains Decimal in the planner.
"""
from dataclasses import dataclass
from enum import Enum
from math import isfinite

from strategy_runtime.contracts import OrderSide


class CashDisposition(Enum):
    AVAILABLE = "AVAILABLE"
    RECEIVABLE = "RECEIVABLE"


def _number(value, name):
    if type(value) not in (int, float) or not isfinite(value):
        raise ValueError(f"{name} must be a finite number")


@dataclass(frozen=True, slots=True)
class AccountBalances:
    cash: float
    quantity: int
    receivable: float = 0.0

    def __post_init__(self):
        _number(self.cash, "cash")
        _number(self.receivable, "receivable")
        if type(self.quantity) is not int or self.quantity < 0:
            raise ValueError("quantity must be a nonnegative integer")

    def equity(self, price: float) -> float:
        _number(price, "valuation price")
        if price <= 0:
            raise ValueError("valuation price must be positive")
        return self.cash + self.receivable + self.quantity * price


@dataclass(frozen=True, slots=True)
class FillPosting:
    balances: AccountBalances
    gross: float
    fees: float
    net: float


def post_fill(balances: AccountBalances, *, side: OrderSide, quantity: int,
              price: float, fee_rate: float,
              disposition: CashDisposition = CashDisposition.AVAILABLE) -> FillPosting:
    """Post one confirmed fill; an unfilled order must never call this function."""
    if type(balances) is not AccountBalances or type(side) is not OrderSide:
        raise TypeError("posting requires typed balances and OrderSide")
    if type(disposition) is not CashDisposition:
        raise TypeError("posting requires CashDisposition")
    if type(quantity) is not int or quantity <= 0:
        raise ValueError("fill quantity must be a positive integer")
    _number(price, "fill price")
    _number(fee_rate, "fee rate")
    if price <= 0 or not 0 <= fee_rate < 1:
        raise ValueError("invalid fill price or fee rate")
    if side is OrderSide.BUY and disposition is not CashDisposition.AVAILABLE:
        raise ValueError("buy fill cannot be credited to receivables")
    if side is OrderSide.SELL and quantity > balances.quantity:
        raise ValueError("sell quantity exceeds holdings")
    cash, held, receivable, gross, fees, net = _post_confirmed_fill(
        balances.cash, balances.quantity, balances.receivable, side is OrderSide.BUY,
        quantity, price, fee_rate, disposition is CashDisposition.RECEIVABLE)
    return FillPosting(AccountBalances(cash, held, receivable), gross, fees, net)


def _post_confirmed_fill(cash, held, receivable, is_buy, quantity, price, fee_rate,
                         deferred=False):
    """Private hot path for facts already validated by a typed executor plan.

    No frame/object cloning and no second price/quantity validation per fill.
    All three actual execution paths use this exact arithmetic kernel.
    """
    gross = quantity * price
    fees = gross * fee_rate
    if is_buy:
        net = gross + fees
        cash -= net
        held += quantity
    else:
        net = gross - fees
        held -= quantity
        if deferred:
            receivable += net
        else:
            cash += net
    return cash, held, receivable, gross, fees, net


def accrue_receivable(balances: AccountBalances, amount: float) -> AccountBalances:
    """Recognize a dated entitlement; cash is unchanged until settlement."""
    if type(balances) is not AccountBalances:
        raise TypeError("event posting requires AccountBalances")
    _number(amount, "receivable amount")
    if amount < 0:
        raise ValueError("receivable amount must be nonnegative")
    return AccountBalances(balances.cash, balances.quantity, balances.receivable + amount)


def settle_receivable(balances: AccountBalances, amount: float) -> AccountBalances:
    """Transfer an authenticated due amount without introducing rounding."""
    if type(balances) is not AccountBalances:
        raise TypeError("event posting requires AccountBalances")
    _number(amount, "settlement amount")
    if amount < 0:
        raise ValueError("settlement amount must be nonnegative")
    cash, receivable = _settle_confirmed_receivable(balances.cash, balances.receivable, amount)
    return AccountBalances(cash, balances.quantity, receivable)


def post_split(balances: AccountBalances, ratio: float) -> AccountBalances:
    if type(balances) is not AccountBalances:
        raise TypeError("split posting requires AccountBalances")
    _number(ratio, "split ratio")
    if ratio <= 0:
        raise ValueError("split ratio must be positive")
    changed = balances.quantity * ratio
    if not float(changed).is_integer():
        raise ValueError("CORPORATE_ACTION_UNSUPPORTED: fractional split entitlement")
    return AccountBalances(balances.cash, int(changed), balances.receivable)


def _settle_confirmed_receivable(cash, receivable, amount):
    """Private dated-event path; ordering and duplicate prevention belong to TXE."""
    return cash + amount, receivable - amount
