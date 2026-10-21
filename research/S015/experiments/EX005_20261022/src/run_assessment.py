"""Execute only prospectively bound parameter points and center fee stress."""

import argparse
import cloudpickle
import time
from common import ROOT, EROOT, WORK, EXPERIMENT, context, read, save
import pandas as pd
import numpy as np
from czsc_trader.application import publish_evidence_many
from czsc_trader.research_tools import EvaluationEvidenceWrite

TEMP = ROOT / ".tmp/s015_stage4/requests"


def summarize(req, result, parent, kind, index):
    run = result.runs[0]
    assert len(result.runs) == 1 and len(run.execution.account_daily) == 434
    fills = run.execution.fills
    if len(fills):
        amounts = fills.quantity.astype(float) * fills.price.astype(float)
        np.testing.assert_allclose(
            fills.fees.astype(float), amounts * req.costs[0].one_way_cost, rtol=1e-12, atol=1e-8
        )
    m = run.observation.to_dict()
    return {
        "candidate_id": req.strategy.candidate_id,
        "parameters": dict(req.strategy.payload["parameters"]),
        "parent_id": parent,
        "kind": kind,
        "point_index": index,
        "evaluation_id": run.identity.evaluation_id,
        "request_hash": result.request_hash,
        "result_hash": result.result_hash,
        "observation": m,
        "benchmark_metrics": run.buyhold.metrics,
        "actual_cost": req.costs[0].one_way_cost,
        "benchmark_cagr": (float(run.buyhold.account_daily.equity.iloc[-1]) / 100000) ** (252 / 434)
        - 1,
        "fees": float(fills.fees.sum()),
        "input_bindings": {k: v.to_dict() for k, v in req.input_bindings.items()},
    }


def load_requests(cid):
    return cloudpickle.loads((TEMP / f"{cid}.pkl").read_bytes())


def store_block(ctx, items, outputs):
    writes = []
    rows = []
    for (parent, kind, index, req), out in zip(items, outputs, strict=True):
        if out.status.value != "SUCCEEDED":
            save(
                WORK / "failure.json",
                {
                    "parent_id": parent,
                    "kind": kind,
                    "point_index": index,
                    "status": out.status.value,
                    "error": {"code": out.error.code, "message": out.error.message},
                    "request_hash": out.request_hash,
                },
            )
            raise RuntimeError((parent, kind, index, out.error))
        rows.append(summarize(req, out.result, parent, kind, index))
        name = f"{parent}_{kind}_{index if index is not None else 'center'}"
        writes.append(EvaluationEvidenceWrite(EXPERIMENT, name, req, out.result))
    publications = publish_evidence_many(ctx, tuple(writes))
    for row, pub in zip(rows, publications, strict=True):
        if pub.status.value != "PUBLISHED":
            retry_cache = ROOT / ".tmp/s015_stage4/publication_retry.pkl"
            retry_cache.write_bytes(cloudpickle.dumps((items, outputs, publications)))
            save(WORK / "publication_outcomes.json", [
                {"parent_id": item[0], "kind": item[1], "point_index": item[2],
                 "status": outcome.status.value,
                 "reference": None if outcome.reference is None else outcome.reference.to_dict(),
                 "error": str(outcome.error)}
                for item, outcome in zip(items, publications, strict=True)])
            save(
                WORK / "publication_failure.json",
                {"row": row, "status": pub.status.value, "error": str(pub.error)},
            )
            raise RuntimeError(pub.error)
        row["evidence"] = pub.reference.to_dict()
        path = WORK / "results" / f"{row['parent_id']}.json"
        existing = read(path) if path.exists() else []
        assert all(
            (x["kind"], x["point_index"]) != (row["kind"], row["point_index"]) for x in existing
        )
        save(path, existing + [row])
    return rows


def precheck(ctx):
    cid = "C0004"
    requests = load_requests(cid)
    items = [
        (cid, "parameter", 0, requests["parameters"][0]),
        (cid, "stress", None, requests["stress"]),
    ]
    if (EROOT / "others/precheck.json").exists():
        raise RuntimeError("precheck already retained; do not repeat")
    serial = ctx.evaluation.evaluate(items[0][3])
    outputs = ctx.evaluation.evaluate_many(tuple(x[3] for x in items))
    assert all(out.status.value == "SUCCEEDED" for out in outputs), outputs
    for name in ("decisions", "orders", "fills", "trades", "account_daily"):
        pd.testing.assert_frame_equal(
            getattr(serial.runs[0].execution, name),
            getattr(outputs[0].result.runs[0].execution, name),
        )
    assert serial.result_hash == outputs[0].result.result_hash
    rows = store_block(ctx, items, outputs)
    save(
        EROOT / "others/precheck.json",
        {
            "status": "PASS",
            "checks": [
                "bound parameter serial/parallel five ledgers and result hash identical",
                "standard and stress actual fill fees verified",
                "both new accounts formally published",
            ],
            "formal_accounts": 2,
            "physical_evaluations": 3,
            "evidence": [r["evidence"] for r in rows],
        },
    )
    print({"precheck": "PASS", "formal_accounts": 2}, flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["precheck", "all"])
    parser.add_argument("--batch-size", type=int, default=16)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 64:
        raise ValueError("batch size must be between1 and64")
    ctx = context()
    if args.mode == "precheck":
        precheck(ctx)
        return
    assert read(EROOT / "others/precheck.json")["status"] == "PASS"
    centers = read(WORK / "centers.json")
    for n, row in enumerate(centers):
        cid = row["candidate_id"]
        while not (WORK / "plans" / f"{cid}.json").exists() or not (TEMP / f"{cid}.pkl").exists():
            print({"waiting_for_plan": cid}, flush=True)
            time.sleep(10)
        reqs = load_requests(cid)
        path = WORK / "results" / f"{cid}.json"
        saved = read(path) if path.exists() else []
        done = {(r["kind"], r["point_index"]) for r in saved}
        items = [
            (cid, "parameter", i, req)
            for i, req in enumerate(reqs["parameters"])
            if ("parameter", i) not in done
        ]
        if ("stress", None) not in done:
            items.append((cid, "stress", None, reqs["stress"]))
        for start in range(0, len(items), args.batch_size):
            block = items[start : start + args.batch_size]
            outputs = ctx.evaluation.evaluate_many(tuple(x[3] for x in block))
            store_block(ctx, block, outputs)
            print(
                {
                    "center": cid,
                    "center_number": n + 1,
                    "completed_for_center": len(read(path)),
                    "expected_for_center": len(reqs["parameters"]) + 1,
                },
                flush=True,
            )
        assert len(read(path)) == len(reqs["parameters"]) + 1
    print({"complete_centers": 98, "expected_new_accounts": 3170}, flush=True)


if __name__ == "__main__":
    main()
