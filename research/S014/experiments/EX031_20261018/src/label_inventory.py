"""Inventory immutable H1/H3 labels; no fits or new execution."""

from pathlib import Path
import json
import pandas as pd

EX = Path(__file__).resolve().parents[1]
f = pd.read_csv(EX / "others/inputs.csv").set_index("signal")
l = pd.read_csv(EX / "others/labels.csv")
rows = []
excluded = []
for scope, base in [
    ("full_methanol", f.A & f.z.notna()),
    ("common_features", f.A & f.feature_ready),
    ("evaluation2023plus", f.A & f.feature_ready & f.year.ge(2023)),
]:
    for h in [1, 3]:
        q = l.loc[l.horizon.eq(h)].set_index("signal").reindex(f.index)
        for year in range(2020, 2027):
            m = base & f.year.eq(year)
            g = q.loc[m]
            rows.append(
                {
                    "scope": scope,
                    "year": year,
                    "horizon": h,
                    "parent": int(m.sum()),
                    "missing_label": int(g.status.isna().sum()),
                    "mature": int(g.maturity.ge(0).sum()),
                    "filled_closed": int(g.status.eq("CLOSED").sum()),
                    "unfilled": int(g.status.eq("UNFILLED").sum()),
                    "right_censored": int(g.maturity.lt(0).sum()),
                    "raw_mature_mean": float(g.loc[g.maturity.ge(0), "net_return"].mean())
                    if g.maturity.ge(0).any()
                    else None,
                }
            )
            for sig, r in g.loc[g.maturity.lt(0) | g.status.isna()].iterrows():
                excluded.append(
                    {
                        "scope": scope,
                        "year": year,
                        "horizon": h,
                        "signal": int(sig),
                        "date": f.loc[sig, "date"],
                        "reason": "NO_HISTORICAL_LABEL" if pd.isna(r.status) else "RIGHT_CENSORED",
                    }
                )
h1 = set(l.loc[l.horizon.eq(1) & l.maturity.ge(0), "signal"])
h3 = set(l.loc[l.horizon.eq(3) & l.maturity.ge(0), "signal"])
only = sorted((h1 - h3) & set(f.index[f.A & f.z.notna()]))
result = {
    "status": "PASS",
    "inventory": rows,
    "excluded": excluded,
    "H1_only_mature_parent_signals": only,
    "H1_only_dates": f.loc[only, "date"].tolist(),
    "new_labels": 0,
    "new_accounts": 0,
    "new_fits": 0,
    "note": "H1 own mature population reported separately. Paired H1/H3 comparisons use common mature labels, not H1-only outcomes. No fills or returns recomputed.",
}
(EX / "others/label_inventory.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
    encoding="utf-8",
    newline="\n",
)
print(json.dumps({"H1_only_parent_dates": result["H1_only_dates"], "excluded_rows": len(excluded)}))
