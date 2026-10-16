"""Synthetic boundary checks; no market observations or strategy evaluations."""
from pathlib import Path
import json

import pandas as pd
from annual_contract import evaluate_annual_contract


def main():
    checks = []
    dates = pd.to_datetime(["2020-12-30", "2020-12-31", "2021-01-04", "2021-01-05"])

    def evaluate(left, right, exits=(), sessions=dates, cash=100):
        return evaluate_annual_contract(pd.Series(left, index=sessions), pd.Series(right, index=sessions),
                                        pd.to_datetime(exits), initial_cash=cash, expected_sessions=sessions)

    result = evaluate([90, 90, 80, 80], [95, 95, 90, 90])
    assert abs(result["annual"][1]["strategy_return"] - (80 / 90 - 1)) < 1e-12
    assert abs(result["annual"][1]["strategy_drawdown"] - (1 - 80 / 90)) < 1e-12
    assert abs(result["strategy_full_drawdown_diagnostic"] - .2) < 1e-12
    checks.append("cross-year holdings use previous year-end equity; annual and full drawdown differ")
    single = pd.to_datetime(["2026-10-15"])
    equal_return = evaluate([175], [150], sessions=single)
    assert equal_return["annual"][0]["return_pass"]
    checks.append("exact 1.5 times positive benchmark return passes without annualizing partial year")
    equal_dd = evaluate([90], [90], sessions=single)
    assert not equal_dd["annual_drawdown_pass"]
    checks.append("equal positive drawdowns fail strict comparison")
    flat = evaluate([100], [100], sessions=single)
    assert not flat["annual_return_pass"] and not flat["annual_drawdown_pass"]
    checks.append("zero benchmark return requires strictly positive strategy return; zero drawdown tie fails")
    nonpositive = evaluate([101], [99], sessions=single)
    assert nonpositive["annual_return_pass"] and nonpositive["annual_drawdown_pass"]
    checks.append("positive strategy return and lower drawdown pass against losing benchmark")
    long_dates = pd.bdate_range("2020-01-02", periods=120)
    concentrated = evaluate([101] * 120, [99] * 120, exits=long_dates[:6], sessions=long_dates)
    assert concentrated["frequency"] == 3 and concentrated["frequency_pass"]
    below = evaluate([101] * 120, [99] * 120, exits=long_dates[:5], sessions=long_dates)
    assert not below["frequency_pass"]
    checks.append("six early exits over 120 sessions pass frequency 3 despite empty later rolling windows")
    try:
        evaluate_annual_contract(pd.Series([100], index=single), pd.Series([100], index=single), (),
                                 initial_cash=100, expected_sessions=dates)
    except ValueError:
        checks.append("missing account sessions are rejected")
    else:
        raise AssertionError("missing account sessions admitted")
    destination = Path(__file__).resolve().parents[1] / "others/annual_contract_check.json"
    destination.write_text(json.dumps({"status": "PASS", "synthetic_only": True, "checks": checks,
                                       "strategy_evaluations": 0, "parameter_searches": 0},
                                      ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"S014_ANNUAL_CONTRACT=PASS CHECKS={len(checks)}")


if __name__ == "__main__":
    main()
