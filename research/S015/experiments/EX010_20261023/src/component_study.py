"""S015 dual-objective component study; fixed inputs, no strategy search."""

# ruff: noqa: E402
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from decimal import Decimal, ROUND_FLOOR
from hashlib import sha256
from io import BytesIO
import json
from multiprocessing import get_context
import os
from pathlib import Path
from time import perf_counter
from uuid import UUID
import zipfile

for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[key] = "1"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

import numpy as np
import pandas as pd
from czsc_trader.application import (
    RepositoryContext,
    create_research_context,
    publish_evidence,
    diagnose_accounts,
)
from czsc_trader.research_tools import (
    ResearchBatchRef,
    ExecutionResources,
    ExperimentRef,
    EvidenceRef,
    MaterialEvidenceWrite,
    AccountRunRef,
    AccountDiagnosisRequest,
    EvaluationIdentity,
    EvaluationWindow,
)
from dataflows import DataRequest, Dataset, PreparedDataRef
from strategy_manager import CandidateKey
from trading_execution_engine import MarketExecutionRules, DailyQuote, OrderSpec, resolve_fill

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parents[1]
EX = ExperimentRef("S015", HERE.name)
WORK = ROOT / "research/S015/assets/runs" / EX.experiment_id / "dual_objective_components"
DEFS = (
    ("trend5", "五日趋势", "log(Close/Close.shift(5))", "短暂卖压之后延续还是持续下跌", "trend"),
    (
        "trend20",
        "二十日趋势位置",
        "Close/rolling_mean(Close,20)-1",
        "中期趋势可能决定反弹收益空间",
        "trend",
    ),
    (
        "pressure",
        "收盘相对成交均价",
        "Close/(Amount/Volume)-1",
        "收盘买卖压力的旧信息能否在新短期限提供增量",
        "pressure",
    ),
    ("body", "当日开收盘变化", "log(Close/Open)", "当天卖压相对尾盘修复", "pressure"),
    (
        "location",
        "收盘区间位置",
        "(2*Close-High-Low)/(High-Low)",
        "收盘靠近高位是否比仅有反弹更可靠",
        "pressure",
    ),
    (
        "lower_wick",
        "下影吸收",
        "(min(Open,Close)-Low)/(High-Low)",
        "盘中探底后恢复是否区别于下跌持续",
        "recovery",
    ),
    (
        "calm_range",
        "近期振幅收缩",
        "-mean((High-Low)/Close,5)/mean((High-Low)/Close,20)",
        "近期压力扩张可能识别损失风险",
        "risk",
    ),
    (
        "efficiency5",
        "五日有向效率",
        "sum(log_return,5)/sum(abs(log_return),5)",
        "有方向的价格路径与无方向波动不同",
        "trend",
    ),
    (
        "afternoon",
        "午后价格修复",
        "log(last_close/first_afternoon_open)",
        "收盘前恢复是否有后续信息",
        "intraday",
    ),
    (
        "late_hour",
        "最后一小时收益",
        "log(last_close/open_of_14:30_bar)",
        "更近时点的压力是否优于全天开收盘",
        "intraday",
    ),
    (
        "afternoon_reversal",
        "午后相对上午恢复",
        "afternoon_return-morning_return",
        "卖压在盘中是否消退",
        "intraday",
    ),
    (
        "downside_balance",
        "日内下跌强度占比",
        "-sum(min(log(bar_close/bar_open),0)**2)/sum(log(bar_close/bar_open)**2)",
        "下跌波动占比是否区分损失风险",
        "risk",
    ),
)


def read(p):
    return json.loads(p.read_bytes())


def save(p, v):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(v, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8", newline="\n"
    )


def context():
    return create_research_context(
        RepositoryContext.discover(ROOT),
        ResearchBatchRef("S015"),
        resources=ExecutionResources(max_workers=8, native_threads_per_worker=1, random_seed=13),
    )


def material(p, name=None):
    media = {
        ".py": "text/x-python",
        ".md": "text/markdown",
        ".json": "application/json",
        ".csv": "text/csv",
    }[p.suffix]
    return publish_evidence(
        context(), MaterialEvidenceWrite(EX, name or p.stem, p.read_bytes(), media, p.suffix[1:])
    )


def c0031_evidence():
    rows = read(ROOT / "research/S015/assets/runs/EX003_20261021/strategy_study/grid_results.json")
    row = next(x for x in rows if x["candidate_id"] == "C0031")
    ref = EvidenceRef.from_dict(row["evidence"])
    return ref, read(ref.resolve(ROOT))


def data_identity(identity):
    return {
        key: str(getattr(identity, key))
        for key in ("dataset", "source", "symbol", "data_start", "data_cutoff", "content_sha256")
    }


def inputs():
    ctx = context()
    audit = read(ROOT / "research/S015/experiments/EX001_20261021/others/data_audit.json")
    saved = audit["prepared_reference"]
    prepared = PreparedDataRef(
        UUID(saved["space_id"]), UUID(saved["preparation_id"]), saved["manifest_sha256"]
    )
    values, ids = {}, {}
    for ds in (Dataset.ETF_OHLCV, Dataset.ETF_UNADJUSTED_DAILY):
        req = DataRequest(
            ds, "159326.SZ", "2024-09-09", "2026-10-21", "2026-10-21", frequency="daily"
        )
        result = ctx.data.fetch(req, prepared=prepared)
        if not result.ready:
            raise RuntimeError(result.error)
        expected = next(x for x in audit["items"] if x["dataset"] == ds.value)["identity"][
            "content_sha256"
        ]
        assert result.identity.content_sha256 == expected
        values[ds] = result.dataframe.sort_values("Date").reset_index(drop=True)
        ids[ds.value] = data_identity(result.identity)
    minute_audit = read(
        ROOT / "research/S015/experiments/EX003_20261021/others/execution_data_audit.json"
    )
    saved_m = minute_audit["prepared"]["reference"]
    prepared_m = PreparedDataRef(
        UUID(saved_m["space_id"]), UUID(saved_m["preparation_id"]), saved_m["manifest_sha256"]
    )
    req_m = DataRequest(
        Dataset.ETF_UNADJUSTED_INTRADAY,
        "159326.SZ",
        "2025-01-02",
        "2026-10-21",
        "2026-10-21",
        frequency="30m",
    )
    result_m = ctx.data.fetch(req_m, prepared=prepared_m)
    if not result_m.ready:
        raise RuntimeError(result_m.error)
    assert result_m.identity.content_sha256 == minute_audit["identity"]["content_sha256"]
    minute = result_m.dataframe.sort_values("Date").reset_index(drop=True)
    ids[Dataset.ETF_UNADJUSTED_INTRADAY.value] = data_identity(result_m.identity)
    raw, adj = values[Dataset.ETF_UNADJUSTED_DAILY], values[Dataset.ETF_OHLCV]
    assert len(raw) == len(adj) == 509 and len(minute) == 3472
    assert raw.Date.equals(adj.Date)
    assert pd.to_datetime(raw.Date).max() == pd.Timestamp("2026-10-21")
    return (
        raw,
        adj,
        minute,
        {"identities": ids, "daily_prepared": saved, "minute_prepared": saved_m},
    )


def features(raw, minute):
    c, o, h, lo = (raw[k].astype(float) for k in ("Close", "Open", "High", "Low"))
    r = np.log(c).diff()
    width = h - lo
    amp = width / c
    x = pd.DataFrame(
        {
            "trend5": np.log(c).diff(5),
            "trend20": c / c.rolling(20).mean() - 1,
            "pressure": c / (raw.Amount / raw.Volume) - 1,
            "body": np.log(c / o),
            "location": (2 * c - h - lo) / width,
            "lower_wick": (pd.concat([o, c], axis=1).min(axis=1) - lo) / width,
            "calm_range": -amp.rolling(5).mean() / amp.rolling(20).mean(),
            "efficiency5": r.rolling(5).sum() / r.abs().rolling(5).sum(),
        }
    )
    minute = minute.copy()
    minute["day"] = pd.to_datetime(minute.Date).dt.strftime("%Y-%m-%d")
    expected_times = ("10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00")
    records = {}
    for day, g in minute.groupby("day", sort=True):
        assert tuple(pd.to_datetime(g.Date).dt.strftime("%H:%M")) == expected_times
        bar = np.log(g.Close.to_numpy(float) / g.Open.to_numpy(float))
        morning = np.log(float(g.Close.iloc[3]) / float(g.Open.iloc[0]))
        afternoon = np.log(float(g.Close.iloc[-1]) / float(g.Open.iloc[4]))
        total = float((bar**2).sum())
        records[day] = {
            "afternoon": float(afternoon),
            "late_hour": float(np.log(float(g.Close.iloc[-1]) / float(g.Open.iloc[6]))),
            "afternoon_reversal": float(afternoon - morning),
            "downside_balance": float(-(np.minimum(bar, 0) ** 2).sum() / total) if total else 0.0,
        }
    for name in (d[0] for d in DEFS[8:]):
        x[name] = (
            pd.to_datetime(raw.Date)
            .dt.strftime("%Y-%m-%d")
            .map({day: row[name] for day, row in records.items()})
        )
    # Baselines are controls, not extra component definitions or screened windows.
    x["base_r1"] = r
    x["base_r5"] = np.log(c).diff(5)
    x["base_vol20"] = r.rolling(20).std(ddof=0)
    return x


def archive_diagnosis():
    references = read(
        ROOT / "research/S015/experiments/EX008_20261022/others/account_archives.json"
    )
    all_daily, summary, manifests = {}, {}, {}
    for label, saved in references.items():
        ref = EvidenceRef.from_dict(saved)
        with zipfile.ZipFile(ref.resolve(ROOT)) as z:
            a = pd.read_csv(BytesIO(z.read("account_daily.csv")), float_precision="round_trip")
            f = pd.read_csv(BytesIO(z.read("fills.csv")), float_precision="round_trip")
            t = pd.read_csv(BytesIO(z.read("trades.csv")), float_precision="round_trip")
            m = json.loads(z.read("manifest.json"))
            audit = json.loads(z.read("audit.json"))
        assert len(a) == 415 and a.date.iloc[0] == "2025-02-06" and a.date.iloc[-1] == "2026-10-21"
        assert (
            a.cash_before.iloc[0] == 100000
            and a.quantity_before.iloc[0] == 0
            and audit["status"] == "PASS"
        )
        f["day"] = pd.to_datetime(f.fill_time).dt.strftime("%Y-%m-%d")
        previous_close = a.close.shift(1)
        pieces = []
        for i, row in a.iterrows():
            fills = f[f.day.eq(row.date)]
            buys, sells = fills[fills.side.eq("BUY")], fills[fills.side.eq("SELL")]
            entry = float((buys.quantity * (row.close - buys.price)).sum())
            sold = float(sells.quantity.sum())
            exit_pnl = (
                float((sells.quantity * (sells.price - previous_close.iloc[i])).sum())
                if len(sells)
                else 0.0
            )
            held = (
                float((row.quantity_before - sold) * (row.close - previous_close.iloc[i]))
                if row.quantity_before - sold
                else 0.0
            )
            fees = float(fills.fees.sum())
            before = float(a.equity.iloc[i - 1]) if i else 100000.0
            actual = float(row.equity - before)
            residual = actual - (entry + held + exit_pnl - fees)
            assert abs(residual) < 1e-7, (label, row.date, residual)
            assert abs(row.equity - (row.cash + row.quantity * row.close)) < 1e-7
            pieces.append(
                {
                    "date": row.date,
                    "entry": entry,
                    "holding": held,
                    "exit": exit_pnl,
                    "fees": fees,
                    "net_pnl": actual,
                    "residual": residual,
                    "quantity": int(row.quantity),
                    "quantity_before": int(row.quantity_before),
                }
            )
        daily = pd.DataFrame(pieces)
        equity = np.r_[100000.0, a.equity.to_numpy(float)]
        dd = 1 - equity / np.maximum.accumulate(equity)
        summary[label] = {
            "archive": saved,
            "sessions": len(a),
            "net_return": float(equity[-1] / 100000 - 1),
            "max_drawdown": float(dd.max()),
            "closed_trades": int(t.status.eq("CLOSED").sum()),
            "pnl_totals": {
                k: float(daily[k].sum()) for k in ("entry", "holding", "exit", "fees", "net_pnl")
            },
            "max_reconciliation_residual": float(daily.residual.abs().max()),
            "years": [
                {
                    "year": int(y),
                    **{
                        k: float(g[k].sum())
                        for k in ("entry", "holding", "exit", "fees", "net_pnl")
                    },
                }
                for y, g in daily.groupby(pd.to_datetime(daily.date).dt.year)
            ],
            "worst5_pnl_days": daily.nsmallest(5, "net_pnl").to_dict("records"),
        }
        all_daily[label], manifests[label] = daily, m
        daily.to_csv(WORK / f"archive_diagnosis_{label}.csv", index=False)
    assert manifests["S011-v1"]["execution_data"] == manifests["C0031"]["execution_data"]
    gate = read(ROOT / "research/S015/experiments/EX009_20261022/protocols/comparative_gate.json")
    assert summary["S011-v1"]["net_return"] == gate["conditions"][0]["baseline_value"]
    assert abs(summary["S011-v1"]["max_drawdown"] - gate["conditions"][1]["baseline_value"]) < 1e-14
    # Use the public diagnosis on its supported schema. The old ZIP accounts are
    # reconciled above without relabelling them as schema-7 account evidence.
    ref, payload = c0031_evidence()
    ident = payload["runs"][0]["identity"]
    identity = EvaluationIdentity(
        CandidateKey(**ident["candidate"]), **{k: v for k, v in ident.items() if k != "candidate"}
    )
    public = diagnose_accounts(
        RepositoryContext.discover(ROOT),
        AccountDiagnosisRequest(
            AccountRunRef(ref, identity),
            None,
            EvaluationWindow("full", date(2025, 1, 2), date(2026, 10, 21)),
        ),
    )
    save(HERE / "others/public_c0031_diagnosis.json", public.to_dict())
    save(
        HERE / "others/account_facts.json",
        {
            "accounts": summary,
            "public_diagnosis": {
                "status": public.status.value,
                "issues": list(public.issues),
                "scope": "C0031 original 434-session account only; 415-session ZIP archives are not supported by this API. Unsupported is preserved; independent archive arithmetic above is not reported as public diagnosis success.",
            },
            "comparison": "415-session archives use their own independent initial cash; public 434-session result is not substituted.",
            "causality": "Pnl components and cross-account differences are accounting facts, not causal counterfactuals.",
        },
    )
    return all_daily


def round_floor(value, tick=0.001):
    t = Decimal(str(tick))
    return float((Decimal(str(value)) / t).to_integral_value(rounding=ROUND_FLOOR) * t)


def event_labels(adj, raw):
    _, payload = c0031_evidence()
    rules = MarketExecutionRules.from_dict(payload["request_identity"]["market_rules"])
    assert payload["request_identity"]["pricing"]["basis"] == "HFQ_RESEARCH"
    assert rules.symbol == "159326.SZ"
    rows = []
    for i in range(75, len(adj)):
        signal_day = pd.Timestamp(adj.Date.iloc[i]).date()
        raw_close = float(raw.Close.iloc[i])
        scale = float(adj.Close.iloc[i]) / raw_close
        requested = round_floor(raw_close * 1.01)
        guard = round_floor(round_floor(raw_close * 1.1) - 0.001)
        limit = min(requested, guard) * scale
        quantity = min(
            1000000, int(Decimal("100000") / (Decimal(str(limit)) * Decimal("1.001") * 100)) * 100
        )
        for horizon in (1, 2, 3):
            j, k = i + 1, i + horizon + 1
            common = {
                "signal_date": str(signal_day),
                "horizon": horizon,
                "signal_position": i,
                "label_end_position": k,
                "entry_date": None,
                "exit_date": None,
                "status": "RIGHT_CENSORED",
                "label": None,
                "price_return": None,
                "downside": None,
                "quantity": quantity,
                "buy_limit": limit,
                "buy_price": None,
                "sell_price": None,
                "buy_trigger": None,
                "sell_trigger": None,
            }
            if k >= len(adj):
                rows.append(common)
                continue
            entry_day, exit_day = (pd.Timestamp(adj.Date.iloc[p]).date() for p in (j, k))
            common.update(entry_date=str(entry_day), exit_date=str(exit_day))

            def fill(p, order):
                day = pd.Timestamp(adj.Date.iloc[p]).date()
                quote = adj.iloc[p]
                return resolve_fill(
                    order,
                    session_open=float(quote.Open),
                    session_time=pd.Timestamp(day).replace(hour=9, minute=30).to_pydatetime(),
                    intraday_touches=(),
                    session_limits=rules.for_session(day),
                    daily_quote=DailyQuote(float(quote.Low), float(quote.High)),
                )

            buy = fill(j, OrderSpec("BUY", "LIMIT", quantity, limit))
            if not buy.filled:
                common["status"] = "BUY_UNFILLED"
                rows.append(common)
                continue
            sell = fill(k, OrderSpec("SELL", "MARKET", quantity))
            if not sell.filled:
                common["status"] = "EXIT_UNFILLED"
                rows.append(common)
                continue
            # Independent, overlapping event labels, each starting from cash.
            # They never form a combined account or an executable strategy.
            pnl = quantity * (sell.price - buy.price) - quantity * (sell.price + buy.price) * 0.001
            common.update(
                status="FILLED",
                label=float(pnl / 100000),
                price_return=float(sell.price * (1 - 0.001) / (buy.price * (1 + 0.001)) - 1),
                downside=float(max(0, 1 - float(adj.Low.iloc[j:k].min()) / buy.price)),
                buy_price=buy.price,
                sell_price=sell.price,
                buy_trigger=buy.trigger,
                sell_trigger=sell.trigger,
            )
            assert quantity % 100 == 0 and quantity * buy.price * 1.001 <= 100000 + 1e-8
            rows.append(common)
    return pd.DataFrame(rows)


def prepare():
    assert not (HERE / "others/protocol_refs.json").exists(), (
        "Protocol is immutable; inspect existing state before rerunning."
    )
    WORK.mkdir(parents=True, exist_ok=True)
    raw, adj, minute, facts = inputs()
    x = features(raw, minute)
    assert np.isfinite(x.iloc[75:].to_numpy(float)).all()
    # Causal feature tests perturb all future bars after a fixed cutoff.
    cutoff = 300
    changed = raw.copy()
    changed.loc[cutoff + 1 :, "Close"] *= 1.05
    changed_m = minute[
        pd.to_datetime(minute.Date).dt.normalize() <= pd.Timestamp(raw.Date.iloc[cutoff])
    ]
    xx = features(changed, changed_m)
    np.testing.assert_allclose(
        x.iloc[: cutoff + 1], xx.iloc[: cutoff + 1], rtol=0, atol=0, equal_nan=True
    )
    differences = np.log(raw.Close).diff() - np.log(adj.Close).diff()
    facts.update(
        daily_rows=509,
        minute_rows=3472,
        evaluation_sessions=434,
        max_raw_adjusted_log_return_difference=float(differences.abs().max()),
        causal_future_perturbation="PASS",
        minute_times="8 exact bars per day; last bar 15:00",
        publication_limits="Historical daily adjustment publication and intraday vendor availability at 17:30 remain unverified.",
        sources="Existing S015 DFLS preparations only; no prepare, refresh, new data, or adjacent batch input.",
    )
    save(HERE / "others/input_facts.json", facts)
    accounts = archive_diagnosis()
    x.insert(0, "date", pd.to_datetime(raw.Date).dt.strftime("%Y-%m-%d"))
    x.to_csv(WORK / "features.csv", index=False)
    for label, daily in accounts.items():
        x[f"{label}_held"] = x.date.map(daily.set_index("date").quantity.gt(0).to_dict())
    x.to_csv(WORK / "features_with_account_states.csv", index=False)
    protocol = {
        "schema_version": 1,
        "stage": 2,
        "mandate": "MANDATE/3",
        "definitions": [
            {
                "id": key,
                "name": name,
                "formula": formula,
                "hypothesis": hyp,
                "family": family,
                "orientation": "Higher score expected to identify more profitable or less risky conditions; fixed before label evaluation.",
            }
            for key, name, formula, hyp, family in DEFS
        ],
        "horizons": [1, 2, 3],
        "component_horizon_budget": 36,
        "new_strategy_accounts": 0,
        "decision_time": "T 17:30; all input bars through T; event entry T+1; exit T+h+1 open (h>=1, no same-day sale)",
        "label": "Each independent event starts with 100000 cash; SRT-equivalent frozen limit sizing formula, TXE public resolve_fill with retained full-session market rules, one-way cost .001; no reinvestment across events.",
        "units": "Adjusted execution prices and quantities use the retained HFQ_RESEARCH contract; raw prices used for .001 tick planning before price-scale conversion.",
        "right_censor": "No labels beyond 2026-10-21; right-censored and unfilled events excluded and counted separately. No forced exit or assumed fill.",
        "downside": "Worst low from entry day through day before planned exit, relative to actual entry. Daily-range entry timing unknown; entry-day low is conservative geometry, not realized post-entry loss.",
        "folds": {
            "training_minimum_decision_sessions": 100,
            "test_ranges_relative_to_434": [[100, 184], [184, 268], [268, 352], [352, 434]],
            "purge": "Only labels whose exit date is strictly before first test decision are used for training.",
        },
        "grouping": "Past-training 1/3 and 2/3 quantiles; fixed orientation; high/low/middle separately; no threshold search.",
        "controls": ["r1", "r5", "vol20"],
        "incremental": "Ridge alpha=10; controls versus controls+one component for event return and downside; training-only standardization.",
        "outputs": [
            "high-low mean net event label",
            "retained profitable label amount",
            "avoided negative label amount",
            "missed positive label amount",
            "coverage counts",
            "2025/2026 sign stability",
            "incremental prediction loss gain",
            "block20 interval",
        ],
        "diagnostics": "499 moving-block20 resamples, seed13; intervals are exploratory, overlap and selection history remain. No independent holdout or confirmed statistical significance.",
        "judgment": "SUPPORTED only for a clearly stated role and horizon with high-low direction consistent in 2025 and 2026 and positive incremental loss gain in both years for that role. This is RSCH evidence classification, not an added strategy acceptance gate. Empty support is a valid result.",
        "account_context": "Fixed actual 415-session accounts are descriptive conditioning only. State at T is observed; no cancellation of trades or subtraction treated as counterfactual equity.",
        "resources": {
            "max_workers": 8,
            "native_threads_per_worker": 1,
            "seed": 13,
            "nested_parallelism": False,
        },
        "scope": "No combined rule, Optuna search, new candidate, stage3/4, freeze, PTE, prod, new market data or changed dates.",
        "input_facts": facts,
        "prior_seen": "All samples previously used in development. Prior EX002 explored related daily features; this is a new question/label/execution comparison, not fresh independent discovery.",
    }
    save(HERE / "protocols/component_protocol.json", protocol)
    # Protocol and implementation are formally published before event labels.
    refs = {}
    for p in (
        HERE / "protocols/component_protocol.json",
        Path(__file__),
        HERE / "others/account_facts.json",
        HERE / "others/input_facts.json",
        HERE / "others/public_c0031_diagnosis.json",
    ):
        refs[p.name] = material(p).to_dict()
    save(HERE / "others/protocol_refs.json", refs)
    labels = event_labels(adj, raw)
    labels.to_csv(WORK / "event_labels.csv", index=False)
    save(
        HERE / "others/label_coverage.json",
        {
            str(h): g.status.value_counts().astype(int).to_dict()
            for h, g in labels.groupby("horizon")
        },
    )
    print(
        json.dumps(
            {
                "prepared": EX.experiment_id,
                "comparisons": 36,
                "label_coverage": read(HERE / "others/label_coverage.json"),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


def ridge_predict(train, y, test):
    mean, sd = train.mean(axis=0), train.std(axis=0)
    sd = np.where(sd < 1e-12, 1.0, sd)
    a, b = (train - mean) / sd, (test - mean) / sd
    beta = np.linalg.solve(a.T @ a + 10 * np.eye(a.shape[1]), a.T @ (y - y.mean()))
    return y.mean() + b @ beta


def contrast(y, high, low):
    return float(y[high].mean() - y[low].mean()) if high.any() and low.any() else None


def evaluate(job):
    component, horizon = job
    x = pd.read_csv(WORK / "features_with_account_states.csv")
    labels = pd.read_csv(WORK / "event_labels.csv")
    labels = labels[labels.horizon.eq(horizon)].set_index("signal_date")
    base = x[["base_r1", "base_r5", "base_vol20"]].to_numpy(float)
    f = x[component].to_numpy(float)
    values = x.date.map(labels.label).to_numpy(float)
    risk = x.date.map(labels.downside).to_numpy(float)
    ends = x.date.map(labels.label_end_position).to_numpy(float)
    status = x.date.map(labels.status).to_numpy()
    valid = (
        np.isfinite(values)
        & np.isfinite(risk)
        & np.isfinite(f)
        & np.isfinite(base).all(axis=1)
        & (status == "FILLED")
    )
    records = []
    for fold, (a, b) in enumerate(((100, 184), (184, 268), (268, 352), (352, 434))):
        start, end = 75 + a, 75 + b
        train = np.flatnonzero(valid & (np.arange(len(x)) < start) & (ends < start))
        test = np.flatnonzero(valid & (np.arange(len(x)) >= start) & (np.arange(len(x)) < end))
        assert len(train) > 80 and len(test) > 20
        q1, q2 = np.quantile(f[train], [1 / 3, 2 / 3])
        assert q2 > q1
        groups = np.where(f[test] >= q2, 1, np.where(f[test] <= q1, -1, 0))
        added = np.column_stack([base, f])
        for target, yy in (("return", values), ("downside", risk)):
            pb = ridge_predict(base[train], yy[train], base[test])
            pa = ridge_predict(added[train], yy[train], added[test])
            if target == "return":
                rb, ra = pb, pa
            else:
                db, da = pb, pa
        for j, p in enumerate(test):
            row = {
                "date": x.date.iloc[p],
                "fold": fold,
                "group": int(groups[j]),
                "feature": float(f[p]),
                "label": float(values[p]),
                "downside": float(risk[p]),
                "return_base_loss": float((rb[j] - values[p]) ** 2),
                "return_added_loss": float((ra[j] - values[p]) ** 2),
                "risk_base_loss": float((db[j] - risk[p]) ** 2),
                "risk_added_loss": float((da[j] - risk[p]) ** 2),
                "train_size": len(train),
                "train_last_exit_position": int(ends[train].max()),
                "test_start_position": start,
            }
            for account in ("S011-v1", "C0031"):
                row[f"{account}_held"] = (
                    None
                    if pd.isna(x[f"{account}_held"].iloc[p])
                    else bool(x[f"{account}_held"].iloc[p])
                )
            records.append(row)
    a = pd.DataFrame(records)

    def summarize(frame):
        y = frame.label.to_numpy()
        d = frame.downside.to_numpy()
        groups = frame.group.to_numpy()
        high, low = groups == 1, groups == -1
        positives = np.maximum(y, 0)
        negatives = np.maximum(-y, 0)

        def fraction(a, b):
            return float(a / b) if b else None

        def gain(prefix):
            return float(
                1 - frame[f"{prefix}_added_loss"].sum() / frame[f"{prefix}_base_loss"].sum()
            )

        return {
            "n": len(frame),
            "high_n": int(high.sum()),
            "low_n": int(low.sum()),
            "middle_n": int((groups == 0).sum()),
            "mean_label": float(y.mean()),
            "high_mean": float(y[high].mean()) if high.any() else None,
            "low_mean": float(y[low].mean()) if low.any() else None,
            "high_low_return": contrast(y, high, low),
            "high_low_downside": contrast(d, high, low),
            "retained_profit_fraction": fraction(positives[high].sum(), positives.sum()),
            "avoided_loss_fraction": fraction(negatives[low].sum(), negatives.sum()),
            "missed_profit_fraction": fraction(positives[low].sum(), positives.sum()),
            "return_incremental_gain": gain("return"),
            "risk_incremental_gain": gain("risk"),
        }

    overall = summarize(a)
    years = {str(year): summarize(g) for year, g in a.groupby(pd.to_datetime(a.date).dt.year)}
    groups = a.group.to_numpy()
    y = a.label.to_numpy()
    risk = a.downside.to_numpy()
    rng = np.random.default_rng(13)
    n = len(a)
    indices = (
        rng.integers(0, n - 20 + 1, (499, int(np.ceil(n / 20))))[:, :, None] + np.arange(20)
    ).reshape(499, -1)[:, :n]
    ci = []
    for yy in (y, risk):
        vals = [contrast(yy[ix], groups[ix] == 1, groups[ix] == -1) for ix in indices]
        vals = [v for v in vals if v is not None]
        ci.append([float(z) for z in np.quantile(vals, [0.025, 0.975])])
    supported_return = (
        all(
            v["high_low_return"] is not None
            and v["high_low_return"] > 0
            and v["return_incremental_gain"] > 0
            for v in years.values()
        )
        and len(years) == 2
    )
    supported_risk = (
        all(
            v["high_low_downside"] is not None
            and v["high_low_downside"] < 0
            and v["risk_incremental_gain"] > 0
            for v in years.values()
        )
        and len(years) == 2
    )
    result = {
        "component": component,
        "horizon": horizon,
        "summary": overall,
        "years": years,
        "high_low_return_interval_block20": ci[0],
        "high_low_downside_interval_block20": ci[1],
        "supported_return": supported_return,
        "supported_risk": supported_risk,
        "status": "SUPPORTED" if supported_return or supported_risk else "INEFFECTIVE",
        "folds": {str(k): summarize(g) for k, g in a.groupby("fold")},
        "account_states": {
            f"{account}:{state}": summarize(g)
            for account in ("S011-v1", "C0031")
            for state, g in a.dropna(subset=[f"{account}_held"]).groupby(f"{account}_held")
            if len(g) > 10
        },
    }
    return result, records


def run():
    assert (HERE / "others/protocol_refs.json").exists()
    assert not (HERE / "others/component_results.json").exists()
    jobs = [(row[0], h) for row in DEFS for h in (1, 2, 3)]
    start = perf_counter()
    # A real transport/equality precheck precedes the full fixed batch.
    serial = evaluate(jobs[0])
    with ProcessPoolExecutor(max_workers=2, mp_context=get_context("spawn")) as pool:
        parallel = pool.submit(evaluate, jobs[0]).result()
    assert serial == parallel
    results = []
    event_rows = []
    with ProcessPoolExecutor(max_workers=8, mp_context=get_context("spawn")) as pool:
        for result, records in pool.map(evaluate, jobs):
            results.append(result)
            event_rows.extend(
                {"component": result["component"], "horizon": result["horizon"], **r}
                for r in records
            )
            print(
                json.dumps(
                    {
                        "completed": len(results),
                        "component": result["component"],
                        "horizon": result["horizon"],
                        "status": result["status"],
                    }
                ),
                flush=True,
            )
    assert len(results) == 36
    pd.DataFrame(event_rows).to_csv(WORK / "all_held_forward_events.csv", index=False)
    corr = (
        pd.read_csv(WORK / "features.csv")
        .iloc[75:][[row[0] for row in DEFS]]
        .corr(method="spearman")
    )
    corr.to_csv(WORK / "component_rank_correlations.csv")
    save(
        HERE / "others/component_results.json",
        {
            "comparisons": results,
            "comparison_count": 36,
            "supported_pairs": sum(r["status"] == "SUPPORTED" for r in results),
            "elapsed_seconds": perf_counter() - start,
            "parallel_serial_equivalence": "PASS",
            "resources": {"workers": 8, "native_threads": 1, "nested": False},
            "source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        },
    )
    print("COMPONENT_STUDY_COMPLETE", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "run"))
    args = parser.parse_args()
    prepare() if args.mode == "prepare" else run()
