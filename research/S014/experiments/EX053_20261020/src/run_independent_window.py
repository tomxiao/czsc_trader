"""Run the requested independent TDR account after exact original-window parity."""
from datetime import date
import argparse
import json
from pathlib import Path
import sys

from czsc_trader.application import BacktestRequest, RepositoryContext
from czsc_trader.cli.backtest import run_independent_backtest
from strategy_runtime import ExecutionPriceBasis

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EX / 'work'))
from build_candidate import build, build_declared_candidate  # noqa: E402


def main(candidate_id='C9522'):
    prefix = '' if candidate_id == 'C9522' else 'c9523_'
    control = json.loads((EX / f'others/{prefix}full_control.json').read_bytes())
    assert control['status'] == 'PASS_EXACT_ORIGINAL_FULL_WINDOW'
    assert not (EX / f'others/{prefix}independent_backtest.json').exists()
    candidate, _ = build() if candidate_id == 'C9522' else build_declared_candidate()
    request = BacktestRequest('600722.SH', 'stock', date(2026, 6, 1), date(2026, 10, 19),
                             100000, 100, ExecutionPriceBasis.HFQ_RESEARCH)
    result = run_independent_backtest(RepositoryContext.discover(ROOT), candidate, request, ROOT / 'outputs')
    value = {'status': result.status, 'command': result.command,
             'result': result.result, 'artifacts': result.artifacts,
             'original_candidate': 'S014-C9521', 'window_adapter_candidate': candidate.reference_id,
             'full_window_equivalence': control['account']}
    with (EX / f'others/{prefix}independent_backtest.json').open('x', encoding='utf-8', newline='\n') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write('\n')
    print(json.dumps(value, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--candidate', choices=('C9522', 'C9523'), default='C9522')
    main(parser.parse_args().candidate)
