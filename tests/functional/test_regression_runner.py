"""Regression orchestration must not trade completeness for a shorter run."""
from collections import Counter
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('regression_runner',
    Path(__file__).parents[2] / 'scripts/test_regression.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_regression_discovers_new_files_and_balances_without_duplicates(tmp_path):
    for name in ('tests/test_a.py', 'tests/nested/test_b.py',
                 'packages/execution_channels/tests/extra_test.py', 'tests/helper.py'):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    files = runner.discover_files(tmp_path)
    assert len(files) == 3 and 'tests/helper.py' not in files
    lanes = runner.partition(files, {'tests/test_a.py': 100., 'tests/nested/test_b.py': 40.}, 2)
    assert Counter(f for lane in lanes for f in lane) == Counter(files)
    assert ['tests/test_a.py'] in lanes


@pytest.mark.parametrize('fault', [None, 'missing', 'duplicate', 'uncollected'])
def test_regression_results_must_match_collected_nodes(tmp_path, fault):
    identities = [['tests.test_a', 'test_ok'], ['tests.test_a', 'test_bad[x::y]']]
    (tmp_path / 'one-collected.json').write_text(json.dumps(identities))
    cases = ['<testcase classname="tests.test_a" name="test_ok"/>',
             '<testcase classname="tests.test_a" name="test_bad[x::y]"><failure/></testcase>']
    if fault == 'missing':
        cases.pop()
    elif fault == 'duplicate':
        cases.append(cases[0])
    elif fault == 'uncollected':
        cases.append('<testcase classname="tests.test_a" name="test_unknown"/>')
    (tmp_path / 'one.xml').write_text('<testsuite>' + ''.join(cases) + '</testsuite>')
    if fault:
        with pytest.raises(ValueError, match='coverage mismatch'):
            runner.check_coverage(tmp_path, ['one'])
    else:
        assert runner.check_coverage(tmp_path, ['one']) == dict(nodes=2, failures=1, skipped=0)
