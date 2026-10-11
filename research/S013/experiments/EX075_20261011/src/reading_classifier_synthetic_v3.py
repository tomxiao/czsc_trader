"""Artificial classification fixtures only; no real statistical results read."""

import copy
import hashlib
import json
from pathlib import Path

import reading_classifier_v3 as c


def fixture():
    return {
        "partial": {
            "n": 80,
            "residual_df": 61,
            "reason": None,
            "value": -0.3,
            "component_residual_fraction": 0.6,
            "target_residual_fraction": 0.7,
        },
        "raw_bootstrap": {"valid": 500, "ic95": [-0.4, -0.1]},
        "partial_bootstrap": {"valid": 500, "ic95": [-0.5, -0.1]},
        "walk_forward": {
            "aggregate": {
                "n": 40,
                "reason": None,
                "mse_controls": 2.0,
                "mse_augmented": 1.0,
                "mse_pastmean": 3.0,
            }
        },
    }


def check():
    checks = []
    p = fixture()
    assert c.classify("return4_net", p)["status"] == "LIMITED_FULL_POOL_RETURN_INFORMATION"
    for name, status in (
        ("EXPLAINED_COMPONENT", "FULLY_EXPLAINED_COMPONENT"),
        ("CONSTANT_COMPONENT", "CONSTANT_COMPONENT"),
        ("CONSTANT_TARGET", "CONSTANT_TARGET"),
        ("TARGET_EXPLAINED_OR_CONSTANT", "TARGET_EXPLAINED_OR_CONSTANT"),
    ):
        case = fixture()
        case["partial"].update(reason=name, value=None)
        case["partial_bootstrap"].update(valid=0, ic95=None)
        item = c.classify("return4_net", case)
        assert item["status"] == status and item["stage"] == "STRUCTURAL_NULL"
        assert item["partial_valid"] == 0 and item["partial_ci"] is None
    checks.append("adequate_n_df_oos_structural_nulls_before_unavailable_CI")

    for key, val in (("n", 19), ("residual_df", 9), ("residual_df", None)):
        case = fixture()
        case["partial"].update(reason="EXPLAINED_COMPONENT", value=None)
        case["partial"][key] = val
        assert c.classify("return4_net", case)["stage"] == "INPUT_N_DF_OOS_COVERAGE"
    for change in ({"n": 19}, {"reason": "INSUFFICIENT_TEST_SAMPLE"}):
        case = fixture()
        case["partial"]["reason"] = "EXPLAINED_COMPONENT"
        case["walk_forward"]["aggregate"].update(change)
        assert c.classify("return4_net", case)["stage"] == "INPUT_N_DF_OOS_COVERAGE"
    checks.append("fixed_input_n20_df10_oos20_precedes_structural_null")

    for key, status in (
        ("component_residual_fraction", "FULLY_EXPLAINED_COMPONENT"),
        ("target_residual_fraction", "TARGET_EXPLAINED_OR_CONSTANT"),
    ):
        case = fixture()
        case["partial"][key] = 1e-10
        case["partial_bootstrap"].update(valid=0, ic95=None)
        assert c.classify("return4_net", case)["status"] == status
    case = fixture()
    case["partial"]["component_residual_fraction"] = 1.00001e-10
    case["partial_bootstrap"]["valid"] = 399
    assert c.classify("return4_net", case)["stage"] == "GENERAL_PARTIAL_CI_AVAILABILITY"
    case["partial_bootstrap"]["valid"] = 400
    assert c.classify("return4_net", case)["status"] == "LIMITED_FULL_POOL_RETURN_INFORMATION"
    checks.append("unchanged_explained1e_minus10_and400CI_boundaries")

    case = fixture()
    case["partial_bootstrap"]["ic95"] = [0.1, 0.4]
    assert c.classify("return4_net", case)["status"] == "OPPOSITE_DIRECTION_COUNTEREVIDENCE"
    assert c.classify("downside4_oc", case)["status"] == "INCONCLUSIVE_RAW_PARTIAL_CONFLICT"
    case["raw_bootstrap"]["ic95"] = [0.01, 0.2]
    assert c.classify("downside4_oc", case)["status"] == "LIMITED_FULL_POOL_RISK_INFORMATION"
    assert c.classify("return4_net", case)["status"] == "OPPOSITE_DIRECTION_COUNTEREVIDENCE"
    case["partial_bootstrap"]["ic95"] = [-0.4, -0.1]
    assert c.classify("return4_net", case)["status"] == "INCONCLUSIVE_RAW_PARTIAL_CONFLICT"
    checks.append("fixed_independent_return_negative_risk_positive_no_opposite_rescue")

    for baseline in ("mse_controls", "mse_pastmean"):
        for value in (0.5, 1.0):
            case = fixture()
            case["walk_forward"]["aggregate"][baseline] = value
            item = c.classify("return4_net", case)
            assert item["status"] == "CORRELATED_WITHOUT_CONFIRMED_PREDICTIVE_INCREMENT"
    case = fixture()
    case["partial_bootstrap"]["ic95"] = [-0.4, 0.0]
    assert c.classify("return4_net", case)["status"] == "INCONCLUSIVE_PREDICTIVE_ONLY"
    case["walk_forward"]["aggregate"]["mse_controls"] = 1.0
    assert c.classify("return4_net", case)["status"] == "NO_INCREMENT_OBSERVED"
    checks.append("two_baselines_separate_exact_ties_fail_CI_zero_uncertain")

    case = fixture()
    case["raw_bootstrap"].update(valid=399, ic95=None)
    before = copy.deepcopy(case)
    item = c.classify("return4_net", case)
    assert item["raw_ci"] is None and any(
        "Raw CI unavailable" in text for text in item["limitations"]
    )
    assert case == before and not item["economic_gate"] and not item["account_authorization"]
    case["walk_forward"]["aggregate"]["mse_controls"] = None
    assert c.classify("return4_net", case)["stage"] == "OOS_METRICS_UNAVAILABLE"
    checks.append("missing_CI_and_MSE_kept_unavailable_no_input_mutation_or_account_authority")

    refusals = []
    for label, interval in (
        ("return8_net", [-0.4, -0.1]),
        ("return4_net", [-0.1, -0.4]),
        ("return4_net", [float("nan"), 0.2]),
        ("return4_net", [0.2]),
    ):
        case = fixture()
        case["partial_bootstrap"]["ic95"] = interval
        try:
            c.classify(label, case)
        except ValueError:
            refusals.append({"label": label, "interval_repr": repr(interval)})
        else:
            raise AssertionError("missing refusal")
    return {
        "status": "PASS_ARTIFICIAL_FIXTURES_ONLY",
        "checks": checks,
        "refusals": refusals,
        "source_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (Path(c.__file__), Path(__file__))
        },
        "real_data_reads": 0,
        "real_statistics": 0,
        "signals": 0,
        "accounts": 0,
        "allocate": 0,
        "publish": 0,
        "DEV": 0,
    }


if __name__ == "__main__":
    proof = check()
    Path(__file__).with_suffix(".json").write_text(
        json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(proof, ensure_ascii=False))
