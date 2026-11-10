"""Archive prelaunch material only after public EX046 creation."""
import argparse
import json
from hashlib import sha256
from pathlib import Path

root = Path.cwd()
tmp = root/'.tmp/s019-stage2-resume'
parser = argparse.ArgumentParser()
parser.add_argument('--copy',action='store_true')
args = parser.parse_args()
work = root/'research/S019/experiments/EX046_20261111'
mapping = {
    'protocols/anchors.json':'ex046_anchor_selection.json',
    'protocols/reversible_design.json':'reversible_design.json',
    'others/reversible_checks.json':'reversible_checks.json',
    'others/reversible_id_probe.json':'reversible_id_probe.json',
    'others/recipe_probe.json':'ex046_recipe_probe.json',
    'src/check_reversible.py':'check_reversible.py',
    'src/probe_reversible_ids.py':'probe_reversible_ids.py',
    'src/probe_recipe.py':'probe_ex046_recipe.py',
    'src/prepare_recipe.py':'prepare_ex046_recipe.py',
    'src/archive_preparation.py':'archive_ex046_preparation.py',
}
records=[]
for dest,src in mapping.items():
    source=tmp/src
    assert source.is_file(),source
    records.append({'source':source.relative_to(root).as_posix(),'sha256':sha256(source.read_bytes()).hexdigest(),
        'formal_copy':dest})
recipe=json.loads((tmp/'ex046_recipe.json').read_bytes())
probe=json.loads((tmp/'ex046_recipe_probe.json').read_bytes())
checks=json.loads((tmp/'reversible_checks.json').read_bytes())
assert probe['status']==checks['status']=='PASS'
assert probe['recipe_sha256']==sha256((tmp/'ex046_recipe.json').read_bytes()).hexdigest()
assert probe['anchors_sha256']==sha256((tmp/'ex046_anchor_selection.json').read_bytes()).hexdigest()
assert probe['source_file_sha256']==checks['prepared_source_sha256']==sha256((root/recipe['source_paths']['strategy.py']).read_bytes()).hexdigest()
assert checks['verification_source_sha256']==sha256((tmp/'check_reversible.py').read_bytes()).hexdigest()
assert probe['runner_sha256']==sha256((root/recipe['source_paths']['batch_runner.py']).read_bytes()).hexdigest()
if args.copy:
    assert work.is_dir() and (work/'protocols/specs.json').is_file()
    assert not (work/'protocols/run_manifest.json').exists(), 'Archive must precede frozen run preflight'
    assert json.loads((work/'protocols/specs.json').read_bytes()) == recipe['specs']
    assert (work/'src/strategy.py').read_bytes()==(root/recipe['source_paths']['strategy.py']).read_bytes()
    for row in records:
        content=(root/row['source']).read_bytes()
        dest=work/row['formal_copy']
        if dest.exists():
            assert dest.read_bytes()==content,dest
        else:
            dest.write_bytes(content)
    value={'status':'PASS','scope':'Prelaunch source/material archive; no account replay',
        'recipe_sha256':sha256((tmp/'ex046_recipe.json').read_bytes()).hexdigest(),'materials':records}
    target=work/'protocols/preparation_materials.json'
    payload=(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()
    if target.exists():
        assert target.read_bytes()==payload
    else:
        target.write_bytes(payload)
print('PREPARATION_MATERIALS', 'COPIED' if args.copy else 'READY',len(records))
