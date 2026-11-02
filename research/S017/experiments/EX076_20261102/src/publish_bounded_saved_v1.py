"""Explicit delivery-only retry of saved RSCH-verified input; no account replay."""
# ruff: noqa: E402
from finalize_bounded_stage4_v1 import (ROOT, OUTPUT, SCRATCH, KEYS, read, save, require,
    load_inputs, publish, CandidatePerformanceAssessmentRequest, d, m)
from hashlib import sha256
from time import perf_counter


def main():
    begun = perf_counter()
    manifest, _, _, _, _, _, plan_refs, _ = load_inputs()
    summary = read(OUTPUT / "analysis.json")
    verified = read(OUTPUT / "rsch_verification.json")
    require(verified["status"] == "PASS_RSCH_HARD_GATE_QUANTILE_AND_RANKING_VERIFICATION",
            "Saved numerical review did not pass")
    require(summary["source_manifest_sha256"] == sha256((OUTPUT / "manifest.json").read_bytes()).hexdigest(),
            "Published workload changed after numerical review")
    request = CandidatePerformanceAssessmentRequest.from_dict(read(SCRATCH / "request.json"))
    panel = m.AssessmentPanel.from_dict(read(OUTPUT / "panel.json"))
    comparison_request = m.CalmarComparisonRequest.from_dict(read(OUTPUT / "comparison_request.json"))
    compared = m.CandidateComparison.from_dict(read(OUTPUT / "comparison.json"))
    require(request.sha256 == panel.request_sha256 and comparison_request.panel == panel
            and comparison_request.sha256 == compared.request_sha256,
            "Saved request, panel and comparison identities differ")
    references = tuple(d.EvidenceRef.from_dict(record["evidence"])
        for group in (manifest["standards"].values(), manifest["pressures"].values(),
                      (record for key in KEYS for record in manifest["parameters"][key])) for record in group)
    require(len(references) == 269, "Saved publication scope differs")
    print("SAVED_NUMERICAL_REVIEW_REUSED_DELIVERY_ONLY", flush=True)
    publish(request, panel, comparison_request, compared, summary, references, plan_refs)
    save(OUTPUT / "delivery_only_retry.json", {"status": "DELIVERY_ONLY_RETRY_PASSED",
        "cause_of_prior_failure": "Windows process queue synchronization reported WinError 5 and 6; root cause unproven",
        "retry": "one explicit direct authorized CLI invocation, same public 12-worker implementation",
        "new_strategy_replays": 0, "numerical_assessment_recomputed_before_assembly": False,
        "saved_manifest_sha256": summary["source_manifest_sha256"],
        "elapsed_seconds": perf_counter() - begun,
        "parent_step_log": ".tmp/s017-bounded-v1/finalize.log",
        "root": str(ROOT.relative_to(ROOT))})
    print("DELIVERY_ONLY_RETRY_PASSED", flush=True)


if __name__ == "__main__":
    main()
