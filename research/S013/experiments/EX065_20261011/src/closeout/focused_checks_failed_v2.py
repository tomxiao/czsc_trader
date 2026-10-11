"""Pure role/schema checks; all actual account/data/public mutations prohibited."""
import ast
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from czsc_trader.research_tools.context import ExperimentRef, ResearchBatchRef
from czsc_trader.research_tools.evaluation_access import EvaluationAccess
from dataflows import Dataflows
from strategy_manager import CandidateKey

import postprocess as closeout

HERE = Path(__file__).resolve().parent
GATES = ('return', 'annual_drawdown', 'frequency', 'negative_buyhold_year_profit')
checks, calls = [], []


def forbidden(*args, **kwargs):
    calls.append('forbidden real capability')
    raise AssertionError('Pure proof forbids actual financial/account/data/public capability')


def fixture(qualified, preferred=True):
    new = ['N_GAP_EXIT'] if qualified else []
    selection = {'preferred': 'N_GAP_EXIT' if qualified and preferred else None,
        'fivecheck_labels': ['B0'] + new, 'absolute_tail_improvement': bool(qualified and preferred),
        'center_qualification_unchanged': True, 'four_tail_nonworsening': False}
    rows, accounts = {}, {}
    for label in ('B0', 'N_GAP_EXIT'):
        good = label == 'B0' or qualified
        rows[label] = {'center_economics': {'gates': dict.fromkeys(GATES,good), 'qualified': good},
            'parameter_references': [{}] * (32 if good else 0)}
    names = ['N_GAP_EXIT', 'N_GAP_EXIT-technical-spawn']
    if qualified:
        names += [f'N_GAP_EXIT-P{i:02}' for i in range(32)] + ['fee-stress-N_GAP_EXIT']
    accounts = {name: {'status':'COMPLETE'} for name in names}
    technical = {'synthetic_public_ref':'technical'}
    state = {'status':'STANDARD_ACCOUNTS_COMPLETE','accounts':accounts,'attempts':len(names), 'technical_reference':technical}
    plans = {'N_GAP_EXIT': {'status':'DECLARED' if qualified else 'NOT_APPLICABLE'}}
    bundle = {'status':'NATIVE_EVIDENCE_BUNDLE_COMPLETE',
        'analysis':{'status':'COMPLETE','rows':rows,'selection':selection},
        'fivechecks':{label:{'diagnostic_only':True,'center_economic_gate_unchanged':True} for label in selection['fivecheck_labels']},
        'all_new_native_accounts':accounts, 'new_actual_evaluations':len(names),
        'qualified_registration_candidates':new,'account_audits':dict.fromkeys(names,{}),
        'technical_reference':technical,'account_counts':{'old_standard_unique':33,'old_fee_unique':1,
            'new_business_unique':1+32*int(qualified),'technical_repeat':1,
            'new_fee_unique':int(qualified),'new_actual':len(names)}}
    return bundle,state,plans,selection


def reject(name, mutate, qualified=True):
    b,s,p,q = deepcopy(fixture(qualified))
    mutate(b,s,p,q)
    try:
        closeout.validate_shape(b,s,p,GATES,q)
    except (ValueError, KeyError):
        checks.append(name)
    else:
        raise AssertionError('Expected refusal: '+name)


def main():
    with (patch.object(EvaluationAccess,'prepare',forbidden),
          patch.object(EvaluationAccess,'evaluate',forbidden),
          patch.object(EvaluationAccess,'evaluate_many',forbidden),
          patch.object(Dataflows,'prepare',forbidden),patch.object(Dataflows,'fetch',forbidden),
          patch.object(closeout,'register_candidate',forbidden),patch.object(closeout,'publish_evidence',forbidden),
          patch.object(closeout,'assemble_delivery',forbidden),patch.object(closeout,'validate_delivery',forbidden),
          patch.object(closeout,'runner_module',forbidden)):
        for good, preferred in ((False,False),(True,True),(True,False)):
            b,s,p,q = fixture(good,preferred)
            assert closeout.validate_shape(b,s,p,GATES,q) == (['N_GAP_EXIT'] if good else [])
            assert s['attempts'] == (35 if good else 2)
            checks.append(f'Exact conditional2or35 qualified={good} preferred={preferred}')
        reject('Missing failed center',lambda b,s,p,q:b['analysis']['rows'].pop('N_GAP_EXIT'))
        reject('Third unauthorized policy',lambda b,s,p,q:b['analysis']['rows'].update(N_LOCK={}))
        reject('Partial native bundle',lambda b,s,p,q:b.update(status='PARTIAL'))
        reject('Terminal failure journal',lambda b,s,p,q:s.update(status='FAILED'))
        reject('32 missing point',lambda b,s,p,q:b['analysis']['rows']['N_GAP_EXIT']['parameter_references'].pop())
        reject('Failed center cannot run32',lambda b,s,p,q:b['analysis']['rows']['N_GAP_EXIT'].update(parameter_references=[{}]*32),False)
        reject('False center qualification',lambda b,s,p,q:b['analysis']['rows']['N_GAP_EXIT']['center_economics'].update(qualified=False))
        reject('Extra economic gate forbidden',lambda b,s,p,q:b['analysis']['rows']['B0']['center_economics']['gates'].update(extra=True))
        reject('Gate numeric rather than bool forbidden',lambda b,s,p,q:b['analysis']['rows']['N_GAP_EXIT']['center_economics']['gates'].update(frequency=1))
        reject('Wrong public preference',lambda b,s,p,q:b['analysis'].update(selection={}))
        reject('No qualified selfchecks even withoutpreferred',lambda b,s,p,q:b['fivechecks'].pop('N_GAP_EXIT'))
        reject('Selfchecks cannot veto qualification',lambda b,s,p,q:b['fivechecks']['N_GAP_EXIT'].update(diagnostic_only=False))
        reject('Missing declared plan',lambda b,s,p,q:p['N_GAP_EXIT'].update(status='NOT_APPLICABLE'))
        reject('False plan after failure',lambda b,s,p,q:p['N_GAP_EXIT'].update(status='DECLARED'),False)
        reject('Register unqualified center',lambda b,s,p,q:b['qualified_registration_candidates'].append('N_GAP_EXIT'),False)
        reject('Extra P00 technical account forbidden',lambda b,s,p,q:s['accounts'].update({'N_GAP_EXIT-P00-technical-spawn':{'status':'COMPLETE'}}))
        reject('New B0 fee forbidden',lambda b,s,p,q:s['accounts'].update({'fee-stress-B0':{'status':'COMPLETE'}}))
        reject('Missing qualified fee',lambda b,s,p,q:s['accounts'].pop('fee-stress-N_GAP_EXIT'))
        reject('Failed individual account',lambda b,s,p,q:s['accounts']['N_GAP_EXIT-P03'].update(status='FAILED'))
        reject('Attempts drift',lambda b,s,p,q:s.update(attempts=36))
        reject('Public count drift',lambda b,s,p,q:b['account_counts'].update(new_actual=34))
        reject('No public technical proof',lambda b,s,p,q:s.update(technical_reference=None))
        reject('Technical proof mismatch',lambda b,s,p,q:b.update(technical_reference={}))
        batch = ResearchBatchRef('S013')
        mandate = closeout.d.DeliveryReference(batch,closeout.d.DeliveryStage.MANDATE,6,'1'*64)
        previous = closeout.d.DeliveryReference(batch,closeout.d.DeliveryStage.CANDIDATES,56,'2'*64)
        closeout.checked_predecessors(mandate,previous,57)
        checks.append('Actual public typed exact Mandate6 CAND56 to57 contract')
        try:
            closeout.checked_predecessors(mandate,previous,58)
        except ValueError:
            checks.append('Wrong CandidateSet revision refused')
        else:
            raise AssertionError('wrong revision accepted')
        key = CandidateKey('S013','C8880')
        assert CandidateKey(**key.to_dict()) == key
        checks.append('Typed public CandidateKey serialization exact')
        native_evidence = closeout.d.CandidateSet((),(),(),'Synthetic complete negative result, not market evidence.')
        content = closeout.d.DeliveryContent(native_evidence,closeout.d.DeliveryStatus.COMPLETE,(),(),report='synthetic')
        assert closeout.d.DeliveryContent.from_dict(content.to_dict()).payload == native_evidence
        checks.append('Public typed delivery payload decode without private API')
        ref = closeout.EvidenceRef(ExperimentRef('S013','EX000_SYNTHETIC'),'3'*64+'.json','3'*64,
            'application/json','synthetic-account','account_evaluation',6)
        entry = closeout.d.CandidateEntry(closeout.d.CandidateIdentityRef(key,'4'*64),
            'synthetic hypothesis','synthetic qualification',(closeout.d.EvaluationEvidenceRef(ref),))
        nonempty = closeout.d.DeliveryContent(closeout.d.CandidateSet((entry,),(),(),'synthetic'),
            closeout.d.DeliveryStatus.COMPLETE,(),(),report='synthetic')
        restored = closeout.d.DeliveryContent.from_dict(nonempty.to_dict())
        assert restored.payload.candidates == (entry,) and restored.payload.candidates[0].evaluations[0].evidence == ref
        checks.append('Retained typed public candidate/evidence schema exact')
        tree = ast.parse((HERE/'postprocess.py').read_text('utf-8'))
        called = {n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
        assert not called.intersection({'prepare','evaluate','evaluate_many','fetch','panels'})
        checks.append('No financial scheduling or direct datafetch in closeout AST')
        assert not any(isinstance(n,ast.ImportFrom) and n.module == 'unittest.mock' for n in ast.walk(tree))
        checks.append('Production closeout has no monkeypatches')
        minimal = {'rows':{},'selection':{'preferred':None}}
        for label in ('B0','N_GAP_EXIT'):
            minimal['rows'][label] = {'center_economics':{'net_cagr':.1,'drawdown':.2,'frequency60':4.,
                'gates':dict.fromkeys(GATES,False),'annual':{},'benchmark_annual':{}},
                'parameter_summary':dict.fromkeys(('q10_cagr','q90_drawdown','joint_pass_count'),None),
                'parameter_references':[], 'gate_pass_counts':{}}
        report = closeout.report_text(SimpleNamespace(bundle={'analysis':minimal,'fivechecks':{}},counts={'new_actual_evaluations':2}))
        assert 'signal holding' in report and 'position' in report and 'EX064' in report and 'N_LOCK' not in report
        checks.append('Signalholding vs actualfills and negative exploratory source explicitly reported')
        assert not calls
        checks.append('Zero actual native/data/financial/public calls under spies')
    result = {'status':'PURE_PASS','checks':checks,'check_count':len(checks),'capability_calls':calls,
        'actual_native_accounts_read':0,'new_account_preparations':0,'new_account_evaluations':0,
        'publications_registrations_assemblies':0,'source_sha256':sha256((HERE/'postprocess.py').read_bytes()).hexdigest(),
        'limits':['Shape and typed public contracts only. collect/finalize not executed on actual accounts.',
            'Future readonly fee audit may fetch only previously bound prepared local inputs, no prepare/evaluate/provider.',
            'FULL material validation is not economic success or goal completion.']}
    (HERE/'focused.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n','utf-8')
    print(json.dumps({'status':'PURE_PASS','check_count':len(checks),'financial_calls':[]}))


if __name__ == '__main__':
    main()
