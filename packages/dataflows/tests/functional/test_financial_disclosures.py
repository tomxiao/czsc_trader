"""Public preparation of observed filings, with an offline vendor boundary."""

from __future__ import annotations

from dataclasses import replace
import json

import pandas as pd
import pytest

from dataflows import (
    DataCoverageRequirement, DataRequest, DataStatus, Dataset, FinancialDisclosureParameters,
    FinancialReportKind, FinancialReportType, PreparePolicy, PrepareStatus, SourceRequestError,
)
from dataflows.errors import DataContractError, EmptyDataError, IncompleteDataError
from dataflows.financial_disclosures import fetch_company_financial_disclosures


_NUMBERS = {
    FinancialReportKind.INCOME: dict(revenue=100.25, oper_cost=60, operate_profit=20, total_profit=22,
                                    n_income=18, n_income_attr_p=15, minority_gain=3, income_tax=4,
                                    non_oper_income=2, non_oper_exp=None),
    FinancialReportKind.BALANCE_SHEET: dict(total_assets=1000, total_liab=300, total_hldr_eqy_exc_min_int=600,
        total_hldr_eqy_inc_min_int=700, money_cap=100, accounts_receiv=10, notes_receiv=5, inventories=25,
        contract_assets=None, fix_assets=200, cip=50),
    FinancialReportKind.CASH_FLOW: dict(net_profit=18, n_cashflow_act=-2, c_fr_sale_sg=120,
                                       c_paid_goods_s=90, c_pay_acq_const_fiolta=None),
    FinancialReportKind.FINANCIAL_INDICATOR: dict(profit_dedt=10, extra_item=5, grossprofit_margin=40.25,
        ocfps=0.15, roe=2.1, q_dtprofit=5, q_gsprofit_margin=None, q_sales_yoy=-5,
        q_netprofit_yoy=7.25, dt_netprofit_yoy=2.5),
}


def _row(kind=FinancialReportKind.INCOME, **changes):
    row = dict(ts_code="600722.SH", ann_date="20250425", end_date="20250331", update_flag="1",
               **_NUMBERS[kind])
    if kind is not FinancialReportKind.FINANCIAL_INDICATOR:
        row.update(f_ann_date="20250425", report_type="1", comp_type="1")
    return {**row, **changes}


def _request(kind=FinancialReportKind.INCOME, **changes):
    parameters = FinancialDisclosureParameters(
        kind, "2024-12-31", "2025-03-31",
        None if kind is FinancialReportKind.FINANCIAL_INDICATOR else FinancialReportType.LATEST_CONSOLIDATED,
    )
    return replace(DataRequest(Dataset.COMPANY_FINANCIAL_DISCLOSURES, "600722.SH", "2025-04-01",
                               "2025-04-30", None, frequency="event", parameters=parameters), **changes)


class FinancialPro:
    def __init__(self, rows, *, failure=None, gap=None):
        self.rows = rows
        self.failure = failure
        self.gap = gap
        self.calls = []
        self.calendar_calls = []

    def __getattr__(self, api):
        if api not in {kind.value for kind in FinancialReportKind}:
            raise AssertionError(f"unexpected API: {api}")

        def fetch(**kwargs):
            self.calls.append((api, kwargs))
            if self.failure:
                raise self.failure
            return pd.DataFrame(self.rows, dtype=object)
        return fetch

    def trade_cal(self, **kwargs):
        self.calendar_calls.append(kwargs)
        days = pd.date_range(kwargs["start_date"], kwargs["end_date"])
        if self.gap:
            days = days[days != pd.Timestamp(self.gap)]
        return pd.DataFrame(dict(cal_date=days.strftime("%Y%m%d"), is_open=(days.weekday < 5).astype(int)))


def _bind(monkeypatch, pro):
    monkeypatch.setattr("dataflows.financial_disclosures.get_tushare_pro", lambda ignored=None: pro)


@pytest.mark.parametrize("kind", list(FinancialReportKind), ids=['DFLS-31-C01', 'DFLS-31-C02', 'DFLS-31-C03', 'DFLS-31-C04'])
def test_prepare_and_pinned_fetch_preserve_four_kinds_raw_nulls_versions_and_identity(
    kind, monkeypatch, flow_factory,
):
    # Same-period null/value variants and exact duplicates must all survive.
    first = _row(kind)
    nullable = next(field for field, value in _NUMBERS[kind].items() if value is None)
    second = _row(kind, **{nullable: 9.125, "update_flag": "0"})
    pro = FinancialPro([first, second, first.copy()])
    _bind(monkeypatch, pro)
    flow, request = flow_factory(), _request(kind)
    prepared = flow.prepare((request,), policy=PreparePolicy.REFRESH)
    assert prepared.ready, prepared.items
    result = flow.fetch(request, prepared=prepared.reference)
    assert result.ready, result.error
    assert len(result.dataframe) == 3
    assert result.dataframe.RecordId.nunique() == 3
    assert result.dataframe[nullable].isna().sum() == 2
    assert result.dataframe[nullable].dropna().tolist() == [9.125]
    assert sorted(result.dataframe.update_flag) == ["0", "1", "1"]
    assert result.dataframe.Date.eq(pd.Timestamp("2025-04-25")).all()
    # Friday filing -> Monday decision at 15:00 (synthetic weekday calendar).
    assert result.dataframe.AvailableDate.eq(pd.Timestamp("2025-04-28 15:00")).all()
    observed_raw = [json.loads(value) for value in result.dataframe.RawRecord]
    assert observed_raw.count(first) == 2 and observed_raw.count(second) == 1
    assert result.prepared == prepared.reference
    metadata = result.identity.metadata
    assert metadata["version_status"] == "MULTIPLE_OBSERVED_ROWS"
    assert metadata["ambiguous_report_periods"] == ["20250331"]
    assert metadata["original_disclosure_version_verified"] is False
    assert metadata["historical_vendor_arrival_verified"] is False
    assert metadata["historical_revision_history_verified"] is False
    assert len(metadata["source_response_sha256"]) == 64
    assert pd.Timestamp(metadata["retrieved_at"]).tzinfo is not None
    assert result.identity.temporal_contract.availability_time_field == "AvailableDate"
    assert metadata["provider_binding"] and metadata["dfls_revision"]
    api, query = pro.calls[0]
    assert api == kind.value and query["start_date"] == "20241231"
    indicator = kind is FinancialReportKind.FINANCIAL_INDICATOR
    assert query["end_date"] == ("20250331" if indicator else "20250430")
    assert ("report_type" not in query) if indicator else query["report_type"] == "1"
    assert metadata["period_basis"] == (
        "MIXED_CUMULATIVE_AND_SINGLE_QUARTER" if indicator else
        "PERIOD_END_SNAPSHOT" if kind is FinancialReportKind.BALANCE_SHEET else "YEAR_TO_DATE_CUMULATIVE"
    )
    assert flow.prepare((request,), policy=PreparePolicy.REUSE).reference == prepared.reference
    # Reading and reuse stay offline even if the vendor becomes unavailable.
    pro.failure = AssertionError("pinned reads must not query")
    subset = flow.fetch(replace(request, start="2025-04-25", end="2025-04-25"), prepared=prepared.reference)
    assert subset.ready and subset.identity.content_sha256 == result.identity.content_sha256
    assert len(pro.calls) == len(pro.calendar_calls) == 1


def test_DFLS_31_C05_actual_disclosure_controls_window_and_availability():
    pro = FinancialPro([
        _row(ann_date="20250331", f_ann_date="20250425"),
        _row(ann_date="20250425", f_ann_date="20250506", revenue=200),
        _row(ann_date="20250425", f_ann_date=None, revenue=300),
    ])
    request = _request()
    frame, metadata = fetch_company_financial_disclosures(request, pro=pro)
    assert sorted(frame.revenue) == [100.25, 300]
    assert metadata["excluded_rows"] == 1
    assert frame.AvailableDate.eq(pd.Timestamp("2025-04-28 15:00")).all()
    # Report-period window alone cannot allow a future disclosure into a past input.
    pro.rows = [_row(f_ann_date="20250506")]
    with pytest.raises(EmptyDataError):
        fetch_company_financial_disclosures(request, pro=pro)




@pytest.mark.parametrize("mutation", [
    {'revenue': '100.25'},
    {'revenue': True},
], ids=['DFLS-31-C06', 'DFLS-31-C07'])
def test_invalid_financial_source_is_rejected_before_calendar(mutation):
    pro = FinancialPro([_row(**mutation)])
    with pytest.raises(DataContractError) as raised:
        fetch_company_financial_disclosures(_request(), pro=pro)
    assert raised.value.code == "DATA_CONTRACT_MISMATCH"
    assert len(pro.calls) == 1 and not pro.calendar_calls


@pytest.mark.parametrize(("fault", "status", "code"), [
    ('possible_truncation', DataStatus.INCOMPLETE, 'INCOMPLETE_DATA'),
    ('expected_period', DataStatus.INCOMPLETE, 'INCOMPLETE_DATA'),
], ids=['DFLS-32-C01', 'DFLS-32-C02'])
def test_empty_incomplete_or_failed_financial_preparation_never_has_a_reference(
    fault, status, code, monkeypatch, flow_factory,
):
    row = _row()
    if fault == "missing_field":
        del row["revenue"]
    pro = FinancialPro([] if fault == "empty" else [row] * (100 if fault == "possible_truncation" else 1),
        failure=SourceRequestError("source denied") if fault == "source_rejection" else None,
        gap="2025-04-26" if fault == "calendar_gap" else None)
    request = _request()
    if fault == "expected_period":
        request = replace(request, parameters=replace(request.parameters, expected_periods=("2024-12-31", "2025-03-31")))
    if fault == "coverage":
        request = replace(request, coverage=DataCoverageRequirement(maximum_start_lag_days=None, minimum_observations=2))
    if fault == "coverage":
        # Coverage is a public preparation responsibility, not a source parser rule.
        _bind(monkeypatch, pro)
        prepared = flow_factory().prepare((request,), policy=PreparePolicy.REFRESH)
        assert prepared.status is PrepareStatus.FAILED and prepared.reference is None
        item, = prepared.items
        assert item.status is status and item.error.code == code and item.identity is None
    else:
        expected = {"EMPTY_DATA": EmptyDataError, "DATA_CONTRACT_MISMATCH": DataContractError,
                    "SOURCE_REQUEST_FAILED": SourceRequestError, "INCOMPLETE_DATA": IncompleteDataError}[code]
        with pytest.raises(expected) as caught:
            fetch_company_financial_disclosures(request, pro=pro)
        assert caught.value.code == code
        if fault == "expected_period":
            assert caught.value.context["missing_periods"] == ["2024-12-31"]
    assert len(pro.calls) == 1


def test_DFLS_32_C03_partial_financial_batch_has_no_global_reference(monkeypatch, flow_factory):
    pro = FinancialPro([_row()])
    _bind(monkeypatch, pro)
    first = _request()
    second = replace(first, parameters=replace(first.parameters, expected_periods=("2024-12-31",)))
    prepared = flow_factory().prepare((first, second), policy=PreparePolicy.REFRESH)
    assert prepared.status is PrepareStatus.PARTIAL and prepared.reference is None
    assert [item.status for item in prepared.items] == [DataStatus.READY, DataStatus.INCOMPLETE]


def test_DFLS_32_C04_refresh_preserves_old_financial_observations(monkeypatch, flow_factory):
    pro = FinancialPro([_row()])
    _bind(monkeypatch, pro)
    flow, request = flow_factory(), _request()
    original = flow.prepare((request,), policy=PreparePolicy.REFRESH)
    assert original.ready
    pro.rows = [_row(revenue=999)]
    refreshed = flow.prepare((request,), policy=PreparePolicy.REFRESH)
    assert refreshed.ready and refreshed.reference != original.reference
    assert flow.fetch(request, prepared=original.reference).dataframe.revenue.tolist() == [100.25]
    assert flow.fetch(request, prepared=refreshed.reference).dataframe.revenue.tolist() == [999]
    wrong_kind = flow.fetch(_request(FinancialReportKind.CASH_FLOW), prepared=original.reference)
    assert wrong_kind.error.code == "REQUEST_NOT_PREPARED"
    expanded = flow.fetch(replace(request, end="2025-05-01"), prepared=original.reference)
    assert expanded.error.code == "REQUEST_NOT_PREPARED"
    strict = flow.fetch(replace(request, required_cutoff="2025-04-30"), prepared=original.reference)
    assert strict.status is DataStatus.INCOMPLETE
