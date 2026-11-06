"""Compare source-only replacements with the immutable retained V4 accounts."""
from dataclasses import asdict, replace
from datetime import date, datetime
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys

from czsc_trader.application import (ExperimentRequest, FrozenRuntimeUpgradeRequest, RepositoryContext,
    create_experiment, create_research_context, prepare_frozen_runtime_upgrade, publish_evidence, validate_experiment)
from czsc_trader.research_tools import (EquityBuyHold, EquityEvaluationRequest, EquitySources, EvaluationBenchmark,
    EvaluationEvidenceWrite, EvidenceRef, ExperimentOutcome, ExperimentRef, ExperimentReportWrite,
    ExperimentValidationRequest, ExperimentValidationScope, MaterialEvidenceWrite, ResearchBatchRef,
    ResearchExecutionSession)
from czsc_trader.research_tools.equity_replay import materialize_equity
from dataflows import (Dataflows, DataSpace, Dataset, EquityDataRequest, PreparePolicy, ProviderBinding,
                       ProviderConfig, SourceRef, TimeInterval, tushare_equity_bindings)
from strategy_manager.freeze_contracts import FrozenVersionReference, ResearchEvidenceOwner, ResearchEvidenceRef
from strategy_runtime import EquityInputBinding, EquityStrategyCandidate, EquityStrategyDefinition, ExecutionResources
from strategy_runtime.deployment import load_strategy_deployment, validate_release_package
from strategy_runtime.observation_preparation import request_selection


ROOT = Path.cwd()
OUT = ROOT / '.tmp/rsch-source-contract-review/equivalence'
OUT.mkdir(parents=True, exist_ok=True)
REPO = RepositoryContext.discover(ROOT)
NEW_SOURCE = SourceRef('tushare-cn-market', 'v1')
COORDINATES = {
    'S003': ('EX004_20261106', ('account_ref_C9960.json',)),
    'S011': ('EX085_20261106', ('account_STANDARD.json',)),
    'S015': ('EX094_20261106', ('account_STANDARD.json', 'account_FEE_X2.json')),
}
GENERATED_FIELDS = {'decision_id', 'order_id', 'fill_id', 'cycle_id', 'owner', 'plan_identity',
                    'opening_signal_identity', 'implementation'}
ABS_TOL = 1e-8


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


def retained(family):
    experiment, files = COORDINATES[family]
    for name in files:
        doc = read(ROOT / 'research' / family / 'experiments' / experiment / 'others' / name)
        ref = EvidenceRef.from_dict(doc.get('new_reference', doc))
        path = ref.resolve(ROOT)
        payload = path.read_bytes()
        if sha256(payload).hexdigest() != ref.sha256:
            raise ValueError('retained account evidence hash differs')
        material = materialize_equity(payload, lambda item: (path.parent / (item['sha256'] + '.json')).read_bytes())
        yield ref, material.payload


def preserved_source(family, binding):
    path = OUT / family / 'retained-data'
    path.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'research' / family / 'assets/data/assets.sqlite3'
    old = sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)
    copy = sqlite3.connect(path / 'assets.sqlite3')
    try:
        old.execute('PRAGMA query_only=ON')
        old.backup(copy)
    finally:
        old.close()
        copy.close()
    read_only = Dataflows(base_dir=ROOT, space=DataSpace(path.relative_to(ROOT)), providers=ProviderConfig(bindings={}))
    retained_by_request = {}
    equity = tushare_equity_bindings(source=NEW_SOURCE, env_file=ROOT / '.env')
    tables = {}

    def read_retained(query):
        result = retained_by_request[request_selection(query)]
        return result.dataframe.copy(deep=True), dict(result.identity.metadata)

    for role, parameters in binding.request_bindings:
        query = EquityDataRequest(parameters.instrument, parameters.source, parameters.query)
        result = read_only.fetch(query, prepared=binding.prepared)
        if not result.ready or result.identity.content_sha256 != binding.expected_identities[role]:
            raise ValueError(f'retained {role} input differs from the original evidence')
        retained_by_request[request_selection(query)] = result
        equity[parameters.provider_key] = ProviderBinding(parameters.source.provider, parameters.source.revision, read_retained)
    for item in binding.observation_bindings:
        if item.request is None:
            continue
        result = read_only.fetch(item.request, prepared=binding.prepared)
        if not result.ready or result.identity.content_sha256 != item.content_sha256:
            raise ValueError(f'retained table {item.input.name} differs from the original evidence')
        retained_by_request[request_selection(item.request)] = result
        tables[item.request.dataset] = ProviderBinding('retained-table-for-source-control', 'v1', read_retained)
    if any(item.input.dataset is Dataset.STOCK_MONEYFLOW for item in binding.observation_bindings):
        calendar = Dataflows(base_dir=ROOT, space=DataSpace((OUT / family / 'calendar').relative_to(ROOT)),
                             providers=ProviderConfig(env_file=ROOT / '.env'))

        def calendar_provider(query):
            prepared = calendar.prepare((query,), policy=PreparePolicy.REUSE)
            if not prepared.ready:
                raise ValueError('calendar selection did not prepare')
            result = calendar.fetch(query, prepared=prepared.reference)
            if not result.ready:
                raise ValueError(result.error)
            return result.dataframe.copy(deep=True), dict(result.identity.metadata)

        tables[Dataset.TRADING_CALENDAR] = ProviderBinding('tushare-calendar-for-source-control', 'v1', calendar_provider)
    return ProviderConfig(bindings=tables, equity_bindings=equity)


def difference(left, right, path, discrepancies, max_numeric):
    if isinstance(left, dict) and isinstance(right, dict):
        a, b = set(left) - GENERATED_FIELDS, set(right) - GENERATED_FIELDS
        if a != b:
            discrepancies.append((path, sorted(a - b), sorted(b - a)))
        for key in sorted(a & b):
            difference(left[key], right[key], f'{path}.{key}', discrepancies, max_numeric)
    elif isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            discrepancies.append((path + '.count', len(left), len(right)))
        for i, (a, b) in enumerate(zip(left, right)):
            difference(a, b, f'{path}[{i}]', discrepancies, max_numeric)
    elif type(left) in (int, float) and type(right) in (int, float):
        d = abs(left - right)
        max_numeric[0] = max(max_numeric[0], d)
        if d > ABS_TOL or (type(left) is type(right) is int and left != right):
            discrepancies.append((path, left, right))
    elif left != right or type(left) is not type(right):
        discrepancies.append((path, left, right))


def preserved_identity(original, new, definition):
    roles = dict(original.request_bindings)
    updates = dict(new.request_bindings)
    change_roles = {name for name, item in roles.items() if (
        (definition.execution_input is not None and name.startswith('execution:'))
        or (definition.auxiliary_inputs and name.startswith('auxiliary:')))}
    for name, item in roles.items():
        expected = replace(item, source=NEW_SOURCE) if name in change_roles else item
        if updates.get(name) != expected:
            raise ValueError(f'physical request changed outside the approved source fields: {name}')
    if original.observation_bindings != new.observation_bindings:
        raise ValueError('retained table inputs changed')
    for role, digest in original.expected_identities.items():
        if role not in change_roles and new.expected_identities[role] != digest:
            raise ValueError(f'unchanged input changed: {role}')
    return {role: {'before': original.expected_identities[role], 'after': new.expected_identities[role]}
            for role in sorted(change_roles)}


def run(family):
    dest = OUT / family
    dest.mkdir(exist_ok=True)
    baseline = tuple(retained(family))
    original = EquityInputBinding.from_dict(baseline[0][1]['request']['input_binding'])
    release = validate_release_package(ROOT / 'strategies', family + '-v1')
    installed = load_strategy_deployment(ROOT / 'strategies', family + '-v1')
    definition = EquityStrategyDefinition.from_dict(dict(release.release.payload['equity_definition']))
    proposed = (replace(definition, execution_input=replace(definition.execution_input, source=NEW_SOURCE))
        if definition.execution_input is not None else replace(definition, auxiliary_inputs=tuple(
            replace(item, source=NEW_SOURCE) for item in definition.auxiliary_inputs)))
    candidate = EquityStrategyCandidate(family, 'C9971', proposed, installed.source_root)
    assert definition.source_sha256 == proposed.source_sha256 and definition.parameters_json == proposed.parameters_json
    providers = preserved_source(family, original)
    context = create_research_context(REPO, ResearchBatchRef(family), providers=providers,
        execution_spec=definition.execution_spec, resources=ExecutionResources(1, 1, 17))
    marker = dest / 'experiment.json'
    if marker.exists():
        experiment = ExperimentRef.from_dict(read(marker))
    else:
        experiment = create_experiment(context, ExperimentRequest(f'{family}-v1 持续供数来源迁移核对',
            '在原窗口、资金及费用下，只替换冻结输入 SourceRef，核对逐日信号、订单和账户结果。', date(2026, 11, 6)))
        marker.write_bytes(encode(experiment.to_dict()))
    home = experiment.resolve(ROOT)
    (home / 'src/verify_replacement.py').write_bytes(Path(__file__).read_bytes())
    evidence_refs = [item[0] for item in baseline]
    cases = []
    with ResearchExecutionSession(context, experiment=experiment) as session:
        requests = []
        for _, account in baseline:
            old = account['request']
            source = EquitySources(**{key: SourceRef(**item) for key, item in old['sources'].items()})
            window = TimeInterval(**{key: datetime.fromisoformat(value) for key, value in old['window'].items()})
            binding = EquityInputBinding.from_dict(old['input_binding'])
            assert binding == original
            requests.append(EquityEvaluationRequest(experiment, candidate, window, date.fromisoformat(old['history_start']),
                source, old['initial_cash'], old['fee_rate'],
                benchmark=EvaluationBenchmark(EquityBuyHold(definition.execution_spec)),
                window_id=old['window_id'], scenario_id=old['scenario_id'], measurement_tier=old['measurement_tier'],
                drawdown_basis=old['drawdown_basis'], concentration_basis=old['concentration_basis'],
                observation_requests=tuple(item.request for item in binding.observation_bindings)))
        prepared = tuple(context.evaluation.prepare(request, execution=session) for request in requests)
        outputs = context.evaluation.evaluate_many(prepared, execution=session)
        for (old_ref, old), handle, output in zip(baseline, prepared, outputs, strict=True):
            if output.result is None:
                raise RuntimeError(str(output.error))
            new_ref = publish_evidence(context, EvaluationEvidenceWrite(experiment, 'continuous-source-' + handle.request.scenario_id,
                handle, output.result), execution=session)
            evidence_refs.append(new_ref)
            new = materialize_equity(output.result).payload
            identities = preserved_identity(original, handle.request.input_binding, definition)
            a, b = old['runs']['candidate'], new['runs']['candidate']
            discrepancies, maximum = [], [0.0]
            difference(a, b, 'candidate', discrepancies, maximum)
            case = {'status': 'PASS' if not discrepancies else 'FAIL', 'scenario': handle.request.scenario_id,
                'window': old['request']['window'], 'old_ref': old_ref.to_dict(), 'new_ref': new_ref.to_dict(),
                'counts': {name: len(a[name]) for name in ('decisions', 'orders', 'fills', 'account_daily', 'trades')},
                'maximum_numeric_difference': maximum[0], 'differences': len(discrepancies),
                'example_differences': discrepancies[:12], 'source_product_identities': identities}
            cases.append(case)
            (dest / (case['scenario'] + '.json')).write_bytes(encode(case))
            print(family, case['scenario'], case['status'], case['counts'], case['differences'], flush=True)

    scope = {'user_reply': '同意', 'scope': 'source comparison and same-version review preparation',
             'application_authorized': False, 'status': 'PREPARATION_ONLY',
             'note': 'Application requires a separate decision tied to the exact new release and package identity.'}
    payload = {'family': family, 'scope': scope, 'candidate': candidate.key.to_dict(),
        'new_definition': proposed.to_dict(), 'old_release_hash': release.release.release_hash,
        'source_sha256': definition.source_sha256, 'results': cases, 'ignored_generated_fields': sorted(GENERATED_FIELDS),
        'absolute_numeric_tolerance': ABS_TOL}
    comparison = publish_evidence(context, MaterialEvidenceWrite(experiment, 'source-only-comparison', encode(payload),
        'application/json', 'json'))
    evidence_refs.append(comparison)
    owner = ResearchEvidenceOwner(family, experiment.experiment_id)

    def for_upgrade(ref):
        return ResearchEvidenceRef(owner, ref.evidence_id, ref.sha256)

    passed = all(case['status'] == 'PASS' for case in cases)
    if passed:
        consent = publish_evidence(context, MaterialEvidenceWrite(experiment, 'preparation-scope', encode(scope),
            'application/json', 'json'))
        evidence_refs.append(consent)
        staged = prepare_frozen_runtime_upgrade(REPO, FrozenRuntimeUpgradeRequest(
            FrozenVersionReference(family, 'v1', release.release.release_hash, release.package_sha256), candidate,
            for_upgrade(consent), '仅切换冻结输入的 SourceRef 为 tushare-cn-market/v1，代码、参数与其余输入约定一致。',
            'RSCH', (for_upgrade(comparison),), dest / 'review-package'))
        payload['plan'] = {'path': staged.plan_path.relative_to(ROOT).as_posix(), 'sha256': staged.plan_sha256,
            'old': staged.original.to_dict(), 'new': staged.migrated.to_dict(), 'application_authorized': False}
    (home / 'others/source-switch-review.json').write_bytes(encode(payload))
    lines = ['# ' + family + '-v1 持续供数来源迁移核对', '', 'Status: ' + ('COMPLETED' if passed else 'FAILED'), '',
             '按原窗口、资金和费用复用已认证账户作为对照。重新计算仅切换冻结来源键的一侧，其他输入内容一致。', '',
             '| 场景 | 决策 | 订单 | 成交 | 日账 | 差异 |', '| --- | ---: | ---: | ---: | ---: | ---: |']
    for case in cases:
        n = case['counts']
        lines.append(f"| {case['scenario']} | {n['decisions']} | {n['orders']} | {n['fills']} | {n['account_daily']} | {case['differences']} |")
    lines.extend(['', '归属策略内容变化产生的运行标识不参与经济字段比较。数值绝对容差为 1e-8。', '',
        '待批材料详见 [字段与账本证据](others/source-switch-review.json)。', '',
        '发布包阶段为审阅准备，正式应用由用户针对精确新旧身份决定。生产行情准备与经济事实另行验收。', ''])
    report = home / 'report.md'
    report.write_text('\n'.join(lines), encoding='utf-8')
    ref = publish_evidence(context, ExperimentReportWrite(experiment, sha256(report.read_bytes()).hexdigest(),
        ExperimentOutcome.COMPLETED if passed else ExperimentOutcome.FAILED, tuple(evidence_refs)))
    validation = validate_experiment(REPO, ExperimentValidationRequest(experiment, ExperimentValidationScope.REPORT_PUBLICATION))
    (dest / 'completion.json').write_bytes(encode({'experiment': experiment.to_dict(), 'status': 'PASS' if passed else 'FAIL',
        'report': ref.to_dict(), 'report_validation': validation.to_dict(), 'plan': payload.get('plan'), 'cases': cases}))
    print(family, 'REPORT', validation.status, flush=True)


if __name__ == '__main__':
    run(sys.argv[1])
