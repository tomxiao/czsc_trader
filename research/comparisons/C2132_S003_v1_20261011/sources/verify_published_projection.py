"""Authenticate S003 cached outcomes and reserialize full public projections; no replay."""
from hashlib import sha256
from pathlib import Path
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence
from czsc_trader.research_tools.evidence import EvidenceRef
from strategy_runtime import canonical_sha256
from run_compare import ROOT, WORK, OUT, read, write, cache_read


def main():
    receipt = next(x for x in read(OUT / "account_receipts.json") if x["family"] == "S003")
    references = [receipt["center"], receipt["stress"], *[x["reference"] for x in receipt["parameters"]]]
    labels = ["center", "stress", *[f"P{i:02}" for i in range(32)]]
    rows = []
    for raw, label in zip(references, labels, strict=True):
        ref = EvidenceRef.from_dict(raw)
        path = ref.resolve(ROOT)
        assert sha256(path.read_bytes()).hexdigest() == ref.sha256
        cached = WORK / f"S003-{label}.pkl.gz"
        request, result = cache_read(cached)
        regenerated = serialize_evaluation_evidence(request, result)
        original = read(path)
        assert regenerated == original, label
        exact = canonical_sha256(regenerated)
        assert exact == canonical_sha256(original)
        rows.append({"reference": raw, "status": "PASS", "full_projection_exact": True,
                     "canonical_sha256": exact, "cache_sha256": sha256(cached.read_bytes()).hexdigest(),
                     "request_hash": original["request_hash"], "result_hash": original["result_hash"]})
        print("FULL_AUTHENTICATED_PROJECTION", label, "PASS", flush=True)
    write(WORK / "s003_projection_proof.json", {"status": "PASS", "accounts": rows,
          "native_public_audit_unchanged": True, "financial_replay": False,
          "method": "Public serializer authenticates expected request/result then exact full-object comparison with immutable published evidence",
          "source_sha256": sha256(Path(__file__).read_bytes()).hexdigest()})


if __name__ == "__main__":
    main()
