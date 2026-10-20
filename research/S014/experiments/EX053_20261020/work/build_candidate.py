"""Construct an unregistered C9522 value through the public SRT API."""

import json
from pathlib import Path

from strategy_runtime import StrategyCandidate, StrategyRuntime, implementation_sha256


WORK = Path(__file__).resolve().parent
SOURCE_ROOT = WORK / "c9522/strategy_runtime"


def build():
    source_hash = implementation_sha256(
        ("strategies/trend_permission.py",), source_root=SOURCE_ROOT
    )
    payload = {
        "parameters": {"permission_profile": "AGE_PRIOR_TREND_PERMISSION"},
        "runtime": {
            "contract_version": 2,
            "module": "strategy_runtime.strategies.trend_permission",
            "qualname": "TrendPermissionStrategy",
            "source_files": ["strategies/trend_permission.py"],
            "source_sha256": source_hash,
        },
    }
    candidate = StrategyCandidate("S014", "C9522", payload, SOURCE_ROOT)
    # Authentication and abstract-contract checks are executed, not assumed.
    description = StrategyRuntime().describe(candidate)
    return candidate, description


def main():
    candidate, description = build()
    output = {
        "candidate": candidate.reference_id,
        "payload": dict(candidate.payload),
        "runtime_sha256": description.runtime_sha256,
        "runtime_identity_sha256": candidate.runtime_identity_sha256,
        "source_root": SOURCE_ROOT.relative_to(WORK).as_posix(),
        "registration_performed": False,
    }
    # This editable work payload is not a registration or research receipt.
    path = WORK / "candidate.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=dict) + "\n",
                    encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in output.items() if k != "payload"}, ensure_ascii=False))


if __name__ == "__main__":
    main()


def build_declared_candidate():
    """Create a distinct identity declaring its simulated-fill feedback limit.

    The original builder, source and C9522 payload remain unchanged, preserving
    their existing published technical control. This successor changes metadata
    only and must not be admitted to PTE as confirmed-execution feedback.
    """
    from strategy_runtime import DecisionFeedback

    original, _ = build()
    payload = dict(original.payload)
    payload["decision_feedback"] = DecisionFeedback.SIMULATED_FILL_FEEDBACK.value
    candidate = StrategyCandidate("S014", "C9523", payload, SOURCE_ROOT)
    return candidate, StrategyRuntime().describe(candidate)
