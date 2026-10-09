"""Prospective existing-information complements following actual cost attribution."""
from copy import deepcopy
from hashlib import sha256
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from common import SOURCE, PROTOCOLS, RUNS, EXPERIMENT, context, parent_parameters, write, read, config_hash


def main():
    assert not (PROTOCOLS / 'initial_plan.json').exists()
    assert read(RUNS / 'trade_attribution.json')['status'] == 'PASS'
    configs, seen = [], set()

    def add(parent='C2308', *, profile='all', threshold=-.2, enabled=True,
            application='ordinary_entries', hold=None, raw_acf=None, raw=False):
        p = deepcopy(parent_parameters(parent))
        if raw:
            p['bull']['acf_min'] = raw_acf
        else:
            p['opportunity_confirmation'] = {'enabled': enabled, 'profile': profile,
                'threshold': float(threshold), 'weighting': 'EQUAL_BLOCKS' if profile == 'all' else 'EQUAL_FEATURES',
                'application': application, 'route_scope': 'bull'}
        if hold:
            p[hold[0]]['max_hold'] = hold[1]
        digest = config_hash(p)
        if digest in seen:
            return
        seen.add(digest)
        configs.append({'parent': parent, 'parameters': p,
            'label': f'{parent}-{profile}-{threshold}-{application}-' + ('disabled' if not enabled else 'enabled')
                     + (f'-hold-{hold}' if hold else '') + (f'-bull-raw-acf-{raw_acf}' if raw else '')})

    for parent in ('C2308', 'C2132'):
        add(parent, enabled=False)
    for parent in ('C2308', 'C2132'):
        for floor in (0., .05, .1):
            add(parent, raw=True, raw_acf=floor)
    for profile in ('all', 'acf_volume'):
        for threshold in (-.3, -.2):
            for application in ('all_entries', 'ordinary_entries'):
                add(profile=profile, threshold=threshold, application=application)
    for profile in ('acf', 'volume'):
        add(profile=profile)
    for hold in (('bull', 7), ('bear', 3)):
        for application in ('all_entries', 'ordinary_entries'):
            add(hold=hold, application=application)
    auth = {'date': '2026-10-09', 'user_message': '请继续',
        'authorized_next_action': 'continue stage-three cost sensitivity and complementary confirmation research',
        'branch': 'codex/s013-research-continuation',
        'data': 'S013 existing 510500.SH 2020-01-02..2026-09-30 developer pool plus existing warmup',
        'hard_gates': 'same four exact mandate gates at 10bp; 20/30bp report-only',
        'excluded': ['fixed cooldown', 'other batch results/data', 'external acquisition', 'new dependencies',
                     'platform edits', 'stage advancement', 'freeze', 'production', 'merge/tag/push']}
    write(PROTOCOLS / 'authorization.json', auth)
    plan = {'name': 'cost_confirmation_initial', 'prechecked_controls': ['C3000', 'C3001'],
        'configurations': configs,
        'attribution_sha256': sha256((RUNS / 'trade_attribution.json').read_bytes()).hexdigest(),
        'basis': '2023 C2308 bull/regime-exit trades are loss-making; C2132 total CAGR is stronger but weak-year price contribution insufficient; retain state-reentry amount gate and test bull price/volume confirmation separately.',
        'competing_explanations': ['frequency reduction alone', 'missed profitable entries',
                                  'shorter holding changes prices and fees', 'known-pool adaptive selection',
                                  'single large 2024 return concentration'],
        'source_files': {p.relative_to(SOURCE).as_posix(): sha256(p.read_bytes()).hexdigest()
                         for p in SOURCE.rglob('*.py')},
        'resources': {'max_workers': 4, 'native_threads': 1, 'request_workers': 1, 'seed': 13},
        'known_information': 'all prior S013 results and this developer pool reused; no holdout',
        'scope': 'only buys use extra confirmation; original exits unchanged except two explicitly declared max-hold parameter controls; no waiting-day gate',
        'diagnostics': 'annual price/fee attribution and representative full-account 20/30bp pressure; not new eligibility gates',
        'continuation': 'refine meaningful boundary improvements or test amplitude-based state hysteresis if entry filters cannot retain frequency; no fixed-count adequacy claim'}
    write(PROTOCOLS / 'initial_plan.json', plan)
    refs = {}
    for name, path in (('authorization', PROTOCOLS / 'authorization.json'),
                       ('initial-plan', PROTOCOLS / 'initial_plan.json'),
                       ('trade-attribution', RUNS / 'trade_attribution.json')):
        refs[name] = publish_evidence(context(1), MaterialEvidenceWrite(EXPERIMENT,
            'cost-confirmation-' + name, path.read_bytes(), 'application/json', 'json')).to_dict()
    write(PROTOCOLS / 'initial_references.json', refs)
    print({'published': True, 'configurations': len(configs)}, flush=True)


if __name__ == '__main__':
    main()
