"""Freeze four complementary price-category controls before native evaluation."""
from copy import deepcopy
from strategy_runtime import StrategyRuntime, StrategyCandidate, implementation_sha256
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.evidence import EvidenceRef
from common import ROOT, SRC, PROTOCOLS, EXPERIMENT, DEPENDENCIES, context, read, write, file_hash


def main():
    assert not (PROTOCOLS / 'plan_references.json').exists()
    prior = read(ROOT / 'research/S013/experiments/EX041_20261011/protocols/plan.json')
    controls = deepcopy(prior['controls'])
    for old, label in zip(prior['configurations'], ('B0-TIME-CLOSE','B0-TIME-BODY'), strict=True):
        old = deepcopy(old)
        old.update(label=label, reused=True, reuse_from='EX041_20261011', reuse_label=old['label'])
        controls.append(old)
    files = ['strategies/' + name + '.py' for name in
             ('range_reversion','adaptive_range','confirmed_range','reentry_confirmed_range','mechanism_range','__init__')]
    source_hash = implementation_sha256(files, source_root=SRC / 'strategy_runtime')
    configurations = []
    mechanisms = ('MEAN_BEAR_TIME_BELOW_CLOSE','MEAN_BEAR_TIME_BELOW_BODY',
                  'MEAN_BEAR_TIME_ABOVE_CLOSE','MEAN_BEAR_TIME_ABOVE_BODY')
    for index, mechanism in enumerate(mechanisms):
        payload = deepcopy(controls[1]['payload'])
        payload['parameters']['mechanism'] = mechanism
        payload['runtime'].update(module='strategy_runtime.strategies.mechanism_range', qualname='MechanismRange',
                                  source_files=files, source_sha256=source_hash)
        strategy = StrategyCandidate('S013', f'C{4900+index}', payload, SRC / 'strategy_runtime')
        identity = StrategyRuntime().identify(strategy, dependencies=DEPENDENCIES)
        expected = deepcopy(controls[1]['payload']['parameters'])
        expected['mechanism'] = mechanism
        assert payload['parameters'] == expected
        configurations.append({'label':f'N{index}','index':index,'candidate_id':strategy.candidate_id,
            'content_sha256':identity.content_sha256,'payload':payload,'source_directory':'strategy_runtime',
            'background':'MEAN','mechanism':mechanism,'mode':'M1','existing_identity':None,
            'reused':False,'parent_control':'B0-MEAN'})
    ctx=context(1)
    for cfg in configurations:
        assert not (ctx.repository.research_registry_root / f"S013/candidates/{cfg['candidate_id']}.json").exists()
        assert not (ROOT / f"research/S013/assets/candidates/{cfg['candidate_id']}").exists()
    previous = read(ROOT / 'research/S013/assets/deliveries/CANDIDATES/38/delivery.json')
    names={'native-anchors','research-decision','prior-account-descriptive-diagnosis'}
    diagnosis={r['name']:r for r in previous['content']['evidence'] if r['name'] in names}
    assert set(diagnosis)==names
    for value in diagnosis.values():
        ref=EvidenceRef.from_dict(value)
        assert ref.experiment.strategy_id=='S013' and file_hash(ref.resolve(ROOT))==ref.sha256
    pure=read(ROOT / '.tmp/ex043_parameters/focused.json')
    assert pure['status']=='PURE_PASS' and pure['new_account_evaluations']==0
    plan={'name':'S013-EX043-complementary-bear-time-exit-category-directions',
        'controls':controls,'configurations':configurations,
        'cells':[{k:cfg[k] for k in ('background','mechanism','label','candidate_id','content_sha256')} for cfg in controls+configurations],
        'mandate':prior['mandate'],'authorization':prior['authorization'],
        'previous_delivery':read(ROOT / 'research/S013/experiments/EX042_20261011/protocols/delivery_reference.json'),
        'diagnosis_references':diagnosis,
        'hypothesis':'Uniform bearTIME direction gates failed2023. Complementary strict signal-exit price categories may retain recoveries that a uniform gate removes. Test both BELOW/ABOVE scopes and CLOSE/BODY predicates without presuming negative-price exits are harmful.',
        'mechanism':'At T, only flat-before AND originaleligible AND rawregime=bear AND last final signal exit reason=time/route=bear AND last exit Close strictly BELOW or ABOVE its own signal entry Close anchor receives strict Close_T>previous daily Close or Close_T>Open_T gate before original score. Classify only final bearTIME exit. EQUAL/nonbearTIME/initial context=None; all unselected categories retain original MEAN score. Every any-route entry consumes/clears reason/route/category. Flat refusal, eligibility failure and raw change preserve all. No future price windows, magnitude/tolerance/threshold/year exception.',
        'preserved':'All13 original numeric values/full domains, H8/H4 signal holding units, all holding exit priority/loss/trail/range/time/regime and original confirmation score retained. Existing strict-past-L centered bearACF and warmupL+21 remain; original execution/cost/data/benchmark/date calendar retained.',
        'fixed_new_choices':'Four categorical scope+direction choices and exit-anchor memory outside13numeric coordinates. Strict price category does not equal actual trade PnL. No categorical robustness or independent validation claim.',
        'strongest_counterevidence':'EX042 original2023 BELOW-source actual contribution+2.3049pp, MEAN/BODY2024 BELOW-source about+33.6747/+33.6749pp. Old-path groups cannot predict new-account deletion profit; categories change with endogenous signal path. EX041 both uniformTIME gates2023 about-1.25%, EX040 all-bear gates under110closed. No assumption that BELOW is adverse; complementaryABOVE controls mandatory.',
        'selection_history':'Repeatedly exposed S013 development pool. Chosen after37-account complete native EXIT-anchor/cash diagnosis and EX016 prior short-window counterevidence. No new future window computed. Review found no exact source-plan bearTIME selected BELOW/ABOVE reentry gate; EX016 conditioned whether exits occur, EX041 gated allTIME reentries. Structural novelty is not evidence of profit.',
        'predeclared_selection':'Four new complete business configurations/five actual evaluations inclN0serial-spawn exact duplicate;four old controls exact native reuse. Only new centers satisfying all4original economic gates receive32business/33actual originalfull13-domain points each. OriginalEX01532 exact native reuse once if anyqualifier. No failed center expansion, point replacement, narrowdomains or diagnostic veto. Qualifyingcenter plus absoluteQ10CAGR/Q90DD and both relative degradations improving against original required for improvement.',
        'counts':{'new_business_configurations':4,'new_evaluations':5,'reused_controls':4},
        'resources':{'max_workers':8,'native_threads':1,'request_workers':1,'seed':13},
        'boundaries':'RSCH S013stage3; no adjacent batch bytes/newdata/dependencies/platform/freeze/PTE/prod/merge/tag/push.',
        'source_files':{p.relative_to(SRC).as_posix():file_hash(p) for p in SRC.rglob('*.py') if 'strategy_runtime' in p.parts or p.name in ('direction_oracle.py','synthetic_checks.py')},
        'date_contract':'Frozen41v2 full bound-calendar pair audit retained exactly. No dropping endpoint T or requiring T+1 signal OHLC.',
        'prospective_pure_verification':pure}
    write(SRC.parent/'experiment.json',{'type':'ExperimentRef','strategy_id':'S013','experiment_id':EXPERIMENT.experiment_id})
    write(PROTOCOLS/'plan.json',plan)
    write(PROTOCOLS/'authorization.json',prior['authorization'])
    write(PROTOCOLS/'plan_references.json',{p.stem:publish_evidence(ctx,MaterialEvidenceWrite(EXPERIMENT,
        'mechanism-'+p.stem,p.read_bytes(),'application/json','json')).to_dict() for p in (PROTOCOLS/'plan.json',PROTOCOLS/'authorization.json')})
    print({'declared':EXPERIMENT.experiment_id,'new_configurations':4},flush=True)


if __name__=='__main__':
    main()
