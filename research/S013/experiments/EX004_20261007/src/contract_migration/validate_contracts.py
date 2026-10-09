"""S013-owned calendar, causal mapping and history coverage boundary checks."""
# ruff: noqa: E402
from pathlib import Path
import json
import sys

SRC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SRC))

import pandas as pd
from dataflows import DataRequest, Dataset
from strategy_runtime import ParameterSet, TradableWindow
from adaptive_synthetic_precheck import AdaptiveRange, RangeReversion, make_parameters


def main():
    dates = tuple(day.date() for day in pd.bdate_range('2019-01-01', periods=720))
    window = TradableWindow(dates[300], dates[-1])
    variants = [RangeReversion(ParameterSet(make_parameters()['bull'])),
                AdaptiveRange(ParameterSet(make_parameters()))]
    expanded = make_parameters(regime_window=60)
    expanded['bear']['range_window'] = 240
    variants.append(AdaptiveRange(ParameterSet(expanded)))
    for strategy in variants:
        request = strategy.calendar_request(window)
        assert request.dataset is Dataset.TRADING_CALENDAR and request.symbol == 'SSE'
        assert request.end == window.end.isoformat()
        scope = strategy.derive_calculation_scope(window, dates)
        assert set(scope.inputs) == {'daily', 'execution'}
        assert all(isinstance(value, DataRequest) for value in scope.inputs.values())
        assert scope.signal_dates[dates[300]] == dates[299]
        assert scope.signal_dates[dates[-1]] == dates[-2]
        assert scope.calculation_dates == dates[299:-1]
        assert scope.inputs['execution'].start == dates[299].isoformat()
        for name, value in scope.inputs.items():
            assert value.end == dates[-2].isoformat() == value.required_cutoff
            assert value.coverage.observations_through == dates[299].isoformat()
            depth = next(item.lookback_sessions for item in strategy.definition.inputs.requirements if item.name == name)
            assert value.coverage.minimum_sessions == depth
            assert value.start == dates[300 - depth].isoformat()
        for calendar in (dates[300:], dates[298:]):
            try:
                strategy.derive_calculation_scope(window, calendar)
            except ValueError:
                pass
            else:
                raise AssertionError('insufficient history accepted')
        try:
            strategy.derive_calculation_scope(window, tuple(day for day in dates if day != window.start))
        except ValueError:
            pass
        else:
            raise AssertionError('missing trading endpoint accepted')
    print('PASS: strategy-owned date mapping and full DataRequest coverage boundaries')
    output = SRC.parents[4] / 'research/S013/assets/runs/EX004_20261007/contract_migration/strategy_scope_boundary_check.json'
    output.write_text(json.dumps({'status': 'PASS', 'variants': len(variants),
        'checks': ['next-session causal mapping', 'full input coverage before first signal',
                   'insufficient history rejection', 'missing trading endpoint rejection']}, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
