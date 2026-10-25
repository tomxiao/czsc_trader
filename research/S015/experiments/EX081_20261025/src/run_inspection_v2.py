"""Successor inspection: an incomplete cancellation requires operator review."""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import date
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path

import run_inspection as original
from czsc_trader.application import (
    CandidateInspectionRequest, FreezeTarget, InspectionDataKind, InspectionProtocol,
    describe_inspection_environment, inspect_candidate, load_candidate,
)
from czsc_trader.research_tools import EvidenceRef
from paper_trading_engine.inspection_contracts import CoverageRequirement
from paper_trading_engine.lifecycle import AccountHealth
from strategy_manager import StrategyRegistry
from strategy_manager import freeze_contracts as f
from strategy_runtime.inspection import InspectionControl

ROOT, HOME, OUT = original.ROOT, original.HOME, original.OUT
NEW_ID = 'c9304_partial_cancel_blocked'
OLD_ID = 'c9304_partial_cancel_retry'
BASIS = (
    'packages/paper_trading_engine/src/paper_trading_engine/broker.py',
    'packages/paper_trading_engine/src/paper_trading_engine/futu_execution.py',
    'packages/paper_trading_engine/src/paper_trading_engine/inspection_contracts.py',
    'packages/paper_trading_engine/tests/functional/test_channel_safety.py',
)


def fingerprint(path):
    return sha256(path.read_bytes()).hexdigest()


def verify_prepared(path):
    prepared = original.read(path)
    for relative, expected in prepared['source_hashes'].items():
        assert fingerprint(ROOT / relative) == expected, relative
    for value in prepared['references'].values():
        ref = EvidenceRef.from_dict(value)
        assert fingerprint(ref.resolve(ROOT)) == ref.sha256
    return prepared


def revise(saved, design):
    """Pure correction from pre-existing business rules and prescribed input facts."""
    protocol = InspectionProtocol.from_dict(saved['protocol'])
    pte = protocol.pte
    positive, prior = pte.scenarios
    assert positive.scenario_id == 'c9304_partial_full_cycle' and prior.scenario_id == OLD_ID
    enter, = tuple(x for x in prior.decisions if x.step_id == 'enter')
    events = prior.channel_events[:5]
    assert [x.event_id for x in events] == [
        'entry_accepted', 'entry_open', 'entry_partial', 'entry_repeated', 'entry_cancelled']
    cancelled = events[-1]
    assert cancelled.cumulative_filled_quantity == 45500
    assert cancelled.average_fill_price == Decimal('1.088')
    # Decimal input arithmetic; no report/trace value is used to choose expectations.
    cost = Decimal(cancelled.cumulative_filled_quantity) * cancelled.average_fill_price + cancelled.cumulative_fee
    cash = prior.initial_cash - cost
    assert cost == Decimal('49553.5040') and cash == Decimal('50446.4960')
    allowed = {'LOAD', 'enter:decision', 'enter:repeat', 'enter:submit', *(x.event_id for x in events)}
    checks = []
    for check in prior.checkpoints:
        if check.after_event_id not in allowed:
            continue
        if check.after_event_id == 'entry_cancelled':
            assert check.position_quantity == 45500 and check.cycle_target_quantity == 91100
            assert check.available_cash == cash and check.frozen_cash == 0
            check = replace(check, health=AccountHealth.BLOCKED)
        checks.append(check)
    revised = replace(prior, scenario_id=NEW_ID, decisions=(enter,), channel_events=events,
                      checkpoints=tuple(checks), restart_after=('entry_partial',))
    coverage = tuple(replace(x, scenario_ids=(positive.scenario_id,),
        reason=x.reason + ' Mandatory coverage is supplied by the unchanged complete-cycle scenario.')
        if x.requirement is CoverageRequirement.REQUIRED else x for x in pte.coverage)
    result = replace(protocol, pte=replace(pte, scenarios=(positive, revised), coverage=coverage))
    assert result.pte.scenarios[0].to_dict() == pte.scenarios[0].to_dict()
    assert result.pte.failures == pte.failures and len(pte.failures) == 3
    assert result.float_tolerance == protocol.float_tolerance == 0
    assert InspectionProtocol.from_dict(result.to_dict()) == result
    reasoning = deepcopy(design)
    states = reasoning['expected_entry_cycle_states'].pop(OLD_ID)
    reasoning['expected_entry_cycle_states'][NEW_ID] = {k: v for k, v in states.items() if k in allowed}
    terminal = reasoning['expected_entry_cycle_states'][NEW_ID]['entry_cancelled']
    assert Decimal(terminal['cash_budget']) == prior.initial_cash == Decimal('100000')
    assert Decimal(terminal['buy_cost_including_fees']) == cost
    assert terminal['target_quantity'] == 91100 and terminal['phase'] == 'ACTIVE'
    reasoning['arithmetic'].pop(OLD_ID)
    reasoning['arithmetic'][NEW_ID] = {
        'initial_cash': str(prior.initial_cash), 'partial_quantity': 45500,
        'fill_price': str(cancelled.average_fill_price), 'fee': str(cancelled.cumulative_fee),
        'buy_cost_including_fees': str(cost), 'available_cash_after_cancel': str(cash),
        'frozen_cash_after_cancel': '0', 'cycle_target_quantity': 91100, 'health': 'BLOCKED',
    }
    reasoning['revision'] = {
        'supersedes_scenario': OLD_ID, 'scenario': NEW_ID,
        'reason': 'The original scenario omitted required operator acknowledgement and incorrectly assumed automatic retry. Existing execution-gap policy requires BLOCKED after incomplete terminal cancellation.',
        'basis': list(BASIS), 'first_scenario_and_three_faults_unchanged': True,
        'new_market_data': False, 'candidate_changed': False,
        'cancel_scope': 'Channel-originated partial cancellation without a local cancellation action or operator acknowledgement; no automatic retry is permitted.',
        'recovery_scope': 'Restart after partial fill; the subsequent cancellation must reconcile to the same blocked account as uninterrupted execution.',
        'not_covered': 'Operator acknowledgement and subsequent retry are not expressible in the public inspection scenario contract and are not claimed.',
    }
    reasoning['limits'].append(reasoning['revision']['not_covered'])
    return result, reasoning


def prepare():
    paths = (HOME / 'protocols/inspection_v2.json', OUT / 'pte_design_v2.json',
             OUT / 'protocol_correction.json', OUT / 'prepared_v2.json')
    assert all(not x.exists() for x in paths), 'Preserve all prior preparation/revision artifacts'
    verify_prepared(OUT / 'prepared.json')
    saved = original.read(HOME / 'protocols/inspection.json')
    assert saved['candidate'] == original.KEY.to_dict() and saved['content_sha256'] == original.CONTENT
    protocol, reasoning = revise(saved, original.read(OUT / 'pte_design.json'))
    ctx = original.context()
    registration = StrategyRegistry(ctx.repository.research_registry_root).get_candidate_registration(original.KEY)
    assert registration.content_sha256 == original.CONTENT
    candidate = load_candidate(ctx.repository, original.KEY)
    assert dict(candidate.payload['parameters']) == original.PARAMETERS
    environment = describe_inspection_environment(ctx.repository)
    assert json.loads(json.dumps(environment.to_dict())) == saved['environment'], 'Platform environment changed; reassess before preparing'
    assert not (ROOT / 'strategies/S015/versions/v1.json').exists()
    corrected = deepcopy(saved)
    corrected['protocol'] = protocol.to_dict()
    corrected['protocol_revision'] = 2
    corrected['predecessor_protocol'] = {'path': 'protocols/inspection.json',
        'sha256': fingerprint(HOME / 'protocols/inspection.json')}
    corrected['stop_rule'] = saved['stop_rule'] + ' This separately recorded successor corrects a documented protocol-design error against pre-existing execution-gap policy; preserve the original FAIL and never claim it passed.'
    correction = {
        'type': 'PROTOCOL_DESIGN_CORRECTION', 'revision': 2, 'candidate_changed': False,
        'original_protocol_sha256': fingerprint(HOME / 'protocols/inspection.json'),
        'original_report_sha256': fingerprint(OUT / 'inspection_report.json'),
        'original_prepared_sha256': fingerprint(OUT / 'prepared.json'),
        'rule': 'Incomplete terminal orders require operator acknowledgement. Budget preservation does not authorize automatic retry.',
        'basis': {x: fingerprint(ROOT / x) for x in BASIS},
        'scope': reasoning['revision'],
        'preservation': 'Original protocol, expectations, source and FAIL report remain immutable; v2 is not a relabeling of the first outcome.',
        'limits': ['No platform or candidate change', 'No new input preparation or future market access',
                   'No operator acknowledgement or post-acknowledgement retry coverage'],
    }
    original.save(paths[0], corrected)
    original.save(paths[1], reasoning)
    original.save(paths[2], correction)
    materials = [*paths[:3], Path(__file__).resolve(), HOME / 'src/run_inspection.py',
                 HOME / 'src/pte_protocol.py', HOME / 'protocols/inspection.json',
                 OUT / 'pte_design.json', OUT / 'prepared.json', OUT / 'inspection_report.json',
                 *(ROOT / x for x in BASIS)]
    refs = {p.relative_to(ROOT).as_posix(): original.material(ctx, p).to_dict() for p in materials}
    original.save(paths[3], {'status': 'READY', 'revision': 2, 'references': refs,
        'source_hashes': {p.relative_to(ROOT).as_posix(): fingerprint(p) for p in materials}})
    print('PROTOCOL_V2_READY', len(protocol.pte.scenarios), len(protocol.pte.failures), flush=True)


def inspect():
    assert not (OUT / 'inspection_report_v2.json').exists(), 'Preserve existing v2 report'
    verify_prepared(OUT / 'prepared_v2.json')
    saved = original.read(HOME / 'protocols/inspection_v2.json')
    ctx = original.context()
    registration = StrategyRegistry(ctx.repository.research_registry_root).get_candidate_registration(original.KEY)
    assert registration.content_sha256 == original.CONTENT
    target = saved['target']
    request = CandidateInspectionRequest(original.KEY, f.DecisionReference.from_dict(saved['selection']), ctx, original.EX,
        FreezeTarget(target['version'], target['parent_version'], target['change_summary'],
            date.fromisoformat(target['selection_data_cutoff']), date.fromisoformat(target['forward_start'])),
        InspectionProtocol.from_dict(saved['protocol']), original.replays(), InspectionDataKind.HISTORICAL,
        remaining_risks=tuple(saved['remaining_risks']))

    def progress(event):
        value = asdict(event)
        with (original.CACHE / 'progress_v2.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(value, ensure_ascii=False) + '\n')
        print(json.dumps(value, ensure_ascii=False), flush=True)

    report = inspect_candidate(ctx.repository, request, control=InspectionControl(
        timeout_seconds=1200., max_workers=4, on_progress=progress))
    original.save(OUT / 'inspection_report_v2.json', report.to_dict())
    summary = {'status': report.status.value, 'behavior_equivalence': report.behavior_equivalence.status.value,
        'pte_runtime': report.pte_runtime.status.value, 'inspection_sha256': report.sha256,
        'plan_sha256': report.plan.sha256 if report.plan else None,
        'release_sha256': report.release.release_sha256 if report.release else None,
        'package_sha256': report.release.package_sha256 if report.release else None,
        'protocol_revision': 2, 'original_failure_preserved': True,
        'forward_runtime': 'BLOCKED_BY_CANDIDATE_SOURCE', 'freeze': 'NOT_REQUESTED', 'production': 'NOT_TOUCHED'}
    original.save(OUT / 'inspection_summary_v2.json', summary)
    if report.plan:
        original.save(OUT / 'freeze_plan_v2.json', report.plan.to_dict())
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'inspect'))
    args = parser.parse_args()
    {'prepare': prepare, 'inspect': inspect}[args.mode]()
