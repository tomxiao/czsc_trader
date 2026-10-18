"""One source-pinned CZCE calendar omission; never infer other holidays."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .errors import DataRepairError
from .history_patches.common import frame_content_sha256


PATCH_ID = "CZCE_CALENDAR_20221231_V1"
PATCH_VERSION = 1
PATCH_SOURCE_HASHES = (
    "64b6e3670a44f71c865aedb53ecd9a4505846f77dee45cdafe92a3c9f690d4e6",
    "1e0d63309187bd8d6867328d2d4a79e32d593d0fa370fab5c19858881fd06eab",
)
_SOURCES = (
    {
        "url": "https://www.czce.com.cn/cn/uploadfile/2022/08/31/20220831175459720.pdf",
        "sha256": PATCH_SOURCE_HASHES[0],
        "title": "郑州商品交易所甲醇期货业务细则",
        "published_date": "2022-08-31",
        "effective_date": "2022-12-01",
        "article": 8,
        "page": 1,
    },
    {
        "url": "https://app.www.gov.cn/govdata/gov/202212/08/495070/article.html",
        "sha256": PATCH_SOURCE_HASHES[1],
        "title": "国务院办公厅关于2023年部分节假日安排的通知",
        "published_date": "2022-12-08",
        "article": 1,
    },
)
_DATE = pd.Timestamp("2022-12-31")
_PREVIOUS = pd.Timestamp("2022-12-30")


def apply_czce_calendar_patch(
    dataframe: pd.DataFrame,
    *,
    exchange: str,
    start_date: str,
    end_date: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Insert only the certified missing date, or reject contradictory facts.

    The two official sources establish the holiday under the then-effective
    MA trading rule. This is not a copy of CZCE notice 2022/719. The previous
    session must be present in the input, rather than guessed or fetched.
    """
    if exchange != "CZCE" or not pd.Timestamp(start_date) <= _DATE <= pd.Timestamp(end_date):
        return dataframe.copy(), {}
    required = {"Date", "IsOpen", "PreviousTradingDate"}
    if set(dataframe.columns) != required:
        raise DataRepairError(f"{PATCH_ID}: canonical calendar columns required")
    dates = pd.to_datetime(dataframe["Date"], errors="coerce")
    if dates.isna().any() or dates.duplicated().any() or not dates.eq(dates.dt.normalize()).all():
        raise DataRepairError(f"{PATCH_ID}: unique normalized calendar dates required")
    target = dataframe.loc[dates.eq(_DATE)]
    if not target.empty:
        row = target.iloc[0]
        if row["IsOpen"] != 0 or pd.Timestamp(row["PreviousTradingDate"]) != _PREVIOUS:
            raise DataRepairError(f"{PATCH_ID}: existing holiday row conflicts with official evidence")
        return dataframe.copy(), {}
    previous = dataframe.loc[dates.eq(_PREVIOUS)]
    if len(previous) != 1 or previous.iloc[0]["IsOpen"] != 1:
        raise DataRepairError(f"{PATCH_ID}: verified previous session 2022-12-30 required")
    raw_hash = frame_content_sha256(dataframe)
    row = pd.DataFrame({"Date": [_DATE], "IsOpen": [0], "PreviousTradingDate": [_PREVIOUS]})
    repaired = pd.concat([dataframe, row], ignore_index=True).sort_values("Date").reset_index(drop=True)
    record = {
        "patch_id": PATCH_ID,
        "patch_version": PATCH_VERSION,
        "evidence_basis": "OFFICIAL_RULE_AND_GOVERNMENT_HOLIDAY",
        "exchange": exchange,
        "affected_dates": ["2022-12-31"],
        "original_row": None,
        "repaired_row": {
            "Date": "2022-12-31", "IsOpen": 0, "PreviousTradingDate": "2022-12-30",
        },
        "previous_session_basis": "EXISTING_INPUT_CALENDAR_OPEN_ROW",
        "raw_content_sha256": raw_hash,
        "repaired_content_sha256": frame_content_sha256(repaired),
        "official_sources": [dict(source) for source in _SOURCES],
    }
    return repaired, {"calendar_repairs": [record]}
