"""Supplemental read-only EX035 request/data audit; no new account execution."""

import json
from copy import deepcopy

from audit_accounts import Checks, references


STABLE_REQUEST_FIELDS = (
    "asset_type", "benchmark", "costs", "data_cutoff", "data_identity",
    "execution_mode", "frequency_window_days", "initial_cash", "market_rules",
    "metric_semantics_version", "price_basis", "pricing", "schema_version",
    "symbol", "windows",
)
STABLE_SUPPORT_FIELDS = (
    "available_through", "entry_order_type", "evaluation_fee_rate",
    "execution_input_identities", "execution_policy", "execution_requests",
    "exit_order_type", "mode",
)


def audit_identity(account_json):
    """Compare economic contract, actual input content hashes and market-only flags.

    Runtime source, strategy identity, experiment, and preparation transaction IDs
    may legitimately differ. Native/request worker budgets are not serialized by
    account_evaluation/7 and must be audited separately from the frozen runner.
    """
    original = references()[0]
    c = Checks()
    for key in ("data_identity", "execution_mode", "schema_version", "source_kind"):
        c.equal(account_json.get(key), original[key], f"account invariant {key}")
    request = account_json["request_identity"]
    for key in STABLE_REQUEST_FIELDS:
        c.equal(request.get(key), original["request_identity"][key], f"request invariant {key}")
    c.equal(set(account_json["input_bindings"]), set(original["input_bindings"]), "same input binding windows")
    for window, old_binding in original["input_bindings"].items():
        binding = account_json["input_bindings"].get(window)
        if binding is None:
            continue
        c.equal(binding["schema_version"], old_binding["schema_version"], "binding schema")
        c.equal(set(binding["plan"]), set(old_binding["plan"]), "same plan fields")
        for key in old_binding["plan"]:
            if key != "strategy":
                c.equal(binding["plan"].get(key), old_binding["plan"][key], f"input plan invariant {key}")
    c.equal(len(account_json["runs"]), len(original["runs"]), "same run count")
    for run, old_run in zip(account_json["runs"], original["runs"]):
        for key in ("window_id", "scenario_id", "signal_window"):
            c.equal(run.get(key), old_run[key], f"run invariant {key}")
        support = run["signal_support"]
        for key in STABLE_SUPPORT_FIELDS:
            c.equal(support.get(key), old_run["signal_support"][key], f"support invariant {key}")
        # Future flags route computation only. They must remain market-only and
        # unchanged even while the intervention changes held/entry state.
        market_fields = ("signal_date", "valid_session", "ready", "parent", "high", "threshold", "gap_autocorr")
        decisions = [{k: r[k] for k in market_fields} for r in run["ledgers"]["decisions"]["data"]]
        old_decisions = [{k: r[k] for k in market_fields} for r in old_run["ledgers"]["decisions"]["data"]]
        c.rows(decisions, old_decisions, "whole-window market-only policy inputs")
    return c.result(
        "ECONOMIC_CONTRACT_AND_INPUT_IDENTITY",
        original_data_identity=original["data_identity"],
        execution_input_content_identities=original["runs"][0]["signal_support"]["execution_input_identities"],
        workers_scope="Account schema omits worker counts; frozen runner/config supplies separate evidence",
        allowed_differences=["runtime source/hash", "strategy identity", "experiment identity",
                             "preparation transaction identity", "runtime-dependent signal_data_identity"],
    )


def selfcheck():
    original = references()[0]
    outcomes = {"original_pass": audit_identity(original)["status"] == "PASS"}
    mutations = {
        "fee_detected": lambda a: a["request_identity"]["costs"][0].update(one_way_cost=0),
        "content_hash_detected": lambda a: a["runs"][0]["signal_support"]["execution_input_identities"].update(execution_daily="0" * 64),
        "market_flag_detected": lambda a: a["runs"][0]["ledgers"]["decisions"]["data"][0].update(parent=1),
        "calendar_plan_detected": lambda a: a["input_bindings"]["full"]["plan"].update(calendar_sha256="0" * 64),
    }
    for name, mutate in mutations.items():
        account = deepcopy(original)
        mutate(account)
        outcomes[name] = audit_identity(account)["status"] == "FAIL"
    return {"status": "PASS" if all(outcomes.values()) else "FAIL", "checks": outcomes,
            "new_account_evaluations": 0}


if __name__ == "__main__":
    print(json.dumps(selfcheck(), indent=2))
