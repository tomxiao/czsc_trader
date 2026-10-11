"""Freeze the complete single-coordinate one-step method before native-byte reads."""
import subprocess
from common import ROOT, SRC, PROTOCOLS, EXPERIMENT, context, read, write, file_hash
from native_reference import verified_json
from coordinate import COORDINATES, COORDINATE_NAMES
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.evidence import EvidenceRef


def main():
    assert not (PROTOCOLS / 'plan_reference.json').exists()
    assert read(SRC.parent / 'experiment.json') == EXPERIMENT.to_dict()
    subprocess.run([str(ROOT / '.venv/Scripts/ruff.exe'), 'check', str(SRC)], check=True, cwd=ROOT)
    pure = read(ROOT / '.tmp/ex047-coordinate-prototype/focused.json')
    assert pure['status'] == 'PURE_PASS' and pure['new_account_evaluations'] == 0
    for name in ('coordinate.py', 'focused_checks.py', 'transition.py'):
        assert (SRC / name).read_bytes() == (ROOT / '.tmp/ex047-coordinate-prototype' / name).read_bytes()
        assert file_hash(SRC / name) == pure['source_files'][name]
    for name in ('native_reference.py', 'transition.py'):
        assert (SRC / name).read_bytes() == (ROOT / 'research/S013/experiments/EX044_20261011/src' / name).read_bytes()
    geometry = read(ROOT / 'research/S013/experiments/EX046_20261011/protocols/geometry.json')
    assert tuple(tuple(row) for row in geometry['coordinates']) == COORDINATES
    assert tuple(row[0] for row in geometry['coordinates']) == COORDINATE_NAMES
    centers = read(ROOT / 'research/S013/assets/runs/EX043_20261011/account_references.json')
    matrix = read(ROOT / 'research/S013/assets/runs/EX043_20261011/parameter_matrix_v3.json')
    assert matrix['status'] == 'COMPLETE'
    rows = sorted((row for row in matrix['rows'] if row['center'] == 'B0-TIME'), key=lambda row: row['point_index'])
    assert [row['point_index'] for row in rows] == list(range(32))
    accounts = {'center': centers['B0-TIME'], **{f"P{row['point_index']:02d}": row['reference'] for row in rows}}
    assert len(accounts) == 33
    for value in accounts.values():
        ref = EvidenceRef.from_dict(value)
        assert ref.experiment.strategy_id == 'S013' and file_hash(ref.resolve(ROOT)) == ref.sha256
    external_names = ['research/S013/experiments/EX036_20261011/src/confirmation_diagnosis_v2.py',
        'research/S013/experiments/EX033_20261011/src/diagnose.py',
        'research/S013/experiments/EX043_20261011/src/direction_oracle.py',
        'research/S013/experiments/EX043_20261011/protocols/parameter_plans.json',
        'research/S013/assets/runs/EX043_20261011/parameter_matrix_v3.json',
        'research/S013/assets/runs/EX043_20261011/account_references.json']
    external_names += ['research/S013/experiments/EX035_20261011/src/' + name for name in
                       ('common.py', 'account_reference.py', 'analysis_reference.py', 'ledger_reference.py')]
    contrast = ROOT / '.tmp/ex046-native-contrast'
    snapshot = {p.name: {'sha256': file_hash(p), 'bytes': p.stat().st_size, 'source': p.read_text(encoding='utf-8')}
                for p in sorted(contrast.iterdir()) if p.suffix in ('.py', '.json') and p.name != 'native_contrast.json'}
    assert len(snapshot) == 5 and file_hash(contrast / 'native_contrast.json') == '98929006cde8d198611e05dccc04796d59b55fe71c39dd4540db4cb285d33353'
    supplement = read(contrast / 'native_contrast.json')
    assert supplement['status'] == 'PASS' and supplement['new_account_evaluations'] == 0
    assert supplement['source_sha256'] == file_hash(contrast / 'diagnose_v3.py')
    ctx = context(1)
    supplemental_refs = {}
    for name, body in (('native-contrast', (contrast / 'native_contrast.json').read_bytes()),
                       ('contrast-source-history', None)):
        if body is None:
            write(PROTOCOLS / 'contrast_source_history.json', {'files': snapshot,
                'success_sha256': file_hash(contrast / 'native_contrast.json'),
                'scope': 'EX046 old/new2 actual native centers; independent cash/whole-lot/date/cycle contrast. Two retained diagnostic assumption failures corrected; no new accounts or modification of FULL42.'})
            body = (PROTOCOLS / 'contrast_source_history.json').read_bytes()
        supplemental_refs[name] = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, name, body, 'application/json', 'json')).to_dict()
    write(PROTOCOLS / 'contrast_references.json', supplemental_refs)
    old = read(ROOT / 'research/S013/experiments/EX046_20261011/protocols/plan.json')
    plan = {'name': 'S013-EX047-original13-single-coordinate-observed-state-probe',
        'input_accounts': accounts, 'source_files': {p.name: file_hash(p) for p in SRC.glob('*.py')},
        'external_source_files': {name: file_hash(ROOT / name) for name in external_names},
        'pure_checks': pure, 'coordinates': geometry['coordinates'], 'original_protocol': geometry['protocol'],
        'method': 'Authenticate original center+full32 native serialized/public identity, point plan/lineage/coordinates, full independent funds/benchmark/features/calendar/signal state. Every native T date and every13coordinate: forward replaces only center numerical coordinate by its existing point value; reverse restores only point numerical coordinate to center. Each is evaluated separately on observed center and point predecision state. Original rangeW replaces only corresponding position; entry/exit/H/ACF/score threshold replaces its rule/value; original L replaces full independently authenticated score; regimeW and threshold separately recomputed from bound HFQ Close_t/Close_t-W minus1 and original return units. Equality remains bull. No modified state is propagated.',
        'recording': 'Retain all32*1636 dates, both observed states, four full-feature A/B/C/D outcomes and all13 forward/reverse decisions/complete next-original-state. Typed RouteRule rejects invalid single-axis mappings; any failure prevents PASS, not outcome-based omission. Counts by complete signal and execution year, None dates retained; cancellation/overlap/nonadditivity explicit. Probe is not a new parameter account or alternative investment policy.',
        'supplemental_evidence': supplemental_refs,
        'economic_targets': 'Original four gates plus qualifying original-numeric-center/all13 full domains/same32joint5% coordinates, absolute Q10CAGR/Q90DD and both relative degradations improvement. No new diagnostic veto or goal relaxation.',
        'selection_history': 'After EX043/45 absolute tails worsened and EX046 category expiry center failed return. EX024 three-day raw regime majority equals proposed raw-momentum median3 for any finite inputs/threshold; reject duplicate before evaluation. EX017/30 delayed bull exits failed; bear-only rawbull exit confirmation not identical but currently only a possible mechanism, no new financial result.',
        'limits': 'Posthoc local logical intervention on endogenous observed signal states of dependent, repeatedly seen original S013 paths. Single-coordinate direct effects, reproduction/removal counts overlap and cannot be added, ranked as profit contributions, or interpreted as total policy/account causal effects. Unknown modified holdings/cash/lot sizes are not propagated. All13 simultaneous changes may interact/cancel. No independent validation/newdata/threshold grid/new financial evaluation.',
        'counts': {'unique_native_accounts_full_diagnosis': 33, 'supplemental_actual_centers': 2,
                   'unique_native_accounts_across_materials': 35, 'new_account_evaluations': 0, 'new_account_preparations': 0,
                   'complete_coordinate_pair_days': 32 * 13 * 1636, 'pure_step_evaluations': 32 * 13 * 1636 * 4},
        'mandate': old['mandate'], 'authorization': 'User autonomous completion无需评审; existing S013stage3only',
        'previous_delivery': read(ROOT / 'research/S013/experiments/EX046_20261011/protocols/delivery_reference.json'),
        'boundaries': 'RSCH; zero prepare/evaluate/download/newdata/otherbatch/platform/dependency/prod/PTE/freeze/merge/tag/push',
        'objective_achieved': False}
    write(PROTOCOLS / 'plan.json', plan)
    ref = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, 'prospective-single-coordinate-plan',
        (PROTOCOLS / 'plan.json').read_bytes(), 'application/json', 'json'))
    write(PROTOCOLS / 'plan_reference.json', ref.to_dict())
    assert verified_json(ref.to_dict()) == plan
    print({'declared': EXPERIMENT.experiment_id, 'original_native_accounts': 33, 'new': 0}, flush=True)


if __name__ == '__main__':
    main()
