"""Plot published continuous accounts; not an extra evaluation or selection."""

import json
from hashlib import sha256
import os
from pathlib import Path

os.environ["MPLCONFIGDIR"] = str(Path(".tmp/s017-research/matplotlib").resolve())
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from czsc_trader.research_tools import EvidenceRef
from run import ROOT, WORK, read


def main():
    analysis = read(WORK / "others/analysis.json")
    if analysis["status"] != "PASS":
        raise ValueError("complete account analysis required")
    fig, axes = plt.subplots(
        2, 1, figsize=(12, 7), sharex=True, gridspec_kw={"height_ratios": [2, 1]}
    )
    for key, value in analysis["source_accounts"].items():
        ref = EvidenceRef.from_dict(value)
        content = ref.resolve(ROOT).read_bytes()
        if sha256(content).hexdigest() != ref.sha256:
            raise ValueError("changed account")
        account = json.loads(content)
        variants = [(key, account["runs"]["candidate"])]
        if key == "C0013":
            variants.append(("Buy and hold", account["runs"]["buy_hold"]))
        for label, run in variants:
            rows = pd.DataFrame(run["account_points"])
            # Account points retain exact observation timestamps and all fees.
            times = pd.to_datetime(rows["time"], utc=True)
            equity = rows.equity / account["request"]["initial_cash"]
            peak = equity.cummax().clip(lower=1.0)
            axes[0].plot(times, equity, label=label, linewidth=1)
            axes[1].plot(times, (equity / peak - 1.0) * 100, label=label, linewidth=0.8)
    axes[0].set_ylabel("Equity / initial cash")
    axes[0].set_yscale("log")
    axes[1].set_ylabel("Drawdown (%)")
    axes[1].axhline(-25, color="grey", linestyle="--", linewidth=0.8)
    axes[0].set_title(WORK.name + " | LITE 2019-2025 | net of 0.1% per side")
    for ax in axes:
        ax.grid(alpha=0.2)
    axes[0].legend(ncol=5, fontsize=8)
    fig.tight_layout()
    fig.savefig(WORK / "others/equity_drawdown.png", dpi=160)
    plt.close(fig)
    print("PLOT_SAVED")


if __name__ == "__main__":
    main()
