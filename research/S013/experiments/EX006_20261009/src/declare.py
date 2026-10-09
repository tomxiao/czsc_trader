"""Prospective S007-style opportunity/confirmation separation on S013 data."""
from copy import deepcopy
from hashlib import sha256

from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from common import ROOT, SRC, EXPERIMENT, PROTOCOLS, context, parent_parameters, read, write, config_hash


def main():
    if (PROTOCOLS / 'initial_plan.json').exists():
        raise RuntimeError('prospective plan already exists')
    migration = read(ROOT / 'research/S013/materials/contract_migration_20261009.json')
    centers = [row['successor'] for row in migration['candidate_migration'] if row['stage4_center']]
    source = ROOT / 'strategies/S007/releases/v1/runtime/strategy_runtime/strategies/s007_v1.py'
    manifest = read(ROOT / 'strategies/S007/releases/v1/release_manifest.json')
    assert sha256(source.read_bytes()).hexdigest() == manifest['files']['runtime/strategy_runtime/strategies/s007_v1.py']
    authorization = {'date': '2026-10-09', 'source': '本主会话真实用户指令',
        'user_messages': ['增加固定冷却日的方式不可取，可以考虑能否增加一个确认分作为买入控制',
                          '可以参考一下S007-v1的策略表达'],
        'phase': 'S013 stage three continues', 'branch': 'codex/s013-research-continuation',
        'data': 'S013 existing 510500.SH developer pool, 2020-01-02..2026-09-30 and required existing warmup',
        'reference_permission': 'S007-v1 strategy definition and executable expression only; no S007 research results or seed data',
        's007_reference': {'source_path': source.relative_to(ROOT).as_posix(), 'source_sha256': sha256(source.read_bytes()).hexdigest(),
                           'release_hash': manifest['strategy_version_hash']},
        'excluded': ['fixed cooldown', 'other batch data/results', 'new providers or dependencies', 'platform changes',
                     'stage four/five', 'freeze', 'production', 'merge/tag/push']}
    write(PROTOCOLS / 'authorization.json', authorization)
    configs, seen = [], set()

    def add(parent, profile='all', threshold=-.5, enabled=True, orientation=1,
            scope='both', lookback=120, remove_acf=False):
        p = deepcopy(parent_parameters(parent))
        assert p['bull']['cooldown'] == p['bear']['cooldown'] == 0
        if remove_acf:
            p['bear']['acf_min'] = None
        p['confirmation'] = {'enabled': enabled, 'profile': profile, 'threshold': float(threshold),
                             'orientation': orientation, 'scope': scope, 'lookback': lookback}
        digest = config_hash(p)
        if digest in seen:
            return
        seen.add(digest)
        configs.append({'parent': parent, 'label': f'{parent}-{profile}-{threshold}-{orientation}-{scope}-n{lookback}'
                       + ('-disabled' if not enabled else '') + ('-oldacf-off' if remove_acf else ''), 'parameters': p})

    for center in centers:
        add(center, enabled=False)
    for center in centers:
        for threshold in (-.2, -.1, 0., .1):
            add(center, threshold=threshold)
    profiles = ('acf', 'turnover', 'volume', 'acf_turnover', 'acf_volume', 'turnover_volume')
    for center in ('C9018', 'C9023'):
        for profile in profiles:
            for threshold in (-.2, 0., .1):
                add(center, profile, threshold)
        for threshold in (-.1, 0., .1):
            add(center, threshold=threshold, orientation=-1)
    add('C9023', enabled=False, remove_acf=True)
    add('C9023', 'acf', 0., remove_acf=True)
    for scope in ('bull', 'bear'):
        for threshold in (-.1, 0.):
            add('C9023', threshold=threshold, scope=scope)
    for threshold in (-.1, 0.):
        add('C9023', threshold=threshold, lookback=60)
    plan = {'name': 'confirmation_initial', 'hypothesis': 'entry confirmation selects information quality rather than elapsed time',
        'borrowed_expression': 'separate existing opportunity/exit logic from a buy-only causal rolling-percentile score',
        'reference_snapshot': {'source': source.read_text(encoding='utf-8'),
                               'definition': read(ROOT / 'strategies/S007/versions/v1.json')},
        'features': {'acf': 'existing 20-return lag1 ACF; positive orientation, state confirmation',
                     'turnover': 'Amount / trailing20 mean Amount; positive participation orientation',
                     'volume': 'mean of last20 log Volume changes; positive growth orientation, same expression as S007-v1'},
        'normalization': 'complete trailing120 observations, current midrank centered[-.5,.5]; one trailing60 contrast',
        'weights': 'equal and fixed within each declared subset; no outcome-fit weights',
        'scope': 'original opportunity AND confirmation>=threshold while flat; original holding/exit state; zero cooldown',
        'initial_evidence': 'ACF exploratory support; amount/volume confirmation not established; stage-two combination negatives retained',
        'competing_explanations': ['redundant bear ACF restriction', 'lower turnover alone', 'volume/amount duplication',
                                  'missed profitable entries or delayed protective state routes', 'same-data adaptive selection'],
        'controls': ['ten exact disabled-model accounts', 'single and paired feature ablations',
                     'same-date reversed score', 'old bear ACF on/off x confirmation ACF on/off', 'route-specific gates',
                     'causal prefix/future invariance and immediate next-session reconsideration'],
        'hard_gates': ['CAGR>=1.5*same BuyHold', 'each calendar-year drawdown strictly smaller',
                       'closed*60/1636>=4', 'strict positive actual return in negative BuyHold years'],
        'diagnostics_only': ['annual profit margin', '20/30bp pressure', 'conditional opportunities/score and price/fee attribution'],
        'boundary': 'threshold[-.2,.1] provisional; expand or refine useful boundary improvements; no fixed trial-count adequacy claim',
        'known_information': 'full developer pool reused and all S013 past results seen; no holdout; S007 expression only read',
        'resources': {'max_workers': 4, 'native_threads': 1, 'request_workers': 1, 'seed': 13},
        'method': 'Optuna fixed queue dedup, public TDR FULL accounts', 'configurations': configs,
        'source_files': {p.relative_to(SRC).as_posix(): sha256(p.read_bytes()).hexdigest()
                         for p in (SRC / 'strategy_runtime').rglob('*.py')}}
    write(PROTOCOLS / 'initial_plan.json', plan)
    refs = {}
    for filename in ('authorization.json', 'initial_plan.json'):
        refs[filename] = publish_evidence(context(1), MaterialEvidenceWrite(EXPERIMENT,
            'buy-confirmation-' + filename.removesuffix('.json').replace('_', '-'),
            (PROTOCOLS / filename).read_bytes(), 'application/json', 'json')).to_dict()
    write(PROTOCOLS / 'initial_references.json', refs)
    print({'published': True, 'configurations': len(configs), 'centers': centers}, flush=True)


if __name__ == '__main__':
    main()
