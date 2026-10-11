"""Supplementary synthetic fixed-anchor checks; no actual data/statistics."""

from pathlib import Path
from hashlib import sha256
import json
import numpy as np
import pandas as pd
from price_authentication import authenticate_price_units

HERE = Path(__file__).parent


def main():
    idx = pd.bdate_range("2020-01-01", periods=20)
    f = pd.DataFrame({"Open": np.arange(20) + 100.0, "Close": np.arange(20) + 99.5}, index=idx)
    observed = authenticate_price_units(f, f * 0.2803, 0.2803, idx)
    assert observed["all_label_scale_rows"] == 20
    assert observed["all_labels_and_maturity_scale_invariant"]
    refusals = []
    for name, anchor, warm in (
        ("changed anchor", 0.2804, f * 0.2803),
        ("wrong units", 0.2803, f),
        ("missing overlap", 0.2803, (f * 0.2803).set_axis(idx + pd.Timedelta(days=100))),
    ):
        try:
            authenticate_price_units(f, warm, anchor, idx)
        except (ValueError, AssertionError):
            refusals.append(name)
        else:
            raise AssertionError(name)
    out = {
        "status": "PASS",
        "checks": [
            "native/public fixed anchor overlap",
            "all four labels scale invariant",
            "all maturity and missing tails unchanged",
        ],
        "refusals": refusals,
        "new_source_files": {
            n: sha256((HERE / n).read_bytes()).hexdigest()
            for n in ("driver_pricefix.py", "price_authentication.py", "price_fix_checks.py")
        },
        "actual_statistics": 0,
        "accounts": 0,
        "provider": 0,
    }
    path = HERE / "price_fix_checks.json"
    assert not path.exists()
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print({"status": "PASS", "checks": 3, "refusals": len(refusals)})


if __name__ == "__main__":
    main()
