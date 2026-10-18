from pathlib import Path
import pandas as pd, json

root = Path.cwd()
ex = root / "research/S014/experiments/EX031_20261018"
f = pd.read_csv(ex / "others/predictions.csv")
f = f.loc[f.A]
rows = []
for env, g in f.groupby("environment"):
    for year, q in [("ALL", g), ("WITHOUT2026", g.loc[g.year.ne(2026)]), *list(g.groupby("year"))]:
        r = q.Y3 - q.score_B
        z = q.z.eq(1)
        delta = q.Y3 * (q.sel_Bz.astype(int) - q.sel_B.astype(int))
        rows.append(
            {
                "environment": env,
                "year": str(year),
                "n": len(q),
                "up_n": int(z.sum()),
                "not_up_n": int((~z).sum()),
                "D1": float(r[z].mean() - r[~z].mean()) if z.any() and (~z).any() else None,
                "D2": float(delta.mean()),
                "changed_decisions": int(q.sel_Bz.ne(q.sel_B).sum()),
            }
        )
(ex / "others/environment_annual.json").write_text(
    json.dumps(
        {
            "scope": "Predeclared environment and year diagnostics; existing fixed scores only",
            "rows": rows,
            "new_fits": 0,
        },
        indent=2,
        allow_nan=False,
    )
    + "\n",
    encoding="utf-8",
    newline="\n",
)
print(pd.DataFrame(rows).to_string(index=False))
print("zero_direction_count", int(pd.read_csv(ex / "others/methanol.csv").r.eq(0).sum()))
