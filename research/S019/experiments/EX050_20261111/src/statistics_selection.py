"""EX041 typed annual selection-stability reuse plus exact later sources.

prepare writes a typed request only. compute performs read-only public TDR
projection; no strategy replay. Selection uses original six center gates and NAR.
"""
import argparse
from collections import defaultdict
from pathlib import Path

import statistics_analysis as stats
import strategy_evaluator as se
from czsc_trader import research_tools as d
from czsc_trader.application import RepositoryContext, project_selection_window_facts
from strategy_runtime import canonical_sha256

WORK, ROOT = stats.WORK, stats.ROOT
PRIOR_FILES = (
    stats.EXPERIMENTS / 'EX039_20261110/others/statistics_selection_projection.json',
    stats.PRIOR / 'others/statistics_incremental_projection.json',
)


def existing():
    values = [d.SelectionWindowFactsResult.from_dict(stats.read(p)) for p in PRIOR_FILES]
    assert all(not p.failures for p in values)
    assert values[0].request.plan.calendar == values[1].request.plan.calendar
    return values


def targets():
    mandate = stats.read(ROOT / 'research/S019/assets/deliveries/MANDATE/2/delivery.json')
    items = next(x for x in mandate['content']['payload']['items'] if x['item_id'] == 'targets')['requirement']['targets']
    selected = [x for x in items if x['target_id'].startswith('center-')]
    assert len(selected) == 6
    return se.ResearchTargets.from_dict({'type': 'ResearchTargets', 'requirements': selected, 'frequency_window_days': 60})


def prepare():
    old = existing()
    inventory = stats.read(WORK / 'statistics_inventory.json')
    protocol = stats.read(WORK / 'statistics_protocol.json')
    known = {s.evaluation.sha256 for projection in old for s in projection.request.sources}
    additions = [r for r in inventory['rows'] if r['reference']['sha256'] not in known]
    assert len(known) + len(additions) == inventory['unique_implementations']
    raw_plan = old[0].request.plan.to_dict()
    raw_plan['limitations'] = protocol['limitations']
    plan = se.SelectionWindowPlan.from_dict(raw_plan)
    request = d.SelectionWindowFactsRequest(tuple(d.SelectionWindowSource(
        se.AssessmentCandidate('S019-' + row['candidate_id'], row['content_sha256']),
        d.EvidenceRef.from_dict(row['reference'])) for row in additions), plan, 60, 3,
        d.SelectionProjectionBudget(10000, 50000000000, 5000000000))
    assert d.SelectionWindowFactsRequest.from_dict(request.to_dict()) == request
    rule = se.SelectionRule('S019-original-center-gates-NAR-v1',
        stats.digest(ROOT / 'research/S019/materials/stage1_agreement.md'), targets(),
        (se.SelectionMetricOrder(se.ResearchMetric.NET_ANNUAL_RETURN, se.SelectionDirection.MAXIMIZE),))
    stats.save('statistics_selection_request.json', request.to_dict())
    stats.save('statistics_selection_preparation.json', {
        'status': 'PREPARED_NOT_COMPUTED', 'new_accounts': 0,
        'reuse_sources': {p.relative_to(ROOT).as_posix(): stats.digest(p) for p in PRIOR_FILES},
        'source_sha256': stats.digest(Path(__file__)),
        'request_sha256': stats.digest(WORK / 'statistics_selection_request.json'),
        'protocol_sha256': stats.digest(WORK / 'statistics_protocol.json'),
        'inventory_sha256': stats.digest(WORK / 'statistics_inventory.json'),
        'reused_implementations': len(known), 'incremental_implementations': len(additions),
        'incremental_candidate_bytes': sum(r['candidate_bytes'] for r in additions),
        'public_projection_budget': request.budget.to_dict(), 'rule': rule.to_dict(),
        'limitations': protocol['limitations'] + [
            'Historical candidate universe was chosen using the full seen sample; annual results are retrospective diagnostics.',
            'Adaptive gated-NAR selection bias remains NOT_ESTIMATED; this measures observed chronological selection sensitivity.',
            'Sharpe-proxy PBO/DSR are omitted in this preparation to avoid a second full-family return extraction.']})
    print('SELECTION_REQUEST_PREPARED', len(known), len(additions))


def compute():
    prepared = stats.read(WORK / 'statistics_selection_preparation.json')
    assert prepared['source_sha256'] == stats.digest(Path(__file__))
    for path, fingerprint in prepared['reuse_sources'].items():
        assert stats.digest(ROOT / path) == fingerprint
    assert prepared['request_sha256'] == stats.digest(WORK / 'statistics_selection_request.json')
    request = d.SelectionWindowFactsRequest.from_dict(stats.read(WORK / 'statistics_selection_request.json'))
    path = WORK / 'statistics_incremental_projection.json'
    if path.exists():
        incremental = d.SelectionWindowFactsResult.from_dict(stats.read(path))
        assert incremental.request == request
    else:
        incremental = project_selection_window_facts(RepositoryContext.discover(ROOT), request)
        stats.save(path.name, incremental.to_dict())
    assert not incremental.failures
    projections = [*existing(), incremental]
    groups, facts = defaultdict(list), {}
    for projection in projections:
        for binding in projection.sources:
            groups[(binding.context_sha256, canonical_sha256(binding.scenario_context.to_dict()))].append(binding)
        for fact in projection.facts:
            key = fact.source_id, fact.window.window_id
            if key in facts:
                assert facts[key] == fact
            facts[key] = fact
    outcomes = []
    rule = se.SelectionRule.from_dict(prepared['rule'])
    for context, bindings in groups.items():
        ids = {item for binding in bindings for item in (binding.source_id, binding.benchmark_source_id)}
        analysis = se.SelectionStabilityRequest(request.plan, rule, tuple(bindings),
                    tuple(f for f in facts.values() if f.source_id in ids), targets())
        result = se.assess_selection_stability(analysis)
        outcomes.append({'context': context, 'members': [x.candidate.candidate_id for x in bindings],
                         'request': analysis.to_dict(), 'result': result.to_dict()})
    stats.save('statistics_selection.json', {'status': 'COMPLETE', 'groups': outcomes,
               'new_accounts': 0, 'preparation_sha256': stats.digest(WORK / 'statistics_selection_preparation.json'),
               'incremental_projection_sha256': stats.digest(path),
               'actual_adaptive_nar_gated_selection_bias': 'NOT_ESTIMATED',
               'limitations': prepared['limitations']})
    print('SELECTION_COMPLETE', sum(len(x) for x in groups.values()), len(groups))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('prepare', 'compute'))
    options = parser.parse_args()
    {'prepare': prepare, 'compute': compute}[options.action]()
