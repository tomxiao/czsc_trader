# Risk ownership: INFRA-01
"""Regression orchestration must not trade completeness for a shorter run."""
from collections import Counter
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

spec = importlib.util.spec_from_file_location('regression_runner',
    Path(__file__).parents[2] / 'scripts/test_regression.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)




def test_INFRA_01_C01_regression_discovers_new_files_and_balances_without_duplicates(tmp_path):
    for name in ('tests/test_a.py', 'tests/nested/test_b.py',
                 'packages/execution_channels/tests/extra_test.py', 'tests/helper.py'):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    files = runner.discover_files(tmp_path)
    assert len(files) == 3 and 'tests/helper.py' not in files
    (tmp_path / 'tests/test_unseen.py').touch()
    assert 'tests/test_unseen.py' in runner.discover_files(tmp_path)


def test_INFRA_01_C04_lane_file_order_preserves_nested_conftest_scope(tmp_path):
    files = ['suite/nested/test_first.py', 'suite/test_middle.py', 'suite/nested/test_last.py']
    nested = tmp_path / 'suite/nested'
    nested.mkdir(parents=True)
    (tmp_path / 'pytest.ini').write_text('[pytest]\n', encoding='utf-8')
    (nested / 'conftest.py').write_text(
        'import pytest\n@pytest.fixture\ndef local_fact():\n    return 42\n', encoding='utf-8')
    for name in (files[0], files[2]):
        (tmp_path / name).write_text(
            'def test_local_scope(local_fact):\n    assert local_fact == 42\n', encoding='utf-8')
    (tmp_path / files[1]).write_text('def test_parent():\n    assert True\n', encoding='utf-8')
    # Cost order enters a child, collects its parent file, then revisits the
    # child. Exercise real pytest file collection, not node IDs (which avoid
    # the affected Directory recollection path).
    lane, = runner.partition(files, dict(zip(files, (30., 20., 10.))), 1)
    assert Counter(lane) == Counter(files)
    report = tmp_path / 'result.xml'
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',
               CZSC_PYTEST_RUN_ID=f'runner-order-{tmp_path.name}')
    env.pop('CZSC_PYTEST_COLLECTION', None)
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', '-c', 'pytest.ini', '--confcutdir', str(tmp_path),
         '-q', f'--junitxml={report}', *lane], cwd=tmp_path,
        env=env, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    cases = list(runner.ET.parse(report).iter('testcase'))
    assert len(cases) == 3
    assert all(case.find('error') is None and case.find('failure') is None for case in cases)


def test_INFRA_01_C05_regression_costs_use_three_valid_runs_despite_newer_empty_runs(tmp_path):
    files = [f'tests/test_{key}.py' for key in 'abcd']
    reports = {
        11: ('<testsuite><testcase classname="tests.test_b" time=".1"/>'
             '<testcase classname="tests.test_b" time="0"><error/></testcase></testsuite>'),
        10: None,
        9: '<testsuite',
        8: '<testsuite/>',
        7: '<testcase classname="tests.retired" time="100"/>',
        6: '<testcase classname="tests.test_a" time="2"/>',
        5: ('<testsuite><testcase classname="tests.test_a" time="99"/>'
            '<testcase classname="tests.test_b" time="4"/></testsuite>'),
        4: '<testcase classname="tests.test_c" time="6"/>',
        3: '<testcase classname="tests.test_d" time="8"/>',
    }
    for sequence, xml in reports.items():
        run = tmp_path / f'run-{sequence}'
        run.mkdir()
        if xml is not None:
            (run / 'lane.xml').write_text(xml, encoding='utf-8')
        os.utime(run, (1000 + sequence, 1000 + sequence))
    # Latest per-file measurements win; a fourth usable run stays outside the
    # bounded history even though missing/invalid reports did not consume slots.
    assert runner.measured_costs(files, tmp_path) == {
        'tests/test_a.py': 2., 'tests/test_b.py': 4., 'tests/test_c.py': 6.,
    }


@pytest.mark.parametrize('fault', [pytest.param('missing', id='INFRA-01-C06'), pytest.param('duplicate', id='INFRA-01-C07'), pytest.param('skipped', id='INFRA-01-C08')])
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
    elif fault == 'skipped':
        cases[1] = '<testcase classname="tests.test_a" name="test_bad[x::y]"><skipped/></testcase>'
    (tmp_path / 'one.xml').write_text('<testsuite>' + ''.join(cases) + '</testsuite>')
    if fault == 'skipped':
        result = runner.check_coverage(tmp_path, ['one'])
        assert result == dict(nodes=2, failures=0, skipped=1)
        assert result['skipped'] > 0  # The public runner's PASS gate consumes this count.
        good = '# tests 46\n# pass 46\n# fail 0\n# cancelled 0\n# skipped 0\n# todo 0'
        assert runner.check_node_coverage(good)['tests'] == 46
        with pytest.raises(ValueError, match='Node'):
            runner.check_node_coverage(good.replace('# pass 46', '# pass 45').replace('# skipped 0', '# skipped 1'))
    elif fault:
        with pytest.raises(ValueError, match='coverage mismatch'):
            runner.check_coverage(tmp_path, ['one'])
    else:
        assert runner.check_coverage(tmp_path, ['one']) == dict(nodes=2, failures=1, skipped=0)


def test_INFRA_01_C02_seed_affinity_keeps_each_file_once():
    affinity = tuple(f'tests/functional/test_candidate_{name}.py' for name in (
        'freeze', 'contract_admission', 'inspection_roundtrip', 'inspection_failure'))
    files = ['tests/test_a.py', 'tests/test_b.py', *affinity]
    costs = {'tests/test_a.py': 100., 'tests/test_b.py': 40., **dict.fromkeys(affinity, 30.)}
    lanes = runner.partition(files, costs, 2)
    assert Counter(name for lane in lanes for name in lane) == Counter(files)
    assert sum(bool(set(lane) & set(affinity)) for lane in lanes) == 1
    assert all(lane == sorted(lane) for lane in lanes)


def test_INFRA_01_C03_single_affinity_group_does_not_create_empty_lanes():
    files = ['tests/functional/test_candidate_freeze.py',
             'tests/functional/test_candidate_contract_admission.py']
    assert runner.partition(files, dict.fromkeys(files, 30.), 12) == [sorted(files)]
