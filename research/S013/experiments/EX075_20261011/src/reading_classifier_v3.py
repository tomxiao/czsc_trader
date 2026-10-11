"""Pure prospective reading order; no fitting, market input or financial I/O."""

import math


def _interval(value):
    if value is None:
        return None
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise ValueError("two ordered finite CI bounds required")
    lower, upper = value
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in value) or lower > upper:
        raise ValueError("two ordered finite CI bounds required")
    return lower, upper


def classify(label, panel):
    """Apply fixed labels separately. Structural nulls precede CI availability."""
    if label not in ("return4_net", "downside4_oc"):
        raise ValueError("only two fixed primary labels permitted")
    partial = panel["partial"]
    aggregate = panel["walk_forward"]["aggregate"]
    raw_boot, partial_boot = panel["raw_bootstrap"], panel["partial_bootstrap"]
    result = {
        "label": label,
        "status": None,
        "stage": None,
        "economic_gate": False,
        "account_authorization": False,
        "next_step_ceiling": "Separate authorization for actual decision-state validation only",
        "raw_ci": raw_boot.get("ic95"),
        "partial_ci": partial_boot.get("ic95"),
        "partial_reason": partial.get("reason"),
        "oos_reason": aggregate.get("reason"),
        "raw_valid": raw_boot["valid"],
        "partial_valid": partial_boot["valid"],
        "n": partial["n"],
        "residual_df": partial["residual_df"],
        "oos_n": aggregate["n"],
        "limitations": [
            "Already-seen development pool; uncorrected descriptive CI and point OOS MSE"
        ],
    }

    def finish(status, stage):
        result.update(status=status, stage=stage)
        return result

    # The already fixed numerical sample rules are unchanged.
    if (
        partial["n"] < 20
        or partial["residual_df"] is None
        or partial["residual_df"] < 10
        or aggregate["n"] < 20
        or aggregate.get("reason") is not None
    ):
        return finish("INSUFFICIENT_DATA_OR_UNAVAILABLE", "INPUT_N_DF_OOS_COVERAGE")

    # Do not demand an impossible partial CI when a structural null is identified.
    reason = partial.get("reason")
    if reason == "CONSTANT_COMPONENT":
        return finish("CONSTANT_COMPONENT", "STRUCTURAL_NULL")
    if reason == "CONSTANT_TARGET":
        return finish("CONSTANT_TARGET", "STRUCTURAL_NULL")
    component_fraction = partial.get("component_residual_fraction")
    target_fraction = partial.get("target_residual_fraction")
    if (
        reason == "EXPLAINED_COMPONENT"
        or component_fraction is not None
        and component_fraction <= 1e-10
    ):
        result["limitations"].append(
            "Augmented ridge MSE can change effective regularization of redundant inputs; not new information"
        )
        return finish("FULLY_EXPLAINED_COMPONENT", "STRUCTURAL_NULL")
    if (
        reason == "TARGET_EXPLAINED_OR_CONSTANT"
        or target_fraction is not None
        and target_fraction <= 1e-10
    ):
        return finish("TARGET_EXPLAINED_OR_CONSTANT", "STRUCTURAL_NULL")

    ci = _interval(partial_boot.get("ic95"))
    raw_ci = _interval(raw_boot.get("ic95"))
    if partial_boot["valid"] < 400 or ci is None or partial.get("value") is None:
        return finish("INSUFFICIENT_DATA_OR_UNAVAILABLE", "GENERAL_PARTIAL_CI_AVAILABILITY")
    if raw_ci is None:
        result["limitations"].append("Raw CI unavailable; no raw-direction assertion is made")

    mse_names = ("mse_controls", "mse_augmented", "mse_pastmean")
    if any(aggregate.get(k) is None or not math.isfinite(aggregate[k]) for k in mse_names):
        return finish("INSUFFICIENT_DATA_OR_UNAVAILABLE", "OOS_METRICS_UNAVAILABLE")
    improved_controls = aggregate["mse_augmented"] < aggregate["mse_controls"]
    improved_mean = aggregate["mse_augmented"] < aggregate["mse_pastmean"]
    result.update(
        improved_controls=improved_controls,
        improved_pastmean=improved_mean,
        delta_controls=aggregate["mse_controls"] - aggregate["mse_augmented"],
        delta_pastmean=aggregate["mse_pastmean"] - aggregate["mse_augmented"],
    )
    lower, upper = ci
    expected = upper < 0 if label == "return4_net" else lower > 0
    opposite = lower > 0 if label == "return4_net" else upper < 0
    raw_opposite = raw_ci is not None and (
        raw_ci[0] > 0 if label == "return4_net" else raw_ci[1] < 0
    )
    if opposite:
        return finish("OPPOSITE_DIRECTION_COUNTEREVIDENCE", "FIXED_DIRECTION")
    if expected and raw_opposite:
        return finish("INCONCLUSIVE_RAW_PARTIAL_CONFLICT", "RAW_PARTIAL_CONFLICT")
    if expected and improved_controls and improved_mean:
        category = (
            "LIMITED_FULL_POOL_RETURN_INFORMATION"
            if label == "return4_net"
            else "LIMITED_FULL_POOL_RISK_INFORMATION"
        )
        return finish(category, "FIXED_DIRECTION_AND_BOTH_BASELINES")
    if expected:
        return finish(
            "CORRELATED_WITHOUT_CONFIRMED_PREDICTIVE_INCREMENT", "BASELINE_COUNTEREVIDENCE"
        )
    if improved_controls and improved_mean:
        return finish("INCONCLUSIVE_PREDICTIVE_ONLY", "DIRECTION_UNCERTAIN")
    return finish("NO_INCREMENT_OBSERVED", "DIRECTION_AND_BASELINE_UNSUPPORTED")
