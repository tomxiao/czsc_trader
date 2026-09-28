"""S011 EX01: formal no-return sell-side expectation mechanism gate."""

from __future__ import annotations

from bisect import bisect_right
from datetime import date
import json

import numpy as np
import pandas as pd
import tushare

from dataflows import DataRequest, DataStatus, Dataset
from research_experiment import (
    ExperimentCapabilities,
    ExperimentDefinition,
    ExperimentDependency,
    ExperimentMode,
    ExperimentOutcome,
    ExperimentProtocol,
    ExperimentResult,
    ExperimentStage,
    ResearchExperiment,
)


EXPERIMENT_ID = "20260928_S011_EX01"
ETF_SYMBOL = "159326.SZ"
INDEX_SYMBOL = "931994.CSI"
REPORT_START = "2023-09-09"
START = "2024-09-09"
END = "2026-09-24"
SNAPSHOT_START = "2024-08"
SNAPSHOT_END = "2026-08"
SNAPSHOT_LAG_DAYS = 35
REVISION_MAX_AGE_DAYS = 365
REVISION_THRESHOLD = 0.01
ROLLING_SESSIONS = 20
THRESHOLD_LOOKBACK = 252
THRESHOLD_MIN_OBSERVATIONS = 126
ENTRY_QUANTILE = 0.70
EXIT_QUANTILE = 0.50
SEED = 2026092801

PASS_THRESHOLDS = {
    "comparable_rows": 3000,
    "revised_members": 40,
    "median_weight_coverage": 0.75,
    "rolling_60_distinct_members_p10": 20.0,
    "temperature_sessions": 300,
    "temperature_changed_sessions": 250,
    "positive_broker_company_days": 100,
    "negative_broker_company_days": 100,
}


def _sessions(calendar: pd.DataFrame) -> pd.DatetimeIndex:
    frame = calendar.copy()
    frame["Date"] = pd.to_datetime(frame["Date"]).dt.normalize()
    values = frame.loc[frame["IsOpen"].eq(1), "Date"].sort_values().unique()
    result = pd.DatetimeIndex(values)
    if result.empty or result.has_duplicates or not result.is_monotonic_increasing:
        raise ValueError("trading sessions are empty, duplicated or unordered")
    return result


def _snapshot_weight_panel(
    snapshots: pd.DataFrame, sessions: pd.DatetimeIndex
) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = snapshots.copy()
    frame["Date"] = pd.to_datetime(frame["Date"]).dt.normalize()
    frame["Weight"] = pd.to_numeric(frame["Weight"], errors="raise")
    if frame.duplicated(["Date", "ConstituentSymbol"]).any():
        raise ValueError("index snapshots contain duplicate members")
    totals = frame.groupby("Date")["Weight"].sum()
    if not totals.between(90.0, 110.0).all() or not frame["Weight"].gt(0).all():
        raise ValueError("index snapshot weights are invalid")

    source_dates = sorted(pd.Timestamp(value) for value in frame["Date"].unique())
    effective: dict[pd.Timestamp, pd.Timestamp] = {}
    for source_date in source_dates:
        threshold = source_date + pd.Timedelta(days=SNAPSHOT_LAG_DAYS)
        position = sessions.searchsorted(threshold, side="left")
        if position < len(sessions):
            effective[source_date] = sessions[position]
    if not effective:
        raise ValueError("no index snapshot becomes causally usable")

    daily: list[pd.DataFrame] = []
    available_pairs = sorted((available, source) for source, available in effective.items())
    available_dates = [item[0] for item in available_pairs]
    for session in sessions:
        position = bisect_right(available_dates, session) - 1
        if position < 0:
            continue
        source_date = available_pairs[position][1]
        selected = frame.loc[
            frame["Date"].eq(source_date), ["ConstituentSymbol", "Weight"]
        ].copy()
        selected["AvailableDate"] = session
        selected["SnapshotSourceDate"] = source_date
        daily.append(selected)
    if not daily:
        raise ValueError("index weight panel is empty")
    panel = pd.concat(daily, ignore_index=True).rename(
        columns={"ConstituentSymbol": "Symbol"}
    )
    availability = pd.DataFrame(
        [
            {"SnapshotSourceDate": source, "SnapshotAvailableDate": available}
            for source, available in effective.items()
        ]
    ).sort_values("SnapshotSourceDate")
    return panel, availability


def _revision_events(
    reports: pd.DataFrame, weight_panel: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    frame = reports.copy()
    for column in ("Date", "AvailableDate", "VendorCreatedAt"):
        frame[column] = pd.to_datetime(frame[column])
    frame["ForecastPeriod"] = frame["ForecastPeriod"].astype("string").str.strip()
    frame = frame.loc[
        frame["ForecastPeriod"].notna() & frame["ForecastPeriod"].ne("")
    ].copy()
    order = [
        "Symbol",
        "Institution",
        "ForecastPeriod",
        "AvailableDate",
        "VendorCreatedAt",
        "Date",
        "ReportTitle",
    ]
    frame = frame.sort_values(order, kind="mergesort").drop_duplicates(
        ["Symbol", "Institution", "ForecastPeriod", "AvailableDate"], keep="last"
    )
    groups = frame.groupby(
        ["Symbol", "Institution", "ForecastPeriod"], dropna=False, sort=False
    )
    frame["PreviousDate"] = groups["Date"].shift(1)
    frame["PreviousAvailableDate"] = groups["AvailableDate"].shift(1)
    frame["PreviousNetProfitForecast"] = groups["NetProfitForecast"].shift(1)
    frame["PreviousEarningsPerShareForecast"] = groups[
        "EarningsPerShareForecast"
    ].shift(1)
    age = (frame["Date"] - frame["PreviousDate"]).dt.days
    np_pair = (
        frame["NetProfitForecast"].notna()
        & frame["PreviousNetProfitForecast"].notna()
        & frame["PreviousNetProfitForecast"].abs().gt(1e-12)
    )
    eps_pair = (
        ~np_pair
        & frame["EarningsPerShareForecast"].notna()
        & frame["PreviousEarningsPerShareForecast"].notna()
        & frame["PreviousEarningsPerShareForecast"].abs().gt(1e-12)
    )
    current = frame["NetProfitForecast"].where(
        np_pair, frame["EarningsPerShareForecast"]
    )
    previous = frame["PreviousNetProfitForecast"].where(
        np_pair, frame["PreviousEarningsPerShareForecast"]
    )
    frame["RevisionMetric"] = np.select(
        [np_pair, eps_pair], ["NET_PROFIT", "EPS"], default="UNAVAILABLE"
    )
    frame["RelativeRevision"] = current.sub(previous).div(previous.abs()).where(
        (np_pair | eps_pair)
        & age.between(0, REVISION_MAX_AGE_DAYS, inclusive="both")
        & frame["PreviousAvailableDate"].lt(frame["AvailableDate"])
    )
    frame = frame.merge(
        weight_panel,
        on=["AvailableDate", "Symbol"],
        how="left",
        validate="many_to_one",
    )
    active = frame.loc[frame["Weight"].notna()].copy()
    comparable = active.loc[active["RelativeRevision"].notna()].copy()
    comparable["RevisionSign"] = np.select(
        [
            comparable["RelativeRevision"].gt(REVISION_THRESHOLD),
            comparable["RelativeRevision"].lt(-REVISION_THRESHOLD),
        ],
        [1.0, -1.0],
        default=0.0,
    )
    broker_day = (
        comparable.groupby(
            ["AvailableDate", "Symbol", "Institution"], observed=True
        )
        .agg(
            RevisionSign=("RevisionSign", "median"),
            RelativeRevision=("RelativeRevision", "median"),
            ForecastPeriods=("ForecastPeriod", "nunique"),
            Weight=("Weight", "first"),
            SnapshotSourceDate=("SnapshotSourceDate", "first"),
        )
        .reset_index()
    )
    company_day = (
        broker_day.groupby(["AvailableDate", "Symbol"], observed=True)
        .agg(
            RevisionScore=("RevisionSign", "mean"),
            MedianRelativeRevision=("RelativeRevision", "median"),
            Institutions=("Institution", "nunique"),
            ForecastPeriods=("ForecastPeriods", "sum"),
            Weight=("Weight", "first"),
            SnapshotSourceDate=("SnapshotSourceDate", "first"),
        )
        .reset_index()
    )
    return comparable, broker_day, company_day


def _temperature_ledger(
    company_day: pd.DataFrame, sessions: pd.DatetimeIndex
) -> pd.DataFrame:
    values = company_day.copy()
    values["SignedWeight"] = values["RevisionScore"] * values["Weight"]
    daily = (
        values.groupby("AvailableDate", observed=True)
        .agg(
            SignedWeight=("SignedWeight", "sum"),
            ObservedWeight=("Weight", "sum"),
            RevisedCompanies=("Symbol", "nunique"),
            Institutions=("Institutions", "sum"),
        )
        .reindex(sessions, fill_value=0.0)
    )
    daily.index.name = "Date"
    daily["DailyRevisionTone"] = daily["SignedWeight"].div(
        daily["ObservedWeight"].replace(0.0, np.nan)
    )
    daily["RevisionTemperature20"] = daily["SignedWeight"].rolling(
        ROLLING_SESSIONS
    ).sum().div(
        daily["ObservedWeight"].rolling(ROLLING_SESSIONS).sum().replace(0.0, np.nan)
    )
    history = daily["RevisionTemperature20"].shift(1)
    daily["EntryThresholdQ70"] = history.rolling(
        THRESHOLD_LOOKBACK, min_periods=THRESHOLD_MIN_OBSERVATIONS
    ).quantile(ENTRY_QUANTILE)
    daily["ExitThresholdQ50"] = history.rolling(
        THRESHOLD_LOOKBACK, min_periods=THRESHOLD_MIN_OBSERVATIONS
    ).quantile(EXIT_QUANTILE)
    return daily


def _behavior_episodes(ledger: pd.DataFrame) -> list[dict[str, object]]:
    holding = False
    entry: pd.Timestamp | None = None
    episodes: list[dict[str, object]] = []
    for day, row in ledger.iterrows():
        score = row["RevisionTemperature20"]
        upper = row["EntryThresholdQ70"]
        lower = row["ExitThresholdQ50"]
        if pd.isna(score) or pd.isna(upper) or pd.isna(lower):
            continue
        if not holding and score >= upper:
            holding = True
            entry = pd.Timestamp(day)
        elif holding and score <= lower:
            assert entry is not None
            holding = False
            episodes.append(
                {
                    "entry_date": entry.strftime("%Y-%m-%d"),
                    "exit_date": pd.Timestamp(day).strftime("%Y-%m-%d"),
                    "holding_sessions": int(
                        ledger.index.get_loc(day) - ledger.index.get_loc(entry)
                    ),
                }
            )
            entry = None
    return episodes


def _concentration(values: pd.Series) -> dict[str, float | int]:
    weights = values.astype(float).abs().sort_values(ascending=False)
    total = float(weights.sum())
    return {
        "count": int(len(weights)),
        "top1_share": 0.0 if total == 0 else float(weights.iloc[:1].sum() / total),
        "top5_share": 0.0 if total == 0 else float(weights.iloc[:5].sum() / total),
    }


def _rolling_distinct_members(
    comparable: pd.DataFrame, sessions: pd.DatetimeIndex
) -> pd.Series:
    presence = (
        comparable.assign(Observed=1)
        .pivot_table(
            index="AvailableDate",
            columns="Symbol",
            values="Observed",
            aggfunc="max",
            fill_value=0,
        )
        .reindex(sessions, fill_value=0)
    )
    return presence.rolling(60, min_periods=60).max().sum(axis=1, min_count=1).dropna()


def _weight_coverage(snapshots: pd.DataFrame, members: set[str]) -> pd.Series:
    values = []
    for _, group in snapshots.groupby("Date"):
        total = float(group["Weight"].sum())
        covered = float(
            group.loc[group["ConstituentSymbol"].isin(members), "Weight"].sum()
        )
        values.append(covered / total if total else np.nan)
    return pd.Series(values, dtype=float).dropna()


def _write_frame(context, name: str, frame: pd.DataFrame) -> None:
    frame.to_csv(
        context.workspace.path(name),
        index=False,
        compression="gzip" if name.endswith(".gz") else None,
        lineterminator="\n",
        date_format="%Y-%m-%d %H:%M:%S",
    )


def synthetic_precheck() -> None:
    sessions = pd.bdate_range("2024-01-01", periods=220)
    weight_panel = pd.DataFrame(
        [
            {"AvailableDate": day, "Symbol": symbol, "Weight": 50.0,
             "SnapshotSourceDate": sessions[0] - pd.Timedelta(days=40)}
            for day in sessions for symbol in ("000001.SZ", "600000.SH")
        ]
    )
    rows = []
    for symbol, sign in (("000001.SZ", 1.0), ("600000.SH", -1.0)):
        for position, value in ((10, 100.0), (30, 100.0 * (1 + 0.02 * sign))):
            rows.append({
                "Date": sessions[position] - pd.Timedelta(days=1),
                "AvailableDate": sessions[position],
                "VendorCreatedAt": sessions[position] - pd.Timedelta(hours=12),
                "Symbol": symbol,
                "Institution": "TEST",
                "ForecastPeriod": "2024Q4",
                "ReportTitle": f"{symbol}-{position}",
                "NetProfitForecast": value,
                "EarningsPerShareForecast": value / 100,
            })
    comparable, broker_day, company_day = _revision_events(
        pd.DataFrame(rows), weight_panel
    )
    if len(comparable) != 2 or sorted(broker_day["RevisionSign"].tolist()) != [-1.0, 1.0]:
        raise ValueError("synthetic revision comparison changed")
    ledger = _temperature_ledger(company_day, sessions)
    if ledger["RevisionTemperature20"].dropna().empty:
        raise ValueError("synthetic temperature is empty")
    if REVISION_THRESHOLD != 0.01 or SNAPSHOT_LAG_DAYS != 35:
        raise ValueError("frozen revision or snapshot rule changed")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id=EXPERIMENT_ID,
            strategy_id="S011",
            mode=ExperimentMode.DISCOVERY,
            research_question=(
                "Can causally available sell-side forecast revisions form a broad, "
                "changing and sufficiently dense expectation mechanism for 159326.SZ?"
            ),
            hypothesis=(
                "Same-broker forecast revisions aggregate into a diversified expectation "
                "temperature that qualifies for one later return-increment test."
            ),
            falsification_conditions=(
                "Any non-empty sell-side source fails DFLS identity or completeness",
                "Comparable revisions cover fewer than 40 members or 3000 rows",
                "Historical member weight coverage median is below 75 percent",
                "Revision breadth or temperature variation misses a frozen density gate",
            ),
            development_cutoff=date(2026, 9, 24),
            random_seed=SEED,
            allowed_datasets=(
                Dataset.INDEX_CONSTITUENT_WEIGHT.value,
                Dataset.SELL_SIDE_FORECAST.value,
                Dataset.TRADING_CALENDAR.value,
            ),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.MECHANISM_DISCOVERY,
                first_principles=(
                    "Earnings expectations can change before reported fundamentals",
                    "Breadth across companies and institutions is harder to explain by one report",
                ),
                information_paths=(
                    "Causal broker forecast revision -> historical-member breadth -> later ETF repricing",
                ),
                stage_objectives=(
                    "Materialize one frozen no-return expectation-temperature ledger",
                    "Decide whether exactly one return-increment test is warranted",
                ),
                observation_metrics=(
                    "DFLS status and content identity",
                    "comparable revision rows and member coverage",
                    "weight coverage and concentration",
                    "temperature variation and diagnostic behavior density",
                ),
                methodology=(
                    "Net profit first and EPS fallback within company-institution-period",
                    "1 percent revision threshold and 20-session weighted aggregation",
                    "35-calendar-day lag for monthly index snapshots",
                    "No prices, returns, parameter search or candidate creation",
                ),
            ),
            dependencies=(
                ExperimentDependency("numpy", np.__version__),
                ExperimentDependency("pandas", pd.__version__),
                ExperimentDependency("tushare", tushare.__version__),
            ),
            capabilities=ExperimentCapabilities(),
            subjects=(ETF_SYMBOL,),
        )

    def synthetic_precheck(self) -> None:
        synthetic_precheck()

    def execute(self, context) -> ExperimentResult:
        calendar_result = context.data.fetch(
            DataRequest(
                Dataset.TRADING_CALENDAR,
                "SSE",
                REPORT_START,
                END,
                END,
                options={"env_file": ".env"},
            )
        )
        if calendar_result.status is not DataStatus.READY or calendar_result.identity is None:
            raise ValueError(f"trading calendar failed: {calendar_result.status.value}")
        full_sessions = _sessions(calendar_result.dataframe)
        sessions = full_sessions[
            (full_sessions >= pd.Timestamp(START)) & (full_sessions <= pd.Timestamp(END))
        ]

        snapshots: list[pd.DataFrame] = []
        identities: list[dict[str, object]] = [{
            "kind": "calendar",
            "dataset": calendar_result.identity.dataset,
            "symbol": calendar_result.identity.symbol,
            "rows": len(calendar_result.dataframe),
            "content_sha256": calendar_result.identity.content_sha256,
            "status": calendar_result.status.value,
        }]
        for month in pd.period_range(SNAPSHOT_START, SNAPSHOT_END, freq="M"):
            result = context.data.fetch(
                DataRequest(
                    Dataset.INDEX_CONSTITUENT_WEIGHT,
                    INDEX_SYMBOL,
                    month.strftime("%Y-%m-01"),
                    month.end_time.strftime("%Y-%m-%d"),
                    None,
                    options={"env_file": ".env"},
                )
            )
            if result.status is not DataStatus.READY or result.identity is None:
                raise ValueError(f"index snapshot failed for {month}: {result.status.value}")
            frame = result.dataframe.copy()
            source_date = pd.to_datetime(frame["Date"]).max()
            selected = frame.loc[pd.to_datetime(frame["Date"]).eq(source_date)].copy()
            selected["SnapshotRequestMonth"] = str(month)
            snapshots.append(selected)
            identities.append({
                "kind": "index_weight",
                "dataset": result.identity.dataset,
                "symbol": result.identity.symbol,
                "request_period": str(month),
                "rows": len(selected),
                "content_sha256": result.identity.content_sha256,
                "status": result.status.value,
            })
        snapshot_frame = pd.concat(snapshots, ignore_index=True)
        weight_panel, snapshot_availability = _snapshot_weight_panel(
            snapshot_frame, sessions
        )
        symbols = sorted(snapshot_frame["ConstituentSymbol"].astype(str).unique())

        reports: list[pd.DataFrame] = []
        fatal_statuses: list[dict[str, str]] = []
        empty_symbols: list[str] = []
        for symbol in symbols:
            result = context.data.fetch(
                DataRequest(
                    Dataset.SELL_SIDE_FORECAST,
                    symbol,
                    REPORT_START,
                    END,
                    None,
                    options={"env_file": ".env"},
                )
            )
            identity = result.identity
            identities.append({
                "kind": "sell_side_forecast",
                "dataset": Dataset.SELL_SIDE_FORECAST.value,
                "symbol": symbol,
                "rows": len(result.dataframe),
                "content_sha256": None if identity is None else identity.content_sha256,
                "status": result.status.value,
            })
            if result.status is DataStatus.EMPTY:
                empty_symbols.append(symbol)
            elif result.status is not DataStatus.READY or identity is None:
                fatal_statuses.append({
                    "symbol": symbol,
                    "status": result.status.value,
                    "error": "" if result.error is None else result.error.code,
                })
            else:
                reports.append(result.dataframe.copy())
        if not reports:
            raise ValueError("no sell-side forecast rows were published")
        report_frame = pd.concat(reports, ignore_index=True)
        report_frame["AvailableDate"] = pd.to_datetime(report_frame["AvailableDate"])
        report_frame = report_frame.loc[
            report_frame["AvailableDate"].between(pd.Timestamp(START), pd.Timestamp(END))
        ].copy()

        comparable, broker_day, company_day = _revision_events(
            report_frame, weight_panel
        )
        ledger = _temperature_ledger(company_day, sessions)
        episodes = _behavior_episodes(ledger)
        rolling_distinct = _rolling_distinct_members(comparable, sessions)
        revised_members = set(comparable["Symbol"].astype(str).unique())
        coverage = _weight_coverage(snapshot_frame, revised_members)
        temperature = ledger["RevisionTemperature20"].dropna()
        sign_counts = broker_day["RevisionSign"].value_counts()
        positive = int(sign_counts.get(1.0, 0))
        negative = int(sign_counts.get(-1.0, 0))

        company_contribution = company_day.assign(
            Contribution=lambda value: value["RevisionScore"].abs() * value["Weight"]
        ).groupby("Symbol")["Contribution"].sum()
        institution_contribution = broker_day.assign(
            Contribution=lambda value: value["RevisionSign"].abs() * value["Weight"]
        ).groupby("Institution", dropna=False)["Contribution"].sum()

        checks = {
            "no_fatal_dfls_status": len(fatal_statuses) == 0,
            "comparable_rows": len(comparable) >= PASS_THRESHOLDS["comparable_rows"],
            "revised_members": len(revised_members) >= PASS_THRESHOLDS["revised_members"],
            "median_weight_coverage": float(coverage.median())
            >= PASS_THRESHOLDS["median_weight_coverage"],
            "rolling_60_distinct_members_p10": float(rolling_distinct.quantile(0.1))
            >= PASS_THRESHOLDS["rolling_60_distinct_members_p10"],
            "temperature_sessions": len(temperature)
            >= PASS_THRESHOLDS["temperature_sessions"],
            "temperature_changed_sessions": int(temperature.diff().abs().gt(1e-12).sum())
            >= PASS_THRESHOLDS["temperature_changed_sessions"],
            "positive_broker_company_days": positive
            >= PASS_THRESHOLDS["positive_broker_company_days"],
            "negative_broker_company_days": negative
            >= PASS_THRESHOLDS["negative_broker_company_days"],
        }
        qualifies = all(checks.values())
        decision = (
            "PROCEED_TO_SINGLE_INFORMATION_INCREMENT_TEST"
            if qualifies
            else "STOP_SELL_SIDE_EXPECTATION_PATH"
        )
        episode_frame = pd.DataFrame(episodes)
        exits = pd.Series(0, index=sessions, dtype=int)
        for item in episodes:
            exits.loc[pd.Timestamp(item["exit_date"])] = 1
        rolling_closed = exits.rolling(60, min_periods=60).sum().dropna()
        summary = {
            "decision": decision,
            "checks": checks,
            "thresholds": PASS_THRESHOLDS,
            "reads_etf_prices": False,
            "reads_real_returns": False,
            "reads_sealed_validation": False,
            "candidate_created": False,
            "historical_member_union": len(symbols),
            "sell_side_ready_symbols": len(reports),
            "sell_side_empty_symbols": len(empty_symbols),
            "fatal_dfls_statuses": fatal_statuses,
            "report_rows_in_window": len(report_frame),
            "comparable_rows": len(comparable),
            "revised_members": len(revised_members),
            "positive_broker_company_days": positive,
            "neutral_broker_company_days": int(sign_counts.get(0.0, 0)),
            "negative_broker_company_days": negative,
            "weight_coverage": {
                "median": float(coverage.median()),
                "p10": float(coverage.quantile(0.1)),
                "minimum": float(coverage.min()),
            },
            "rolling_60_distinct_members": {
                "median": float(rolling_distinct.median()),
                "p10": float(rolling_distinct.quantile(0.1)),
                "minimum": float(rolling_distinct.min()),
            },
            "temperature": {
                "sessions": len(temperature),
                "changed_sessions": int(temperature.diff().abs().gt(1e-12).sum()),
                "minimum": float(temperature.min()),
                "p10": float(temperature.quantile(0.1)),
                "median": float(temperature.median()),
                "p90": float(temperature.quantile(0.9)),
                "maximum": float(temperature.max()),
            },
            "company_concentration": _concentration(company_contribution),
            "institution_concentration": _concentration(institution_contribution),
            "diagnostic_behavior": {
                "entries": len(episodes) + int(
                    not ledger["EntryThresholdQ70"].dropna().empty
                    and ledger.iloc[-1]["RevisionTemperature20"]
                    >= ledger.iloc[-1]["EntryThresholdQ70"]
                ),
                "closed_episodes": len(episodes),
                "holding_sessions_median": None
                if episode_frame.empty
                else float(episode_frame["holding_sessions"].median()),
                "rolling_60_closed_median": float(rolling_closed.median()),
                "rolling_60_closed_p10": float(rolling_closed.quantile(0.1)),
                "episodes": episodes,
                "boundary": "diagnostic state changes only; not orders or account trades",
            },
            "snapshot_lag_days": SNAPSHOT_LAG_DAYS,
            "vendor_history_mode": "CURRENT_VENDOR_SNAPSHOT",
            "snapshot_publication_time_verified": False,
        }

        _write_frame(context, "source_identities.csv", pd.DataFrame(identities))
        _write_frame(context, "index_snapshots.csv.gz", snapshot_frame)
        _write_frame(context, "snapshot_availability.csv", snapshot_availability)
        _write_frame(context, "sell_side_reports.csv.gz", report_frame)
        _write_frame(context, "comparable_revisions.csv.gz", comparable)
        _write_frame(context, "company_revision_days.csv.gz", company_day)
        _write_frame(context, "expectation_temperature.csv.gz", ledger.reset_index())
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        artifacts = tuple(
            context.workspace.register_artifact(name, kind)
            for name, kind in (
                ("source_identities.csv", "dfls-source-identities"),
                ("index_snapshots.csv.gz", "historical-index-snapshots"),
                ("snapshot_availability.csv", "conservative-snapshot-availability"),
                ("sell_side_reports.csv.gz", "causal-sell-side-report-panel"),
                ("comparable_revisions.csv.gz", "same-broker-comparable-revisions"),
                ("company_revision_days.csv.gz", "company-revision-events"),
                ("expectation_temperature.csv.gz", "sell-side-expectation-temperature"),
                ("summary.json", "mechanism-gate-summary"),
            )
        )
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS if qualifies else ExperimentOutcome.FAIL,
            facts={
                "decision": decision,
                "comparable_rows": len(comparable),
                "revised_members": len(revised_members),
                "temperature_sessions": len(temperature),
                "closed_diagnostic_episodes": len(episodes),
                "reads_real_returns": False,
            },
            diagnostics={
                "checks": checks,
                "fatal_dfls_statuses": fatal_statuses,
                "snapshot_publication_time_verified": False,
            },
            artifacts=artifacts,
        )
