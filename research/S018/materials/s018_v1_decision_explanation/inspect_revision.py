"""Run the authorized S018 explanation revision through public stage-five APIs."""
# ruff: noqa: E402
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
BATCH = HERE.parents[1]
PRIOR = BATCH / 'experiments/EX069_20261108'
sys.path.insert(0, str(PRIOR / 'src'))
sys.path.insert(0, str(BATCH / 'experiments/EX070_20261108/src'))

from czsc_trader.application import (RepositoryContext, CandidateRegistrationRequest,
    CandidateInspectionRequest, EquityInspectionProtocol, EquityInspectionReplay, ExperimentRequest,
    FreezeTarget, InspectionDataKind, create_experiment, inspect_candidate, load_candidate,
    record_research_decision, register_candidate)
from czsc_trader.application.research_evidence import validate_inspection
from dataflows import EquityDataRequest, TimeInterval
from data_inputs import build_data_context
from paper_trading_engine.equity_inspection import EquityPteDecision, EquityPteReconcile, EquityPteScenario
from paper_trading_engine.execution_reference import ExecutionReferenceBinding
from run_inspection import protocol, interval_of
from strategy_manager import CandidateEvidence, StrategyRegistry, freeze_contracts as f
from strategy_runtime import EquityInputBinding, EquityStrategyCandidate, EquityStrategyDefinition, InspectionControl, equity_source_hash

CONTENT = 'eed1402632677da0767f53d1304421a81ff2dbb3ed4739b79b560c881325d135'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')


def main():
    repo = RepositoryContext.discover(ROOT)
    old = StrategyRegistry(repo.strategy_root).get_version('S018', 'v1')
    definition = EquityStrategyDefinition.from_dict(dict(old.strategy_payload['equity_definition']))
    source = HERE / 'src'
    revision = EquityStrategyCandidate('S018', 'C9397',
        replace(definition, source_sha256=equity_source_hash(source, ('strategy.py',))), source)
    assert revision.content_identity.content_sha256 == CONTENT
    research, _, _ = build_data_context(repo, definition.execution_spec)
    scratch = ROOT / '.tmp/s018-v1-stage5'
    location = scratch / 'experiment.json'
    if location.exists():
        from czsc_trader.research_tools import ExperimentRef
        experiment = ExperimentRef.from_dict(read(location))
    else:
        experiment = create_experiment(research, ExperimentRequest(
            'S018-v1 决策解释修订阶段五检验', '验证待检包行为、隔离 PTE 以及前瞻图的决策解释。', date(2026, 11, 9)))
        save(location, experiment.to_dict())
    exp = experiment.resolve(ROOT)
    authorization = exp / 'protocols/authorization.json'
    if not authorization.exists():
        save(authorization, {'date': '2026-11-09', 'user_reply': '同意',
            'proposal': '批准 S018-v1 决策解释修订稿进入阶段五，使用隔离 PTE 前瞻图完成 RSCH 可读性签核，再审议原地升级。',
            'source_commit': 'c1a5e2e4b', 'candidate': revision.key.to_dict(), 'content_sha256': CONTENT,
            'scope': '只检验该修订稿，复用留存开发池、通道回报和已知场景。'})
    record = register_candidate(repo, CandidateRegistrationRequest(revision, experiment, (), revision.definition.dependencies))
    assert load_candidate(repo, revision.key).content_identity == revision.content_identity
    selection = record_research_decision(repo, f.ResearchDecision(
        's018-c9397-explanation-stage-five', 'S018', f.DecisionAction.APPROVE,
        f.CandidateSelectionSubject(record.key, record.content_sha256, record.record_sha256),
        CandidateEvidence(authorization.relative_to(ROOT).as_posix(), sha256(authorization.read_bytes()).hexdigest()),
        '用户批准精确的 S018-v1 解释修订稿进入阶段五。'))
    retained = read(PRIOR / 'others/pte_verification.json')
    binding = EquityInputBinding.from_dict(read(PRIOR / 'others/prepared_binding.json'))
    requests = tuple(dict.fromkeys(EquityDataRequest(p.instrument, p.source, p.query)
                                   for _, p in binding.request_bindings))
    zone = ZoneInfo('America/New_York')
    replay = EquityInspectionReplay(f.InspectionCoordinate('MU_DEVELOPMENT', 'STANDARD'), binding, requests,
        TimeInterval(datetime(2023, 1, 3, 9, 30, tzinfo=zone), datetime(2026, 10, 30, 16, tzinfo=zone)),
        100000., .001, execution_reference=ExecutionReferenceBinding.from_dict(retained['raw_binding']))
    pte = protocol(repo, retained)
    flat = next(row for window in [retained, *retained['previous_scenarios']]
                for row in window['decisions'] if not row['orders']
                and row['before']['actual_quantity'] == row['after']['actual_quantity'] == 0)
    span = interval_of(flat)
    cash = Decimal('100000')
    wait_case = EquityPteScenario('flat-wait-no-order',
        (EquityPteReconcile(cash, 0), EquityPteDecision(span, span.start, expected='NO_ORDER')),
        cash, 0, Decimal(0))
    pte = replace(pte, scenarios=(*pte.scenarios, wait_case))
    target = FreezeTarget('v1', old.parent_version, 'S018 决策解释修订，阶段五隔离待检包',
        date.fromisoformat(str(old.selection_data_cutoff)), date.fromisoformat(str(old.forward_start)))
    request = CandidateInspectionRequest(revision.key, selection, research, experiment, target,
        EquityInspectionProtocol('candidate-inspection-v4', 'ECONOMIC_V1', 0., pte),
        (replay,), InspectionDataKind.HISTORICAL)
    attempt = exp / 'others' / f'attempt{len(list((exp / "others").glob("attempt*"))) + 1:02}'
    save(attempt / 'protocol.json', request.protocol.to_dict())
    report = inspect_candidate(repo, request, control=InspectionControl(max_workers=2, timeout_seconds=900,
        on_progress=lambda event: print(event.stage, getattr(event, 'message', ''), flush=True)))
    save(attempt / 'report.json', report.to_dict())
    save(scratch / 'latest.json', {'attempt': attempt.relative_to(ROOT).as_posix(),
                                  'inspection': report.reference.to_dict()})
    assert validate_inspection(ROOT, report.reference) == report
    for goal in (report.behavior_equivalence, report.pte_runtime):
        for case in goal.cases:
            print(case.case_id, case.status.value, case.summary, flush=True)
    if report.status is not f.InspectionStatus.PASS:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
