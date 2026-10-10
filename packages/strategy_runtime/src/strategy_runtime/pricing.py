"""Price and quantity units shared by planning and execution hosts."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from math import isfinite, isclose

import pandas as pd

from .errors import RuntimeContractError


class ExecutionPriceBasis(StrEnum):
    UNADJUSTED = "UNADJUSTED"
    HFQ_RESEARCH = "HFQ_RESEARCH"


def _factors(raw: pd.DataFrame, adjusted: pd.DataFrame) -> pd.Series:
    raw = pd.DataFrame(raw, copy=False)
    adjusted = pd.DataFrame(adjusted, copy=False)
    columns = ["open", "high", "low", "close"]
    for frame in (raw, adjusted):
        if not {"dt", *columns}.issubset(frame.columns):
            raise RuntimeContractError("pricing requires daily OHLC and sessions")
        dates = pd.to_datetime(frame["dt"], errors="raise").dt.normalize()
        if frame.empty or dates.isna().any() or dates.duplicated().any():
            raise RuntimeContractError("pricing requires unique nonempty daily sessions")
        values = frame[columns].astype(float)
        if (values.isna() | values.isin([float("inf"), -float("inf")]) | (values <= 0)).any().any():
            raise RuntimeContractError("pricing requires positive finite daily OHLC")
    left = raw.assign(dt=pd.to_datetime(raw["dt"]).dt.normalize()).set_index("dt")
    right = adjusted.assign(dt=pd.to_datetime(adjusted["dt"]).dt.normalize()).set_index("dt")
    if not left.index.isin(right.index).all():
        raise RuntimeContractError("HFQ factors do not cover raw daily sessions")
    ratios = right.loc[left.index, columns] / left[columns]
    factor = ratios["close"]
    if (factor.isna() | factor.isin([float("inf"), -float("inf")]) | (factor <= 0)).any():
        raise RuntimeContractError("HFQ factors must be positive and finite")
    if not ratios.div(factor, axis="index").sub(1).abs().le(1e-10).all().all():
        raise RuntimeContractError("HFQ OHLC do not share one daily adjustment factor")
    return factor


@dataclass(frozen=True, slots=True)
class ExecutionPricing:
    """UNADJUSTED shares or fixed research units at normalized HFQ prices.

    The anchor is fixed before the evaluation window. It changes price units,
    never returns, and is shared by account snapshots, plans and benchmarks.
    """

    basis: ExecutionPriceBasis = ExecutionPriceBasis.UNADJUSTED
    anchor_date: date | None = None
    anchor_factor: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.basis, ExecutionPriceBasis):
            raise RuntimeContractError("pricing basis requires ExecutionPriceBasis")
        if self.basis is ExecutionPriceBasis.UNADJUSTED:
            if self.anchor_date is not None or self.anchor_factor is not None:
                raise RuntimeContractError("unadjusted pricing does not accept an HFQ anchor")
        elif (type(self.anchor_date) is not date or isinstance(self.anchor_factor, bool)
              or not isinstance(self.anchor_factor, int | float)
              or not isfinite(self.anchor_factor) or self.anchor_factor <= 0):
            raise RuntimeContractError("HFQ research pricing requires a dated positive finite anchor")

    @classmethod
    def from_daily(cls, basis: ExecutionPriceBasis, raw: pd.DataFrame,
                   adjusted: pd.DataFrame, anchor_date: date) -> "ExecutionPricing":
        if not isinstance(basis, ExecutionPriceBasis) or type(anchor_date) is not date:
            raise RuntimeContractError("pricing requires an ExecutionPriceBasis and an anchor date")
        if basis is ExecutionPriceBasis.UNADJUSTED:
            return cls(basis)
        factors = _factors(raw, adjusted)
        anchor = pd.Timestamp(anchor_date)
        if anchor not in factors.index:
            raise RuntimeContractError("HFQ anchor session has no authenticated factor")
        return cls(basis, anchor_date, float(factors.loc[anchor]))

    def to_dict(self) -> dict[str, object]:
        return {"basis": self.basis.value,
                "quantity_unit": "SHARE" if self.basis is ExecutionPriceBasis.UNADJUSTED else "RESEARCH_UNIT",
                "anchor_date": None if self.anchor_date is None else self.anchor_date.isoformat(),
                "anchor_factor": self.anchor_factor}

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "ExecutionPricing":
        try:
            result = cls(ExecutionPriceBasis(value["basis"]),
                         None if value["anchor_date"] is None else date.fromisoformat(value["anchor_date"]),
                         value["anchor_factor"])
        except (KeyError, ValueError, TypeError) as exc:
            raise RuntimeContractError("invalid execution pricing contract") from exc
        if result.to_dict() != value:
            raise RuntimeContractError("execution pricing fields or quantity units differ")
        return result

    @property
    def fingerprint(self) -> str:
        from .models import canonical_sha256
        return canonical_sha256(self.to_dict())

    def apply(self, frame: pd.DataFrame, *, raw_daily: pd.DataFrame,
              adjusted_daily: pd.DataFrame) -> pd.DataFrame:
        """Convert admitted raw quotes into this account's price/volume units."""
        numerical = pd.DataFrame(frame, copy=False)
        result = numerical.copy()
        if self.basis is ExecutionPriceBasis.UNADJUSTED:
            result.attrs = deepcopy(frame.attrs)
            return result
        factors = _factors(raw_daily, adjusted_daily)
        anchor = pd.Timestamp(self.anchor_date)
        if anchor in factors.index and not isclose(
            float(factors.loc[anchor]), self.anchor_factor, rel_tol=1e-10, abs_tol=0
        ):
            raise RuntimeContractError("HFQ anchor differs from admitted daily prices")
        dates = pd.to_datetime(numerical["dt"], errors="raise").dt.normalize()
        scales = dates.map(factors) / self.anchor_factor
        if scales.isna().any():
            raise RuntimeContractError("HFQ factors do not cover execution quote sessions")
        for column in ("open", "high", "low", "close"):
            if column in result:
                result[column] = result[column].to_numpy(dtype=float) * scales.to_numpy()
        if "vol" in result:
            result["vol"] = result["vol"].to_numpy(dtype=float) / scales.to_numpy()
        result.attrs = deepcopy(frame.attrs)
        return result
