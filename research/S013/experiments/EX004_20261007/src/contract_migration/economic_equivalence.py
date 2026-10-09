"""Compare immutable S013 account evidence with a freshly serialized TDR result.

This module only reads dictionaries/files; it does not prepare or execute a run.
Import compare_evidence(old_json, serialize_evaluation_evidence(bound, result)).
New candidate identities may differ; economic facts and ID relationships must match.
"""
from copy import deepcopy
from hashlib import sha256
import json


ID_FIELDS = {"decision_id", "order_id", "fill_id", "cycle_id"}
LEDGERS = ("decisions", "orders", "fills", "account_daily", "trades")
SEMANTIC_FIELDS = (
    "symbol", "asset_type", "windows", "data_cutoff", "initial_cash", "costs",
    "benchmark", "execution_mode", "frequency_window_days", "price_basis", "pricing",
    "metric_semantics_version",
)


def _normalize_table(table, registries):
    result = deepcopy(table)
    for row in result["data"]:
        for key in ID_FIELDS & row.keys():
            value = row[key]
            if value is None or value == "":
                continue
            registry = registries.setdefault(key, {})
            registry.setdefault(value, f"{key}:{len(registry)}")
            row[key] = registry[value]
    # pandas_version is exporter metadata, not dataframe semantics.
    result.get("schema", {}).pop("pandas_version", None)
    return result


def _table_projection(run):
    ids = {}
    output = {"signals": _normalize_table(run["signals"], ids),
              "signal_dtypes": run["signal_dtypes"], "signal_window": run["signal_window"]}
    for key in LEDGERS:
        output[key] = _normalize_table(run["ledgers"][key], ids)
    benchmark = run["buyhold"]
    if benchmark is None:
        output["buyhold"] = None
    else:
        ids = {}
        output["buyhold"] = {
            "account_daily": _normalize_table(benchmark["account_daily"], ids),
            "orders": _normalize_table(benchmark["orders"], ids),
            "benchmark": benchmark["benchmark"], "metrics": benchmark["metrics"],
            "execution": None,
        }
        if benchmark["execution"] is not None:
            output["buyhold"]["execution"] = {
                key: _normalize_table(benchmark["execution"][key], ids) for key in LEDGERS
            }
    return output


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode()).hexdigest()


def compare_evidence(old, new):
    """Return per-table exact equality proof; raise at the first material mismatch.

    Every row, column, dtype and binary64 value is compared. ID values alone are
    normalized in first-occurrence order across all tables, preserving references.
    No monetary tolerance is used; any discrepancy needs explicit investigation.
    """
    for key in SEMANTIC_FIELDS:
        if old["request_identity"][key] != new["request_identity"][key]:
            raise AssertionError(f"request semantic mismatch: {key}")
    def index(value):
        return {(run["window_id"], run["scenario_id"]): run for run in value["runs"]}
    lhs, rhs = index(old), index(new)
    if len(lhs) != len(old["runs"]) or len(rhs) != len(new["runs"]) or lhs.keys() != rhs.keys():
        raise AssertionError("run coordinates mismatch or duplicate")
    proof = []
    for coordinate in lhs:
        before, after = _table_projection(lhs[coordinate]), _table_projection(rhs[coordinate])
        rows = {}
        for key in before:
            if before[key] != after[key]:
                raise AssertionError(f"economic mismatch: {coordinate}: {key}")
            if key in {"signals", *LEDGERS}:
                rows[key] = {"rows": len(before[key]["data"]), "sha256": _digest(before[key])}
        proof.append({"window_id": coordinate[0], "scenario_id": coordinate[1],
                      "status": "EXACT_EQUAL", "tables": rows,
                      "projection_sha256": _digest(before)})
    return {"status": "PASS", "comparison": "all economic rows and dtypes exact; relational IDs normalized",
            "runs": proof}
