"""The maintained benchmark uses the current API without research artifacts."""
import importlib.util
from pathlib import Path
import pytest


@pytest.mark.parametrize('market',['CN','US'])
def test_synthetic_benchmark_runs_with_isolated_current_facts(tmp_path,market):
    path=Path(__file__).resolve().parents[2]/'scripts/benchmarks/equity_replay_benchmark.py'
    spec=importlib.util.spec_from_file_location('account_benchmark',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result=module.run_benchmark(rows=16,repeats=2,market=market,output=tmp_path)
    assert result['status']=='PASS'
    assert result['runs'][0]['table_hashes']==result['runs'][1]['table_hashes']
    assert result['runs'][0]['runtime']['rows']==16
    assert (tmp_path/'result.json').is_file()
