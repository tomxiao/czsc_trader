from dataclasses import replace
import pytest
from strategy_runtime import (
    materialize_observation,
    SignalAvailability,
)
from packages.strategy_runtime.tests.observation_fixture_support import (
    signal_panel_plan,
)


@pytest.mark.parametrize(
    "status,reason",
    [
        ("INACTIVE", None),
    ],
    ids=["SRT-25-C03"],
)
def test_v3_inactive_and_unavailable_values_do_not_leak_stale_targets_or_guides(status, reason):
    definition, plan = signal_panel_plan()
    evidence = dict(plan.evidence, obs_target_status=status, obs_reason=reason)
    for key in ("obs_target", "obs_segment", "obs_center"):
        evidence.pop(key)
    observed = materialize_observation(definition, replace(plan, evidence=evidence))
    target = observed.signal_panel.series[1]
    assert target.status == SignalAvailability(status)
    assert target.value is None and target.segment_id is None and target.guides == ()
    assert target.reason == reason
