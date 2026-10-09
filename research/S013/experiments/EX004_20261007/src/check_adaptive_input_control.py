"""Authenticate both public preparations, including pre-2020 signal warmup."""
from hashlib import sha256
import json
import pandas as pd
from strategy_runtime import StrategyInputBinding, canonical_sha256
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef
from common import ROOT, RUNS, context, cache_read, save


def main():
    research = context(4)
    bindings = []
    inputs = []
    for c in ('C0439', 'C0440'):
        result = cache_read(ROOT / f'.tmp/s013-stage3-hfq/{c}.pkl.gz')
        raw = result.runs[0].signals.support_data['input_binding']
        bindings.append(StrategyInputBinding.from_mapping(raw))
        inputs.append(result.runs[0].signals.support_data['execution_input_identities'])
    plans = [b.plan.to_dict() for b in bindings]
    for p in plans:
        p.pop('strategy')
    assert plans[0] == plans[1] and inputs[0] == inputs[1]
    checks = {}
    for name in bindings[0].plan.requests:
        frames = []
        for b in bindings:
            outcome = research.data.fetch(b.plan.requests[name], prepared=b.prepared)
            assert outcome.ready, outcome.error
            frames.append(outcome.dataframe)
        pd.testing.assert_frame_equal(*frames, check_exact=True, check_dtype=True)
        encoded = frames[0].to_json(orient='table', date_format='iso', double_precision=15).encode('utf-8')
        frame = frames[0]
        checks[name] = {'rows': len(frame), 'columns': list(frame),
                       'serialized_dataframe_sha256': sha256(encoded).hexdigest(),
                       'types': {c: str(v) for c, v in frame.dtypes.items()},
                       'exactly_equal': True}
        if name == 'daily':
            dates = pd.to_datetime(frame.Date)
            checks[name].update({'first_date': dates.min().date().isoformat(),
                                 'last_date': dates.max().date().isoformat(),
                                 'pre_2020_rows': int(dates.lt('2020-01-01').sum())})
            assert checks[name]['pre_2020_rows'] >= 180
    value = {'status': 'PASS', 'candidates': ['C0439', 'C0440'],
             'prepared_references': [b.to_dict()['prepared'] for b in bindings],
             'non_strategy_plan_sha256': canonical_sha256(plans[0]),
             'execution_input_identities': inputs[0], 'public_fetch_exact_checks': checks,
             'claim': '公开fetch按两次不可变准备引用验真；包含180条2019预热的所有命名输入逐值、类型与索引精确一致；整体准备身份随策略不同而独立。仅支持开发池内完整退出政策对照。'}
    save('adaptive_input_control_20261008.json', value)
    ref = publish_evidence(research, MaterialEvidenceWrite(ExperimentRef('S013', 'EX004_20261007'),
        'four-gate-adaptive-input-control', (RUNS / 'adaptive_input_control_20261008.json').read_bytes(),
        'application/json', 'json'))
    save('adaptive_input_control_reference_20261008.json', ref.to_dict())
    print(json.dumps({'status': 'PASS', 'checks': checks, 'reference': ref.to_dict()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
