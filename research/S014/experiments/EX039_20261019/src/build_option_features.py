"""EX039 fixed, offline option-contract-count research features; no fitting."""
from __future__ import annotations

import argparse
import gzip
import json
import re
import socket
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
OUT = EX / "others"
CONTROL_COLUMNS = ["ma_return", "ma_rv20", "ma_volume_ratio20", "option_log_oi",
                   "option_log_volume", "put_share_q", "days_to_expiry"]
PUBLIC_ALIASES = {"ma_return": "opt_ret1", "ma_rv20": "opt_rv20",
                  "ma_volume_ratio20": "opt_vol_ratio", "option_log_oi": "opt_log_oi",
                  "option_log_volume": "opt_log_volume", "put_share_q": "opt_share_Q",
                  "days_to_expiry": "opt_dte", "delta_put_share_matched": "opt_delta_put"}
OPTION_CODE = re.compile(r"^MA(?P<month>\d{3,4})(?P<cp>[CP])(?P<strike>\d+(?:\.\d+)?)\.ZCE$")


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, obj):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(obj, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def offline():
    def blocked(*args, **kwargs):
        raise RuntimeError("EX039 option feature builder forbids network")
    socket.socket.connect = blocked
    socket.create_connection = blocked


def date(value):
    if pd.isna(value) or str(value).strip() in {"", "None", "nan"}:
        raise ValueError("missing date")
    return pd.Timestamp(str(value)).normalize()


def truth(value):
    return value is True or str(value).lower() == "true" or str(value) == "1"


def resolve_raw(value):
    path = Path(value)
    if path.is_absolute():
        raise ValueError("raw response_path must be repository/experiment relative")
    candidates = [ROOT / path, EX / path]
    existing = [p.resolve() for p in candidates if p.is_file()]
    if len(set(existing)) != 1:
        raise ValueError(f"ambiguous or missing raw response path: {value}")
    result = existing[0]
    result.relative_to(EX.resolve() / "others" / "raw")
    return result


def deduplicate(frame, keys):
    if frame.empty:
        return frame
    unique = frame.drop_duplicates().copy()
    if unique.duplicated(keys).any():
        raise ValueError(f"conflicting source rows for {keys}")
    return unique.reset_index(drop=True)


def select_complete_daily(candidates, required_dates):
    """Select complete leaf coverage; never merge a truncated/missing-date parent."""
    complete, rejected = [], []
    for source_id, params, frame in candidates:
        lower = date(params.get("trade_date", params.get("start_date")))
        upper = date(params.get("trade_date", params.get("end_date")))
        expected = {d for d in required_dates if lower <= d <= upper}
        observed = set(frame.trade_date.map(date)) if "trade_date" in frame else set()
        if not expected or len(frame) >= 15000 or not expected <= observed:
            rejected.append({"id": source_id, "status": "EXCLUDED_INCOMPLETE_PARENT_OR_LEAF",
                             "rows": len(frame), "missing_dates": [str(d.date()) for d in sorted(expected-observed)]})
            continue
        complete.append((source_id, expected, frame))
    # Per required date, the narrowest complete request is the final leaf.
    chosen = {}
    for source_id, expected, frame in sorted(complete, key=lambda x: (len(x[1]), x[0])):
        for d in sorted(expected):
            if d not in chosen:
                chosen[d] = (source_id, frame.loc[frame.trade_date.map(date).eq(d)])
    if not chosen:
        raise ValueError("no complete final option daily source segments")
    return pd.concat([chosen[d][1] for d in sorted(chosen)], ignore_index=True), rejected, {
        str(d.date()): chosen[d][0] for d in sorted(chosen)}


def raw_tables(rawrefs_path):
    """Only EX039 project-account standard Tushare bodies are accepted."""
    from czsc_trader.research_tools import EvidenceRef
    published = read(rawrefs_path)
    published = published.get("evidence", published)
    if not isinstance(published, dict):
        raise TypeError("rawrefs must map repository-relative file paths to EvidenceRef")
    tables = {"opt_basic": [], "opt_daily": []}
    sources, failures = [], []
    inventory = read(OUT / "collection_inventory.json")
    required_dates = {date(d) for d in inventory["required_dates"]}
    for request_path in sorted((OUT / "raw" / "requests").glob("*.json")):
        request = read(request_path)
        api = request.get("api_name")
        if api not in tables:
            continue
        result_path = OUT / "raw" / "results" / request_path.name
        if not result_path.is_file():
            raise ValueError(f"missing final result receipt: {result_path.name}")
        result = read(result_path)
        paths = [request_path, result_path]
        response_path = None
        response_candidate = ROOT / request["response_path"]
        if response_candidate.is_file():
            response_path = resolve_raw(request["response_path"])
            paths.append(response_path)
        for path in paths:
            rel = path.relative_to(ROOT).as_posix()
            if rel not in published:
                raise ValueError(f"unpublished raw source: {rel}")
            evidence = EvidenceRef.from_dict(published[rel])
            if digest(evidence.resolve(ROOT)) != evidence.sha256 or digest(path) != evidence.sha256:
                raise ValueError(f"raw evidence mismatch: {rel}")
        source = {"request_path": request_path.relative_to(ROOT).as_posix(),
                  "request_sha256": digest(request_path),
                  "result_path": result_path.relative_to(ROOT).as_posix(),
                  "result_sha256": digest(result_path), "result_evidence": published[result_path.relative_to(ROOT).as_posix()],
                  "response_path": response_path.relative_to(ROOT).as_posix() if response_path else None,
                  "response_sha256": digest(response_path) if response_path else None, "api_name": api,
                  "request": request, "request_evidence": published[request_path.relative_to(ROOT).as_posix()],
                  "response_evidence": published[response_path.relative_to(ROOT).as_posix()] if response_path else None,
                  "result": result}
        sources.append(source)
        if result.get("id") != request.get("id") or result.get("api_name") != api:
            raise ValueError("request/result identity conflict")
        if result.get("status") != "SUCCESS" or result.get("http_status") != 200 or result.get("vendor_code") != 0:
            failures.append({"id": request["id"], "code": result.get("vendor_code"), "status": "SOURCE_ERROR"})
            continue
        if response_path is None or result.get("response_sha256") != digest(response_path):
            raise ValueError("successful receipt response missing/hash conflict")
        body = json.loads(gzip.decompress(response_path.read_bytes()))
        if body.get("code") != 0:
            failures.append({"id": request["id"], "code": body.get("code"), "status": "SOURCE_ERROR"})
            continue
        data = body.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("fields"), list) or not isinstance(data.get("items"), list):
            raise ValueError("source lacks standard data.fields/items")
        frame = pd.DataFrame(data["items"], columns=data["fields"])
        if request.get("superseded") or request.get("split_required"):
            continue
        if result.get("rows") != len(frame):
            raise ValueError("receipt/source row count mismatch")
        if api == "opt_basic" and len(frame) >= int(request["params"].get("limit", 12000)):
            raise ValueError("metadata reached explicit request limit; complete K universe unresolved")
        if api == "opt_daily":
            # Completeness uses the entire exchange response, before MA filtering.
            tables[api].append((request["id"], request["params"], frame))
            continue
        if frame.empty:
            continue
        if "ts_code" not in frame:
            raise ValueError("source missing ts_code")
        frame = frame.loc[frame.ts_code.astype(str).str.match(OPTION_CODE)].copy()
        tables[api].append(frame)
    if not all(tables.values()):
        raise ValueError("no successful metadata/daily tables")
    meta = pd.concat(tables["opt_basic"], ignore_index=True)
    daily, rejected, date_sources = select_complete_daily(tables["opt_daily"], required_dates)
    failures.extend(rejected)
    failures.append({"status": "FINAL_DAILY_COVERAGE", "date_sources": date_sources,
                     "missing_required_dates": [str(d.date()) for d in sorted(required_dates-{date(d) for d in date_sources})]})
    required = {"ts_code", "trade_date", "oi", "vol", "close"}
    if not required <= set(daily):
        raise ValueError(f"daily missing fields: {required-set(daily)}")
    daily = daily.loc[daily.ts_code.astype(str).str.match(OPTION_CODE)].copy()
    # Repeated standard requests must agree, including metadata revisions.
    meta = deduplicate(meta, ["ts_code"])
    daily = deduplicate(daily, ["ts_code", "trade_date"])
    return normalize_metadata(meta), normalize_daily(daily), sources, failures


def normalize_metadata(meta):
    required = {"ts_code", "opt_code", "call_put", "exercise_price", "opt_multiplier",
                "list_date", "delist_date", "maturity_date"}
    if not required <= set(meta):
        raise ValueError(f"metadata missing fields {required-set(meta)}")
    meta = meta.copy()
    for column in ["list_date", "delist_date", "maturity_date"]:
        meta[column] = meta[column].map(date)
    meta["exercise_price"] = pd.to_numeric(meta.exercise_price, errors="coerce")
    meta["opt_multiplier"] = pd.to_numeric(meta.opt_multiplier, errors="coerce")
    errors = []
    for row in meta.itertuples():
        match = OPTION_CODE.fullmatch(str(row.ts_code))
        reason = ""
        if not match or not re.fullmatch(r"OPMA\d{4}\.ZCE", str(row.opt_code)):
            reason = "IDENTITY_FORMAT"
        elif match["cp"] != row.call_put or str(row.opt_code)[4:8][-3:] != match["month"][-3:]:
            reason = "CODE_IDENTITY_CONFLICT"
        elif not np.isfinite(row.exercise_price) or not np.isclose(float(match["strike"]), row.exercise_price, rtol=0, atol=1e-9):
            reason = "STRIKE_CODE_CONFLICT"
        elif not np.isfinite(row.opt_multiplier) or row.opt_multiplier <= 0:
            reason = "MULTIPLIER_INVALID"
        elif row.list_date > row.maturity_date or row.delist_date < row.list_date:
            reason = "LIFECYCLE_CONFLICT"
        # Do not infer the decade from the one-digit native year.
        elif abs(int(str(row.opt_code)[4:6]) + 2000 - row.maturity_date.year) > 1:
            reason = "DECADE_LIFECYCLE_CONFLICT"
        elif any(truth(getattr(row, field, False)) for field in ["adjusted", "is_adjusted", "adjustment_event"]):
            reason = "KNOWN_ADJUSTMENT"
        errors.append(reason)
    meta["identity_error"] = errors
    return meta


def normalize_daily(frame):
    frame = frame.copy()
    frame["Date"] = frame.trade_date.map(date)
    for column in ["oi", "vol", "close"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.set_index(["ts_code", "Date"]).sort_index()


def fetch_futures():
    from dataflows import DataRequest, Dataset, PreparedDataRef, ProviderConfig
    from czsc_trader.application import RepositoryContext, create_research_context
    from czsc_trader.research_tools import ResearchBatchRef
    acceptance_path = ROOT / "research/S014/materials/20261018_methanol_completion/acceptance.json"
    acceptance = read(acceptance_path)
    expected = read(ROOT / "research/S014/experiments/EX032_20261018/others/inputs.json")["data_reference"]
    if acceptance["prepared"] != expected:
        raise ValueError("EX032 and original prepared futures identity differ")
    bound = PreparedDataRef(UUID(expected["space_id"]), UUID(expected["preparation_id"]), expected["manifest_sha256"])
    ctx = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef("S014"), providers=ProviderConfig(bindings={}))
    tables, identities = {}, []
    for asset in acceptance["assets"]:
        req = DataRequest(Dataset(asset["dataset"]), asset["symbol"], asset["start"], asset["end"], asset["end"])
        fetched = ctx.data.fetch(req, prepared=bound)
        if not fetched.ready or fetched.identity.content_sha256 != asset["content_sha256"]:
            raise ValueError(f"prepared futures fetch failed: {asset['symbol']}")
        frame = fetched.dataframe.copy()
        frame["Date"] = pd.to_datetime(frame.Date).dt.normalize()
        tables[asset["symbol"]] = frame.set_index("Date").sort_index()
        identities.append({**asset, "request": {"dataset": asset["dataset"], "symbol": asset["symbol"], "start": asset["start"], "end": asset["end"]}})
    calendar = tables.pop("CZCE")
    sessions = pd.DatetimeIndex(calendar.index[calendar.IsOpen.eq(1)])
    return tables, sessions, {"prepared": expected, "assets": identities, "acceptance_path": acceptance_path.relative_to(ROOT).as_posix(), "acceptance_sha256": digest(acceptance_path)}


def futures_controls(table, p, q, sessions):
    end = sessions.get_loc(p)
    if not isinstance(end, (int, np.integer)) or end < 20:
        raise ValueError("FUTURES_WARMUP")
    dates = sessions[end-20:end+1]
    bars = table.reindex(dates)
    prices = pd.to_numeric(bars.Close, errors="coerce").to_numpy(float)
    volumes = pd.to_numeric(bars.Volume, errors="coerce").to_numpy(float)
    if not np.isfinite(prices).all() or (prices <= 0).any() or not np.isfinite(volumes).all() or (volumes < 0).any():
        raise ValueError("FUTURES_20DAY_MISSING_OR_INVALID")
    if q != dates[-2] or volumes[-1] <= 0 or volumes[-2] <= 0 or volumes[:-1].mean() <= 0:
        raise ValueError("FUTURES_PQ_OR_VOLUME_INVALID")
    returns = np.log(prices[1:] / prices[:-1])
    return {"ma_return": float(returns[-1]), "ma_rv20": float(returns.std(ddof=0)),
            "ma_volume_ratio20": float(volumes[-1] / volumes[:-1].mean())}


def one_feature(row, meta, daily, sessions, tables):
    out = {"Date": str(date(row["date"]).date()), "signal": int(row["signal"]),
           "p": str(row["p"]), "q": str(row["q"]), "contract": row["contract"],
           "option_status": "UNSET", "option_ready": False,
           "historical_adjustments_verified": False, "historical_publication_verified": False}
    try:
        t, p, q = date(row["date"]), date(row["p"]), date(row["q"])
        if p not in sessions or q not in sessions or sessions.get_loc(p)-sessions.get_loc(q) != 1 or not q < p < t:
            raise ValueError("CALENDAR_ALIGNMENT")
        p_index = sessions.get_loc(p)
        if p_index+1 >= len(sessions):
            raise ValueError("AVAILABILITY_CALENDAR_MISSING")
        available = sessions[p_index+1] + pd.Timedelta(hours=15)
        if available > t + pd.Timedelta(hours=15):
            raise ValueError("NOT_AVAILABLE_BY_DECISION")
        out["AvailableDate"] = available.isoformat()
        contract = str(row["contract"])
        universe = meta.loc[meta.opt_code.eq("OP" + contract)].copy()
        if universe.empty:
            raise ValueError("METADATA_K_MISSING")
        # Errors only contaminate contemporaneously valid contracts for this K.
        universe = universe.loc[universe.list_date.le(q) & universe.delist_date.ge(p) & universe.maturity_date.ge(p)]
        if universe.empty:
            raise ValueError("NO_SURVIVING_EXPIRY")
        if universe.identity_error.ne("").any():
            raise ValueError("METADATA_IDENTITY_OR_ADJUSTMENT_CONFLICT")
        viable = []
        for expiry in sorted(universe.maturity_date.unique()):
            known_remaining = int(((sessions > p) & (sessions <= expiry)).sum())
            if known_remaining >= 5:
                viable.append(pd.Timestamp(expiry))
        if not viable:
            raise ValueError("EXPIRY_UNDER_5_SESSIONS_OR_CALENDAR_UNVERIFIED")
        expiry = viable[0]
        universe = universe.loc[universe.maturity_date.eq(expiry)]
        # Listing age uses actually observed open sessions, never weekdays.
        age = universe.list_date.map(lambda x: int(((sessions >= x) & (sessions < q)).sum()))
        universe = universe.loc[age.ge(5)]
        pairs = []
        for strike, group in universe.groupby("exercise_price", sort=True):
            if len(group) == 2 and set(group.call_put) == {"C", "P"}:
                if group.opt_multiplier.nunique() != 1:
                    raise ValueError("PAIR_MULTIPLIER_CONFLICT")
                pair = {v.call_put: v.ts_code for v in group.itertuples()}
                pairs.append({"strike": float(strike), "C": pair["C"], "P": pair["P"]})
            elif group.call_put.duplicated().any():
                raise ValueError("AMBIGUOUS_STRIKE_PAIR")
        out["pair_count"] = len(pairs)
        if len(pairs) < 3:
            raise ValueError("UNDER_3_COMPLETE_METADATA_PAIRS")
        out["expiry"] = str(expiry.date())
        out["days_to_expiry"] = int((expiry-p).days)
        out["known_remaining_sessions"] = int(((sessions > p) & (sessions <= expiry)).sum())
        out["expiry_calendar_censored"] = bool(expiry > sessions.max())
        payload = json.dumps(pairs, sort_keys=True, separators=(",", ":"))
        out["comparison_set_sha256"] = sha256(payload.encode()).hexdigest()
        ids = [pair[cp] for pair in pairs for cp in ["C", "P"]]
        expected = pd.MultiIndex.from_product([ids, [q, p]], names=["ts_code", "Date"])
        bars = daily.reindex(expected)
        if bars.oi.isna().any() or not np.isfinite(bars.oi).all() or bars.oi.lt(0).any():
            raise ValueError("Q_CANDIDATE_PAIR_DAILY_OR_OI_MISSING_INVALID")
        if bars.vol.isna().any() or not np.isfinite(bars.vol).all() or bars.vol.lt(0).any():
            raise ValueError("OPTION_VOLUME_MISSING_INVALID")
        oi_p = np.array([float(bars.loc[(i,p), "oi"]) for i in ids])
        oi_q = np.array([float(bars.loc[(i,q), "oi"]) for i in ids])
        if oi_p.sum() <= 0 or oi_q.sum() <= 0:
            raise ValueError("ZERO_OI_DENOMINATOR")
        put_p, put_q = oi_p[1::2].sum()/oi_p.sum(), oi_q[1::2].sum()/oi_q.sum()
        pair_weights = oi_p.reshape(-1,2).sum(1)/oi_p.sum()
        out.update(delta_put_share_matched=float(put_p-put_q), put_share_q=float(put_q),
                   put_share_p=float(put_p), option_log_oi=float(np.log1p(oi_p.sum())),
                   option_log_volume=float(np.log1p(bars.vol.sum())),
                   total_oi_p=float(oi_p.sum()), total_oi_q=float(oi_q.sum()),
                   max_pair_oi_share=float(pair_weights.max()), oi_pair_hhi=float((pair_weights**2).sum()),
                   positive_oi_contracts_p=int((oi_p>0).sum()), positive_oi_contracts_q=int((oi_q>0).sum()),
                   zero_volume_records=int(bars.vol.eq(0).sum()), zero_close_records=int(bars.close.eq(0).sum()),
                   missing_close_records=int(bars.close.isna().sum()),
                   all_pairs_active=bool(bars.vol.gt(0).all()), comparison_set_json=payload)
        out.update(futures_controls(tables[contract], p, q, sessions))
        out["option_ready"], out["option_status"] = True, "READY_CONTRACT_COUNT_PROXY"
    except (ValueError, KeyError, IndexError) as exc:
        out["option_status"] = str(exc)
    return out


def build(rawrefs):
    offline()
    if (OUT / "option_features.csv").exists():
        raise FileExistsError("preserve previously built option features")
    meta, daily, sources, failures = raw_tables(rawrefs)
    futures, sessions, future_binding = fetch_futures()
    old = ROOT / "research/S014/experiments/EX032_20261018"
    inputs_path = old / "others/inputs.csv"
    old_identity = read(old / "others/inputs.json")
    if digest(inputs_path) != old_identity["input_sha256"]:
        raise ValueError("EX032 inherited input hash mismatch")
    f = pd.read_csv(inputs_path)
    f = f.loc[f.A.map(truth)].copy()
    plan = read(old / "protocols/design.json")
    records = [one_feature(row, meta, daily, sessions, futures) for row in f.to_dict("records")]
    option = pd.DataFrame(records)
    if option.signal.duplicated().any() or option.Date.duplicated().any():
        raise ValueError("duplicate A opportunity date")
    # All-family sample policy is inherited A only; no market/environment pruning.
    inherited = f.drop(columns=["date"]).copy()
    result = inherited.merge(option, on="signal", how="left", validate="one_to_one", suffixes=("", "_option"))
    for name in CONTROL_COLUMNS + ["delta_put_share_matched"]:
        if name not in result:
            result[name] = np.nan
    complete = np.isfinite(result[plan["baseline_columns"] + CONTROL_COLUMNS + ["delta_put_share_matched"]].to_numpy(float)).all(1)
    result["option_model_ready"] = result.option_ready & complete
    for source_column, alias in PUBLIC_ALIASES.items():
        result[alias] = result[source_column]
    result["opt_ready"] = result.option_model_ready
    result["opt_roll"] = result.roll.map(truth).where(result.roll.notna())
    activity = result.get("all_pairs_active", pd.Series(np.nan, index=result.index))
    result["opt_active_pair"] = activity.map(truth).where(activity.notna())
    # Keep only lower-case date in the CSV: the default local provider renames it
    # to Date, so a second Date column would violate the publication contract.
    result = result.rename(columns={"Date": "date"})
    result["option_loss3"] = np.maximum(-result.Y3, 0)
    result["option_negative3"] = result.Y3.lt(0).astype(float).where(result.Y3.notna())
    # Jan 1 is a fixed time boundary, independent of the first valid evaluation row.
    calendar = pd.read_csv(old / "others/calendar.csv")
    maturity_dates = pd.to_datetime(result.maturity.map(calendar.set_index("signal").date))
    for year in [2023, 2024, 2025, 2026]:
        result[f"mature_train_before_{year}"] = result.option_model_ready & result.Y3.notna() & result.maturity.ge(0) & maturity_dates.lt(pd.Timestamp(year,1,1))
    result.to_csv(OUT / "option_features.csv", index=False, lineterminator="\n")
    option.to_csv(OUT / "option_quality.csv", index=False, lineterminator="\n")
    write(OUT / "option_sourcehashes.json", {"implementation": {"path": Path(__file__).relative_to(ROOT).as_posix(), "sha256": digest(__file__)}, "inherited": [{"path": p.relative_to(ROOT).as_posix(), "sha256": digest(p)} for p in [inputs_path, old / "others/inputs.json", old / "others/labels.csv", old / "others/calendar.csv", old / "protocols/design.json", OUT / "collection_inventory.json"]], "raw_files": [{"path": source[key], "sha256": source[key.replace("_path", "_sha256")]} for source in sources for key in ["request_path", "response_path", "result_path"] if source[key] is not None]})
    write(OUT / "option_inputs.json", {"status": "OFFLINE_CONSTRUCTION_COMPLETE", "source_account": "EX039_PROJECT_CONFIGURATION_ONLY", "relation_to_EX038_MCP_account": "UNKNOWN_NOT_MIXED", "raw_sources": sources, "source_failures": failures, "rawrefs_path": Path(rawrefs).relative_to(ROOT).as_posix(), "rawrefs_sha256": digest(rawrefs), "futures_binding": future_binding, "inherited_inputs_sha256": digest(inputs_path), "feature_sha256": digest(OUT / "option_features.csv"), "quality_sha256": digest(OUT / "option_quality.csv"), "baseline_columns": plan["baseline_columns"], "option_control_columns": CONTROL_COLUMNS, "primary_feature": "delta_put_share_matched", "opportunities": len(result), "ready": int(result.option_model_ready.sum()), "quality_counts": result.option_status.value_counts().to_dict(), "sample_policy": "A_ONLY_ALL_FAMILY; annual training exit maturity strictly before Jan1", "expiry_control": "natural days; five-session eligibility requires observed calendar lower bound", "historical_publication_verified": False, "historical_adjustments_verified": False, "limitations": ["same-code contract-count proxy, not same moneyness/notional/IV", "current metadata cannot certify complete historical adjustment chain", "NEXT_CZCE_SESSION_CLOSE is declared lag convention, not historical first publication proof"], "new_calls": 0, "new_return_labels": 0, "new_fits": 0})


def prepare_features():
    offline()
    from dataflows import DataRequest, Dataset, EvidenceParameters, PreparePolicy
    from czsc_trader.application import RepositoryContext, create_research_context
    from czsc_trader.research_tools import ResearchBatchRef
    path = OUT / "option_features.csv"
    ctx = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef("S014"))
    request = DataRequest(Dataset.STRATEGY_FEATURE_EVIDENCE, "S014:EX039:MA_OI_MATCHED_V1", "2020-01-01", "2026-10-15", None, "daily", EvidenceParameters(ROOT, path.relative_to(ROOT).as_posix(), digest(path)))
    prepared = ctx.data.prepare((request,), policy=PreparePolicy.REUSE)
    if not prepared.ready:
        raise RuntimeError(str([(str(i.status), str(i.error)) for i in prepared.items]))
    fetched = ctx.data.fetch(request, prepared=prepared.reference)
    if not fetched.ready:
        raise RuntimeError(str(fetched.error))
    ref = prepared.reference
    write(OUT / "option_prepared.json", {"status": "READY", "reference": {"space_id": str(ref.space_id), "preparation_id": str(ref.preparation_id), "manifest_sha256": ref.manifest_sha256}, "dataset": Dataset.STRATEGY_FEATURE_EVIDENCE.value, "source_sha256": digest(path), "rows": len(fetched.dataframe), "content_sha256": fetched.identity.content_sha256, "historical_publication_verified": False, "new_calls": 0, "new_fits": 0})


def precheck():
    """Pure synthetic semantics; no real source, filesystem fixture, API or fit."""
    offline()
    sessions = pd.bdate_range("2024-01-01", periods=50)
    q, p, t = sessions[25], sessions[26], sessions[27]
    expiry = sessions[40]
    meta_rows, daily_rows = [], []
    for strike in [2300,2400,2500]:
        for cp in ["C","P"]:
            code = f"MA405{cp}{strike}.ZCE"
            meta_rows.append(dict(ts_code=code,opt_code="OPMA2405.ZCE",call_put=cp,exercise_price=strike,opt_multiplier=10,list_date=str(sessions[0].date()),delist_date=str(expiry.date()),maturity_date=str(expiry.date())))
            for d in [q,p]:
                oi = 10 if d == q or cp == "C" else 30
                daily_rows.append(dict(ts_code=code,trade_date=str(d.date()),oi=oi,vol=0,close=0))
    meta, daily = normalize_metadata(pd.DataFrame(meta_rows)), normalize_daily(pd.DataFrame(daily_rows))
    futures = pd.DataFrame({"Close": np.arange(100.,150.), "Volume": 10.},index=sessions)
    row = {"date": str(t.date()),"p": str(p.date()),"q": str(q.date()),"contract": "MA2405.ZCE","signal":27}
    result = one_feature(row,meta,daily,sessions,{"MA2405.ZCE":futures})
    assert result["option_ready"] and abs(result["delta_put_share_matched"]-.25) < 1e-12
    assert result["zero_close_records"] == 12 and not result["all_pairs_active"]
    assert abs(result["oi_pair_hhi"]-1/3) < 1e-12
    broken = daily.drop(daily.index[0])
    assert not one_feature(row,meta,broken,sessions,{"MA2405.ZCE":futures})["option_ready"]
    badmeta = meta.copy()
    badmeta.loc[0,"identity_error"] = "STRIKE_CODE_CONFLICT"
    assert not one_feature(row,badmeta,daily,sessions,{"MA2405.ZCE":futures})["option_ready"]
    zeros = daily.copy()
    zeros["oi"] = 0
    assert one_feature(row,meta,zeros,sessions,{"MA2405.ZCE":futures})["option_status"] == "ZERO_OI_DENOMINATOR"
    short = meta.loc[meta.exercise_price.ne(2500)]
    assert not one_feature(row,short,daily,sessions,{"MA2405.ZCE":futures})["option_ready"]
    fresh = meta.copy()
    fresh["list_date"] = q
    assert not one_feature(row,fresh,daily,sessions,{"MA2405.ZCE":futures})["option_ready"]
    near = meta.copy()
    near["maturity_date"] = sessions[28]
    assert not one_feature(row,near,daily,sessions,{"MA2405.ZCE":futures})["option_ready"]
    missing = futures.copy()
    missing.loc[sessions[20],"Close"] = np.nan
    assert not one_feature(row,meta,daily,sessions,{"MA2405.ZCE":missing})["option_ready"]
    assert date("20241001") == pd.Timestamp("2024-10-01")
    assert not normalize_metadata(pd.DataFrame(meta_rows)).identity_error.ne("").any()
    jan1 = pd.Timestamp("2024-01-01")
    assert not (jan1 < jan1) and pd.Timestamp("2023-12-29") < jan1
    first = pd.DataFrame({"trade_date": [str(q.date())], "ts_code": ["MA405C2300.ZCE"], "oi": [10]})
    second = pd.DataFrame({"trade_date": [str(p.date())], "ts_code": ["MA405C2300.ZCE"], "oi": [20]})
    truncated = pd.concat([first] * 15000, ignore_index=True)
    parent_params = {"start_date": str(q.date()), "end_date": str(p.date())}
    chosen, rejected, provenance = select_complete_daily([
        ("parent", parent_params, truncated),
        ("leaf_q", {"trade_date": str(q.date())}, first),
        ("leaf_p", {"trade_date": str(p.date())}, second)], {q,p})
    assert len(chosen) == 2 and len(rejected) == 1 and set(provenance.values()) == {"leaf_q","leaf_p"}
    chosen, rejected, provenance = select_complete_daily([
        ("missing_parent", parent_params, first),
        ("leaf_q", {"trade_date": str(q.date())}, first),
        ("leaf_p", {"trade_date": str(p.date())}, second)], {q,p})
    assert len(chosen) == 2 and rejected[0]["id"] == "missing_parent"
    assert abs(result["ma_return"] - np.log(126/125)) < 1e-12
    return {"status":"PASS", "checks":15, "new_calls":0, "new_fits":0, "new_return_labels":0, "real_sources_read":False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["precheck", "build", "prepare"])
    parser.add_argument("--rawrefs", type=Path, default=OUT / "rawrefs.json")
    args = parser.parse_args()
    if args.mode == "precheck":
        print(json.dumps(precheck(), ensure_ascii=False))
    elif args.mode == "build":
        build(args.rawrefs)
    else:
        prepare_features()
