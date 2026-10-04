"""Deterministic factor calculations on caller-supplied, point-in-time data.

These functions neither acquire data nor read research artifacts. Date columns
must contain timezone-naive midnight timestamps; availability is not inferred.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class SellSideRevisionParameters:
    maximum_previous_age_days: int = 365
    minimum_relative_revision: float = 0.01
    rolling_sessions: int = 20

    def __post_init__(self) -> None:
        for name in ("maximum_previous_age_days", "rolling_sessions"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        threshold = self.minimum_relative_revision
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            raise ValueError("minimum_relative_revision must be a finite nonnegative number")
        if not np.isfinite(threshold) or threshold < 0:
            raise ValueError("minimum_relative_revision must be a finite nonnegative number")


def _frame(value: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    if not isinstance(value, pd.DataFrame):
        raise TypeError("input must be a DataFrame")
    missing = set(columns).difference(value.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    if value.empty:
        raise ValueError("input must not be empty")
    result = value.loc[:, list(columns)].copy()
    for column in ("ts_code", "con_code", "org_name", "quarter", "source"):
        if column in result and not result[column].map(
            lambda item: isinstance(item, str) and bool(item.strip())
        ).all():
            raise ValueError(f"{column} must contain nonempty strings")
    return result


def _dates(frame: pd.DataFrame, *columns: str) -> None:
    for column in columns:
        try:
            values = pd.to_datetime(frame[column], errors="raise")
            invalid = values.isna().any() or values.dt.tz is not None
            invalid = invalid or not values.eq(values.dt.normalize()).all()
        except (TypeError, ValueError, AttributeError) as error:
            raise ValueError(f"{column} must contain timezone-naive dates") from error
        if invalid:
            raise ValueError(f"{column} must contain timezone-naive dates")
        frame[column] = values


def _numbers(
    frame: pd.DataFrame, *columns: str, positive: bool = False,
    nonnegative: bool = False, allow_missing: bool = False,
) -> None:
    for column in columns:
        if frame[column].map(lambda value: isinstance(value, (bool, np.bool_))).any():
            raise ValueError(f"{column} must contain numeric values")
        try:
            values = pd.to_numeric(frame[column], errors="raise").astype(float)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{column} must contain numeric values") from error
        present = values.dropna() if allow_missing else values
        if not np.isfinite(present).all():
            raise ValueError(f"{column} must contain finite values")
        if positive and not present.gt(0).all():
            raise ValueError(f"{column} must be positive")
        if nonnegative and not present.ge(0).all():
            raise ValueError(f"{column} must be nonnegative")
        frame[column] = values


def _unique(frame: pd.DataFrame, *columns: str) -> None:
    if frame.duplicated(list(columns)).any():
        raise ValueError(f"duplicate identity: {columns}")


def _finite_output(frame: pd.DataFrame, *columns: str) -> None:
    for column in columns:
        if not np.isfinite(frame[column].dropna()).all():
            raise ValueError(f"{column} calculation produced nonfinite values")


def _calendar(calendar: pd.DatetimeIndex) -> pd.DatetimeIndex:
    if not isinstance(calendar, pd.DatetimeIndex):
        raise TypeError("calendar must be a DatetimeIndex")
    if (calendar.empty or calendar.hasnans or calendar.tz is not None
            or calendar.has_duplicates or not calendar.is_monotonic_increasing
            or not calendar.equals(calendar.normalize())):
        raise ValueError("calendar must contain unique, increasing timezone-naive dates")
    return calendar


def _consecutive_sessions(data: pd.DataFrame, calendar: pd.DatetimeIndex) -> None:
    observed = pd.DatetimeIndex(data["trade_date"])
    expected = calendar[(calendar >= observed[0]) & (calendar <= observed[-1])]
    if not observed.equals(expected):
        raise ValueError("dates must cover consecutive calendar sessions")


def calculate_etf_share_change(
    shares: pd.DataFrame, calendar: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Return total_share change within each symbol; first value is undefined.

Inputs: ts_code, trade_date, total_share. Each symbol must cover every calendar
session between its first and last supplied dates; missing sessions fail.
"""
    dates = _calendar(calendar)
    data = _frame(shares, ("ts_code", "trade_date", "total_share"))
    _dates(data, "trade_date")
    _numbers(data, "total_share", positive=True)
    _unique(data, "ts_code", "trade_date")
    data = data.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    for _, group in data.groupby("ts_code", sort=False):
        _consecutive_sessions(group, dates)
    data["share_change"] = data.groupby("ts_code")["total_share"].pct_change(
        fill_method=None
    )
    _finite_output(data, "share_change")
    return data


def calculate_etf_nav_premium(values: pd.DataFrame) -> pd.DataFrame:
    """Return close/nav - 1 from the same published symbol/session observations.

Inputs: ts_code, trade_date, close, nav. Output is a historical observation,
not an assertion that its value was available on trade_date.
"""
    data = _frame(values, ("ts_code", "trade_date", "close", "nav"))
    _dates(data, "trade_date")
    _numbers(data, "close", "nav", positive=True)
    _unique(data, "ts_code", "trade_date")
    data = data.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    data["nav_premium"] = data["close"].div(data["nav"]).sub(1.0)
    _finite_output(data, "nav_premium")
    return data


def calculate_earnings_acceleration_breadth(
    disclosures: pd.DataFrame, membership: pd.DataFrame,
    calendar: pd.DatetimeIndex, *, source_priority: tuple[str, ...],
) -> pd.DataFrame:
    """Aggregate disclosed year-on-year growth acceleration at next session.

Disclosures: ts_code, ann_date, end_date, source, profit_growth_yoy (already
normalized by the data provider). Membership: dt, con_code, weight. Earliest
disclosure per company/reporting period wins, with explicit source priority
breaking same-date ties. Baseline must already be disclosed at ann_date.
Unpaired periods, nonmembers and disclosures beyond calendar are not events.
"""
    dates = _calendar(calendar)
    if (not isinstance(source_priority, tuple) or not source_priority
            or any(not isinstance(item, str) or not item.strip() for item in source_priority)
            or len(set(source_priority)) != len(source_priority)):
        raise ValueError("source_priority must be a nonempty tuple of unique source names")
    data = _frame(disclosures, (
        "ts_code", "ann_date", "end_date", "source", "profit_growth_yoy",
    ))
    _dates(data, "ann_date", "end_date")
    _numbers(data, "profit_growth_yoy")
    _unique(data, "ts_code", "ann_date", "end_date", "source")
    if not data["source"].isin(source_priority).all():
        raise ValueError("every disclosure source must have an explicit priority")
    if data["ann_date"].lt(data["end_date"]).any():
        raise ValueError("disclosure cannot precede its reporting period end")
    members = _frame(membership, ("dt", "con_code", "weight"))
    _dates(members, "dt")
    _numbers(members, "weight", positive=True)
    _unique(members, "dt", "con_code")
    if not members["dt"].isin(dates).all():
        raise ValueError("membership dates must belong to the calendar")
    data["priority"] = data["source"].map(
        {source: position for position, source in enumerate(source_priority)}
    )
    first = data.sort_values(["ts_code", "end_date", "ann_date", "priority"])
    first = first.drop_duplicates(["ts_code", "end_date"])
    prior = first[["ts_code", "end_date", "ann_date", "profit_growth_yoy"]].copy()
    prior["end_date"] += pd.DateOffset(years=1)
    prior = prior.rename(columns={
        "ann_date": "prior_ann_date", "profit_growth_yoy": "prior_growth_yoy",
    })
    events = first.merge(prior, on=["ts_code", "end_date"], how="left", validate="one_to_one")
    events = events.loc[events["prior_ann_date"].le(events["ann_date"])].copy()
    positions = dates.searchsorted(events["ann_date"], side="right")
    events = events.loc[positions < len(dates)].copy()
    events["eligible_session"] = dates.take(positions[positions < len(dates)])
    if not events["eligible_session"].isin(members["dt"]).all():
        raise ValueError("membership lacks an eligible disclosure session")
    events = events.merge(
        members, left_on=["eligible_session", "ts_code"], right_on=["dt", "con_code"],
        how="inner", validate="many_to_one",
    )
    events["acceleration"] = events["profit_growth_yoy"] - events["prior_growth_yoy"]
    _finite_output(events, "acceleration")
    events["positive_weight"] = events["weight"].where(events["acceleration"].gt(0), 0.0)
    events["negative_weight"] = events["weight"].where(events["acceleration"].lt(0), 0.0)
    daily = events.groupby("eligible_session", as_index=False, sort=True).agg(
        disclosures=("ts_code", "nunique"), positive_weight=("positive_weight", "sum"),
        negative_weight=("negative_weight", "sum"),
    )
    daily["net_breadth"] = daily["positive_weight"] - daily["negative_weight"]
    _finite_output(daily, "positive_weight", "negative_weight", "net_breadth")
    return daily


_GROSS_AMOUNT_COLUMNS = tuple(
    f"{side}_{size}_amount" for size in ("sm", "md", "lg", "elg")
    for side in ("buy", "sell")
)


def calculate_external_industry_moneyflow(
    member_flow: pd.DataFrame, index_membership: pd.DataFrame,
) -> pd.DataFrame:
    """Exclude same-session index members before industry flow aggregation.

member_flow is the active industry member panel: trade_date, ts_code,
net_mf_amount and all eight buy/sell sm/md/lg/elg amount fields. Index membership
uses trade_date, ts_code and must cover every input date. Missing amounts fail;
zero gross amount yields undefined net_flow_ratio, not a directional signal.
"""
    data = _frame(member_flow, ("trade_date", "ts_code", "net_mf_amount", *_GROSS_AMOUNT_COLUMNS))
    members = _frame(index_membership, ("trade_date", "ts_code"))
    _dates(data, "trade_date")
    _dates(members, "trade_date")
    _numbers(data, "net_mf_amount")
    _numbers(data, *_GROSS_AMOUNT_COLUMNS, nonnegative=True)
    _unique(data, "trade_date", "ts_code")
    _unique(members, "trade_date", "ts_code")
    dates = pd.DatetimeIndex(data["trade_date"].drop_duplicates().sort_values())
    if not dates.isin(members["trade_date"]).all():
        raise ValueError("index membership lacks an input session")
    outside = data.merge(members.assign(in_index=True), on=["trade_date", "ts_code"], how="left")
    outside = outside.loc[outside["in_index"].isna()].copy()
    outside["positive_flow"] = outside["net_mf_amount"].gt(0)
    outside["gross_order_amount"] = outside[list(_GROSS_AMOUNT_COLUMNS)].sum(axis=1)
    daily = outside.groupby("trade_date", sort=True).agg(
        active_members=("ts_code", "nunique"), positive_member_ratio=("positive_flow", "mean"),
        net_mf_amount=("net_mf_amount", "sum"), gross_order_amount=("gross_order_amount", "sum"),
    ).reindex(dates)
    daily["active_members"] = daily["active_members"].fillna(0).astype(int)
    daily["net_flow_ratio"] = daily["net_mf_amount"].div(
        daily["gross_order_amount"].replace(0.0, np.nan)
    )
    _finite_output(daily, "net_mf_amount", "gross_order_amount", "net_flow_ratio")
    return daily.rename_axis("trade_date").reset_index()


def calculate_sell_side_revision_breadth(
    reports: pd.DataFrame, calendar: pd.DatetimeIndex,
    parameters: SellSideRevisionParameters,
) -> pd.DataFrame:
    """Return rolling signed/observed historical constituent weight.

Inputs: ts_code, report_date, available_session, org_name, quarter, np, eps,
weight. Weight must represent membership at available_session. NP is preferred
when both reports provide it, otherwise the EPS pair is used. Missing NP/EPS
and zero denominators are explicitly noncomparable. Calendar warmup or zero
observed weight produces NaN. No research thresholds or event selection run.
"""
    dates = _calendar(calendar)
    if not isinstance(parameters, SellSideRevisionParameters):
        raise TypeError("parameters must be SellSideRevisionParameters")
    data = _frame(reports, (
        "ts_code", "report_date", "available_session", "org_name", "quarter", "np", "eps", "weight",
    ))
    _dates(data, "report_date", "available_session")
    _numbers(data, "np", "eps", allow_missing=True)
    _numbers(data, "weight", positive=True)
    _unique(data, "ts_code", "org_name", "quarter", "report_date")
    if not data["available_session"].isin(dates).all():
        raise ValueError("available_session must belong to the calendar")
    if not data["available_session"].gt(data["report_date"]).all():
        raise ValueError("reports are available only after report_date")
    weight_counts = data.groupby(["available_session", "ts_code"])["weight"].nunique()
    if weight_counts.gt(1).any():
        raise ValueError("company weight must agree at each available_session")
    data = data.sort_values(
        ["ts_code", "org_name", "quarter", "report_date", "available_session"], kind="stable",
    ).reset_index(drop=True)
    groups = data.groupby(["ts_code", "org_name", "quarter"], sort=False)
    previous = groups[["report_date", "available_session", "np", "eps"]].shift(1)
    age = (data["report_date"] - previous["report_date"]).dt.days
    np_pair = data["np"].notna() & previous["np"].notna()
    current = data["np"].where(np_pair, data["eps"])
    baseline = previous["np"].where(np_pair, previous["eps"])
    comparable = (current.notna() & baseline.notna() & baseline.abs().gt(1e-12)
                  & age.between(0, parameters.maximum_previous_age_days)
                  & previous["available_session"].le(data["available_session"]))
    revision = current.sub(baseline).div(baseline.abs()).where(comparable)
    if not np.isfinite(revision.dropna()).all():
        raise ValueError("revision calculation produced nonfinite values")
    threshold = parameters.minimum_relative_revision
    data["revision_sign"] = np.select(
        [revision.gt(threshold), revision.lt(-threshold)], [1.0, -1.0], default=0.0,
    )
    comparable_reports = data.loc[comparable]
    broker = comparable_reports.groupby(["available_session", "ts_code", "org_name"]).agg(
        revision_sign=("revision_sign", "median"), weight=("weight", "first"),
    ).reset_index()
    company = broker.groupby(["available_session", "ts_code"]).agg(
        revision_sign=("revision_sign", "mean"), weight=("weight", "first"),
    ).reset_index()
    company["signed_weight"] = company["revision_sign"] * company["weight"]
    daily = company.groupby("available_session").agg(
        signed_weight=("signed_weight", "sum"), observed_weight=("weight", "sum"),
    ).reindex(dates, fill_value=0.0)
    window = parameters.rolling_sessions
    numerator = daily["signed_weight"].rolling(window, min_periods=window).sum()
    denominator = daily["observed_weight"].rolling(window, min_periods=window).sum()
    daily["revision_score"] = numerator.div(denominator.replace(0.0, np.nan))
    _finite_output(daily, "signed_weight", "observed_weight", "revision_score")
    if not np.isfinite(numerator.dropna()).all() or not np.isfinite(denominator.dropna()).all():
        raise ValueError("rolling revision weight calculation produced nonfinite values")
    return daily.rename_axis("available_session").reset_index()


def calculate_etf_share_change_5d_lag1(
    shares: pd.DataFrame, calendar: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Return per-symbol five-session share change shifted one session.

Inputs match calculate_etf_share_change. Output share_change_5d_lag1 is a
decimal ratio; the first six observations per symbol are undefined.
"""
    data = calculate_etf_share_change(shares, calendar).drop(columns="share_change")
    data["share_change_5d_lag1"] = data.groupby("ts_code")["total_share"].transform(
        lambda values: values.pct_change(5, fill_method=None).shift(1)
    )
    _finite_output(data, "share_change_5d_lag1")
    return data


def calculate_daily_close_vwap_deviation(values: pd.DataFrame) -> pd.DataFrame:
    """Return close/(amount/volume)-1 as a decimal ratio.

Inputs: ts_code, trade_date, close, amount, volume. Amount must be in currency
units and volume in shares, matching the close quotation; callers must normalize
provider units before calling. Zero volume/amount has no VWAP and fails.
"""
    data = _frame(values, ("ts_code", "trade_date", "close", "amount", "volume"))
    _dates(data, "trade_date")
    _numbers(data, "close", "amount", "volume", positive=True)
    _unique(data, "ts_code", "trade_date")
    data = data.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    data["daily_close_vwap_deviation"] = data["close"].div(
        data["amount"].div(data["volume"])
    ).sub(1.0)
    _finite_output(data, "daily_close_vwap_deviation")
    return data


def _aware_times(values: pd.Series | pd.DatetimeIndex, name: str) -> pd.DatetimeIndex:
    try:
        timestamps = [pd.Timestamp(value) for value in values]
        if any(pd.isna(value) or value.tzinfo is None for value in timestamps):
            raise ValueError("missing timezone or timestamp")
        return pd.DatetimeIndex(pd.to_datetime(timestamps, utc=True))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must contain timezone-aware timestamps") from error


def calculate_prior_us_spx_return(
    observations: pd.DataFrame, session_opens: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Map the latest available SPX return strictly before each A-share open.

Inputs: ts_code='SPX', trade_date, pct_chg, available_at. pct_chg is a percentage
number; output prior_us_spx_return is divided by 100. available_at and
session_opens must be explicit timezone-aware timestamps, converted to UTC.
Each requested open requires an earlier completed observation; missing history
fails. Source trade_date alone is insufficient to infer availability.
"""
    data = _frame(observations, ("ts_code", "trade_date", "pct_chg", "available_at"))
    _dates(data, "trade_date")
    _numbers(data, "pct_chg")
    _unique(data, "ts_code", "trade_date")
    if not data["ts_code"].eq("SPX").all():
        raise ValueError("SPX observations must use ts_code SPX")
    data["available_at"] = _aware_times(data["available_at"], "available_at")
    _unique(data, "available_at")
    if not isinstance(session_opens, pd.DatetimeIndex):
        raise TypeError("session_opens must be a DatetimeIndex")
    opens = _aware_times(session_opens, "session_opens")
    if opens.empty or opens.has_duplicates or not opens.is_monotonic_increasing:
        raise ValueError("session_opens must contain unique increasing timestamps")
    data = data.sort_values("available_at")
    if not data["trade_date"].is_monotonic_increasing:
        raise ValueError("SPX availability order must agree with source session order")
    result = pd.merge_asof(
        pd.DataFrame({"session_open": opens}), data,
        left_on="session_open", right_on="available_at", direction="backward",
        allow_exact_matches=False,
    )
    if result["available_at"].isna().any():
        raise ValueError("SPX history lacks an observation before a requested open")
    result["prior_us_spx_return"] = result["pct_chg"].div(100.0)
    _finite_output(result, "prior_us_spx_return")
    return result


def calculate_chinext_turnover_z20(
    values: pd.DataFrame, calendar: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Return (turnover_rate_f-mean20)/population_std20 for 399006.SZ.

Inputs: ts_code, trade_date, turnover_rate_f. All 20 calendar sessions, including
the current session, are required. Warmup and constant windows yield NaN.
Output chinext_turnover_z20 is dimensionless; uniform unit scaling cancels.
"""
    dates = _calendar(calendar)
    data = _frame(values, ("ts_code", "trade_date", "turnover_rate_f"))
    _dates(data, "trade_date")
    _numbers(data, "turnover_rate_f", nonnegative=True)
    _unique(data, "ts_code", "trade_date")
    if not data["ts_code"].eq("399006.SZ").all():
        raise ValueError("ChiNext turnover requires ts_code 399006.SZ")
    data = data.sort_values("trade_date").reset_index(drop=True)
    _consecutive_sessions(data, dates)
    window = data["turnover_rate_f"].rolling(20, min_periods=20)
    std = window.std(ddof=0)
    data["chinext_turnover_z20"] = data["turnover_rate_f"].sub(window.mean()).div(
        std.replace(0.0, np.nan)
    )
    _finite_output(data, "chinext_turnover_z20")
    return data


def calculate_shibor_on_change_5d(
    values: pd.DataFrame, calendar: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Return on_t-on_t-5 across five calendar sessions without rescaling.

Inputs: trade_date, on. The output shibor_on_change_5d retains the rate unit:
percentage-point changes when input rates are quoted as percentages.
"""
    dates = _calendar(calendar)
    data = _frame(values, ("trade_date", "on"))
    _dates(data, "trade_date")
    _numbers(data, "on")
    _unique(data, "trade_date")
    data = data.sort_values("trade_date").reset_index(drop=True)
    _consecutive_sessions(data, dates)
    data["shibor_on_change_5d"] = data["on"].diff(5)
    _finite_output(data, "shibor_on_change_5d")
    return data


def calculate_daily_intraday_range(values: pd.DataFrame) -> pd.DataFrame:
    """Return (high-low)/close as a decimal ratio from completed daily bars.

Inputs: ts_code, trade_date, high, low, close. Prices must be positive and close
must be inside [low, high]; inconsistent price units or bars fail.
"""
    data = _frame(values, ("ts_code", "trade_date", "high", "low", "close"))
    _dates(data, "trade_date")
    _numbers(data, "high", "low", "close", positive=True)
    _unique(data, "ts_code", "trade_date")
    if (data["high"].lt(data["low"]) | data["close"].lt(data["low"])
            | data["close"].gt(data["high"])).any():
        raise ValueError("daily prices must satisfy low <= close <= high")
    data = data.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    data["daily_intraday_range"] = data["high"].sub(data["low"]).div(data["close"])
    _finite_output(data, "daily_intraday_range")
    return data
