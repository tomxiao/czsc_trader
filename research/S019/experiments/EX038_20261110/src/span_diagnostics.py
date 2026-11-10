"""Describe actual sampled spans and compare existing complete-account controls."""
from pathlib import Path
import json
import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_bytes())


def main():
    summary = read(WORK / "others/summary.json")
    records = []
    for name, row in summary.items():
        m = row["candidate"]
        records.append({"name": name, "id": row["id"], **row["parameters"],
            "nar": m["nar"], "mdd": m["drawdown"], "calmar": m["calmar"], "eligible": m["eligible"]})
    frame = pd.DataFrame(records)
    groups = []
    for span, group in frame.groupby("participation_days", sort=True):
        passing = group.loc[group.eligible]
        groups.append({"span": int(span), "configurations": len(group), "eligible": len(passing),
            "nar_median": float(group.nar.median()), "calmar_median": float(group.calmar.median()),
            "max_calmar": float(group.calmar.max()),
            "max_eligible_nar": None if passing.empty else float(passing.nar.max())})
    controls = []
    for experiment, name in ((36, "trial033"), (37, "trial000"), (37, "trial046")):
        row = read(WORK.parent / f"EX{experiment:03}_20261110/others/summary.json")[name]
        controls.append({"id": {"C0150": "C0101"}.get(row["id"], row["id"]), "evaluated_id": row["id"],
            "parameters": row["parameters"], "account": row["account"], "candidate": row["candidate"]})
    eligible = frame.loc[frame.eligible].sort_values("nar", ascending=False)
    output = {"scope": "Unique configurations only; spans jointly vary with other parameters. Adaptive sample groups are descriptive and do not isolate span causality.",
        "sampled_span_min": int(frame.participation_days.min()), "sampled_span_max": int(frame.participation_days.max()),
        "by_span": groups, "controls": controls, "eligible": eligible.to_dict("records"),
        "shorter_than_ten": {"configurations": int((frame.participation_days < 10).sum()),
            "eligible": int((frame.eligible & (frame.participation_days < 10)).sum())},
        "ten_or_more": {"configurations": int((frame.participation_days >= 10).sum()),
            "eligible": int((frame.eligible & (frame.participation_days >= 10)).sum())}}
    (WORK / "others/span_diagnostics.json").write_bytes((json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())
    print("SPAN_DIAGNOSTICS", len(frame), len(eligible), flush=True)


if __name__ == "__main__":
    main()
