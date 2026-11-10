"""Compare retained complete trade paths with each original parent account."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "research/S019/experiments/EX013_20261110/src"))
from runner import read_account, save  # noqa: E402
import pandas as pd  # noqa: E402
from review_search import read  # noqa: E402


def main(experiment):
    work = ROOT / "research/S019/experiments" / experiment
    design, review = read(work / "protocols/search.json"), read(work / "others/search_review.json")
    chosen_ref, chosen = read_account(work / f"others/{review['frontier_name']}_account.json")
    parent_ref, parent = read_account(ROOT / design["center_control"])
    a, b = chosen["runs"]["candidate"], parent["runs"]["candidate"]
    columns = ["entry_at", "exit_at", "net_return", "net_pnl"]
    left = pd.DataFrame([t for t in a["trades"] if t["status"] == "CLOSED"])[columns]
    right = pd.DataFrame([t for t in b["trades"] if t["status"] == "CLOSED"])[columns]
    joined = left.merge(right, on="entry_at", how="outer", suffixes=("_chosen", "_parent"), indicator=True, validate="one_to_one")
    matched = joined.loc[joined._merge == "both"].copy()
    matched["net_return_delta"] = matched.net_return_chosen-matched.net_return_parent
    changed = matched.loc[matched.exit_at_chosen != matched.exit_at_parent].copy()
    changed = changed.sort_values("net_return_delta", key=abs, ascending=False)
    cases = changed.drop(columns="_merge").head(12).to_dict("records")
    save(work / "others/parent_comparison.json", {"chosen": chosen_ref.to_dict(), "parent": parent_ref.to_dict(),
        "chosen_closed": len(left), "parent_closed": len(right), "matched_entries": len(matched),
        "only_chosen_entries": int((joined._merge == "left_only").sum()),
        "only_parent_entries": int((joined._merge == "right_only").sum()), "different_exit_times": len(changed),
        "largest_changed_exit_examples": cases,
        "interpretation_limit": "Matched entry dates describe path changes; sizing and subsequent opportunity changes remain jointly reflected in full accounts."})
    print("PARENT_COMPARISON", experiment, len(matched), len(changed), flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
