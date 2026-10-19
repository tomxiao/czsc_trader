"""Merge fixed2025 audited equities for visualization; no new return labels."""
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent


def main():
    names = ("daily_2025_equity.csv", "daily_2025_early_cycle_equity.csv", "daily_2025_joint_equity.csv")
    source_hashes = {}
    result = None
    for name in names:
        path = HERE / "accounting" / name
        frame = pd.read_csv(path, float_precision="round_trip").set_index("date")
        if frame.index.has_duplicates or len(frame) != 243:
            raise ValueError("Expected complete243 unique audited2025 sessions")
        if result is None:
            result = frame
        else:
            if not result.index.equals(frame.index):
                raise ValueError("Audited calendars differ")
            for column in result.columns.intersection(frame.columns):
                if not result[column].equals(frame[column]):
                    raise ValueError(f"Shared original/control equity differs: {column}")
            result = result.join(frame.drop(columns=result.columns.intersection(frame.columns)), validate="one_to_one")
        source_hashes["accounting/" + name] = sha256(path.read_bytes()).hexdigest()
    destination = HERE / "daily_2025_all_audited_paths.csv"
    with destination.open("x", encoding="utf-8", newline="") as handle:
        result.to_csv(handle, lineterminator="\n")
    receipt = {"status": "PASS_EXACT_SHARED_CONTROL_EQUITIES", "source_sha256": source_hashes,
               "output_sha256": sha256(destination.read_bytes()).hexdigest(),
               "sessions": 243, "columns": list(result.columns),
               "normalization": "Plot uses original2025 opening278758.90799999965; not first-close rebasing"}
    with (HERE / "plot_input_integrity.json").open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(receipt, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
