"""Prepared data contracts and standard SRT data sources."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping

import pandas as pd

from .contracts import PriceReference, StrategyIdentity, TradableWindow
from .errors import RuntimeContractError
from .models import ExecutionPricingData, canonical_sha256
from .pricing import ExecutionPriceBasis
from .preparation import PreparedInputs


@dataclass(frozen=True, slots=True)
class PreparedStrategyData:
    """Immutable-by-contract data admitted for one strategy tradable window."""

    strategy: StrategyIdentity
    tradable_window: TradableWindow
    available_through: date
    dataset_identity: str
    input_identities: Mapping[str, str]
    price_identities: Mapping[str, str]
    _calendar_dates: tuple[date, ...]
    _signal_dates: Mapping[date, date]
    _calculation_dates: tuple[date, ...]
    _inputs: PreparedInputs
    _pricing: ExecutionPricingData
    _adjusted_closes: Mapping[pd.Timestamp, Decimal] = field(init=False, repr=False, compare=False)
    _execution_closes: Mapping[pd.Timestamp, Decimal] = field(init=False, repr=False, compare=False)
    _raw_closes: Mapping[pd.Timestamp, Decimal] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.strategy != self._inputs.strategy:
            raise RuntimeContractError("prepared inputs belong to another strategy")
        if self.strategy.symbol != self._pricing.symbol:
            raise RuntimeContractError("prepared data symbol differs from strategy")
        if (
            not self._calendar_dates
            or tuple(sorted(set(self._calendar_dates))) != self._calendar_dates
        ):
            raise RuntimeContractError("prepared calendar dates must be unique and ordered")
        if (
            self.tradable_window.start not in self._calendar_dates
            or self.tradable_window.end not in self._calendar_dates
        ):
            raise RuntimeContractError("prepared data does not cover the tradable window")
        if not self._calculation_dates or self._calculation_dates[-1] != self.available_through:
            raise RuntimeContractError("prepared calculation dates have an invalid cutoff")
        inputs = MappingProxyType(dict(sorted(self.input_identities.items())))
        prices = MappingProxyType(dict(sorted(self.price_identities.items())))
        signal_dates = MappingProxyType(dict(sorted(self._signal_dates.items())))
        trading_dates = tuple(
            value for value in self._calendar_dates if self.tradable_window.contains(value)
        )
        if set(signal_dates) != set(trading_dates):
            raise RuntimeContractError("prepared signal dates differ from trading dates")
        object.__setattr__(self, "input_identities", inputs)
        object.__setattr__(self, "price_identities", prices)
        object.__setattr__(self, "_signal_dates", signal_dates)
        expected = canonical_sha256(
            {
                "strategy": self.strategy.reference_id,
                "release_hash": self.strategy.release_hash,
                "tradable_window": {
                    "start": self.tradable_window.start.isoformat(),
                    "end": self.tradable_window.end.isoformat(),
                },
                "available_through": self.available_through.isoformat(),
                "calendar_dates": [value.isoformat() for value in self._calendar_dates],
                "signal_dates": {
                    key.isoformat(): value.isoformat()
                    for key, value in signal_dates.items()
                },
                "calculation_dates": [value.isoformat() for value in self._calculation_dates],
                "inputs": dict(inputs),
                "prices": dict(prices),
            }
        )
        if self.dataset_identity != expected:
            raise RuntimeContractError("prepared dataset identity differs from admitted data")
        for name, frame in (("_adjusted_closes", self._pricing.adjusted_daily),
                            ("_execution_closes", self._pricing.execution_daily),
                            ("_raw_closes", self._pricing.raw_daily)):
            object.__setattr__(self, name, MappingProxyType({
                session: Decimal(str(close))
                for session, close in zip(frame["dt"], frame["close"])
            }))

    @classmethod
    def from_inputs(
        cls,
        *,
        inputs: PreparedInputs,
        pricing: ExecutionPricingData,
    ) -> "PreparedStrategyData":
        input_identities = {
            name: result.identity.content_sha256 for name, result in inputs.results.items()
        }
        price_identities = dict(pricing.identity_hashes)
        identity = canonical_sha256(
            {
                "strategy": inputs.strategy.reference_id,
                "release_hash": inputs.strategy.release_hash,
                "tradable_window": {
                    "start": inputs.tradable_window.start.isoformat(),
                    "end": inputs.tradable_window.end.isoformat(),
                },
                "available_through": inputs.available_through.isoformat(),
                "calendar_dates": [value.isoformat() for value in inputs.calendar_dates],
                "signal_dates": {
                    key.isoformat(): value.isoformat()
                    for key, value in inputs.signal_dates.items()
                },
                "calculation_dates": [value.isoformat() for value in inputs.calculation_dates],
                "inputs": dict(sorted(input_identities.items())),
                "prices": dict(sorted(price_identities.items())),
            }
        )
        return cls(
            inputs.strategy,
            inputs.tradable_window,
            inputs.available_through,
            identity,
            input_identities,
            price_identities,
            inputs.calendar_dates,
            inputs.signal_dates,
            inputs.calculation_dates,
            inputs,
            pricing,
        )

    @property
    def adjusted_daily(self) -> pd.DataFrame:
        return self._pricing.adjusted_daily.copy()

    @property
    def execution_daily(self) -> pd.DataFrame:
        return self._pricing.execution_daily.copy()

    def input_frame(self, name: str) -> pd.DataFrame:
        try:
            return self._inputs.results[name].dataframe.copy()
        except KeyError as exc:
            raise RuntimeContractError(f"prepared input is unavailable: {name}") from exc

    def calendar_dates(self) -> tuple[date, ...]:
        return self._calendar_dates

    def calculation_dates(self) -> tuple[date, ...]:
        return self._calculation_dates

    def trading_dates(self) -> tuple[date, ...]:
        return tuple(
            value for value in self._calendar_dates if self.tradable_window.contains(value)
        )

    def signal_date_for(self, trading_date: date) -> date:
        if not self.tradable_window.contains(trading_date):
            raise RuntimeContractError("trading date is outside the strategy window")
        try:
            return self._signal_dates[trading_date]
        except KeyError as exc:
            raise RuntimeContractError(
                "prepared data has no signal session for trading date"
            ) from exc

    def price_reference(self, signal_date: date, trading_date: date) -> PriceReference:
        """Return the channel-neutral prices used to size one execution plan."""

        signal = pd.Timestamp(signal_date).normalize()
        try:
            adjusted = self._adjusted_closes[signal]
            execution = self._execution_closes[signal]
        except KeyError as exc:
            raise RuntimeContractError(
                "prepared pricing has no unique reference row for the signal session"
            ) from exc
        if trading_date <= signal_date:
            raise RuntimeContractError("execution session must follow the signal session")
        return PriceReference(
            adjusted,
            execution,
            "ADJUSTED_CLOSE",
            "UNADJUSTED_CLOSE" if self._pricing.pricing.basis is ExecutionPriceBasis.UNADJUSTED else "NORMALIZED_HFQ_CLOSE",
            pricing=self._pricing.pricing,
            price_scale=execution / self._raw_closes[signal],
        )
