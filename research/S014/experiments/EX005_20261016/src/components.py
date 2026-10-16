"""Two bounded research components; neither emits a buy/sell instruction."""
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class DailyRiskContext:
    """Completed-session amplitude scale and fixed-limit execution awareness."""
    true_range_fraction: float
    close_at_upper_limit: bool


def observe_completed_session(*, previous_hfq_close: float, hfq_high: float,
                              hfq_low: float, raw_close: float,
                              raw_upper_limit: float, raw_tick: float) -> DailyRiskContext:
    """Consume completed T and T-1 facts only, in their declared price units.

    true_range_fraction is a simple market-amplitude estimate, not a loss limit
    or expected net return. close_at_upper_limit marks elevated historical
    nonfill risk under the fixed 1-percent buy premium; it is not a veto.
    """
    values = (previous_hfq_close, hfq_high, hfq_low, raw_close, raw_upper_limit, raw_tick)
    if any(not isfinite(value) or value <= 0 for value in values):
        raise ValueError("Prices and tick must be positive finite values")
    if hfq_low > hfq_high:
        raise ValueError("Low cannot exceed high")
    scale = max(hfq_high - hfq_low, abs(hfq_high - previous_hfq_close),
                abs(hfq_low - previous_hfq_close)) / previous_hfq_close
    return DailyRiskContext(scale, abs(raw_close - raw_upper_limit) <= raw_tick / 2)
