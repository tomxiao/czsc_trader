"""Adjusted observation roles preserve raw execution and shared physical calendars."""

from dataclasses import replace
import json
import pytest
from dataflows import EquityDataRequest, EquityProduct, MarketId, PriceAdjustment
from strategy_runtime import EquityInputBinding
from packages.strategy_runtime.tests.context_fixture_support import make_candidate
from packages.strategy_runtime.tests.binding_fixture_support import binding_fixture


@pytest.mark.parametrize(
    "market",
    [
        MarketId.CN,
        MarketId.US,
    ],
    ids=["SRT-09-C01", "SRT-09-C02"],
)
def test_hfq_roles_roundtrip_and_shared_calendar(market):
    binding, items = binding_fixture(market)
    serialized = json.loads(json.dumps(binding.to_dict()))
    assert EquityInputBinding.from_dict(serialized) == binding
    assert len(set(r.parameters for _, r in items)) == 3
    assert binding.bind_requests(tuple(r for _, r in items)) == items
    assert binding.bind_requests(tuple(dict((r.parameters, r) for _, r in items).values())) == items
    with pytest.raises(ValueError, match="shared roles"):
        binding.request_key(items[-2][1])
    assert items[-2][1].parameters.query.adjustment is PriceAdjustment.BACKWARD
    assert items[-1][1].parameters.query.adjustment is PriceAdjustment.NONE
    with pytest.raises(ValueError, match="shared roles"):
        binding.request_key(items[-1][1])
    with pytest.raises(ValueError, match="bound product selection"):
        binding.bind_requests(
            tuple(r for _, r in items if r.parameters.query.product is EquityProduct.SESSIONS)
        )
    bad = replace(items[-2][1].parameters.query, adjustment=PriceAdjustment.FORWARD)
    request = EquityDataRequest(binding.instrument, items[-2][1].parameters.source, bad)
    with pytest.raises(ValueError, match="bound product selection"):
        binding.bind_requests(tuple(r for _, r in items) + (request,))


def test_SRT_08_C05_binding_rejects_role_or_fingerprint_substitution():
    binding, items = binding_fixture(MarketId.US)
    with pytest.raises(ValueError, match="explicit request bindings"):
        replace(binding, request_bindings=())
    with pytest.raises(ValueError, match="exact product roles"):
        replace(binding, request_bindings=binding.request_bindings[:-1])
    with pytest.raises(ValueError, match="declared observation"):
        replace(
            binding,
            request_bindings=tuple(
                (
                    key,
                    replace(p, query=replace(p.query, adjustment=PriceAdjustment.NONE))
                    if key == "auxiliary:adjusted:bars"
                    else p,
                )
                for key, p in binding.request_bindings
            ),
        )
    with pytest.raises(ValueError, match="inconsistent content"):
        replace(
            binding,
            auxiliary_inputs=(replace(binding.auxiliary_inputs[0], sessions_sha256="e" * 64),),
        )
    with pytest.raises(ValueError, match="traded HFQ"):
        replace(
            binding,
            request_bindings=tuple(
                (
                    key,
                    replace(p, query=replace(p.query, adjustment=PriceAdjustment.NONE))
                    if key == "bars"
                    else p,
                )
                for key, p in binding.request_bindings
            ),
        )


@pytest.mark.parametrize("role", ["primary", "auxiliary"], ids=["SRT-09-C03", "SRT-09-C04"])
def test_v4_observations_reject_raw_basis(tmp_path, role):
    from strategy_runtime import StrategyComputation, StrategyStateSchema
    from strategy_runtime.models import ExecutionPolicy
    from strategy_runtime.equity_features import FeatureGraph

    original = make_candidate(tmp_path).definition
    auxiliary = replace(
        original.auxiliary_inputs[0], instrument=original.instrument, analysis_price="HFQ"
    )
    v4 = replace(
        original,
        contract_version=4,
        analysis_price="HFQ",
        execution_policy=ExecutionPolicy("TARGET_POSITION", {}),
        feature_graph=FeatureGraph(),
        state_schema=StrategyStateSchema(),
        computation=StrategyComputation.STATEFUL_STEP,
        auxiliary_inputs=(auxiliary,),
    )
    changes = (
        {"analysis_price": "RAW"}
        if role == "primary"
        else {"auxiliary_inputs": (replace(auxiliary, analysis_price="RAW"),)}
    )
    with pytest.raises(ValueError, match="analysis price contract" if role == "primary" else "HFQ"):
        replace(v4, **changes)
