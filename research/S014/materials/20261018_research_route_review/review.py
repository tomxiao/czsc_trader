"""Summarize existing S014 evidence only; no fit, labels, account or upstream call."""
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd
from czsc_trader.research_tools import EvidenceRef

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    target = OUT / "evidence_review.json"
    assert not target.exists(), "Review result already exists"
    source = ROOT / "research/S014/experiments/EX031_20261018"
    result = read(source / "others/result.json")
    refs = result["evidence"]
    selected = ["others/predictions.csv", "others/analysis.json", "others/label_inventory.json"]
    for name in selected:
        assert EvidenceRef.from_dict(refs[name]).resolve(ROOT).read_bytes() == (source / name).read_bytes()
    f = pd.read_csv(source / "others/predictions.csv")
    f = f[f.A].copy()
    assert len(f) == 216 and f.Y1.notna().all() and f.Y3.notna().all()
    # Existing, same-entry labels only. This is arithmetic, not a newly simulated exit.
    f["delta"] = f.Y3 - f.Y1
    rows = []
    for env in ["ALL", "high", "low"]:
        e = f if env == "ALL" else f[f.environment.eq(env)]
        for year in ["ALL", "WITHOUT2026", 2023, 2024, 2025, 2026]:
            y = e if year == "ALL" else e[e.year.lt(2026)] if year == "WITHOUT2026" else e[e.year.eq(year)]
            for z in ["ALL", 1, 0]:
                q = y if z == "ALL" else y[y.z.eq(z)]
                rows.append(dict(environment=env, year=year, methanol_up=z, n=len(q),
                    H1=float(q.Y1.mean()), H3=float(q.Y3.mean()),
                    H3_minus_H1=float(q.delta.mean()), median_delta=float(q.delta.median()),
                    positive_delta=int(q.delta.gt(0).sum()), negative_delta=int(q.delta.lt(0).sum())))
    budget_path = ROOT / "research/S014/experiments/EX029_20261018/others/budget_summary.json"
    budget = read(budget_path)
    candidates = budget["candidate_summaries"]
    assert len(candidates) == 66
    annual = []
    for year in range(2020, 2027):
        pairs = [(c, next(a for a in c["annual"] if a["year"] == year)) for c in candidates]
        annual.append(dict(year=year, return_pass=sum(a["return_pass"] for c, a in pairs),
            both_pass=sum(a["both_pass"] for c, a in pairs),
            passed=[dict(candidate=c["candidate"], variant=c["variant"], frequency_pass=c["frequency_pass"])
                for c, a in pairs if a["both_pass"]]))
    output = dict(status="EXISTING_EVIDENCE_SUMMARY", new_fits=0, new_labels=0, new_accounts=0,
        new_upstream_calls=0, annual=annual, duration_by_existing_state=rows,
        source_evidence={name: refs[name] for name in selected},
        source_sha256={p.relative_to(ROOT).as_posix(): sha256(p.read_bytes()).hexdigest()
            for p in [budget_path, *(source / name for name in selected), Path(__file__)]},
        limitations=["Adaptive review of already seen evidence; not independent confirmation.",
            "Same-entry H3-H1 is an opportunity label difference, not account profit.",
            "Three changed model decisions do not explain the sixty-opportunity group difference.",
            "Annual winners cannot be concatenated into a tradable strategy."])
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps([r for r in rows if r["environment"] == "low" and r["year"] in ["ALL", "WITHOUT2026"]], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
