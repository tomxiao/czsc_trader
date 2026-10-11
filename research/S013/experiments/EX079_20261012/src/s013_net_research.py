"""Single fixed S013 net-opportunity study, using authenticated prior predictions."""
from datetime import date, datetime, timezone
from hashlib import sha256
import importlib
import json
from pathlib import Path
import sys

from czsc_trader.application import create_experiment, ExperimentRequest, publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').exists())
WORK = ROOT / '.tmp/s013-base-net-opportunity'
OUT = ROOT / '.tmp/s013-base-net-result'
sys.path.insert(0, str(ROOT / 'research/S013/experiments/EX058_20261011/src'))
sys.path.insert(0, str(WORK))
common = importlib.import_module('common')


def read(path):
    return json.loads(Path(path).read_text('utf-8-sig'))


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def public(value):
    ref = EvidenceRef.from_dict(value)
    if ref.experiment.strategy_id != 'S013':
        raise ValueError('S013 only')
    path = ref.resolve(ROOT)
    if digest(path) != ref.sha256:
        raise ValueError('Immutable evidence hash mismatch')
    return path


def put(ctx, exp, path):
    path = Path(path)
    media = {'.py': 'text/x-python', '.csv': 'text/csv', '.md': 'text/markdown'}.get(path.suffix, 'application/json')
    return publish_evidence(ctx, MaterialEvidenceWrite(exp, 'net-' + path.stem.replace('_', '-'), path.read_bytes(), media, path.suffix[1:])).to_dict()


def frame(ref):
    import pandas as pd
    value = pd.read_csv(public(ref), index_col='signal_date', float_precision='round_trip')
    value.index = pd.to_datetime(value.index).as_unit('ns')
    return value


def check(plan):
    for name, expected in {**plan['source_files'], **plan['audit_source_files'], **plan['native_cache']}.items():
        if digest(ROOT / name) != expected:
            raise ValueError('Source/input identity changed: ' + name)
    for ref in plan['input_references'].values():
        public(ref)
    authority = read(public(plan['continuation_budget_reference']))
    if authority['reserved_experiment_sequence'] != [f'EX{i:03}' for i in range(79, 89)]:
        raise ValueError('Exact ten-round authority required')


def declare():
    plan = read(WORK / 'prospective.json')
    check(plan)
    if read(WORK / 'focused_checks.json')['status'] != 'PASS':
        raise ValueError('Focused checks required')
    ctx = common.context(1)
    exp = create_experiment(ctx, ExperimentRequest('原信息的扣费后买入机会识别', '原买入确认与14项联合预测能否事前筛选固定四日正净收益机会？', date(2026, 10, 12)))
    if not exp.experiment_id.startswith('EX079_'):
        raise ValueError('Budget slot1 must allocate EX079')
    plan = {**plan, 'experiment': exp.to_dict(), 'declared_utc': datetime.now(timezone.utc).isoformat()}
    write(OUT / 'plan.json', plan)
    write(OUT / 'experiment.json', exp.to_dict())
    refs = {'plan.json': put(ctx, exp, OUT / 'plan.json'), 'focused_checks.json': put(ctx, exp, WORK / 'focused_checks.json'), 'reuse_precheck.json': put(ctx, exp, WORK / 'reuse_precheck.json')}
    src = exp.resolve(ROOT) / 'src'
    src.mkdir(exist_ok=True)
    for name in plan['source_files']:
        path = ROOT / name
        refs[name] = put(ctx, exp, path)
        if path.is_relative_to(ROOT / '.tmp'):
            with (src / path.name).open('xb') as stream:
                stream.write(path.read_bytes())
    write(exp.resolve(ROOT) / 'protocols/plan.json', plan)
    write(exp.resolve(ROOT) / 'protocols/method_references.json', refs)
    print({'experiment': exp.experiment_id, 'quota_started': 1, 'quota_completed': 0, 'new_accounts': 0}, flush=True)


def study():
    import pandas as pd
    import numpy as np
    plan = read(OUT / 'plan.json')
    check(plan)
    exp = ExperimentRef.from_dict(plan['experiment'])
    refs = read(exp.resolve(ROOT) / 'protocols/method_references.json')
    if read(public(refs['plan.json'])) != plan:
        raise ValueError('Published prospective binding changed')
    write(OUT / 'study_attempt.json', {'status': 'STARTED', 'plan_sha256': digest(OUT / 'plan.json'), 'new_accounts': 0})
    bound, result = common.cache_read(ROOT / '.tmp/s013-mechanism-EX058/N0.pkl.gz')
    if serialize_evaluation_evidence(bound, result) != read(public(plan['input_references']['native'])):
        raise ValueError('Complete original native account mismatch')
    if bound.symbol != '510500.SH' or bound.strategy.candidate_id != 'C8880':
        raise ValueError('Original C8880 only')
    raw = frame(plan['input_references']['features.csv'])
    targets = frame(plan['input_references']['labels.csv'])
    opportunity = frame(plan['input_references']['opportunity.csv'])
    prices = frame(plan['input_references']['prices.csv'])
    if not raw.index.equals(prices.index[1:-1]):
        raise ValueError('Original full1635T/native price axis required')
    history = result.runs[0].execution.decisions.copy().set_index('signal_date')
    history.index = pd.to_datetime(history.index).as_unit('ns')
    if not history.index[1:].equals(raw.index):
        raise ValueError('Native original signal anchor prefix required')
    if opportunity.iloc[:, 0].dtype != bool:
        raise ValueError('Original eligibility Boolean required')
    np.testing.assert_array_equal(opportunity.iloc[:, 0], history.loc[raw.index, 'entry_eligible'])
    aux_mask = history.loc[raw.index, 'confirmation_opportunity']
    assembler = importlib.import_module('inputs')
    statistics = importlib.import_module('net_statistics')
    features, labels, aux, proof = assembler.construct(raw, targets, aux_mask)
    prior = read(public(plan['input_references']['statistics.json']))['scopes']['all']['labels']['return_4']['walk_forward']['prediction_records']['controls']
    if common.SOURCE_CALLS:
        raise ValueError('No provider calls allowed')
    for name, value in {'features.csv': features, 'labels.csv': labels, 'auxiliary.csv': aux.to_frame('confirmation_opportunity'), 'original_history.csv': history[['target_position', 'entry_eligible', 'confirmation_opportunity']]}.items():
        with (OUT / name).open('x', encoding='utf-8', newline='\n') as stream:
            value.to_csv(stream, index_label='signal_date', float_format='%.17g')
    write(OUT / 'input_checks.json', {**proof, 'native_exact': True, 'input_references': plan['input_references'], 'provider_calls': 0, 'new_accounts': 0, 'old_records_n': len(prior)})
    outcome = statistics.analyze(features, labels, aux, prior)
    write(OUT / 'statistics.json', outcome)
    write(OUT / 'study_complete.json', {'status': 'COMPLETE', 'analyze_calls': 1, 'statistics_sha256': digest(OUT / 'statistics.json'), 'new_accounts': 0, 'provider_calls': 0})
    ctx = common.context(1)
    result_refs = {name: put(ctx, exp, OUT / name) for name in ('input_checks.json', 'features.csv', 'labels.csv', 'auxiliary.csv', 'original_history.csv', 'statistics.json', 'study_complete.json')}
    write(exp.resolve(ROOT) / 'protocols/result_references.json', result_refs)
    print({'experiment': exp.experiment_id, 'statistics': 'COMPLETE', 'new_accounts': 0}, flush=True)


if __name__ == '__main__':
    {'declare': declare, 'study': study}[sys.argv[1]]()
