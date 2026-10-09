"""Publish authorization and the initial mechanism counterfactuals before execution."""
from copy import deepcopy
from hashlib import sha256

from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from common import ROOT, SRC, EXPERIMENT, PROTOCOLS, context, parent_parameters, read, write


def main():
    if (PROTOCOLS / 'initial_plan.json').exists():
        raise RuntimeError('Initial declaration already exists; do not overwrite')
    authorization = {
        'date': '2026-10-09', 'source': '本主会话真实用户指令',
        'proposal': '回阶段三，研究年度盈利余量与成本敏感性，沿用原目标和数据范围',
        'user_message': '批准', 'branch': 'codex/s013-research-continuation',
        'allowed': ['S013 stage-three mechanisms, search, evaluation, evidence and candidate delivery'],
        'data': '510500.SH; original 2020-01-02..2026-09-30 developer pool; existing S013 assets only',
        'excluded': ['other research batches', 'new data sources or dependencies', 'platform changes',
                     'stage four or five', 'freeze', 'production', 'merge, tag or push'],
        'prior_assessment': read(ROOT / 'research/S013/materials/stage4_assessment_reference_20261008.json'),
    }
    write(PROTOCOLS / 'authorization.json', authorization)
    configurations = []

    def add(label, parent='C9023', band=0., confirm=1, exit_confirm=1,
            direction='both', cooldown=0):
        p = deepcopy(parent_parameters(parent))
        p.update(regime_band=float(band), regime_confirmation=confirm,
                 exit_confirmation=exit_confirm, exit_direction=direction,
                 regime_cooldown=cooldown)
        configurations.append({'label': label, 'parent': parent, 'parameters': p})

    add('disabled-mechanism-exact-control')
    for band in (.001, .002, .003, .005, .01, .02):
        add(f'band-{band}', band=band)
    for confirm in (2, 3, 4):
        add(f'state-confirm-{confirm}', confirm=confirm)
    for count in (2, 3, 4):
        add(f'exit-confirm-{count}', exit_confirm=count)
    for direction in ('bull_to_bear', 'bear_to_bull'):
        add(f'exit-direction-{direction}', direction=direction)
    for count in (1, 2, 3):
        add(f'regime-only-cooldown-{count}', cooldown=count)
    for band in (.002, .005, .01):
        for confirm in (2, 3):
            for count in (1, 2):
                add(f'joint-{band}-{confirm}-{count}', band=band, confirm=confirm,
                    exit_confirm=count)
    for band in (0., .002, .005):
        for count in (1, 2, 3):
            if band == 0. and count == 1:
                continue
            add(f'original-entry-control-{band}-{count}', parent='C9018',
                band=band, exit_confirm=count)
    plan = {
        'name': 'state_stability_initial', 'purpose': 'mechanism counterfactuals, not year-specific fitting',
        'hypotheses': [
            'A deadband suppresses threshold chatter while retaining larger trend transitions.',
            'Consecutive state or exit confirmation can reduce one-session false transitions.',
            'Less turnover may preserve annual net profit but may violate original minimum frequency.',
            'Bull-to-bear exits may serve risk control differently from bear-to-bull exits.',
            'A cooldown after regime exits may reduce immediate churn without restricting time exits.',
        ],
        'competing_explanations': ['signal timing instead of fee saving drives observed changes',
            'waiting loses the protective 2022 exits', 'fewer trades fail frequency or total return'],
        'hard_gates': ['CAGR>=1.5*same-window BuyHold', 'each calendar-year drawdown strictly smaller',
                       'closed trades*60/1636>=4', 'strict positive strategy return in negative BuyHold years'],
        'diagnostics_only': ['annual profit headroom', 'single-side 20/30bp full-account stress',
                             'parameter neighbors', 'fee/price attribution'],
        'selection': 'retain all qualified configurations and non-dominated annual-margin/return/frequency counterexamples',
        'boundary': 'band provisional 0..0.02; confirmation 1..4; expand when boundary improvements appear',
        'resources': {'max_workers': 4, 'native_threads_per_worker': 1, 'request_workers': 1, 'seed': 13},
        'method': 'Optuna fixed queue; main-process study; TDR spawn evaluate_many; FULL account only',
        'known_information': 'entire developer pool repeatedly reused, original stage-four results seen; no independent holdout',
        'initial_budget': len(configurations), 'configurations': configurations,
        'source_files': {str(p.relative_to(SRC)).replace('\\', '/'): sha256(p.read_bytes()).hexdigest()
                         for p in (SRC / 'strategy_runtime').rglob('*.py')},
    }
    write(PROTOCOLS / 'initial_plan.json', plan)
    research = context(1)
    refs = {}
    for filename in ('authorization.json', 'initial_plan.json'):
        refs[filename] = publish_evidence(research, MaterialEvidenceWrite(
            EXPERIMENT, 'stage3-continuation-' + filename.removesuffix('.json').replace('_', '-'),
            (PROTOCOLS / filename).read_bytes(), 'application/json', 'json')).to_dict()
    write(PROTOCOLS / 'initial_references.json', refs)
    print({'published': True, 'configurations': len(configurations)})


if __name__ == '__main__':
    main()
