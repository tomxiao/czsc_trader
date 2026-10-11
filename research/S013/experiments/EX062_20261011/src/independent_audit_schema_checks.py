"""Synthetic-only coverage of actual summary annual schemas; no native reads."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import driver
from independent_audit import compare_economics


def main():
    annual = {'return': .1, 'drawdown': .2, 'opening_equity': 1e6, 'closing_equity': 1.1e6}
    actual = {'net_cagr': .1, 'drawdown': .2, 'frequency60': 4., 'closed_trades': 110,
              'gates': {'return': True}, 'qualified': True,
              'annual': {'2020': annual}, 'benchmark_annual': {'2020': annual}}
    stored = deepcopy(actual)
    stored['benchmark_annual']['2020'] = {'return': .1, 'drawdown': .2}
    compare_economics(actual, stored)
    checks = 1
    for name, key in (('annual', 'closing_equity'), ('benchmark_annual', 'return'),
                      ('benchmark_annual', 'drawdown')):
        wrong = deepcopy(stored)
        wrong[name]['2020'][key] += .01
        try:
            compare_economics(actual, wrong)
        except AssertionError:
            checks += 1
        else:
            raise AssertionError((name, key))
    source = Path(__file__).with_name('independent_audit.py')
    output = {'status': 'PURE_PASS', 'checks': checks, 'native_reads': 0,
              'new_account_evaluations': 0, 'preparations': 0, 'publications': 0,
              'source_sha256': sha256(source.read_bytes()).hexdigest()}
    driver.write(Path(__file__).resolve().parents[1] / 'protocols/independent_audit_schema_checks.json', output)
    print(output)


if __name__ == '__main__':
    main()
