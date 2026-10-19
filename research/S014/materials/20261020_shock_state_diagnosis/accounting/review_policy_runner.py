"""Final EX050 fixed runner/design/old-provider delta review; no real execution."""
import ast
from hashlib import sha256
import json
from pathlib import Path

ROOT = Path.cwd()
OUT = Path(__file__).resolve().parent
EX = ROOT / 'research/S014/experiments/EX050_20261020'
CHECKS = []


def check(name, value):
    assert value, name
    CHECKS.append(name)


def ref(path):
    return {'path': path.relative_to(ROOT).as_posix(), 'sha256': sha256(path.read_bytes()).hexdigest()}


def main():
    expected = {'src/run_accounts.py': '3eea3fcd79b0bb80f4360de64b666b1745da52179a28a034d37d68e566180bcb',
                'src/audit_accounts.py': '07a23131db5a81e726b3b53ac8e44bf4e9e6cfea190541a8e5534e84f72e4b78',
                'src/offline_inputs.py': '731e8fd0cb14859789f54083298b9140e12d1e50be5d71bb1093ab7f5313b380',
                'protocols/design.json': '1845fea88102c01b84890b8571842731ad2b1722977e03bd7a2be113d76532b3'}
    for path, digest in expected.items():
        check('final frozen bytes ' + path, ref(EX / path)['sha256'] == digest)
        if path.endswith('.py'):
            ast.parse((EX / path).read_text(encoding='utf-8'))
    design = json.loads((EX / 'protocols/design.json').read_bytes())
    for value in design.values():
        if isinstance(value, dict) and {'path', 'sha256'} <= value.keys():
            check('exact upstream ' + value['path'], ref(ROOT / value['path'])['sha256'] == value['sha256'])
    profiles = ['ORIGINAL_C9461_CONTROL', 'FIRST_SHOCK_NON_FINAL_DAY_DOMINATED_HOLD', 'FIRST_SHOCK_AFTER_ENTRY_DAY_HOLD']
    check('exact three arms only', design['fixed_parameters'] == [{'policy_profile': v} for v in profiles] and design['candidate_ids'] == ['S014-C9500', 'S014-C9501', 'S014-C9502'])
    check('correct actual C9461 control', design['baseline_account_ref']['sha256'] == '935b74f311a04b11e494d7adea80c7c9d1badb7776706e0761a77679dc8751e0' and design['baseline_result_hash'] == 'a3c398bd3f3259bbf8e46a6339a36a8bd83b2ccd924526240b0ca604b0f21bcb')
    check('all seven original gates unchanged', design['original_annual_acceptance_years'] == list(range(2020, 2027)))
    toy = json.loads((EX / 'others/synthetic_precheck.json').read_bytes())
    prefix = json.loads((EX / 'others/audit_prefix_precheck.json').read_bytes())
    source_sha = 'ac4fcdbdc5c46b1d43f31f53dda2de0635fea8f4f0cff8889a083a86f87e76f3'
    check('62synthetic666SRT exact current source', toy['checks_count'] == 62 and toy['actual_SRT_observation_materializations'] == 666 and toy['source_sha256'] == source_sha)
    check('current synthetic implementation', toy['precheck_source_sha256'] == ref(EX / 'src/precheck.py')['sha256'])
    check('seven prefix current internal identity', prefix['checks_count'] == 7 and prefix['audit_source_sha256'] == expected['src/audit_accounts.py'] and prefix['precheck_source_sha256'] == ref(EX / 'src/prefix_precheck.py')['sha256'])
    old_provider = ROOT / 'research/S014/experiments/EX017_20261017/src/pinned_inputs.py'
    normalized = old_provider.read_text(encoding='utf-8').replace('EX = Path(__file__).resolve().parents[1]', 'EX = ROOT / "research/S014/experiments/EX017_20261017"\nREVISION_SOURCE = EX / "src/pinned_inputs.py"')
    normalized = normalized.replace('sha256(Path(__file__).read_bytes())', 'sha256(REVISION_SOURCE.read_bytes())')
    normalized = normalized.replace("create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S014'))", "create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S014'), providers=ProviderConfig(bindings={}))")
    check('offline helper exactly original plus declared sourceanchor and emptycatalog context', ast.dump(ast.parse(normalized), include_attributes=False) == ast.dump(ast.parse((EX / 'src/offline_inputs.py').read_text(encoding='utf-8')), include_attributes=False))
    runner = (EX / 'src/run_accounts.py').read_text(encoding='utf-8')
    check('real control and source gates bind current immutable identities', all(s in runner for s in ['gate_source_review.json', 'gate_control_independent.json', 'source_lock_sha256', 'account_ref', 'No blind retry after dispatch']))
    check('empty publication and no network', 'providers=ProviderConfig(bindings={})' in runner and 'socket.socket.connect = no_network' in runner and 'requests.sessions.Session.request = no_network' in runner)
    check('actual source independently reviewed', json.loads((OUT / 'policy_source_review.json').read_bytes())['source_sha256'] == source_sha)
    report = {'status': 'PASS', 'reviewer': 'A', 'source_sha256': source_sha, 'reviewed_files': [ref(EX / p) for p in expected],
              'check_count': len(CHECKS), 'checks': CHECKS, 'implementation': ref(Path(__file__).resolve()),
              'manual_review': ['Internal audit retains corrected validE/dailyE.signalD and D actual funded quantity, initial100000/0. Control checks every old field/economic projection exactly.',
                                'Internal S2 does not claim an independent formula recomputation; independent actual lifecycle oracle will recompute source-price scalar log terms.',
                                'Own actual completed strict-net-loss feedback, first assessment/latch memory, original-state/target/funded differences remain distinct.',
                                'Existing pending/cost/support/GRACE/deadline/reservation retained. No new economic rejection gate or fallback.',
                                'Provider helper delta only anchors old EX017 revision/path and explicit empty fetch context. Public local evidence writes have no supplier or external upload.',
                                'Source control must independently PASS actual C9461 exact before either treatment. No treatment selected on partial economics.'],
              'actual_accounts': 0, 'new_fits': 0, 'new_supplier_calls': 0}
    path = OUT / 'policy_runner_pre_review.json'
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'review': ref(path), 'checks': len(CHECKS)}))


if __name__ == '__main__':
    main()
