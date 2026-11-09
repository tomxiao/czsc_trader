# Risk ownership: TDR-28
"""Overnight PTE preparation cannot see next-session publication arrivals."""
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from dataflows import EquityProduct, MarketId, TimeInterval
from czsc_trader.research_tools import ResearchExecutionSession
from paper_trading_engine.equity_advice import prepare_equity_decision
from paper_trading_engine.execution_inputs import resolve_live_context
from test_formal_v4_runtime import raw_binding
from test_v4_dataset_observation_flow import observation_fixture


@pytest.mark.parametrize('market', [MarketId.US])
def test_overnight_observations_cap_primary_auxiliary_tables_and_raw(tmp_path, market):
    context, request, products, _ = observation_fixture(tmp_path, market)
    with ResearchExecutionSession(context, experiment=request.experiment) as session:
        request = context.evaluation.prepare(request, execution=session).request
    row = products[EquityProduct.BARS].iloc[2]
    interval = TimeInterval(row.BarStart.to_pydatetime(), row.Date.to_pydatetime())
    previous_close = products[EquityProduct.BARS].iloc[1].Date.to_pydatetime()
    as_of = previous_close + timedelta(hours=5)
    binding = request.input_binding.for_observations()
    requests = tuple(query for query in request.requests(context.execution_spec)
                     if getattr(query.parameters, 'query', None) is None
                     or query.parameters.query.product is not EquityProduct.TRADING_FACTS)
    sessions = next(query for role, query in binding.bind_requests(requests) if role == 'sessions')
    calendar = context.data.fetch(sessions, prepared=binding.prepared)
    raw = raw_binding(context.data, binding)
    reference = raw.fetch(context.data, interval, latency_seconds=0, as_of=as_of)
    prepared = prepare_equity_decision(context.data, request.candidate, binding, requests,
        interval, fee_rate=request.fee_rate, live=True, as_of=as_of,
        execution_reference=reference,
        execution_context=resolve_live_context(request.candidate, interval,
            calendar.dataframe, calendar.identity.metadata))
    assert prepared.as_of == as_of
    assert prepared.interval == interval
    assert prepared.execution_reference.observed_through == previous_close
    assert max(prepared.v4_replay._data.ends) == previous_close
    assert all(max(data.ends) <= as_of for _, data in prepared.v4_replay._auxiliary)
    for _, table in prepared.v4_replay._observations:
        assert table.view(interval.start).rows == table.view(as_of).rows
    if market is MarketId.US:
        weights = dict(prepared.v4_replay._observations)['weights']
        assert len(weights.view(interval.start)) == 4
    with pytest.raises(ValueError, match='no later than execution start'):
        replace(prepared, as_of=interval.start + timedelta(seconds=1))

    # A price publication dated T but arriving after this run cannot supply
    # the execution reference merely because T+1 has not yet opened.
    fetched = context.data.fetch(raw.request, prepared=raw.prepared)
    frame = fetched.dataframe.copy(deep=True)
    frame.loc[frame.Date == previous_close, 'AvailableDate'] = as_of + timedelta(seconds=1)
    dataflows = SimpleNamespace(fetch=lambda *args, **kwargs: SimpleNamespace(
        ready=True, identity=fetched.identity, dataframe=frame))
    assert raw.fetch(dataflows, interval, latency_seconds=0).observed_through == previous_close
    assert raw.fetch(dataflows, interval, latency_seconds=0, as_of=as_of).observed_through < previous_close
    for invalid in (as_of.replace(tzinfo=None), interval.start + timedelta(seconds=1)):
        with pytest.raises(ValueError, match='cutoff'):
            raw.fetch(dataflows, interval, latency_seconds=0, as_of=invalid)
