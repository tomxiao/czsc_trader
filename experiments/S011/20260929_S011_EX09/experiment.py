"""S011-only constituent/forecast data gate. No security prices or return labels."""
from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import numpy as np
import pandas as pd
from dataflows import DataRequest, Dataset
from research_experiment import (
    ExperimentCapabilities, ExperimentDefinition, ExperimentDependency,
    ExperimentMode, ExperimentOutcome, ExperimentProtocol, ExperimentResult,
    ExperimentStage, ResearchExperiment,
)

ID = "20260929_S011_EX09"
PREDECESSOR = "20260929_S011_EX03"
START, END = "2024-09-09", "2026-09-28"
LAG, AGE = 35, 180
EPS = "EarningsPerShareForecast"
KEY = ["Symbol", "Institution", "ForecastPeriod"]
REPORT_KEY = ["Date", "Symbol", "Institution", "ReportTitle", "Authors", "ReportType", "Classification"]


def normalize_reports(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for name in ("Date", "AvailableDate", "VendorCreatedAt"):
        result[name] = pd.to_datetime(result[name], errors="raise")
    for name in KEY:
        result[name] = result[name].astype("string").str.strip()
    result[EPS] = pd.to_numeric(result[EPS], errors="raise")
    if np.isinf(result[EPS].dropna().to_numpy(dtype=float)).any():
        raise ValueError("infinite EPS")
    if not result["AvailableDate"].gt(result["Date"]).all():
        raise ValueError("availability must be after report date")
    if not result["AvailableDate"].gt(result["VendorCreatedAt"].dt.normalize()).all():
        raise ValueError("availability must be after vendor update day")
    return result


def active_institutions(reports: pd.DataFrame, day: pd.Timestamp, period: str) -> pd.DataFrame:
    mask = (reports["AvailableDate"].le(day) & reports["Date"].le(day)
            & reports["Date"].ge(day - pd.Timedelta(days=AGE))
            & reports["ForecastPeriod"].eq(period)
            & reports["Institution"].notna() & reports["Institution"].ne(""))
    selected = reports.loc[mask].copy()
    if selected.empty:
        return pd.DataFrame(columns=[*KEY, "EpsValues", "MissingEps", "Valid"])
    latest = selected.groupby(KEY)["Date"].transform("max")
    selected = selected.loc[selected["Date"].eq(latest)]
    grouped = selected.groupby(KEY, dropna=False)[EPS].agg(
        EpsValues="nunique", MissingEps=lambda x: bool(x.isna().any()),
    ).reset_index()
    grouped["Valid"] = grouped["EpsValues"].eq(1) & ~grouped["MissingEps"]
    return grouped


def select_snapshot(weights: pd.DataFrame, day: pd.Timestamp) -> pd.DataFrame:
    eligible = weights.loc[weights["Date"].le(day - pd.Timedelta(days=LAG))]
    if eligible.empty:
        return eligible
    return eligible.loc[eligible["Date"].eq(eligible["Date"].max())]


def coverage_row(weights: pd.DataFrame, active: pd.DataFrame) -> dict:
    counts = active.loc[active["Valid"].eq(True)].groupby("Symbol").size()
    n = weights["ConstituentSymbol"].map(counts).fillna(0)
    total = float(weights["Weight"].sum())
    if total <= 0:
        raise ValueError("empty or invalid snapshot weights")
    return {"Members": len(weights), "WeightTotal": total,
            "MembersWithOneInstitution": int(n.ge(1).sum()),
            "MembersWithTwoInstitutions": int(n.ge(2).sum()),
            "WeightWithOneInstitutionPct": float(weights.loc[n.ge(1), "Weight"].sum()/total*100),
            "WeightWithTwoInstitutionsPct": float(weights.loc[n.ge(2), "Weight"].sum()/total*100),
            "AmbiguousOrMissingInstitutionKeys": int((~active["Valid"].astype(bool)).sum())}


def synthetic_checks() -> None:
    day = pd.Timestamp("2026-06-30")
    rows = []
    def add(symbol, org, report, available, eps, period="2026Q4"):
        rows.append({"Symbol": symbol, "Institution": org, "Date": report,
                     "AvailableDate": available, "VendorCreatedAt": report,
                     "ForecastPeriod": period, EPS: eps})
    add("A", "I", "2026-06-01", "2026-06-02", 0.)
    add("A", "I", "2026-06-01", "2026-06-02", 0.)
    add("A", "J", "2026-06-01", "2026-06-02", -1.)
    add("B", "I", "2026-05-01", "2026-05-04", 1.)
    add("B", "I", "2026-06-01", "2026-06-02", 2.)
    add("B", "I", "2026-06-01", "2026-06-02", 3.)
    add("C", "I", "2026-06-29", "2026-07-01", 4.)
    add("D", "I", "2026-06-01", "2026-06-02", 4., "2027Q4")
    add("E", "I", str((day-pd.Timedelta(days=180)).date()), "2026-01-05", 1.)
    add("F", "I", str((day-pd.Timedelta(days=181)).date()), "2026-01-05", 1.)
    add("G", "I", "2026-06-01", "2026-06-02", np.nan)
    reports = normalize_reports(pd.DataFrame(rows))
    active = active_institutions(reports, day, "2026Q4")
    assert set(active.loc[active.Valid, "Symbol"]) == {"A", "E"}
    assert int(active.Valid.sum()) == 3
    assert set(active.loc[~active.Valid, "Symbol"]) == {"B", "G"}
    weights = pd.DataFrame({"Date": [day-pd.Timedelta(days=35)]*2,
                            "ConstituentSymbol": ["A", "B"], "Weight": [60., 40.]})
    assert select_snapshot(weights, day-pd.Timedelta(days=1)).empty
    assert len(select_snapshot(weights, day)) == 2
    row = coverage_row(weights, active.loc[active.Symbol.isin(["A", "B"])])
    assert row["WeightWithOneInstitutionPct"] == row["WeightWithTwoInstitutionsPct"] == 60.
    assert len(active_institutions(reports, day, "2027Q4")) == 1
    changed = reports.copy()
    changed.loc[changed.Symbol.eq("C"), EPS] = 999.
    pd.testing.assert_frame_equal(active, active_institutions(changed, day, "2026Q4"))


class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(
            schema_version=1, experiment_id=ID, strategy_id="S011", mode=ExperimentMode.FORMAL,
            research_question="Can current constituent and forecast sources establish a historical ETF basket data gate?",
            hypothesis="Union-symbol READY counts may overstate timely, fiscal-year-consistent weighted coverage.",
            falsification_conditions=("Missing constituent publication evidence or forecast vintage identity blocks historical promotion",),
            development_cutoff=date(2026,9,28), validation_cutoff=date(2026,9,29), random_seed=2026092909,
            allowed_datasets=(Dataset.INDEX_CONSTITUENT_WEIGHT.value, Dataset.SELL_SIDE_FORECAST.value,
                              Dataset.TRADING_CALENDAR.value),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.DATA_GATE,
                first_principles=("An ETF basket forecast needs identifiable contemporaneous members and forecasts",),
                information_paths=("Conditional lagged weights and dated available forecast events to coverage only",),
                stage_objectives=("Audit weighted availability, institution duplicates and forecast vintage boundaries",),
                observation_metrics=("Weighted fiscal-year coverage, update delay, duplicate and conflict counts",),
                methodology=("Fixed 35 calendar-day weight lag diagnostic, 180-day report age, separate FY0/FY1",),
                predecessor_experiment_ids=(PREDECESSOR,),
            ),
            subjects=("159326.SZ",),
            dependencies=(ExperimentDependency("numpy", np.__version__), ExperimentDependency("pandas", pd.__version__)),
            # Formal context requires both capabilities even for non-price data.fetch.
            # allowed_datasets contains no prices; results explicitly report no return access.
            capabilities=ExperimentCapabilities(reads_real_returns=True, reads_sealed_validation=True),
        )

    def synthetic_precheck(self):
        synthetic_checks()

    def execute(self, context):
        options = {"env_file": str(Path(__file__).resolve().parents[3]/".env")}
        artifacts, identities, states, forecasts = [], {}, [], []
        def save(name, frame):
            frame.to_csv(context.workspace.path(name), index=False, lineterminator="\n",
                         compression="gzip" if name.endswith(".gz") else None)
            artifacts.append(context.workspace.register_artifact(name, "S011-EX09-data-audit"))
        def fetch(dataset, symbol, start, frequency):
            return context.data.fetch(DataRequest(dataset, symbol, start, END, None, frequency, options))
        def identity(result):
            return {"content_sha256": result.identity.content_sha256,
                    "metadata": dict(result.identity.metadata), "rows": len(result.dataframe)}

        w = fetch(Dataset.INDEX_CONSTITUENT_WEIGHT, "931994.CSI", "2024-09-01", "snapshot")
        cal = fetch(Dataset.TRADING_CALENDAR, "SSE", START, "daily")
        if not w.ready or not cal.ready:
            raise ValueError("weights or calendar unavailable")
        identities["weights"], identities["calendar"] = identity(w), identity(cal)
        weights = w.dataframe.copy()
        weights["Date"] = pd.to_datetime(weights["Date"])
        if weights.duplicated(["Date", "ConstituentSymbol"]).any() or weights["Weight"].le(0).any():
            raise ValueError("invalid weight snapshot")
        totals = weights.groupby("Date")["Weight"].sum()
        if not np.isfinite(weights["Weight"]).all() or not totals.between(99,101).all():
            raise ValueError("snapshot weight totals differ from 100 percent")
        save("weights.csv.gz", weights)
        save("calendar.csv.gz", cal.dataframe)
        symbols = sorted(weights["ConstituentSymbol"].unique())
        for i, symbol in enumerate(symbols, 1):
            result = fetch(Dataset.SELL_SIDE_FORECAST, symbol, START, "report_event")
            row = {"Symbol": symbol, "Status": result.status.value,
                   "ErrorCode": result.error.code if result.error else "", "Rows": 0, "EpsRows": 0}
            if result.ready:
                frame = normalize_reports(result.dataframe)
                if not frame["Symbol"].eq(symbol).all():
                    raise ValueError("forecast symbol mismatch")
                forecasts.append(frame)
                identities[symbol] = identity(result)
                row.update(Rows=len(frame), EpsRows=int(frame[EPS].notna().sum()))
            states.append(row)
            if i % 20 == 0 or i == len(symbols):
                print(f"EX09 forecast sources: {i}/{len(symbols)}", flush=True)
        statuses = pd.DataFrame(states)
        save("source_status.csv", statuses)
        if not forecasts:
            raise ValueError("no forecast records; source status preserved")
        reports = pd.concat(forecasts, ignore_index=True)
        save("forecast_snapshot.csv.gz", reports)
        empty_symbols = set(statuses.loc[statuses.Status.eq("EMPTY"), "Symbol"])
        failed_symbols = set(statuses.loc[~statuses.Status.isin(["READY", "EMPTY"]), "Symbol"])
        snaps=[]
        for day, group in weights.groupby("Date"):
            total=float(group.Weight.sum())
            snaps.append({"SnapshotDate": day, "Members":len(group), "TotalWeight":total,
                          "UnionNeverReadyWeightPct":float(group.loc[group.ConstituentSymbol.isin(empty_symbols),"Weight"].sum()/total*100),
                          "QueryFailedWeightPct":float(group.loc[group.ConstituentSymbol.isin(failed_symbols),"Weight"].sum()/total*100),
                          "PublicationTimeVerified":False})
        save("snapshot_source_coverage.csv", pd.DataFrame(snaps))

        calendar=cal.dataframe
        sessions=pd.DatetimeIndex(pd.to_datetime(calendar.loc[calendar.IsOpen.eq(1),"Date"]))
        rows=[]
        for day in sessions:
            basket=select_snapshot(weights, day)
            for year_offset in (0,1):
                period=f"{day.year+year_offset}Q4"
                record={"Date":day, "YearOffset":year_offset, "ForecastPeriod":period,
                        "LeftTruncated": bool(day < pd.Timestamp(START)+pd.Timedelta(days=AGE)),
                        "Status":"NO_SNAPSHOT" if basket.empty else "CONDITIONAL_ON_35_DAY_LAG"}
                if not basket.empty:
                    active=active_institutions(reports,day,period)
                    active=active.loc[active.Symbol.isin(basket.ConstituentSymbol)]
                    record.update(SnapshotDate=basket.Date.iloc[0], **coverage_row(basket,active))
                rows.append(record)
        daily=pd.DataFrame(rows)
        save("daily_conditional_coverage.csv",daily)
        duplicates=reports.groupby(["Date",*KEY],dropna=False)[EPS].agg(
            Rows="size",EpsValues="nunique",MissingEps=lambda x: bool(x.isna().any())).reset_index()
        save("same_institution_day_duplicates.csv",duplicates.loc[duplicates.Rows.gt(1)])
        periods=reports.groupby("ForecastPeriod",dropna=False).agg(Rows=(EPS,"size"),EpsRows=(EPS,"count")).reset_index()
        save("forecast_period_counts.csv",periods)
        delay=(reports.VendorCreatedAt.dt.normalize()-reports.Date).dt.days
        updates=reports.assign(UpdateDelayDays=delay).groupby(delay).size().rename("Rows").reset_index(name="Rows")
        updates.columns=["UpdateDelayDays","Rows"]
        save("vendor_update_delays.csv",updates)
        stable=daily.loc[daily.Status.eq("CONDITIONAL_ON_35_DAY_LAG") & ~daily.LeftTruncated]
        coverage_summary=[]
        for offset, group in stable.groupby("YearOffset"):
            coverage_summary.append({"year_offset":int(offset),"days":len(group),
                "one_institution_weight_pct":{str(k):float(v) for k,v in group.WeightWithOneInstitutionPct.quantile([0,.5,1]).items()},
                "two_institution_weight_pct":{str(k):float(v) for k,v in group.WeightWithTwoInstitutionsPct.quantile([0,.5,1]).items()}})
        if PREDECESSOR not in context.predecessors:
            raise ValueError("verified predecessor missing")
        previous=json.loads((Path(__file__).resolve().parent.parent/PREDECESSOR/"artifacts"/"summary.json").read_text(encoding="utf-8"))
        status="DATA_ACCESS_INCOMPLETE" if failed_symbols else "DATA_GATE_BLOCKED"
        summary={"decision":status,"audit_execution_complete":True,"symbol":"159326.SZ",
            "union_symbols":len(symbols),"ready_symbols":int(statuses.Status.eq("READY").sum()),
            "empty_symbols":len(empty_symbols),"failed_symbols":len(failed_symbols),
            "snapshot_count":len(totals),"weight_rows":len(weights),"forecast_rows":len(reports),
            "unique_reports":len(reports.drop_duplicates(REPORT_KEY)),"eps_rows":int(reports[EPS].notna().sum()),
            "records_available_after_cutoff":int(reports.AvailableDate.gt(pd.Timestamp(END)).sum()),
            "update_delay_days":{str(k):float(v) for k,v in delay.quantile([0,.5,.95,1]).items()},
            "same_day_institution_period_multirow_groups":int(duplicates.Rows.gt(1).sum()),
            "same_day_institution_period_conflict_groups":int(duplicates.EpsValues.gt(1).sum()),
            "missing_institution_rows":int((reports.Institution.isna() | reports.Institution.eq("")).sum()),
            "invalid_annual_period_rows":int((~reports.ForecastPeriod.str.fullmatch(r"\d{4}Q4",na=False)).sum()),
            "conditional_coverage_after_warmup":coverage_summary,
            "weight_identity_matches_ex03":identities["weights"]["content_sha256"] == previous["source_identities"]["weights"]["content_sha256"],
            "historical_weight_publication_verified":False,"historical_forecast_vintages_verified":False,
            "blockers":["MONTHLY_WEIGHT_PUBLICATION_UNKNOWN","CURRENT_VENDOR_SNAPSHOT_NOT_HISTORICAL_VINTAGE"],
            "return_labels_read":False,"account_replay_performed":False,"effective_components_added":0,
            "forecast_age_days":AGE,"weight_lag_days_assumed":LAG,
            "source_identities":identities}
        context.workspace.path("summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False,default=str)+"\n",encoding="utf-8")
        artifacts.append(context.workspace.register_artifact("summary.json","S011-EX09-summary"))
        return ExperimentResult(outcome=ExperimentOutcome.INCONCLUSIVE,
            facts={"decision":status,"return_labels_read":False,"effective_components_added":0},
            diagnostics={"forecast_rows":len(reports),"failed_symbols":len(failed_symbols)},artifacts=tuple(artifacts))
