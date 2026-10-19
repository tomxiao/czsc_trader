"""EX039 fixed ETF input preparation; no fitting, relabeling or account replay.

Run ``precheck`` offline first. ``prepare`` requires the published design lock
and uses the batch's default public DFLS provider binding exactly once.
"""

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import date, datetime, timezone
from enum import Enum
from hashlib import sha256
import json
from pathlib import Path
import sys
from uuid import UUID

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
OUT = EX / "others"
DEFAULT_COLUMNS = {
    "date": "Date", "available": "AvailableDate",
    "share": "TotalShare", "close": "Close",
}
FEATURE_COLUMNS = ["etf_z", "etf_z_late", "etf_price_ret1", "etf_price_ret5"]


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def plain(value):
    """Serialize public dataclasses without deepcopying their mapping proxies."""
    if is_dataclass(value):
        return {field.name: plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, (UUID, Path)):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    return value


def write(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(plain(value), ensure_ascii=False, indent=2,
                                allow_nan=False) + "\n")


def csv_once(frame, path):
    with path.open("x", encoding="utf-8", newline="") as handle:
        frame.to_csv(handle, index=False, lineterminator="\n")


def source(key):
    from czsc_trader.research_tools import EvidenceRef

    result = read(ROOT / "research/S014/experiments/EX032_20261018/others/result.json")
    value = result["evidence"][key]
    ref = EvidenceRef.from_dict(value)
    path = ref.resolve(ROOT)
    if digest(path) != ref.sha256:
        raise ValueError(f"EX032 source hash mismatch: {key}")
    return path, value


def check_published_lock():
    from czsc_trader.research_tools import EvidenceRef

    lock = read(EX / "protocols/published_design.json")
    if not lock:
        raise ValueError("Published design lock is empty")
    for relative, value in lock.items():
        path = ROOT / relative
        ref = EvidenceRef.from_dict(value)
        if ref.resolve(ROOT).read_bytes() != path.read_bytes():
            raise ValueError(f"Published design mismatch: {relative}")


def event_dates(events, key):
    values = events.get(key, [])
    if not isinstance(values, list):
        raise TypeError(f"{key} must be a list of ISO effective dates")
    dates = pd.DatetimeIndex(pd.to_datetime(values, errors="raise")).normalize()
    if dates.hasnans:
        raise ValueError(f"Invalid event date: {key}")
    return dates


def crosses(start, end, effective):
    if pd.isna(start) or pd.isna(end):
        return False
    return bool(((effective > start) & (effective <= end)).any())


def local_times(values):
    parsed = pd.to_datetime(values, errors="raise")
    if parsed.dt.tz is not None:
        parsed = parsed.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    return parsed


def combine_sources(shares, prices, calendar, share_metadata, price_metadata):
    """Join two explicit public datasets; never infer prices from fund size/NAV."""
    dates = pd.to_datetime(calendar.date, errors="raise").dt.normalize()
    next_session = dict(zip(dates.iloc[:-1], dates.iloc[1:], strict=True))
    assumptions = {}

    def one(frame, names, label, metadata):
        required = {"Date", *names}
        if not required.issubset(frame.columns):
            raise ValueError(f"{label} public schema missing {sorted(required - set(frame.columns))}")
        out = frame[["Date", *names]].copy()
        out["Date"] = local_times(out.Date).dt.normalize()
        if out.Date.duplicated().any() or out.Date.isna().any():
            raise ValueError(f"{label} dates duplicate or missing")
        if "AvailableDate" in frame:
            out[label + "AvailableDate"] = local_times(frame.AvailableDate)
            assumptions[label] = "Retained public AvailableDate column"
        else:
            out[label + "AvailableDate"] = out.Date.map(next_session) + pd.Timedelta(hours=8, minutes=30)
            assumptions[label] = {
                "rule": "Research assumption: next pinned SSE session 08:30 Asia/Shanghai; last source date without a pinned successor remains NaT",
                "public_metadata": dict(metadata),
                "strict_historical_arrival_certified": False,
            }
        return out

    left = one(shares, ["TotalShare"], "Share", share_metadata)
    right = one(prices, ["Close"], "Price", price_metadata)
    joined = left.merge(right, on="Date", how="outer", validate="one_to_one").sort_values("Date")
    # Keep the two availability clocks separate; source gaps stay missing.
    return joined, assumptions


def build_features(frame, calendar, source_frame, events, columns=None):
    """Map exact calendar sessions, preserving missing values and late availability."""
    columns = DEFAULT_COLUMNS if columns is None else columns
    if set(columns) != set(DEFAULT_COLUMNS):
        raise ValueError("etf_columns must explicitly map date/available/share/close")
    missing_columns = sorted(set(columns.values()) - set(source_frame.columns))
    if missing_columns:
        raise ValueError(f"ETF public dataframe schema mismatch: {missing_columns}")
    if calendar.signal.duplicated().any() or calendar.date.duplicated().any():
        raise ValueError("Duplicate pinned calendar signal/date")
    cal = calendar.sort_values("signal").copy()
    cal["date"] = pd.to_datetime(cal.date, errors="raise").dt.normalize()
    if not cal.date.is_monotonic_increasing:
        raise ValueError("Calendar dates must increase in signal order")
    if not np.array_equal(cal.signal.to_numpy(), np.arange(len(cal))):
        raise ValueError("Pinned calendar must have consecutive signal indices from zero")
    f = frame[["signal", "date", "year", "A"]].copy()
    f["date"] = pd.to_datetime(f.date, errors="raise").dt.normalize()
    if f.signal.duplicated().any() or not f.signal.equals(cal.signal):
        raise ValueError("EX032 inputs and calendar signal identities differ")
    if not f.date.equals(cal.date):
        raise ValueError("EX032 inputs and pinned calendar dates differ")
    raw = source_frame.copy()
    raw["_date"] = local_times(raw[columns["date"]]).dt.normalize()
    raw["_available"] = local_times(raw[columns["available"]])
    raw["_price_available"] = (
        local_times(raw["PriceAvailableDate"]) if "PriceAvailableDate" in raw
        else raw["_available"]
    )
    if raw._date.isna().any() or raw._date.duplicated().any():
        raise ValueError("ETF source date missing or duplicated")
    for key in ("share", "close"):
        raw["_" + key] = pd.to_numeric(raw[columns[key]], errors="raise")
    raw = raw.set_index("_date").sort_index()
    dates = pd.DatetimeIndex(cal.date)
    coverage = {
        "expected_sessions": len(dates), "observed_rows": len(raw),
        "missing_sessions": [d.date().isoformat() for d in dates.difference(raw.index)],
        "unexpected_dates": [d.date().isoformat() for d in raw.index.difference(dates)],
        "nonpositive_or_missing_share_dates": [
            d.date().isoformat() for d in raw.index[~np.isfinite(raw._share) | raw._share.le(0)]
        ],
        "nonpositive_or_missing_close_dates": [
            d.date().isoformat() for d in raw.index[~np.isfinite(raw._close) | raw._close.le(0)]
        ],
        "missing_availability_dates": [d.date().isoformat() for d in raw.index[raw._available.isna()]],
        "missing_price_availability_dates": [d.date().isoformat() for d in raw.index[raw._price_available.isna()]],
        "missing_share_sessions": [d.date().isoformat() for d in dates[raw._share.reindex(dates).isna()]],
        "missing_price_sessions": [d.date().isoformat() for d in dates[raw._close.reindex(dates).isna()]],
    }
    coverage["full_calendar_covered"] = not any(coverage[key] for key in (
        "missing_sessions", "unexpected_dates", "missing_share_sessions", "missing_price_sessions",
    ))
    split = event_dates(events, "share_conversion_dates")
    dividend = event_dates(events, "cash_dividend_ex_dates")
    for name, lag in (("p", 2), ("q", 3), ("r", 4), ("p5", 7)):
        f["etf_" + name] = cal.date.shift(lag).to_numpy()
        for field in ("share", "close", "available", "price_available"):
            f[f"_{name}_{field}"] = f["etf_" + name].map(raw["_" + field])
    cutoff = f.date + pd.Timedelta(hours=15)

    def usable(name, field):
        value = f[f"_{name}_{field}"]
        clock = "price_available" if field == "close" else "available"
        return np.isfinite(value) & value.gt(0) & f[f"_{name}_{clock}"].le(cutoff)

    split_main = [crosses(q, p, split) for q, p in zip(f.etf_q, f.etf_p, strict=True)]
    split_late = [crosses(r, q, split) for r, q in zip(f.etf_r, f.etf_q, strict=True)]
    price1_event = [crosses(q, p, split.union(dividend)) for q, p in zip(f.etf_q, f.etf_p, strict=True)]
    price5_event = [crosses(q, p, split.union(dividend)) for q, p in zip(f.etf_p5, f.etf_p, strict=True)]
    f["etf_known_share_event"] = np.array(split_main) | np.array(split_late)
    f["etf_known_price_event"] = np.array(price1_event) | np.array(price5_event)
    for name, left, right, blocked in (
        ("", "p", "q", split_main), ("_late", "q", "r", split_late),
    ):
        valid = usable(left, "share") & usable(right, "share") & ~np.array(blocked)
        change = (f[f"_{left}_share"] / f[f"_{right}_share"] - 1).where(valid)
        f["etf_share_change" + name] = change
        f["etf_z" + name] = change.lt(0).astype(float).where(change.notna())
    for horizon, right, blocked in ((1, "q", price1_event), (5, "p5", price5_event)):
        valid = usable("p", "close") & usable(right, "close") & ~np.array(blocked)
        f[f"etf_price_ret{horizon}"] = np.log(f._p_close / f[f"_{right}_close"]).where(valid)
    f["etf_ready"] = np.isfinite(f[FEATURE_COLUMNS].to_numpy(float)).all(axis=1)
    # Availability columns are retained as auditable actual mapping inputs.
    f = f.rename(columns={f"_{name}_available": f"etf_available_{name}" for name in ("p", "q", "r", "p5")})
    f = f.rename(columns={f"_{name}_price_available": f"etf_price_available_{name}" for name in ("p", "q", "r", "p5")})
    f = f.drop(columns=[column for column in f if column.startswith("_")])
    return f, coverage


def precheck():
    dates = pd.bdate_range("2020-01-02", periods=14)
    calendar = pd.DataFrame({"signal": np.arange(14), "date": dates})
    frame = calendar.assign(year=2020, A=True)
    raw = pd.DataFrame({"Date": dates, "AvailableDate": dates + pd.Timedelta(days=1),
                        "TotalShare": 100 - np.arange(14), "Close": 10 + np.arange(14)})
    out, coverage = build_features(frame, calendar, raw, {})
    assert out.loc[7, "etf_z"] == 1 and out.loc[7, "etf_z_late"] == 1
    np.testing.assert_allclose(out.loc[7, "etf_price_ret5"], np.log(15 / 10))
    assert not out.loc[:6, "etf_ready"].any() and coverage["full_calendar_covered"]
    zero = raw.copy()
    zero["TotalShare"] = 100
    assert build_features(frame, calendar, zero, {})[0].loc[7, "etf_z"] == 0
    missing = raw.drop(index=5)
    result, covered = build_features(frame, calendar, missing, {})
    assert pd.isna(result.loc[7, "etf_z"]) and len(covered["missing_sessions"]) == 1
    delayed = raw.copy()
    delayed.loc[5, "AvailableDate"] = dates[8]
    assert pd.isna(build_features(frame, calendar, delayed, {})[0].loc[7, "etf_z"])
    events = {"cash_dividend_ex_dates": [str(dates[5].date())]}
    dividend_out = build_features(frame, calendar, raw, events)[0]
    assert pd.isna(dividend_out.loc[7, "etf_price_ret1"]) and dividend_out.loc[7, "etf_z"] == 1
    events = {"share_conversion_dates": [str(dates[5].date())]}
    assert pd.isna(build_features(frame, calendar, raw, events)[0].loc[7, "etf_z"])
    duplicate = pd.concat([raw, raw.iloc[[0]]], ignore_index=True)
    try:
        build_features(frame, calendar, duplicate, {})
    except ValueError:
        pass
    else:
        raise AssertionError("Duplicate source dates must fail")
    joined, assumptions = combine_sources(raw[["Date", "TotalShare"]], raw[["Date", "Close"]], calendar, {}, {})
    assert joined.loc[0, "ShareAvailableDate"] == dates[1] + pd.Timedelta(hours=8, minutes=30)
    assert pd.isna(joined.iloc[-1].ShareAvailableDate) and assumptions["Share"]["strict_historical_arrival_certified"] is False
    joined["AvailableDate"] = joined.ShareAvailableDate
    joined.loc[5, "PriceAvailableDate"] = dates[8]
    separated = build_features(frame, calendar, joined, {})[0]
    assert separated.loc[7, "etf_z"] == 1 and pd.isna(separated.loc[7, "etf_price_ret1"])
    return {"status": "PASS", "checks": 10, "network_calls": 0, "fits": 0, "accounts": 0}


def prepare():
    from czsc_trader.application import RepositoryContext, create_research_context
    from czsc_trader.research_tools import ResearchBatchRef
    from dataflows import DataRequest, Dataset, PreparePolicy

    check_published_lock()
    plan = read(EX / "protocols/design.json")
    OUT.mkdir(exist_ok=True)
    if (OUT / "etf_preparation_request.json").exists():
        raise RuntimeError("ETF preparation attempt already reserved; no automatic retry")
    refs = {}
    path, refs["inputs"] = source("others/inputs.csv")
    frame = pd.read_csv(path)
    path, refs["calendar"] = source("others/calendar.csv")
    calendar = pd.read_csv(path)
    path, refs["labels"] = source("others/labels.csv")
    labels = pd.read_csv(path)
    h3 = labels[labels.horizon.eq(3)].set_index("signal")
    np.testing.assert_allclose(frame.Y3, frame.signal.map(h3.net_return), rtol=0, atol=1e-15, equal_nan=True)
    np.testing.assert_allclose(frame.maturity, frame.signal.map(h3.maturity), rtol=0, atol=0, equal_nan=True)
    event_path = OUT / "etf_events.json"
    events = read(event_path) if event_path.exists() else {}
    event_identity = {"path": str(event_path.relative_to(ROOT)).replace("\\", "/"),
                      "present": event_path.exists(),
                      "sha256": digest(event_path) if event_path.exists() else None,
                      "status": events.get("status", "UNKNOWN_NOT_COLLECTED"),
                      "dividend_coverage_certified": events.get("dividend_coverage_certified", False),
                      "share_adjustment_coverage_certified": events.get("share_adjustment_coverage_certified", False)}
    requests = (
        DataRequest(Dataset.ETF_SHARE_SIZE, "510300.SH", "2020-01-01", "2026-10-15", "2026-10-15"),
        DataRequest(Dataset.ETF_UNADJUSTED_DAILY, "510300.SH", "2020-01-01", "2026-10-15", "2026-10-15"),
    )
    write(OUT / "etf_preparation_request.json", {"requests": requests, "policy": PreparePolicy.REUSE,
          "reserved_utc": datetime.now(timezone.utc), "source_evidence": refs,
          "event_identity": event_identity, "automatic_retry": False})
    ctx = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef("S014"))
    prepared = ctx.data.prepare(requests, policy=PreparePolicy.REUSE)
    write(OUT / "etf_preparation.json", prepared)
    if not prepared.ready:
        raise RuntimeError(f"ETF public prepare returned {prepared.status}")
    fetched = {}
    for label, request in zip(("share", "price"), requests, strict=True):
        result = ctx.data.fetch(request, prepared=prepared.reference)
        write(OUT / f"etf_{label}_fetch.json", {"status": result.status, "identity": result.identity,
              "error": result.error, "warnings": result.warnings, "prepared": result.prepared})
        if not result.ready:
            raise RuntimeError(f"ETF public {label} fetch returned {result.status}")
        if result.identity.symbol != request.symbol or result.identity.dataset != request.dataset:
            raise ValueError(f"ETF public {label} fetch returned an inconsistent identity")
        csv_once(result.dataframe, OUT / f"etf_{label}_source.csv")
        fetched[label] = result
    combined, assumptions = combine_sources(
        fetched["share"].dataframe, fetched["price"].dataframe, calendar,
        fetched["share"].identity.metadata, fetched["price"].identity.metadata,
    )
    combined["AvailableDate"] = combined.ShareAvailableDate
    csv_once(combined, OUT / "etf_combined_source.csv")
    columns = plan.get("etf_columns", DEFAULT_COLUMNS)
    features, coverage = build_features(frame, calendar, combined, events, columns)
    csv_once(features, OUT / "etf_features.csv")
    write(OUT / "etf_features.json", {
        "status": "READY_CONDITIONAL_RAW_PROXY", "requests": requests,
        "prepared": prepared.reference,
        "source_identities": {label: value.identity for label, value in fetched.items()},
        "source_dataframe_columns": {label: list(value.dataframe.columns) for label, value in fetched.items()},
        "column_mapping": columns, "availability_assumptions": assumptions,
        "source_csv_sha256": {label: digest(OUT / f"etf_{label}_source.csv") for label in fetched},
        "combined_source_csv_sha256": digest(OUT / "etf_combined_source.csv"),
        "features_csv_sha256": digest(OUT / "etf_features.csv"),
        "source_evidence": refs, "coverage": coverage, "event_identity": event_identity,
        "event_content": events, "feature_columns": FEATURE_COLUMNS,
        "rows": len(features), "feature_ready_rows": int(features.etf_ready.sum()),
        "parent_training_rule": "Only inherited original A opportunities; actual exit maturity date strictly before annual Jan1; enforced by model script, not this preparation.",
        "interpretation": "RAW_SHARE_CHANGE_CONDITIONAL; historical share-unit basis, real arrival timestamps and revisions not fully certified. Do not call this certified net redemption or strict PIT. Unknown event coverage retains conditional raw price controls; confirmed effective events invalidate only crossing windows.",
        "fits": 0, "new_return_labels": 0, "new_accounts": 0,
        "prepare_invocations": 1, "fetch_invocations": 2,
        "transport_http_calls": "Not exposed by the public prepare/fetch result; do not equate prepare invocation with HTTP count.",
    })
    return {"status": "READY_CONDITIONAL_RAW_PROXY", "rows": len(features),
            "feature_ready_rows": int(features.etf_ready.sum())}


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"precheck", "prepare"}:
        raise SystemExit("Usage: prepare_etf.py precheck|prepare")
    print(json.dumps(plain({"precheck": precheck, "prepare": prepare}[sys.argv[1]]()),
                     ensure_ascii=False, allow_nan=False))
