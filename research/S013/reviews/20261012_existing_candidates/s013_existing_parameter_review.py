"""Authenticate and summarize existing standard32 evidence, without new accounts."""
from collections import Counter
import math

from strategy_evaluator import AssessmentEvidence
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.parameter_evaluation import read_parameter_plan
from czsc_trader.research_tools.evaluation import validate_evaluation_evidence
import s013_existing_candidate_review as base


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def main():
    centres = base.read(base.OUT/'centres.json')['rows']
    current = {r['candidate_id']: r for r in centres if r['status'] == 'CURRENT_CONTRACT'}
    plans = {}
    for ref in base.read(base.OUT/'metadata_reference_index.json'):
        document = base.read(base.ref_path(ref))
        for item in walk(document):
            if item.get('type') == 'ParameterEvaluationPlan':
                cid = item['design']['center']['candidate_id'].removeprefix('S013-')
                if cid in current:
                    plans[ref['sha256']] = (ref, item)
            if item.get('type') == 'EvidenceRef' and item.get('media_type') == 'application/json' and 'plan' in item.get('name',''):
                path = base.ref_path(item)
                plan = base.read(path)
                if plan.get('type') == 'ParameterEvaluationPlan':
                    cid = plan['design']['center']['candidate_id'].removeprefix('S013-')
                    if cid in current:
                        plans[item['sha256']] = (item, plan)
    # A direct plan must be the whole referenced document, not an embedded plan.
    plans = {key:(ref, p) for key,(ref,p) in plans.items()
             if base.read(base.ref_path(ref)).get('type') == 'ParameterEvaluationPlan'}
    typed = {}
    for key,(ref, _) in plans.items():
        typed[key] = read_parameter_plan(EvidenceRef.from_dict(ref), repository_root=base.ROOT)
        protocol = typed[key].design.protocol
        assert protocol.point_count == 32 and protocol.radius == .05 and protocol.seed == 13
    print('declared_current_plan_count', len(plans), flush=True)
    target_experiments = {r['experiment']['experiment_id'] for r,_ in plans.values()}
    accounts = {}
    spec = base.importlib.util.spec_from_file_location('review_economics',base.ROOT/'research/S013/experiments/EX074_20261011/src/economics_reference.py')
    module = base.importlib.util.module_from_spec(spec)
    base.sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    for ref in base.read(base.OUT/'account_reference_index.json'):
        if ref['experiment']['experiment_id'] not in target_experiments:
            continue
        evidence = base.read(base.ref_path(ref))
        binding = evidence.get('request_identity',{}).get('parameter_binding')
        if not binding or binding['plan']['sha256'] not in plans:
            continue
        key = binding['plan']['sha256']
        ix = binding['point']['point_index']
        actual_plan_ref = EvidenceRef.from_dict(binding['plan'])
        base.ref_path(binding['plan'])
        assert typed[key].bind_point(actual_plan_ref, ix, repository_root=base.ROOT).to_dict() == binding
        validate_evaluation_evidence(evidence)
        assert len(evidence['assessment_evidence']) == 1
        a = evidence['assessment_evidence'][0]
        cid = typed[key].design.center.candidate_id.removeprefix('S013-')
        assert a['parent'] == typed[key].design.center.to_dict()
        assert a['candidate'] == typed[key].children[ix].candidate.to_dict()
        assert a['scenario_context']['benchmark_contract_sha256'] == base.CONTRACT and a['scenario_context']['one_way_cost'] == .001
        e = module.economics(AssessmentEvidence.from_dict(a))
        value = {'reference': ref, 'point_index': ix, 'candidate_id': a['candidate']['candidate_id'],
                 'result_hash': evidence['result_hash'], 'economics': e}
        if (key,ix) in accounts:
            assert accounts[key,ix]['economics'] == e
        else:
            accounts[key,ix] = value
    rows = []
    for key,(ref,_) in plans.items():
        cid = typed[key].design.center.candidate_id.removeprefix('S013-')
        points = [accounts[key,i] for i in range(32) if (key,i) in accounts]
        gates = {name:sum(p['economics']['gates'][name] for p in points)
                 for name in ('return','annual_drawdown','frequency','negative_buyhold_year_profit')}
        counts = len(points)
        joint = sum(p['economics']['qualified'] for p in points)
        row = {'candidate_id':cid,'plan_reference':ref,'dimensions':len(typed[key].design.space.coordinates),
               'available_points':counts,'point_gate_counts':gates,'joint_pass':joint,
               'robustness_status':'PASS' if counts==joint==32 else ('FAIL' if counts==32 else 'INSUFFICIENT_DATA'),
               'points':points}
        rows.append(row)
    base.save('standard32.json',{'plans':len(rows),'rows':rows,'new_account_evaluations':0})
    historical = Counter()
    for row in centres:
        if row['status']=='HISTORICAL_SCHEMA_NOT_CURRENT':
            ev=base.read(base.ROOT/row['source'])
            historical[(ev['schema_version'],ev['request_identity']['benchmark']['execution']['type'])]+=1
    facts=[]
    for cid,c in current.items():
        a=base.read(base.ROOT/c['source'])['assessment_evidence'][0]
        positive=set(c['positive_buyhold_years'])
        held=sum(p['quantity']>0 for p in a['account'] if p['session'][:4] in positive)
        relevant=[r for r in rows if r['candidate_id']==cid]
        assert len(relevant)==1, (cid,len(relevant))
        p=relevant[0]
        facts.append({'candidate_id':cid,'central_four_pass':c['current_four_gates_pass'],
          'closed_trades':c['economics']['closed_trades'],'positive_year_days':c['positive_year_sessions'],
          'positive_year_closed_trades':c['positive_year_closed_trades'],
          'positive_year_minimum_closed_trades':math.ceil(c['positive_year_sessions']/15),
          'positive_year_frequency60':c['positive_year_frequency60'],
          'positive_year_frequency_pass':c['positive_year_frequency_pass'],
          'positive_year_held_sessions':held,'positive_year_position_fraction':held/c['positive_year_sessions'],
          'standard32_points':p['available_points'],'standard32_joint_pass':p['joint_pass'],
          'robustness_status':p['robustness_status'],
          'all_review_conditions_pass':c['current_four_gates_pass'] and c['positive_year_frequency_pass'] and p['robustness_status']=='PASS'})
    summary={'status':'EXISTING_CANDIDATE_REVIEW_COMPLETE','registered_candidates':len(centres),
      'historical_incomparable':[{'schema':k[0],'benchmark_type':k[1],'count':v} for k,v in historical.items()],
      'current_candidate_count':len(facts),'current_standard32_count':len(rows), 'rows':facts,
      'jointly_qualified_candidates':[r['candidate_id'] for r in facts if r['all_review_conditions_pass']],
      'frequency_year_assignment':'actual closed-cycle exit date',
      'positive_years':next(iter(current.values()))['positive_buyhold_years'],
      'new_experiments':0,'new_accounts':0,'parameter_optimization':False,
      'original_hard_gates_changed':False,'research_remains_paused':True}
    base.save('summary.json',summary)
    print(base.json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
