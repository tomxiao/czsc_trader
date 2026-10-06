"""Phase-one availability audit only; no signal or performance calculations."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pandas as pd
from dataflows import Dataflows, DataRequest, Dataset, DataStatus, LocalCacheConfig


def main():
    root = Path(__file__).resolve().parents[3]
    output = root / "research/S012/materials/data_coverage_v1.json"
    if output.exists():
        raise FileExistsError("Preserve the prior audit; use a successor version.")
    client = Dataflows(
        env_file=root / ".env",
        cache=LocalCacheConfig(root / ".tmp/s012/dfls", "s012-phase1-v1", timedelta(days=1)),
    )
    results = {}
    frames = {}
    for dataset, symbol in (
        (Dataset.TRADING_CALENDAR, "SSE"),
        (Dataset.ETF_UNADJUSTED_DAILY, "518850.SH"),
        (Dataset.ETF_OHLCV, "518850.SH"),
    ):
        request = DataRequest(dataset, symbol, "2020-06-05", "2026-10-04", None)
        result = client.fetch(request)
        record = {
            "request": {"dataset": dataset.value, "symbol": symbol, "start": request.start,
                        "end": request.end, "required_cutoff": None, "frequency": "daily"},
            "status": result.status.value, "warnings": list(result.warnings),
        }
        if result.status is DataStatus.READY:
            identity = result.identity
            record["identity"] = {
                "dataset": identity.dataset, "source": identity.source, "symbol": identity.symbol,
                "data_start": identity.data_start, "data_cutoff": identity.data_cutoff,
                "content_sha256": identity.content_sha256,
                "metadata": dict(identity.metadata),
            }
            frame = result.dataframe
            record["rows"] = len(frame)
            record["duplicate_dates"] = int(frame.Date.duplicated().sum())
            frames[dataset] = frame
        else:
            record["error"] = {"code": result.error.code, "message": result.error.message}
        results[dataset.value] = record
        print(json.dumps({"dataset": dataset.value, "status": record["status"],
                          "rows": record.get("rows"), "error": record.get("error")}, ensure_ascii=False), flush=True)
    comparison = {}
    if Dataset.TRADING_CALENDAR in frames:
        calendar = frames[Dataset.TRADING_CALENDAR]
        sessions = pd.DatetimeIndex(calendar.loc[calendar.IsOpen.eq(1), "Date"]).normalize()
        comparison["expected_sessions"] = len(sessions)
        comparison["first_session"] = str(sessions.min().date())
        comparison["last_session"] = str(sessions.max().date())
        for dataset in (Dataset.ETF_UNADJUSTED_DAILY, Dataset.ETF_OHLCV):
            if dataset in frames:
                observed = pd.DatetimeIndex(frames[dataset].Date).normalize()
                comparison[dataset.value] = {
                    "missing_sessions": [str(x.date()) for x in sessions.difference(observed)],
                    "unexpected_sessions": [str(x.date()) for x in observed.difference(sessions)],
                }
    audit = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "阶段一数据可用性核验，不计算收益、信号或筛选参数。",
        "listing_date": "2020-06-05",
        "listing_source": "https://www.sse.com.cn/disclosure/fund/announcement/c/new/2024-10-17/518850_20241017_BKBE.pdf",
        "listing_source_page": 38,
        "cutoff_policy": "首次探查不预设行情截止日；以完整SSE日历核对实际覆盖，具体评价起止待用户确认。",
        "datasets": results, "calendar_comparison": comparison,
    }
    with output.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(audit, ensure_ascii=False, indent=2, default=str) + "\n")
    print(json.dumps(comparison, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
