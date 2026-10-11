"""Fixed positive-return scientific reading; risk never changes trading role."""

import math


def classify(panel):
    partial = panel["partial"]
    boot = panel["partial_bootstrap"]
    oos = panel["walk_forward"]["aggregate"]
    result = {"status": None, "positive_return_prior": True, "economic_gate": False,
              "strategy_qualification": False, "account_authorization": False,
              "partial_ci": boot["ic95"], "partial_n": partial["n"], "oos_n": oos["n"],
              "reason": None}
    if (partial["n"] < 20 or partial["residual_df"] is None or partial["residual_df"] < 10
            or oos["n"] < 20 or oos["reason"] is not None):
        return {**result, "status": "INSUFFICIENT", "reason": "THIN_OR_UNAVAILABLE_SAMPLE"}
    if partial["reason"] in ("CONSTANT_COMPONENT", "CONSTANT_TARGET", "EXPLAINED_COMPONENT",
                              "TARGET_EXPLAINED_OR_CONSTANT"):
        return {**result, "status": "NO_INCREMENT", "reason": partial["reason"]}
    ci = boot["ic95"]
    if boot["valid"] < 400 or ci is None or partial["value"] is None:
        return {**result, "status": "INSUFFICIENT", "reason": "PARTIAL_CI_UNAVAILABLE"}
    if (len(ci) != 2 or any(not isinstance(v, (float, int)) or not math.isfinite(v) for v in ci)
            or ci[0] > ci[1]):
        raise ValueError("ordered finite partial interval required")
    names = ("mse_controls", "mse_augmented", "mse_pastmean")
    if any(oos[k] is None or not math.isfinite(oos[k]) or oos[k] < 0 for k in names):
        return {**result, "status": "INSUFFICIENT", "reason": "OOS_MSE_UNAVAILABLE"}
    positive = ci[0] > 0
    improve_controls = oos["mse_augmented"] < oos["mse_controls"]
    improve_mean = oos["mse_augmented"] < oos["mse_pastmean"]
    result.update(positive_partial_ci=positive, improved_controls=improve_controls,
                  improved_pastmean=improve_mean, delta_controls=oos["mse_controls"]-oos["mse_augmented"],
                  delta_pastmean=oos["mse_pastmean"]-oos["mse_augmented"])
    if ci[1] < 0:
        status = "OPPOSITE_DIRECTION_COUNTEREVIDENCE"
    elif positive and improve_controls and improve_mean:
        status = "LIMITED_INCREMENT"
    elif positive:
        status = "CORRELATED_WITHOUT_CONFIRMED_PREDICTIVE_INCREMENT"
    elif improve_controls and improve_mean:
        status = "INCONCLUSIVE_PREDICTIVE_ONLY"
    else:
        status = "NO_INCREMENT"
    return {**result, "status": status, "reason": "FIXED_POSITIVE_CI_AND_BOTH_MSE_COMPARATORS"}


def summarize(statistics):
    expected = {"all", "causal_original_policy_flat_eligible"}
    if set(statistics["scopes"]) != expected or statistics["return_direction"] != "positive":
        raise ValueError("both fixed scopes and original positive-return prior required")
    return {"status": "FIXED_DESCRIPTIVE_SCIENTIFIC_READING", "scopes": {
        name: {"return4_net": classify(panel["labels"]["return4_net"]),
               "downside4_oc": {"role": "DIAGNOSTIC_ONLY_NO_SIGN_NO_TRADING_ROLE_NO_GATE",
                                  "partial": panel["labels"]["downside4_oc"]["partial"],
                                  "partial_ci": panel["labels"]["downside4_oc"]["partial_bootstrap"]["ic95"],
                                  "oos": panel["labels"]["downside4_oc"]["walk_forward"]["aggregate"]}}
        for name, panel in statistics["scopes"].items()},
        "fixed_year_phase_reports": "all retained in statistics; no cherry-picked subgroup rescues failure",
        "limits": "Seen development pool; uncorrected repeated family selection. LIMITED_INCREMENT is limited information evidence, never executable economic qualification. Opposite sign cannot rescue this fixed hypothesis."}
