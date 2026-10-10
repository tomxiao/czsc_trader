"""Freeze zero-new66 input/state diagnosis and fixed120 one-step probe."""
import ast
import subprocess
from common import ROOT, SRC, PROTOCOLS, EXPERIMENT, context, read, write, file_hash
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from native_reference import verified_json


def main():
    assert not (PROTOCOLS / 'method_reference.json').exists()
    subprocess.run([str(ROOT / '.venv/Scripts/ruff.exe'), 'check', str(SRC)], check=True, cwd=ROOT)
    focused = read(ROOT / '.tmp/ex044-diagnosis/focused.json')
    assert focused['status'] == 'PURE_PASS' and focused['new_account_evaluations'] == 0
    original = ROOT / 'research/S013/experiments/EX042_20261011/src/native_reference.py'
    assert (SRC / 'native_reference.py').read_bytes() == original.read_bytes()
    old = ast.parse((ROOT / 'research/S013/experiments/EX043_20261011/src/direction_oracle.py').read_text(encoding='utf-8'))
    source = next(node for node in ast.walk(old) if isinstance(node, ast.FunctionDef) and node.name == 'covariance')
    probe = ast.parse((SRC / 'probe.py').read_text(encoding='utf-8'))
    target = next(node for node in probe.body if isinstance(node, ast.FunctionDef) and node.name == 'covariance')
    assert ast.dump(source, include_attributes=False) == ast.dump(target, include_attributes=False)
    centers = read(ROOT / 'research/S013/assets/runs/EX043_20261011/account_references.json')
    matrix = read(ROOT / 'research/S013/assets/runs/EX043_20261011/parameter_matrix_v3.json')
    assert matrix['status'] == 'COMPLETE' and len(matrix['rows']) == 64
    refs = {label + '-center': centers[label] for label in ('B0-TIME', 'N0')}
    refs.update({row['label']: row['reference'] for row in matrix['rows']})
    assert len(refs) == 66
    # Before reading outcome bytes, authenticate the declared formal account digests.
    from czsc_trader.research_tools.evidence import EvidenceRef
    for value in refs.values():
        ref = EvidenceRef.from_dict(value)
        assert ref.experiment.strategy_id == 'S013' and file_hash(ref.resolve(ROOT)) == ref.sha256
    paths = [original, ROOT / 'research/S013/experiments/EX036_20261011/src/confirmation_diagnosis_v2.py',
        ROOT / 'research/S013/experiments/EX033_20261011/src/diagnose.py',
        ROOT / 'research/S013/experiments/EX043_20261011/src/direction_oracle.py',
        ROOT / 'research/S013/experiments/EX043_20261011/protocols/parameter_plans.json',
        ROOT / 'research/S013/assets/runs/EX043_20261011/parameter_matrix_v3.json',
        ROOT / 'research/S013/assets/runs/EX043_20261011/account_references.json']
    paths += [ROOT / 'research/S013/experiments/EX035_20261011/src' / name for name in
              ('common.py', 'account_reference.py', 'analysis_reference.py', 'ledger_reference.py')]
    external = {path.relative_to(ROOT).as_posix(): file_hash(path) for path in paths}
    previous = read(ROOT / 'research/S013/experiments/EX043_20261011/protocols/plan.json')
    plan = {'name': 'S013-EX044-complete-input-state-one-step-diagnosis',
        'input_accounts': refs, 'source_files': {p.name: file_hash(p) for p in SRC.glob('*.py')},
        'external_source_files': external, 'pure_checks': focused,
        'unique_native_accounts_reused': 66, 'new_account_evaluations': 0, 'new_business_configurations': 0,
        'method': 'Authenticate original33 and EX043N0 center+full32, each native identity, serialized account, lineage, point plan/coordinates, full independent cash ledger, equal benchmark, full features/state/calendar. Same-kind64 pairs: A=Fc(Sc),B=Fp(Sc),C=Fc(Sp),D=Fp(Sp) each of1636days; own A/D exactnative. Full target and target/reason6class partitions, all calendar signal/execution years, all contiguous segments, first divergences, physical/full state equality and retained memory, empty groups/tails. Cross-kind33 compare actual targets/reasons/physical state only. No B/C propagation.',
        'probe': 'Only new33, strictpast mean(raw20ACF,120) replaces centered bear ACF in each own observed before-state; actual confirmationL remains original active dimension and score unchanged. Fixed120 from center, outside13 structural choice; no grid/window selection. Probe full target/reason/nextstate acrossall dates andyears. No alternate account/economic outcome.',
        'economic_targets': 'Original four gates and13fullnumericdomains/32samecoordinates remain. No new veto or relaxation.',
        'selection_history': 'Known EX043 N0 qualifies center but Q10CAGR1.784274%,Q90DD34.616333% worse original5.897412%/30.504446%. Relative degradation improvement partly weakcenter. Stop new category gate expansion before fullstate diagnosis. EX042 actual BELOW category cash contains profitable recoveries; not modified policy profit.',
        'limits': 'Posthoc mechanism diagnosis on repeatedly seen, dependent S013 data. Combined13 perturbations, not single-coordinate causes. Multivalued input_only/state_only labels mean one swap suffices to reproduce D; other swap can still matter. No mixed-kind hypothetical state, future cash/PnL/account replay or independent-market validation.',
        'mandate': previous['mandate'], 'authorization': 'User explicitly autonomous completion无需评审; existing S013stage3only.',
        'previous_delivery': read(ROOT / 'research/S013/experiments/EX043_20261011/protocols/delivery_reference.json'),
        'boundaries': 'RSCH; no prepare/evaluate/download/adjacentbatch/platform/deps/production/PTE/freeze/merge/tag/push',
        'objective_achieved': False}
    ctx = context(1)
    write(SRC.parent / 'experiment.json', {'type': 'ExperimentRef', 'strategy_id': 'S013', 'experiment_id': EXPERIMENT.experiment_id})
    write(PROTOCOLS / 'method.json', plan)
    ref = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, 'prospective-input-state-method',
        (PROTOCOLS / 'method.json').read_bytes(), 'application/json', 'json'))
    write(PROTOCOLS / 'method_reference.json', ref.to_dict())
    verified_json(ref.to_dict())
    plan['method_reference'] = ref.to_dict()
    write(PROTOCOLS / 'plan.json', plan)
    ref = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, 'prospective-input-state-plan',
        (PROTOCOLS / 'plan.json').read_bytes(), 'application/json', 'json'))
    write(PROTOCOLS / 'plan_reference.json', ref.to_dict())
    print({'declared': EXPERIMENT.experiment_id, 'reused': 66, 'new': 0}, flush=True)


if __name__ == '__main__':
    main()
