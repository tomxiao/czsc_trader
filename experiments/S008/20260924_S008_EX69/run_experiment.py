from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
from uuid import uuid4

from dataflows import Dataflows
from dotenv import dotenv_values
import pandas as pd
from research_experiment import (
    ExperimentResources,
    ExperimentWorkspace,
    load_experiment,
    load_experiment_input,
)
import tushare as ts

from czsc_trader import load_market_data
from czsc_trader.experiment_archive import (
    build_experiment_manifest,
    validate_experiment_archive,
)
from czsc_trader.research_tools import create_experiment_context, execute_experiment


PREDECESSOR_RECEIPT = "a9c683cb0d64e94fa8930c753e2bfd9626949d1e864b00b8152b9953b0aceb01"


def _managed_intraday_provider(repository_root: Path):
    def provider(request):
        market = load_market_data(
            repository_root / "data" / "raw",
            symbol=str(request.symbol),
            asset_type="etf",
            cutoff=request.end,
        )
        frame = market.intraday.rename(
            columns={
                "dt": "Date",
                "open": "Open",
                "high": "High",
                "low": "Low",
                "close": "Close",
                "vol": "Volume",
                "amount": "Amount",
            }
        )[["Date", "Open", "High", "Low", "Close", "Volume", "Amount"]]
        frame = frame.loc[
            (frame["Date"] >= pd.Timestamp(request.start))
            & (frame["Date"].dt.normalize() <= pd.Timestamp(request.end).normalize())
        ].reset_index(drop=True)
        return frame, {
            "vendor": "managed_manifest_publication",
            "vendor_symbol": request.symbol,
            "asset_type": "etf",
            "period": "30m",
            "adjustment": "hfq",
            "source_time_field": "Date",
            "source_calendar": "SSE",
            "available_at": "BAR_END_TIMESTAMP",
            "primary_key": ["Date"],
            "maximum_start_lag_days": 0,
            "manifest_files": len(market.manifest.get("files", {})),
        }

    return provider


def _summary(name: str, date: str, frame: pd.DataFrame) -> dict[str, object]:
    return {
        "Date": pd.Timestamp(date),
        "Capability": name,
        "Status": "PASS",
        "Rows": int(len(frame)),
        "Columns": ",".join(sorted(str(column) for column in frame.columns)),
        "ErrorType": "",
    }


def _failed_summary(name: str, date: str, exc: Exception) -> dict[str, object]:
    return {
        "Date": pd.Timestamp(date),
        "Capability": name,
        "Status": "FAILED",
        "Rows": 0,
        "Columns": "",
        "ErrorType": type(exc).__name__,
    }


def _futures_capability_provider(repository_root: Path):
    def provider(request):
        if ts.__version__ != "1.4.29":
            raise RuntimeError("Tushare version differs from the frozen experiment dependency")
        token = str(dotenv_values(repository_root / ".env").get("TUSHARE_TOKEN") or "").strip()
        if not token:
            raise RuntimeError("protected Tushare credential is not configured")
        pro = ts.pro_api(token)
        start = "20130729"
        end = "20241231"
        rows: list[dict[str, object]] = []

        def capture(name: str, date: str, call, transform=None) -> pd.DataFrame:
            try:
                frame = call()
                if transform is not None:
                    frame = transform(frame)
                rows.append(_summary(name, date, frame))
                return frame
            except Exception as exc:  # preserved as a capability fact without secrets
                rows.append(_failed_summary(name, date, exc))
                return pd.DataFrame()

        capture(
            "fut_basic_au",
            start,
            lambda: pro.fut_basic(
                exchange="SHFE",
                fut_type="1",
                fut_code="AU",
                fields="ts_code,symbol,exchange,name,fut_code,list_date,delist_date,d_month",
            ),
        )
        start_mapping = capture(
            "fut_mapping_start",
            start,
            lambda: pro.fut_mapping(ts_code="AU.SHF", start_date=start, end_date=start),
        )
        end_mapping = capture(
            "fut_mapping_end",
            end,
            lambda: pro.fut_mapping(ts_code="AU.SHF", start_date=end, end_date=end),
        )
        capture(
            "fut_daily_start",
            start,
            lambda: pro.fut_daily(
                trade_date=start,
                exchange="SHFE",
                fields="ts_code,trade_date,close,settle,vol,amount,oi,oi_chg",
            ),
            lambda frame: frame.loc[frame["ts_code"].astype(str).str.startswith("AU")],
        )
        capture(
            "fut_daily_end",
            end,
            lambda: pro.fut_daily(
                trade_date=end,
                exchange="SHFE",
                fields="ts_code,trade_date,close,settle,vol,amount,oi,oi_chg",
            ),
            lambda frame: frame.loc[frame["ts_code"].astype(str).str.startswith("AU")],
        )
        start_contract = (
            str(start_mapping.iloc[0]["mapping_ts_code"]) if not start_mapping.empty else "AU.SHF"
        )
        end_contract = (
            str(end_mapping.iloc[0]["mapping_ts_code"]) if not end_mapping.empty else "AU.SHF"
        )
        capture(
            "fut_holding_start",
            start,
            lambda: pro.fut_holding(
                trade_date=start,
                symbol=start_contract.split(".")[0],
                exchange="SHFE",
            ),
        )
        capture(
            "fut_holding_end",
            end,
            lambda: pro.fut_holding(
                trade_date=end,
                symbol=end_contract.split(".")[0],
                exchange="SHFE",
            ),
        )
        capture(
            "fut_wsr_start",
            start,
            lambda: pro.fut_wsr(trade_date=start, symbol="AU", exchange="SHFE"),
        )
        capture(
            "fut_wsr_end",
            end,
            lambda: pro.fut_wsr(trade_date=end, symbol="AU", exchange="SHFE"),
        )

        project_datasets = set(Dataflows().datasets)
        required_project_datasets = {
            "futures.shfe_gold.daily",
            "futures.shfe_gold.mapping",
            "futures.shfe_gold.holding",
            "futures.shfe_gold.warehouse_receipt",
        }
        registered = required_project_datasets.issubset(project_datasets)
        frame = pd.DataFrame(rows)
        frame["ProjectDflsRegistered"] = registered
        frame["SdkVersion"] = ts.__version__
        frame = frame.sort_values(["Date", "Capability"]).reset_index(drop=True)
        return frame, {
            "vendor": "tushare_capability_probe",
            "vendor_symbol": request.symbol,
            "source_time_field": "Date",
            "source_calendar": "SHFE",
            "available_at": "NEXT_CHINA_TRADING_SESSION_CONSERVATIVE",
            "primary_key": ["Date", "Capability"],
            "maximum_start_lag_days": 0,
            "stores_raw_vendor_data": False,
        }

    return provider


def main() -> None:
    sys.dont_write_bytecode = True
    experiment_root = Path(__file__).resolve().parent
    repository_root = experiment_root.parents[2]
    if (experiment_root / "experiment_manifest.json").exists():
        raise FileExistsError("completed experiment manifest already exists")
    for name in ("artifacts", "03_execution.md", "04_conclusion.md"):
        if (experiment_root / name).exists():
            raise FileExistsError(f"experiment output already exists: {name}")

    predecessor = load_experiment_input(
        experiment_root.parent / "20260924_S008_EX68" / "artifacts",
        expected_receipt_sha256=PREDECESSOR_RECEIPT,
    )
    loaded = load_experiment(experiment_root)
    workspace = ExperimentWorkspace(
        repository_root
        / ".tmp"
        / "research-experiments"
        / uuid4().hex
        / loaded.definition.experiment_id,
        repository_root,
    )
    dataflows = Dataflows(
        {
            "etf.ohlcv.managed": _managed_intraday_provider(repository_root),
            "futures.shfe_gold.capability": _futures_capability_provider(repository_root),
        }
    )
    context = create_experiment_context(
        loaded.definition,
        repository_root=repository_root,
        dataflows=dataflows,
        workspace=workspace,
        resources=ExperimentResources(max_workers=1, random_seed=2026096901),
        predecessors=(predecessor,),
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("platform did not issue an experiment receipt")
    facts = dict(result.facts)

    artifacts = experiment_root / "artifacts"
    shutil.copytree(workspace.root, artifacts)
    (experiment_root / "03_execution.md").write_text(
        "# S008 EX69 执行\n\n"
        f"通过REX执行，receipt=`{result.receipt.sha256}`。受管30分钟输入共"
        f"{facts['intraday_rows']}行、{facts['intraday_sessions']}个交易日；期货供应商核心能力="
        f"`{facts['futures_core_vendor_pass']}`，项目DFLS就绪="
        f"`{facts['futures_project_dfls_ready']}`。本实验未读取未来收益标签、未读取密封验证区、"
        "未筛选信息、未创建原型、未启动搜索，也未保存Tushare原始记录。\n",
        encoding="utf-8",
    )
    (experiment_root / "04_conclusion.md").write_text(
        "# S008 EX69 结论\n\n"
        f"机器裁决：`{facts['decision']}`。受管30分钟路径通过="
        f"`{facts['intraday_pass']}`，描述量完整率={facts['descriptor_completeness']:.4%}；"
        f"上期所黄金期货核心供应商能力通过=`{facts['futures_core_vendor_pass']}`，仓单完整覆盖="
        f"`{facts['warehouse_full_coverage']}`。30分钟路径可以进入独立的信息价值审计；期货路径"
        "必须先补齐正式DFLS数据集、身份、完整性和available_at合同，未经平台适配不得用于"
        "未来收益检验。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(
        experiment_root,
        {
            "experiment_id": loaded.definition.experiment_id,
            "status": "COMPLETE",
            "experiment_type": "upside_participation_data_and_causality_gate",
            "strategy_id": loaded.definition.strategy_id,
            "credential_id": "SGC-S008-001",
            "symbol": "518880.SH",
            "development_cutoff": loaded.definition.development_cutoff.isoformat(),
            "decision": facts["decision"],
            "promotion_allowed": False,
            "predecessor_experiment_id": predecessor.experiment_id,
            "predecessor_receipt_sha256": predecessor.receipt_sha256,
            "rex_receipt_sha256": result.receipt.sha256,
        },
    )
    validate_experiment_archive(experiment_root)
    print(
        json.dumps(
            {
                "status": "PASS",
                "decision": facts["decision"],
                "receipt_sha256": result.receipt.sha256,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
