"""Explicit RSCH controls: original pure formula panels on common V4 execution."""
from pathlib import Path
from dataclasses import replace
from datetime import date
from hashlib import sha256
import json
import shutil
import sys

ROOT = Path.cwd()
HOME = ROOT / '.tmp/s001-v4-correction'
sys.path.insert(0, str(HOME))
from s001_context import build_context, build_request
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import (ExperimentRef, ResearchExecutionSession,
    EvaluationEvidenceWrite, MaterialEvidenceWrite)
from czsc_trader.research_tools.equity_replay import materialize_equity
from dataflows import Dataset, DataCoverageRequirement, ProviderBinding
from dataflows.local_strategy_data import fetch_strategy_feature_evidence
from strategy_runtime import (EquityStrategyCandidate, equity_source_hash,
    DatasetObservationInput, ObservationAvailability)
from strategy_runtime.dataset_observations import FrozenDataAsset

PROGRAM = '''import pandas as pd
from strategy_runtime import AccountStepResult, StateRecord
from .cycle_planner import plan_cycle

def step(ctx, state):
    frame = ctx.observations['signal_panel'].to_frame()
    row = frame.iloc[-1]
    day = pd.Timestamp(row.Date).date()
    raw_day = pd.Timestamp(ctx.history.last()['Date']).tz_convert('Asia/Shanghai').date()
    if day != raw_day:
        raise ValueError('diagnostic signal panel and RAW reference dates differ')
    target = float(row.target_position)
    decision, locked = plan_cycle(ctx, signal_target=target,
        execution=ctx.parameters['rule']['execution'],
        locked_quantity=state.account.get('locked_quantity'),
        had_position=state.account.get('had_position'),
        reason='reviewed pure-formula signal control',
        facts={'signal_day':day.isoformat(),'factor_score':float(row.factor_score),'regime':str(row.regime)})
    return AccountStepResult(decision,StateRecord((('locked_quantity',locked),
        ('had_position',bool(ctx.account.quantity)))),StateRecord())
'''

def main():
    results = []
    for version, eid in [('v1','EX003_20261106'), ('v2','EX004_20261106')]:
        context, native = build_context(version, extra_bindings={Dataset.STRATEGY_FEATURE_EVIDENCE:
            ProviderBinding('repository-evidence','v1',fetch_strategy_feature_evidence)})
        exp = ExperimentRef('S001', eid)
        with ResearchExecutionSession(context, experiment=exp) as execution:
            for mode in ('complete', 'partial'):
                source = HOME / 'controls' / (version + '-' + mode)
                source.mkdir(parents=True, exist_ok=True)
                panel = HOME / 'signals' / (version + '-' + mode + '.csv')
                shutil.copyfile(panel, source / 'signals.csv')
                shutil.copyfile(native.source_root / 'cycle_planner.py', source / 'cycle_planner.py')
                (source / 'strategy.py').write_text(PROGRAM, encoding='utf-8')
                files = ('strategy.py','cycle_planner.py')
                observation = DatasetObservationInput('signal_panel', Dataset.STRATEGY_FEATURE_EVIDENCE,
                    'S001-' + version + '-' + mode, history_start=date(2026,9,2), history_end=date(2026,11,5),
                    coverage=DataCoverageRequirement(maximum_start_lag_days=None, minimum_observations=1, minimum_sessions=0),
                    availability=ObservationAvailability('Asia/Shanghai','15:00'),
                    asset=FrozenDataAsset('signals.csv',sha256((source/'signals.csv').read_bytes()).hexdigest()))
                definition = replace(native.definition, source_files=files,
                    source_sha256=equity_source_hash(source,files), observation_inputs=(observation,))
                cid = {('v1','complete'):'C9981',('v1','partial'):'C9982',
                       ('v2','complete'):'C9983',('v2','partial'):'C9984'}[version,mode]
                candidate = EquityStrategyCandidate('S001',cid,definition,source)
                request = build_request(context,candidate,exp,window_id='PURE_MATH_'+mode.upper())
                prepared = context.evaluation.prepare(request,execution=execution)
                outcome, = context.evaluation.evaluate_many((prepared,),execution=execution)
                if outcome.result is None:
                    raise RuntimeError(str(outcome.error))
                ref = publish_evidence(context,EvaluationEvidenceWrite(exp,'pure-math-'+mode,prepared,outcome.result),execution=execution)
                path = ref.resolve(ROOT)
                payload = materialize_equity(path.read_bytes(),lambda r:(path.parent/(r['sha256']+'.json')).read_bytes()).payload
                result = {'version':version,'mode':mode,'reference':ref.to_dict(),
                          'content_sha256':candidate.content_identity.content_sha256,
                          'run':payload['runs']['candidate']}
                (source/'account.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
                snapshot = {'purpose':'diagnostic pure formula control; not selected for freezing',
                            'candidate':candidate.payload,'panel_sha256':sha256(panel.read_bytes()).hexdigest(),
                            'panel':panel.read_text(encoding='utf-8'),
                            'sources':{name:(source/name).read_text(encoding='utf-8') for name in files}}
                material = publish_evidence(context,MaterialEvidenceWrite(exp,'pure-math-'+mode+'-construction',
                    json.dumps(snapshot,ensure_ascii=False,indent=2).encode('utf-8'),'application/json','json'))
                record = {k:v for k,v in result.items() if k!='run'}
                record['construction_reference'] = material.to_dict()
                results.append(record)
                print(version,mode,'PASS',ref.evidence_id,'fills',len(result['run']['fills']),flush=True)
    (HOME/'control_refs.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__ == '__main__':
    main()
