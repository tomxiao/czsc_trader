"""Prospective daily-gap study driver. No operation runs on import.

Future CLI actions explicitly declare, read existing prepared inputs, compute
statistics and publish stage-two evidence. No financial prepare/evaluate exists.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from enum import Enum
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
from uuid import UUID

import pandas as pd
from dataflows import DataRequest

from czsc_trader.application import (ExperimentRequest, assemble_delivery, create_experiment,
                                   publish_evidence, validate_delivery)
from czsc_trader.research_tools import MaterialEvidenceWrite, delivery as d
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence
from czsc_trader.research_tools.evidence import EvidenceRef, managed_path

from verification import verify_formula, verify_statistics

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
HERE = Path(__file__).resolve().parent
PRIOR = ROOT/'research/S013/experiments/EX061_20261011'
ORIGINAL = ROOT/'research/S013/experiments/EX058_20261011'
COMPONENTS = ('negative_gap_repair', 'positive_gap_fade')
MODELS = ('controls', 'controls+negative_gap_repair', 'controls+positive_gap_fade', 'controls+both')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    if path.exists():
        raise ValueError('Immutable output already exists: '+str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+'\n', encoding='utf-8')


def load(name, path):
    path = Path(path)
    if name in sys.modules:
        if Path(sys.modules[name].__file__).resolve() != path.resolve():
            raise ValueError('Bound module name collision: '+name)
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def record(value):
    """Serialize public dataclasses, never invent absent to_dict attributes."""
    if is_dataclass(value):
        return {f.name:record(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {str(k):record(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [record(v) for v in value]
    if isinstance(value, (Enum, Path, date, datetime, UUID)):
        return value.value if isinstance(value, Enum) else str(value)
    return value


def public(value):
    ref = EvidenceRef.from_dict(value)
    if ref.experiment.strategy_id != 'S013':
        raise ValueError('Only authorized S013 public evidence')
    return ref.resolve(ROOT)


def guard_prior(candidate_receipt, candidate_validation, component_receipt, mandate_receipt):
    refs = tuple(d.DeliveryReference.from_dict(x['reference']) for x in
                 (mandate_receipt, component_receipt, candidate_receipt))
    expected = ((d.DeliveryStage.MANDATE, 6), (d.DeliveryStage.COMPONENTS, 3), (d.DeliveryStage.CANDIDATES, 56))
    if any(ref.strategy_id != 'S013' or (ref.stage, ref.revision) != e for ref, e in zip(refs, expected, strict=True)):
        raise ValueError('Exact MANDATE6/COMPONENTS3/latest CANDIDATES56 predecessors required')
    validation = d.DeliveryValidation.from_dict(candidate_validation)
    if validation.status != d.ValidationStatus.PASS or validation.scope != d.DeliveryValidationScope.FULL:
        raise ValueError('EX063 FULL56 must PASS before formal declaration')
    return refs


def modules(config):
    required = {config['feature_source'], config['statistics_source'],
        (HERE/'driver.py').relative_to(ROOT).as_posix(), (HERE/'verification.py').relative_to(ROOT).as_posix(),
        'research/S013/experiments/EX058_20261011/src/common.py'}
    if not required.issubset(config['source_files']):
        raise ValueError('Every executing driver/feature/statistics/trusted reducer source must be frozen')
    for relative, hashed in config['source_files'].items():
        if digest(managed_path(ROOT, relative)) != hashed:
            raise ValueError('Frozen source changed: '+relative)
    feature = load('s013_gap_expression', managed_path(ROOT, config['feature_source']))
    stats = load('s013_gap_statistics', managed_path(ROOT, config['statistics_source']))
    if tuple(feature.COMPONENTS) != COMPONENTS or tuple(stats.COMPONENTS) != COMPONENTS:
        raise ValueError('Exactly two predeclared gap expressions required')
    prior = read(PRIOR/'protocols/plan.json')
    if tuple(stats.CONTROLS) != tuple(prior['controls']) or stats.HORIZONS != prior['statistics']['labels']:
        raise ValueError('Original14 controls and6 labels must remain fixed')
    if (stats.METHOD['bootstrap']['replicates'], stats.METHOD['bootstrap']['block_sessions'], stats.METHOD['bootstrap']['seed']) != (500, 40, 13):
        raise ValueError('Fixed block-bootstrap contract changed')
    if stats.METHOD['walk_forward']['models'] != list(MODELS) or stats.METHOD['walk_forward']['test_years'] != list(range(2021,2027)):
        raise ValueError('Fixed models or chronological years changed')
    for key in ('train','ridge','groups','minimum_train_n','minimum_test_n'):
        if stats.METHOD['walk_forward'][key] != prior['statistics']['walk_forward'][key]:
            raise ValueError('Original matured training/ridge/group contract changed')
    return feature, stats


def context():
    # Original public binding/provider revision is preserved. No external fallback.
    common = load('common', ORIGINAL/'src/common.py')
    return common, common.context(1)


def put(ctx, exp, path, name=None):
    path = Path(path)
    media = {'.py':'text/x-python', '.csv':'text/csv', '.md':'text/markdown'}.get(path.suffix, 'application/json')
    return publish_evidence(ctx, MaterialEvidenceWrite(exp, name or path.stem.replace('_','-'),
        path.read_bytes(), media, path.suffix[1:])).to_dict()


def workdir(config):
    path = managed_path(ROOT, config['work_directory'])
    if not path.is_relative_to(ROOT/'.tmp'):
        raise ValueError('Explicit repository.tmp work directory required')
    return path


def exact_daily_calendar(daily_index, calendar_dates, request):
    if not isinstance(request,DataRequest) or request.frequency != 'daily' or str(request.dataset) != 'etf.ohlcv':
        raise TypeError('Actual typed HFQ daily DataRequest required')
    calendar = pd.DatetimeIndex(pd.to_datetime(calendar_dates)).as_unit('ns')
    if calendar.has_duplicates or not calendar.is_monotonic_increasing or calendar.hasnans:
        raise ValueError('Complete bound calendar must be ordered/unique')
    expected = calendar[(calendar >= pd.Timestamp(request.start)) & (calendar <= pd.Timestamp(request.end))]
    if not daily_index.equals(expected):
        raise ValueError('Daily must exactly cover every calendar session in its typed request range')
    return expected


def declare(config):
    work = workdir(config)
    if (work/'experiment.json').exists():
        raise ValueError('No replacement experiment declaration')
    modules(config)
    expected_prior_paths = {'candidate_receipt':'research/S013/deliveries/CANDIDATES/56/receipt.json',
        'candidate_validation':'research/S013/experiments/EX063_20261011/protocols/delivery_validation.json',
        'component_receipt':'research/S013/deliveries/COMPONENTS/3/receipt.json',
        'mandate_receipt':'research/S013/deliveries/MANDATE/6/receipt.json'}
    if any(config[k] != v for k,v in expected_prior_paths.items()):
        raise ValueError('Exact root predecessor paths must remain bound')
    predecessors = guard_prior(*(read(managed_path(ROOT, config[k])) for k in
        ('candidate_receipt', 'candidate_validation', 'component_receipt', 'mandate_receipt')))
    for key in ('feature_proof', 'statistics_proof', 'driver_proof'):
        proof = read(managed_path(ROOT, config[key]))
        if 'PASS' not in proof['status'] and 'READY' not in proof['status']:
            raise ValueError('Pure proof must pass before declaration')
    for key in ('feature_method','feature_proof','statistics_proof','driver_proof'):
        relative = config[key]
        if relative not in config['evidence_files'] or digest(managed_path(ROOT,relative)) != config['evidence_files'][relative]:
            raise ValueError('Exact prospective method/proof bytes must be pinned')
    common, ctx = context()
    exp = create_experiment(ctx, ExperimentRequest('原缺口收复与回吐是否提供控制后增量',
        '固定两种日线非线性交互能否超出原14 controls解释下一开盘之后的收益及风险？',
        date.fromisoformat(config['run_date'])))
    if exp.experiment_id != config['expected_experiment_id']:
        raise ValueError('Public allocated identity differs; preserve allocation and stop, never replacement')
    priorrefs = read(PRIOR/'protocols/result_references.json')
    inputs = {name:priorrefs[name] for name in ('features.csv','labels.csv','opportunity.csv','input_checks.json')}
    for value in inputs.values():
        public(value)
    plan = {'experiment':exp.to_dict(), 'role':'RSCH', 'stage':2,
        'objective':read(PRIOR/'protocols/plan.json')['objective'],
        'economic_targets_unchanged':True, 'new_economic_hard_gates':False,
        'method':read(managed_path(ROOT, config['feature_method'])),
        'statistics':modules(config)[1].METHOD, 'input_references':inputs,
        'predecessors':[r.to_dict() for r in predecessors], 'source_files':config['source_files'],
        'evidence_files':config['evidence_files'],
        'selection_history':'Root observed EX063 fixed-management hard-gate failures. Pure component/driver authors did not read new prices/accounts. Reused seen development pool is not independent validation.',
        'new_account_preparations':0, 'new_account_evaluations':0,
        'provider_revision':'S013-EX058-existing-only',
        'native_input_cache':'.tmp/s013-mechanism-EX058/N0.pkl.gz',
        'stop':'No direction/window/threshold rescue in this fixed study; predictive diagnostics grant no strategy qualification.'}
    write(work/'plan.json', plan)
    refs = {'plan.json':put(ctx, exp, work/'plan.json')}
    for relative in config['source_files']:
        refs[relative] = put(ctx, exp, managed_path(ROOT, relative))
    for key in ('feature_method','feature_proof','statistics_proof','driver_proof'):
        refs[key] = put(ctx, exp, managed_path(ROOT, config[key]), key.replace('_','-'))
    write(exp.resolve(ROOT)/'protocols/plan.json', plan)
    write(exp.resolve(ROOT)/'protocols/method_references.json', refs)
    write(work/'experiment.json', exp.to_dict())
    if common.SOURCE_CALLS:
        raise ValueError('Provider calls forbidden')
    return {'status':'DECLARED_ZERO_ACCOUNTS', 'experiment':exp.to_dict()}


def csv(path, series=False):
    frame = pd.read_csv(path, index_col='signal_date', float_precision='round_trip')
    frame.index = pd.to_datetime(frame.index).as_unit('ns')
    return frame.iloc[:,0] if series else frame


def study(config):
    work = workdir(config)
    feature_module, stats = modules(config)
    exp = ExperimentRef.from_dict(read(work/'experiment.json'))
    plan = read(work/'plan.json')
    if read(public(read(exp.resolve(ROOT)/'protocols/method_references.json')['plan.json'])) != plan:
        raise ValueError('Public declared plan differs')
    if (work/'statistics.json').exists() or (work/'input_checks.json').exists():
        raise ValueError('No automatic rerun/replacement')
    oldrefs = plan['input_references']
    paths = {name:public(value) for name, value in oldrefs.items()}
    oldfeatures, labels, opportunity = csv(paths['features.csv']), csv(paths['labels.csv']), csv(paths['opportunity.csv'], True)
    prior = read(PRIOR/'protocols/plan.json')
    index = oldfeatures.index
    if (len(index) != prior['signal_grid'][2] or index[0] != pd.Timestamp(prior['signal_grid'][0])
            or index[-1] != pd.Timestamp(prior['signal_grid'][1]) or not labels.index.equals(index)
            or not opportunity.index.equals(index) or opportunity.dtype != bool or opportunity.isna().any()):
        raise ValueError('Whole original signal grid/opportunity required')
    common, ctx = context()
    bound, result = common.cache_read(ROOT/plan['native_input_cache'])
    oldchecks = read(paths['input_checks.json'])
    original_ref = oldchecks['old_native_account_reference']
    if serialize_evaluation_evidence(bound, result) != read(public(original_ref)):
        raise ValueError('Original complete native serialization must match public evidence')
    binding = bound.input_bindings['full']
    fetched = ctx.data.fetch(binding.plan.requests['daily'], prepared=binding.prepared)
    if not fetched.ready or fetched.identity.content_sha256 != oldchecks['identities']['srt_daily']['content_sha256']:
        raise ValueError('Exact EX061 prepared daily identity required')
    if fetched.identity.metadata.get('adjustment') != 'hfq':
        raise ValueError('HFQ daily metadata required')
    daily = fetched.dataframe.copy()
    daily.index = pd.DatetimeIndex(pd.to_datetime(daily['Date'])).as_unit('ns')
    exact_daily_calendar(daily.index,binding.plan.calendar_dates,binding.plan.requests['daily'])
    components = feature_module.build_features(daily, index)
    verify_formula(daily, components)
    features = oldfeatures.loc[:,list(stats.CONTROLS)].join(components)
    pd.testing.assert_frame_equal(features.loc[:,list(stats.CONTROLS)], oldfeatures.loc[:,list(stats.CONTROLS)], check_exact=True)
    if common.SOURCE_CALLS:
        raise ValueError('External provider calls forbidden')
    write(work/'input_checks.json', {'status':'PASS', 'signal_n':len(index),
        'old_controls_exact':True, 'labels_original_byte_reuse':True, 'opportunity_original_byte_reuse':True,
        'native_serialization_exact':True, 'original_native_reference':original_ref,
        'input_references':oldrefs, 'hfq_daily_identity':record(fetched.identity),
        'daily_request':record(binding.plan.requests['daily']), 'prepared':record(binding.prepared),
        'space_id':str(ctx.data.binding.space_id), 'calendar_exact':True,
        'component_zero_counts':{c:int(components[c].eq(0).sum()) for c in COMPONENTS},
        'new_account_preparations':0, 'new_account_evaluations':0, 'provider_calls':common.SOURCE_CALLS})
    features.to_csv(work/'features.csv', index_label='signal_date', float_format='%.17g')
    components.to_csv(work/'gap_observations.csv', index_label='signal_date', float_format='%.17g')
    daily.loc[:,['Open','High','Low','Close']].to_csv(work/'daily_snapshot.csv',index_label='signal_date',float_format='%.17g')
    # Copy original label/opportunity bytes exactly; no relabeling or date selection.
    for name in ('labels.csv','opportunity.csv'):
        (work/name).write_bytes(paths[name].read_bytes())
    statistics = stats.analyze(features, labels, opportunity)
    write(work/'statistics.json', statistics)
    refs = read(exp.resolve(ROOT)/'protocols/method_references.json')
    for name in ('input_checks.json','features.csv','labels.csv','opportunity.csv','gap_observations.csv','daily_snapshot.csv','statistics.json'):
        refs[name] = put(ctx, exp, work/name)
    write(exp.resolve(ROOT)/'protocols/result_references.json', refs)
    return {'status':'STATISTICS_COMPLETE_ZERO_ACCOUNTS', 'signal_n':len(index)}


def verify(config):
    work = workdir(config)
    exp = ExperimentRef.from_dict(read(work/'experiment.json'))
    refs = read(exp.resolve(ROOT)/'protocols/result_references.json')
    resolved = {n:public(refs[n]) for n in ('features.csv','labels.csv','opportunity.csv','statistics.json','input_checks.json','daily_snapshot.csv')}
    features = csv(resolved['features.csv'])
    certificate = read(resolved['input_checks.json'])
    old = {n:public(value) for n,value in certificate['input_references'].items()}
    for name in ('labels.csv','opportunity.csv'):
        if digest(resolved[name]) != digest(old[name]):
            raise ValueError('Independent original byte reuse check failed')
    controls = read(work/'statistics.json')['method']['controls']
    pd.testing.assert_frame_equal(features.loc[:,controls],csv(old['features.csv']).loc[:,controls],check_exact=True)
    formula = verify_formula(csv(resolved['daily_snapshot.csv']),features.loc[:,list(COMPONENTS)])
    output = verify_statistics(features, csv(resolved['labels.csv']),
        csv(resolved['opportunity.csv'], True), read(resolved['statistics.json']),
        pd.Timestamp('2026-09-30'))
    output['published_input_references'] = {n:refs[n] for n in resolved}
    output['input_authentication'] = read(resolved['input_checks.json'])
    output['independent_formula'] = formula
    output['original_controls_and_label_opportunity_bytes_exact'] = True
    write(work/'verification.json', output)
    return {'status':output['status'], 'check_count':output['check_count']}


def judgment(config):
    work = workdir(config)
    result = read(work/'statistics.json')
    compact = {scope:{label:{'components':v['components'], 'models':v['walk_forward']['aggregate_models'],
        'groups':v['walk_forward']['aggregate_groups'], 'annual':v['walk_forward']['yearly'],
        'return_cost_proxy':v.get('return_cost_proxy')}
        for label,v in panel['labels'].items()} for scope,panel in result['scopes'].items()}
    output = {'status':'REQUIRES_ROOT_SCIENTIFIC_REVIEW', 'statistics_sha256':digest(work/'statistics.json'),
        'fixed_hypotheses':{'negative_gap_repair':'post-next-open return positive',
                            'positive_gap_fade':'post-next-open return negative/risk positive'},
        'diagnostics':compact, 'new_accounts':0, 'strategy_goal_achieved':False,
        'zero_mass_and_group_overlap':read(work/'verification.json')['coverage'],
        'limits':'Do not invert failed signs/select years/horizons; no statistical automatic economic gate. Root must explicitly judge both components before delivery.'}
    write(work/'judgment_draft.json', output)
    return {'status':output['status']}


def delivery_content(exp, refs, reviewed):
    if reviewed['status'] != 'ROOT_REVIEWED_FIXED_HYPOTHESES' or set(reviewed['components']) != set(COMPONENTS):
        raise ValueError('Explicit root scientific review of both unchanged hypotheses required')
    if reviewed.get('strategy_goal_achieved') is not False or reviewed.get('new_economic_hard_gates') is not False:
        raise ValueError('Predictive component study cannot claim strategy goal or add economic gates')
    entries = []
    for component in COMPONENTS:
        item = reviewed['components'][component]
        test = d.ComponentTestResult(component.upper()+'-fixed-expression-study', exp.experiment_id,
            EvidenceRef.from_dict(refs['plan.json']), d.ComponentTestStatus(item['test_status']), item['judgment'],
            tuple(EvidenceRef.from_dict(refs[k]) for k in ('statistics.json','verification.json','judgment.json')))
        entries.append(d.ComponentEntry(component.upper(),
            d.ExperimentDefinitionRef(EvidenceRef.from_dict(refs['feature_source']), 'build_features'),
            '已有HFQ日线缺口与收盘的固定非线性交互表达；不是独立新信息',
            'return3/5主、return1辅助；downside1/3/5风险', 'T+1 Open至T+1+h Open',
            '原14 controls；固定500x40 seed13；成熟训练ECDF ridge10四模型',
            'T完整OHLC收盘后、T+1最早入场；历史发布时间未独立验证',
            '原HFQ价格；标签不含费用、不是可执行账户利润',
            '已见S013全池主、原C8880事前资格辅助；非封存验证', item['judgment'], (test,)))
    return d.ComponentPanel(tuple(entries), reviewed['conclusion'])


def delivery_contract(batch, panel, refs, predecessors, report):
    return (d.DeliveryDefinition(batch, d.DeliveryStage.COMPONENTS, 4, predecessors),
            d.DeliveryContent(payload=panel, status=d.DeliveryStatus.COMPLETE, facts=(), explanations=(),
                report=report, evidence=tuple(dict.fromkeys(EvidenceRef.from_dict(r) for r in refs.values()))))


def deliver(config):
    work = workdir(config)
    exp = ExperimentRef.from_dict(read(work/'experiment.json'))
    path = exp.resolve(ROOT)
    if (path/'protocols/delivery_reference.json').exists():
        raise ValueError('No delivery overwrite')
    if read(work/'verification.json')['status'] != 'PASS':
        raise ValueError('Independent verification required')
    reviewed = read(managed_path(ROOT, config['reviewed_judgment']))
    if reviewed['statistics_sha256'] != digest(work/'statistics.json'):
        raise ValueError('Review binds exact completed statistics')
    common, ctx = context()
    refs = read(path/'protocols/result_references.json')
    write(work/'judgment.json', reviewed)
    refs['feature_source'] = refs[config['feature_source']]
    for name in ('verification.json','judgment.json'):
        refs[name] = put(ctx, exp, work/name)
    panel = delivery_content(exp, refs, reviewed)
    report = '# 固定缺口非线性表达检验\n\n'+reviewed['conclusion']+'\n\n'
    for component, item in reviewed['components'].items():
        report += f'- {component}: {item["judgment"]}\n'
    report += '\n统计检验不等于完整账户收益，原四门与32参数诊断目标尚未证明改善。\n\n'
    for name, value in refs.items():
        report += f'- [{name}]({EvidenceRef.from_dict(value).path})\n'
    predecessors = tuple(d.DeliveryReference.from_dict(r) for r in read(work/'plan.json')['predecessors'])
    definition, content = delivery_contract(ctx.batch, panel, refs, predecessors, report)
    receipt = assemble_delivery(ctx.repository, definition, content)
    validation = validate_delivery(ctx.repository, receipt.reference, scope=d.DeliveryValidationScope.FULL)
    write(path/'protocols/delivery_reference.json', receipt.reference.to_dict())
    write(path/'protocols/delivery_validation.json', validation.to_dict())
    write(path/'protocols/final_evidence_references.json', refs)
    if validation.status != d.ValidationStatus.PASS:
        raise ValueError('FULL integrity failure retained; not research success')
    if common.SOURCE_CALLS:
        raise ValueError('Forbidden provider calls')
    return {'status':'COMPONENTS4_FULL_PASS', 'strategy_goal_achieved':False, 'new_accounts':0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('declare','study','verify','judgment','deliver'))
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    print(json.dumps(globals()[args.action](read(args.config)), ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()
