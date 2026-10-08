"""Exercise the complete SE self-check on the first fully evaluated center."""
from strategy_evaluator import (
    CandidateAssessmentRequest, PerturbationLink, SelfCheckProtocol,
    CandidateComparisonRequest, ComparisonPolicy, ResearchTargets, assess_candidates, compare_candidates,
)
from czsc_trader.research_tools import EvidenceRef
from phase4_common import HERE, read, save, centers, source, d
from assess import facts, independent_checks


def main():
    plan = read(HERE/'plan.json')
    entry = centers()[0]
    base = facts(entry.evaluations[0].evidence)[0]
    evidence = [base]
    relevant = {case['candidate_id'] for case in plan['cases'][:9]}
    for filename in sorted(HERE.glob('batch_*.json')):
        for row in read(filename)['rows']:
            if row['candidate_id'] in relevant:
                assert row['status'] == 'SUCCEEDED'
                evidence.extend(facts(EvidenceRef.from_dict(row['reference'])))
    assert len(evidence) == 11
    links = tuple(PerturbationLink(e.parent, e.candidate, 1., e.derivation_sha256)
                  for e in evidence if e.parent is not None)
    request = CandidateAssessmentRequest((base.candidate,), SelfCheckProtocol.from_dict(plan['protocol']),
                                          links, tuple(evidence))
    panel = assess_candidates(request)
    checks = independent_checks(request, panel)
    targets = tuple(t for i in source('MANDATE', 5).payload.items
                    if isinstance(i.requirement, d.PerformanceRequirement) for t in i.requirement.targets)
    comparison = compare_candidates(CandidateComparisonRequest((base.candidate,),
        ResearchTargets(targets, 60), panel, ComparisonPolicy.from_dict(plan['comparison_policy'])))
    save('se_precheck.json', {'status': 'PASS', 'scope': '首个已完整评价中心C0440的七指标、资金对账、Bootstrap及标准比较',
        'checks': checks, 'assessment': panel.to_dict(), 'comparison': comparison.to_dict(),
        'family': '预检不组装族矩阵；完整17成员诊断在最终全候选自检执行，非以此代替'})
    print({'precheck': 'PASS', 'interval': panel.rows[0].uncertainty.to_dict(),
           'diagnostics': [x.to_dict() for x in panel.rows[0].diagnostics]}, flush=True)


if __name__ == '__main__':
    main()
