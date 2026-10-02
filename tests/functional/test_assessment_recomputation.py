from dataclasses import replace
import math

import numpy as np
import pytest
from threadpoolctl import threadpool_limits

from strategy_evaluator import (
    annualized_sharpe,
    calculate_dsr_bundle,
    effective_trial_count,
    research_models as m,
)
from czsc_trader.application.delivery_service import _assessment_recomputation_matches


def panel(effective=0.6396147383007816):
    return m.AssessmentPanel(
        "1" * 64,
        "2" * 64,
        (),
        tuple(
            m.FamilyDiagnostic(name, m.DiagnosticStatus.AVAILABLE, value, None)
            for name, value in (("PBO", 0.5), ("DSR_RAW", 0.25), ("DSR_EFFECTIVE", effective))
        ),
        (),
    )


def diagnostic_value(original, index, value):
    diagnostics = list(original.family_diagnostics)
    diagnostics[index] = replace(diagnostics[index], value=value)
    return replace(original, family_diagnostics=tuple(diagnostics))


@pytest.mark.parametrize("probability", [0.0, 1e-250, 0.6396147383007816, 1.0])
def test_effective_dsr_accepts_exact_values_and_finite_roundoff(probability):
    saved = panel(probability)
    assert _assessment_recomputation_matches(saved, saved)
    if probability:
        rounded = diagnostic_value(saved, 2, math.nextafter(probability, 0.0))
        assert _assessment_recomputation_matches(rounded, saved)
        assert _assessment_recomputation_matches(saved, rounded)


@pytest.mark.parametrize(
    ("saved_value", "changed_value"),
    [
        (0.6396147383007816, 0.639614738300782),  # Observed S011 1/16-thread difference.
        (0.5, 0.5 * (1 + 0.5e-12)),
    ],
)
def test_effective_dsr_accepts_bounded_relative_error(saved_value, changed_value):
    assert _assessment_recomputation_matches(panel(changed_value), panel(saved_value))


@pytest.mark.parametrize(
    ("saved_value", "changed_value"),
    [
        (0.5, 0.5 * (1 + 2e-12)),
        (0.5, 0.500001),
        (0.0, math.nextafter(0.0, 1.0)),
        (1e-250, 2e-250),
        (1.0, math.nextafter(1.0, math.inf)),
    ],
)
def test_effective_dsr_rejects_excess_error_and_invalid_probabilities(saved_value, changed_value):
    assert not _assessment_recomputation_matches(panel(changed_value), panel(saved_value))


@pytest.mark.parametrize("index", [0, 1])
def test_other_family_statistics_remain_exact(index):
    saved = panel()
    value = saved.family_diagnostics[index].value
    changed = diagnostic_value(saved, index, math.nextafter(value, 1.0))
    assert not _assessment_recomputation_matches(changed, saved)


def test_diagnostic_identity_status_order_and_panel_identity_remain_exact():
    saved = panel()
    first, second, effective = saved.family_diagnostics
    variants = (
        replace(saved, request_sha256="3" * 64),
        replace(saved, protocol_sha256="3" * 64),
        replace(saved, family_limitations=("changed",)),
        replace(saved, family_diagnostics=(first, second)),
        replace(saved, family_diagnostics=(effective, second, first)),
        replace(saved, family_diagnostics=(first, second, replace(effective, name="renamed"))),
        replace(
            saved,
            family_diagnostics=(
                first,
                second,
                m.FamilyDiagnostic(
                    "DSR_EFFECTIVE", m.DiagnosticStatus.INSUFFICIENT_DATA, None, "missing"
                ),
            ),
        ),
    )
    for changed in variants:
        assert not _assessment_recomputation_matches(changed, saved)


def test_correlated_return_statistics_recompute_across_native_thread_counts():
    rng = np.random.default_rng(37)
    common = rng.normal(0.001, 0.01, (128, 1))
    matrix = common + rng.normal(0, 0.002, (128, 64))
    values = []
    for threads in (1, 2, 8, 16):
        with threadpool_limits(limits=threads):
            sharpes = np.array([annualized_sharpe(column) for column in matrix.T])
            bundle = calculate_dsr_bundle(
                matrix[:, 0], sharpes, raw_count=64, effective_count=effective_trial_count(matrix)
            )
            values.append(panel(bundle.effective.probability))
    assert all(_assessment_recomputation_matches(value, values[0]) for value in values)
