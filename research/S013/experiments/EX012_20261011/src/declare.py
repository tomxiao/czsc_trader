"""Freeze twelve configurations and publish confirmed mandate before evaluation."""
from copy import deepcopy
from dataclasses import replace
import json
from czsc_trader.application import load_candidate, publish_evidence, assemble_delivery, validate_delivery
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools import delivery as d
from strategy_runtime import StrategyRuntime, StrategyCandidate, implementation_sha256
from strategy_manager import CandidateKey
from common import (ROOT, SOURCE, PROTOCOLS, RUNS, EXPERIMENT, DEPENDENCIES,
                    WORKERS, context, benchmark, read, write, file_hash)

def main():
    assert not (PROTOCOLS/'plan.json').exists(), 'Prospective declaration already exists'
    research = context()
    original = load_candidate(research.repository, CandidateKey('S013', 'C2132'))
    for filename in original.payload['runtime']['source_files']:
        target = SOURCE/filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((original.source_root/filename).read_bytes())
    old_source = (SOURCE/'strategies/reentry_confirmed_range.py').read_text(encoding='utf-8')
    # Keep the original trade state machine and exit priority byte-for-byte.
    start = old_source.index('    def __init__')
    end = old_source.index('    @property', start)
    constructor = '''    def __init__(self, parameters):
        p = parameters.values
        c = p['confirmation']
        if not isinstance(c, Mapping) or set(c) != {'profile', 'orientation', 'scope', 'lookback', 'direction'}:
            raise ValueError('exact score-change confirmation contract required')
        if type(c['direction']) is not int or c['direction'] not in (-1, 1):
            raise ValueError('direction must be integer +1 or -1')
        if p['context']['entry_gate'] != 'all':
            raise ValueError('change confirmation applies to all basic opportunities')
        parent = {key: value for key, value in p.items()}
        parent['confirmation'] = {key: value for key, value in c.items() if key != 'direction'}
        parent['confirmation'].update(enabled=True, threshold=0.0)
        super().__init__(ParameterSet(parent))
        self._parameters = parameters

'''
    new_source = old_source[:start]+constructor+old_source[end:]
    new_source = new_source.replace('from strategy_runtime import InputContract, ParameterSet',
        'from strategy_runtime import InputContract, ParameterSet\nfrom .reentry_confirmed_range import ReentryConfirmedRange')
    new_source = new_source.replace('class ReentryConfirmedRange(ConfirmedRange):',
                                    'class ScoreChangeRange(ReentryConfirmedRange):')
    new_source = new_source.replace("        if not c['enabled']:\n            return super().calculate_history(inputs, sessions)\n", '')
    new_source = new_source.replace('        _, normalized = confirmation_features(',
                                    '        raw, normalized = confirmation_features(')
    new_source = new_source.replace('        normalized = normalized.reindex(sessions)\n', '')
    new_source = new_source.replace("        if not np.isfinite(normalized.to_numpy()).all():\n            raise ValueError('complete causal confirmation history missing')\n", '')
    needle = "                 normalized.loc[:, list(PROFILES[c['profile']])].mean(axis=1)) * c['orientation']\n"
    assert new_source.count(needle) == 1
    new_source = new_source.replace(needle, needle+'''        score_delta = score.diff().reindex(sessions)
        score = score.reindex(sessions)
        raw = raw.reindex(sessions)
        normalized = normalized.reindex(sessions)
        if not np.isfinite(score_delta.to_numpy()).all() or not np.isfinite(normalized.to_numpy()).all():
            raise ValueError('complete causal current and prior score history missing')
''')
    old_pass = "            passed = not applies or score.iloc[i] >= c['threshold']"
    assert new_source.count(old_pass) == 1
    new_source = new_source.replace(old_pass,
        "            passed = not applies or c['direction'] * score_delta.iloc[i] >= 0.0")
    new_source = new_source.replace('            confirmation_score=score, confirmation_acf=normalized.acf,',
        '            confirmation_score=score, confirmation_delta=score_delta,\n'
        '            raw_confirmation_acf=raw.acf, raw_confirmation_turnover=raw.turnover,\n'
        '            raw_confirmation_volume=raw.volume, confirmation_acf=normalized.acf,')
    new_source = new_source.replace('"""Information gate for state-exit reentry; explicit raw-volume paired checks."""',
                                  '"""Approved causal score-change gate; original trade exits retained."""')
    (SOURCE/'strategies/score_change_range.py').write_text(new_source, encoding='utf-8', newline='\n')
    known = {read(path)['record']['content_sha256']: path.stem
        for path in (ROOT/'research/registrations/S013/candidates').glob('*.json')}
    configs = []
    for background in range(3):
        for mode in range(4):
            payload = deepcopy(json.loads(json.dumps(dict(original.payload), default=dict)))
            p = payload['parameters']
            if background == 1:
                p['bear']['acf_min'] = .045
            elif background == 2:
                p['bear']['max_hold'] = 3
            if mode == 0:
                p['confirmation']['enabled'] = False
            if mode >= 2:
                p['confirmation'].pop('enabled')
                p['confirmation'].pop('threshold')
                p['confirmation']['direction'] = 1 if mode == 2 else -1
                runtime = payload['runtime']
                runtime['module'] = 'strategy_runtime.strategies.score_change_range'
                runtime['qualname'] = 'ScoreChangeRange'
                runtime['source_files'].append('strategies/score_change_range.py')
                runtime['source_sha256'] = implementation_sha256(runtime['source_files'], source_root=SOURCE)
            identifier = f'C{7000+len(configs):04d}'
            strategy = StrategyCandidate('S013', identifier, payload, SOURCE)
            identity = StrategyRuntime().identify(strategy, dependencies=DEPENDENCIES)
            existing = known.get(identity.content_sha256)
            if existing:
                loaded = load_candidate(research.repository, CandidateKey('S013', existing))
                assert json.loads(json.dumps(dict(loaded.payload), default=dict)) == payload
                identifier = existing
            else:
                assert not (ROOT/f'research/registrations/S013/candidates/{identifier}.json').exists()
            configs.append({'index':len(configs), 'background':f'B{background}', 'mode':f'M{mode}',
                'candidate_id':identifier, 'existing_identity':existing,
                'content_sha256':identity.content_sha256, 'payload':payload})
    assert len(configs) == len({c['content_sha256'] for c in configs}) == 12
    auth = {'date':'2026-10-11', 'source':'direct human approval in current conversation',
        'exact_user_message':'批准，请你自主完成该目标，然后给出通俗易懂的结论',
        'approved_proposal':'Three backgrounds B0 original, B1 bear.acf_min=.045, B2 bear.max_hold=3; four gates M0 off, M1 S>=-.2, M2 delta S>=0, M3 delta S<=0; maximum twelve fixed configurations.',
        'scope':'S013 stage-three mechanism experiment, existing native assets, uniform 1% buy premium and fixed LimitBuyHold benchmark; four economic gates unchanged.',
        'boundaries':'no new data source/dependency, other-family reads, fixed cooldown, historical batch replay, stage four/five, freeze, PTE, production, merge/tag/push'}
    write(PROTOCOLS/'authorization.json', auth)
    refs = {}
    for name, path in (('authorization',PROTOCOLS/'authorization.json'),
                       ('future-contract',ROOT/'research/S013/materials/future_execution_contract_20261010.json')):
        refs[name] = publish_evidence(research, MaterialEvidenceWrite(EXPERIMENT,
            'mechanism-'+name, path.read_bytes(), 'application/json', 'json'))
    predecessor = d.DeliveryReference.from_dict(read(ROOT/'research/S013/deliveries/MANDATE/5/receipt.json')['reference'])
    prior_path = ROOT/'research/S013/assets/deliveries/MANDATE/5/delivery.json'
    refs['prior-mandate'] = publish_evidence(research, MaterialEvidenceWrite(EXPERIMENT,
        'mechanism-prior-mandate-exact-bytes', prior_path.read_bytes(), 'application/json', 'json'))
    old_value = read(prior_path)['content']
    # The prior schema-6 publication remains immutable. Construct the new typed
    # mandate from its items; explicitly supply the new benchmark contract.
    for item in old_value['payload']['items']:
        if item['kind'] == 'BENCHMARK':
            item['requirement'] = d.BenchmarkRequirement(benchmark()).to_dict()
    old = d.DeliveryContent.from_dict(old_value)
    confirmed = d.ConfirmationRecord(d.ConfirmationStatus.CONFIRMED, refs['future-contract'])
    items = tuple(replace(item, statement='策略与可执行买入持有基准统一1%买入溢价；T日已知参考价形成限价，T+1执行；相同单位、价格网格、费用、资金及市场约束。基准固定，不随配置变化。',
        confirmation=confirmed, requirement=d.BenchmarkRequirement(benchmark()))
        if item.kind is d.MandateItemKind.BENCHMARK else item for item in old.payload.items)
    items += (d.MandateItem('future_strategy_buy_premium', d.MandateItemKind.EXECUTION,
        '后续新实验所有策略买入溢价固定为1%；既有账户、交付、资格及排序保持原合同解释。',
        confirmed, d.NumericRequirement('strategy_buy_premium','fraction',.01,.01)),)
    report = ('# S013研究约定修订六：后续统一1%执行合同\n\n'
        '用户确认“采用统一1%合同”，随后指示“不用复验了，后续实验照此执行即可”，并批准12配置机制对照。\n\n'
        '仅修改后续实验基准为LimitBuyHold(100,0.01,0.001,0.1,1000000)，策略买入溢价固定1%。'
        '510500.SH、原开发池、100万元、HFQ研究单位、单侧10bp、T决策T+1执行及四项经济目标沿用MANDATE/5。'
        '负基准年度按新基准实际连续账户收益确定；不写死年份。\n\n'
        '历史MANDATE/5、CANDIDATES/6、ASSESSMENT/2及账户不改写，不开展历史配置批量复验。'
        '本次新标准对照用于机制比较；未批准阶段四、选型、冻结或PTE。\n\n'
        '旧MANDATE/5是schema 6，当前交付API要求schema 7，不能作为机器前驱直接解析。'
        '本修订使用当前强类型重新声明相同目标及获批新执行合同；旧交付精确字节作为关联材料保存，'
        '不补签或修改旧schema，不声称已重新语义校验旧交付。原引用：'+json.dumps(predecessor.to_dict(),ensure_ascii=False)+'\n')
    mandate = assemble_delivery(research.repository,
        d.DeliveryDefinition(research.batch,d.DeliveryStage.MANDATE,6,()),
        replace(old,payload=d.ResearchMandate(items),report=report,evidence=old.evidence+tuple(refs.values())))
    validation = validate_delivery(research.repository,mandate.reference,scope=d.DeliveryValidationScope.FULL)
    assert validation.status is d.ValidationStatus.PASS, validation.to_dict()
    write(PROTOCOLS/'mandate_reference.json',mandate.reference.to_dict())
    write(RUNS/'mandate_validation.json',validation.to_dict())
    plan = {'name':'S013-EX012-mechanism-matrix','configurations':configs,
        'mandate':mandate.reference.to_dict(),'benchmark':benchmark().to_dict(),
        'hypothesis':'Score improvement may add information beyond score level and protect the two known weak directions; unproven before execution.',
        'direction_control':'M2/M3 replace absolute gate, not stack with it. Equality passes both and is separately counted. Current/prior trading-day score; no future data.',
        'interpretation':'Compare each gate to M0 and M1 within background, and background changes within gate. Full annual account attribution, decision/fill paths, raw component changes and rolling-reference effects; no new economic gate.',
        'source_files':{p.relative_to(SOURCE).as_posix():file_hash(p) for p in SOURCE.rglob('*.py')},
        'resources':{'max_workers':WORKERS,'native_threads':1,'request_workers':1,'seed':13},
        'data_scope':'Only S013 existing 510500.SH 2020-01-02..2026-09-30 assets and authorized warmup. No independent holdout; design selected after prior results.',
        'stop':'Complete the fixed twelve, reconcile and explain all outcomes, then report. No adaptive threshold/weight search or parameter joint self-check in this round.',
        'identity_policy':'Full content unchanged reuses registered identity; changed content new identity. M2/M3 have no unused absolute threshold parameter.'}
    write(PROTOCOLS/'plan.json',plan)
    refs['plan'] = publish_evidence(research,MaterialEvidenceWrite(EXPERIMENT,
        'mechanism-prospective-plan',(PROTOCOLS/'plan.json').read_bytes(),'application/json','json'))
    write(PROTOCOLS/'plan_references.json',{k:v.to_dict() for k,v in refs.items()})
    print({'experiment':EXPERIMENT.experiment_id,'mandate':mandate.reference.to_dict(),
           'configurations':12,'existing_identities':[(c['background'],c['mode'],c['candidate_id'])
                for c in configs if c['existing_identity']]},flush=True)

if __name__ == '__main__':
    main()
