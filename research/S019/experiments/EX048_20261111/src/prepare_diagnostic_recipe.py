"""Prepare, but do not open, a predeclared stage-three interaction diagnostic."""
import argparse
import itertools
import json
from hashlib import sha256
from pathlib import Path

ROOT = Path.cwd()

def read(path):
    return json.loads(path.read_bytes())

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--previous', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    work = args.previous.resolve()
    assert read(work/'others/execution.json')['status'] == 'COMPLETE'
    assert read(work/'others/publication.json')['validation']['status'] == 'PASS'
    config = read(work/'protocols/search.json')
    rows = read(work/'others/summary.json')
    old_work = ROOT/'research/S019/experiments/EX046_20261111'
    reusable = {json.dumps(r['parameters'],sort_keys=True):(label,r)
                for label,r in read(old_work/'others/results.json')['accounts'].items()}
    specs, anchors, observations, seen = [], [], [], {}
    selection, choices = [], []
    for family in config['families']:
        name = family['name']
        pool = [r for r in rows.values() if r['family'] == name and r['candidate']['eligible']]
        assert pool, 'Inspect family failure before selecting a different diagnostic'
        center = min(pool, key=lambda r:(-r['candidate']['nar'], r['id']))
        choices.append((family,center,'winner'))
        control = next(r for r in rows.values() if r['family'] == name and r['trial_number'] == 0)
        if control['content_hash'] != center['content_hash']:
            choices.append((family,control,'control'))
    for family,center,role in choices:
        name = family['name']+'_'+role
        p = center['parameters']
        axes = list(family['space'])
        changes = [('center', {})]
        changes += [(f'{key}_{side}', {key:factor}) for key in axes for side,factor in [('lo',.95),('hi',1.05)]]
        if 'exit_width' in axes:
            changes += [(f'exit_pair_{i}',dict(zip(['trail_atr','exit_width'],factors,strict=True)))
                        for i,factors in enumerate(itertools.product((.95,1.05),repeat=2))]
        changes += [(f'participation_joint_{i}',dict(zip(['quiet_fraction','participation_threshold','participation_width'],factors,strict=True)))
                    for i,factors in enumerate(itertools.product((.95,1.05),repeat=3))]
        changes += [(f'all_{side}',dict.fromkeys(axes,factor)) for side,factor in [('lo',.95),('hi',1.05)]]
        members = []
        for suffix,factors in changes:
            parameters = {**p,**{key:p[key]*factor for key,factor in factors.items()}}
            assert 0 < parameters['quiet_fraction'] <= 1 and 0 < parameters['weak_fraction'] <= 1
            assert 0 < parameters['participation_width'] < 1
            assert parameters['trail_atr']-parameters['exit_width']/2 > 0
            signature = json.dumps(parameters,sort_keys=True)
            label = f'{name}_{suffix}'
            if signature in seen:
                label = seen[signature]
            else:
                seen[signature] = label
                spec = {'label':label,'parameters':parameters}
                if not factors:
                    spec['control_account'] = (work/f"others/trials/{center['name']}_account.json").relative_to(ROOT).as_posix()
                elif signature in reusable:
                    old_label, old_row = reusable[signature]
                    assert old_row['definition'] == {**center['definition'],
                        'parameters_json':json.dumps(parameters,sort_keys=True,separators=(',',':'))}
                    spec['reuse_account'] = (old_work/f'others/{old_label}_account.json').relative_to(ROOT).as_posix()
                specs.append(spec)
            members.append(label)
            observations.append({'anchor':name,'label':label,'factors':factors,'kind':suffix})
        anchors.append({'name':name,'center_label':members[0],'members':list(dict.fromkeys(members))})
        selection.append({'family':family['name'],'anchor':name,'role':role,'id':center['id'],'content_hash':center['content_hash'],
            'account':center['account'],'parameters':p,'candidate':center['candidate']})
    value = {'source_experiment':work.relative_to(ROOT).as_posix(),
        'source_summary_sha256':sha256((work/'others/summary.json').read_bytes()).hexdigest(),
        'selection_rule':'Per family: all original six center gates, then maximum unrounded NAR, candidate ID exact tie break; also the original family control when its content differs. Use the same diagnostic design for both.',
        'selected':selection,'specs':specs,'diagnostic_design':{'anchors':anchors},'observations':observations,
        'scope':'Development diagnosis: axis +/-5%, exit-pair corners, participation-triple corners, all-axes +/-5%. Cross-group opposite-direction combinations are not exhaustively covered; full stage-four neighborhood remains separate. Exact EX046 points reuse old evidence; selected centers are replayed as controls.',
        'design_source_sha256':sha256(Path(__file__).read_bytes()).hexdigest()}
    assert not args.output.exists()
    args.output.write_bytes((json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode())
    print('DIAGNOSTIC_RECIPE_READY',len(specs),[x['id'] for x in selection])

if __name__ == '__main__':
    main()
