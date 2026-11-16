"""Validate and import display-only explanations for saved PTE decisions."""

import argparse
from contextlib import nullcontext
from hashlib import sha256
import json
from pathlib import Path

from execution_channels.futu.store import PaperStore
from strategy_runtime.signal_explanation import SignalExplanationSnapshot

from .runtime_lock import RuntimeDatabaseLock


def decision_source_hash(payload: dict) -> str:
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return sha256(content.encode("utf-8")).hexdigest()


def original_calculation(payload: dict):
    output = (payload.get("strategy_output") or {}).get("explanation") or {}
    panel = (payload.get("observation") or {}).get("signal_panel") or {}
    observed = panel.get("explanation") or {}
    return output.get("calculation") or observed.get("calculation")


def import_history(store: PaperStore, document: dict, *, apply: bool = False) -> dict:
    if (type(document) is not dict or set(document) != {"schema", "entries"}
            or document["schema"] != "pte_chart_history.v1"
            or type(document["entries"]) is not list or not document["entries"]):
        raise ValueError("invalid PTE chart history bundle")
    accounts = {}
    seen = set()
    inserted = 0
    with (store.atomic_decision_update() if apply else nullcontext()):
        for entry in document["entries"]:
            if type(entry) is not dict or set(entry) != {"account_id", "decision_id", "source_sha256", "explanation"}:
                raise ValueError("invalid PTE chart history entry")
            account, decision = entry["account_id"], entry["decision_id"]
            if not all(type(key) is str and key.strip() for key in (account, decision)) or (account, decision) in seen:
                raise ValueError("missing or duplicate PTE chart history identity")
            seen.add((account, decision))
            row = store.account_decision(account, decision)
            payload = row["payload"]
            if row["status"] == "SUPERSEDED" or decision_source_hash(payload) != entry["source_sha256"]:
                raise ValueError(f"saved PTE decision changed: {account}/{decision}")
            if original_calculation(payload) is not None:
                raise ValueError(f"PTE decision already has an original calculation: {account}/{decision}")
            explanation = SignalExplanationSnapshot.from_dict(entry["explanation"]).to_dict()
            if account not in accounts:
                accounts[account] = store.chart_decision_history(account)
            records = accounts[account]
            snapshot = {"source_sha256": entry["source_sha256"], "explanation": explanation}
            if decision in records and records[decision] != snapshot:
                raise ValueError(f"PTE decision has a different imported explanation: {account}/{decision}")
            if decision not in records:
                records[decision] = snapshot
                inserted += 1
        if apply and inserted:
            for account, entries in accounts.items():
                store.save_chart_decision_history(account, entries)
    return {"status": "APPLIED" if apply else "VALIDATED", "accounts": len(accounts),
            "entries": len(seen), "new_entries": inserted}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    document = json.loads(args.bundle.read_bytes())
    if not args.database.is_file():
        parser.error("PTE database does not exist")
    with (RuntimeDatabaseLock(args.database) if args.apply else nullcontext()):
        store = PaperStore(args.database) if args.apply else PaperStore.open_readonly(args.database)
        try:
            result = import_history(store, document, apply=args.apply)
        finally:
            store.close()
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
