from __future__ import annotations

from hashlib import sha256
import sqlite3

import pandas as pd
import pytest

from dataflows import (
    DataRequest,
    PreparePolicy,
    EvidenceParameters,
    DataStatus,
    Dataset,
    IncompleteDataError,
    SourceNotReadyError,
)
from dataflows.errors import EmptyDataError, DataContractError, SourceRequestError


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Date": ["2026-09-14", "2026-09-15"],
            "Open": [1.0, 1.1],
            "High": [1.2, 1.3],
            "Low": [0.9, 1.0],
            "Close": [1.1, 1.2],
            "Volume": [100, 120],
            "Amount": [105.0, 138.0],
        }
    )


def _request(dataset: str | Dataset = Dataset.ETF_OHLCV) -> DataRequest:
    return DataRequest(dataset, "588080.SH", "2026-09-14", "2026-09-15", "2026-09-15")


@pytest.mark.parametrize(
    "error_type,status",
    [
        (SourceNotReadyError, DataStatus.WAITING_SOURCE),
        (EmptyDataError, DataStatus.EMPTY),
        (IncompleteDataError, DataStatus.INCOMPLETE),
        (DataContractError, DataStatus.FAILED),
        (SourceRequestError, DataStatus.FAILED),
    ],
    ids=["DFLS-04-C01", "DFLS-04-C02", "DFLS-04-C03", "DFLS-04-C04", "DFLS-04-C05"],
)
def test_public_prepare_preserves_error_semantics_without_publication(
    flow_factory, tmp_path, error_type, status
):
    failure = error_type("source rejected", missing_date="2026-09-15")
    if error_type is EmptyDataError:
        assert isinstance(failure, ValueError)

    def provider(request):
        raise failure

    request = DataRequest(Dataset.SHIBOR_DAILY, None, "2026-09-15", "2026-09-15", None)
    flow = flow_factory({Dataset.SHIBOR_DAILY: provider})
    result = flow.prepare((request,), policy=PreparePolicy.REFRESH)
    assert not result.ready and result.reference is None
    (item,) = result.items
    assert item.status is status and item.identity is None
    assert (item.error.code, item.error.retryable) == (failure.code, failure.retryable)
    assert item.error.context["missing_date"] == "2026-09-15"
    with sqlite3.connect(tmp_path / "space-0/assets.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM asset_lookup").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM preparations").fetchone()[0] == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"dataset": "unknown.dataset"},
        {"start": "2026-09-16"},
        {"dataset": Dataset.COMPANY_FINANCIAL_DISCLOSURES, "frequency": "daily"},
    ],
    ids=["DFLS-01-C01", "DFLS-01-C02", "DFLS-01-C03"],
)
def test_request_shape_rejected_without_acquisition(changes):
    args = dict(
        dataset=Dataset.SHIBOR_DAILY,
        symbol=None,
        start="2026-09-14",
        end="2026-09-15",
        required_cutoff=None,
    )
    if changes.get("dataset") is Dataset.COMPANY_FINANCIAL_DISCLOSURES:
        args["symbol"] = "600000.SH"
    with pytest.raises(ValueError):
        DataRequest(**{**args, **changes})


@pytest.mark.parametrize(
    "through", [pd.Timestamp("2026-09-14"), "not-a-date"], ids=["DFLS-01-C04", "DFLS-01-C05"]
)
def test_observation_cutoff_requires_explicit_iso_string(through):
    from dataflows import DataCoverageRequirement

    with pytest.raises(ValueError, match="observations_through"):
        DataCoverageRequirement(observations_through=through)


def test_DFLS_01_C06_cn_instrument_rejects_us_symbol():
    from dataflows import InstrumentId, MarketId, AssetClass

    with pytest.raises(ValueError):
        InstrumentId(MarketId.CN, AssetClass.STOCK, "AAPL")


@pytest.mark.parametrize(
    "defect",
    [None, "duplicate", "missing", "null", "legacy", "conflict"],
    ids=["DFLS-02-C01", "DFLS-02-C02", "DFLS-02-C03", "DFLS-02-C04", "DFLS-02-C05", "DFLS-02-C06"],
)
def test_panel_primary_key_values_and_declaration(defect):
    from dataflows.facade import _date_bounds

    frame = pd.DataFrame(
        {"Date": ["2026-09-15"] * 2, "ConstituentSymbol": ["600000.SH", "600001.SH"]}
    )
    request = DataRequest(
        Dataset.INDEX_CONSTITUENT_WEIGHT,
        "000905.SH",
        "2026-09-15",
        "2026-09-15",
        None,
        frequency="snapshot",
    )
    metadata = {} if defect == "legacy" else {"primary_key": ["Date", "ConstituentSymbol"]}
    if defect == "duplicate":
        frame.loc[1, "ConstituentSymbol"] = "600000.SH"
    elif defect == "missing":
        frame = frame.drop(columns="ConstituentSymbol")
    elif defect == "null":
        frame.loc[1, "ConstituentSymbol"] = None
    elif defect == "conflict":
        metadata["primary_key"] = ["Date"]
    if defect in {None, "legacy"}:
        before = dict(metadata)
        assert _date_bounds(frame, request, metadata) == ("2026-09-15T00:00:00",) * 2
        assert len(frame) == 2 and metadata == before
    else:
        with pytest.raises(DataContractError):
            _date_bounds(frame, request, metadata)


def test_DFLS_40_C01_feature_evidence_pinned_subset(flow_factory, publish_data, tmp_path) -> None:
    source = tmp_path / "evidence.csv"
    source.write_text(
        "date,feature\n2026-09-01,1.0\n2026-09-02,2.0\n",
        encoding="utf-8",
    )
    request = DataRequest(
        Dataset.STRATEGY_FEATURE_EVIDENCE,
        "S007-v1",
        "2026-09-02",
        "2026-09-03",
        None,
        parameters=EvidenceParameters(
            repository_root=tmp_path,
            source_path=source.name,
            source_sha256=sha256(source.read_bytes()).hexdigest(),
        ),
    )

    result = publish_data(flow_factory(), request)

    assert result.status is DataStatus.READY
    assert result.dataframe["Date"].dt.strftime("%Y-%m-%d").tolist() == ["2026-09-02"]
    assert result.identity is not None
    assert result.identity.source == "repository"


def test_DFLS_40_C02_feature_evidence_rejects_changed_bytes(flow_factory, tmp_path):
    source = tmp_path / "evidence.csv"
    source.write_text("date,feature\n2026-09-02,1.0\n", encoding="utf8")
    params = EvidenceParameters(
        repository_root=tmp_path,
        source_path="evidence.csv",
        source_sha256=sha256(source.read_bytes()).hexdigest(),
    )
    request = DataRequest(
        Dataset.STRATEGY_FEATURE_EVIDENCE,
        "S007-v1",
        "2026-09-02",
        "2026-09-02",
        None,
        parameters=params,
    )
    source.write_text("date,feature\n2026-09-02,2.0\n", encoding="utf8")
    result = flow_factory().prepare((request,), policy=PreparePolicy.REFRESH)
    assert result.reference is None and result.items[0].status is DataStatus.FAILED
    assert result.items[0].identity is None


def test_DFLS_40_C03_feature_evidence_rejects_escaping_path(tmp_path):
    with pytest.raises(ValueError):
        EvidenceParameters(
            repository_root=tmp_path, source_path="../evidence.csv", source_sha256="a" * 64
        )
