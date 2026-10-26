"""Read-only proof: candidate declaration is valid, frozen before-side is unsupported."""
from pathlib import Path
import ast,json
from hashlib import sha256
from czsc_trader.application.runtime_migration import _trading_source_tree
ROOT=Path(__file__).resolve().parents[5]
items=json.loads((ROOT/'research/S001/experiments/EX002_20261026/protocols/observation_sources.json').read_text(encoding='utf-8'))
rows=[]
for ref in ('S001-v1','S001-v2'):
 item=items[ref];version=item['original']['version'];package=ROOT/'strategies/S001/releases'/version
 manifest=json.loads((package/'release_manifest.json').read_text(encoding='utf-8'))
 old_root=package/manifest['runtime_root'];new_root=ROOT/item['source'];module='strategies/s001_'+version+'.py';name='S001'+version.upper()
 before=old_root/module;after=new_root/module
 _trading_source_tree(after.read_bytes(),name)
 try:_trading_source_tree(before.read_bytes(),name)
 except ValueError as exc: reason=str(exc)
 else:raise AssertionError('expected unsupported old declaration')
 assert (old_root/'strategies/s001_common.py').read_bytes()==(new_root/'strategies/s001_common.py').read_bytes()
 def constructor(path,cls):
  tree=ast.parse(path.read_text(encoding='utf-8-sig'));c=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==cls)
  fn=next(n for n in c.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
  fn.body=[n for n in fn.body if not isinstance(n,ast.ImportFrom)]
  for node in ast.walk(fn):
   if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='StrategyDefinition':
    for kw in node.keywords:
     if kw.arg=='observation':kw.value=ast.Constant('<observation>')
  return ast.dump(fn,include_attributes=False)
 assert constructor(old_root/'strategies/s001_common.py','S001Base')==constructor(after,name)
 rows.append({'reference':ref,'candidate_explicit_declaration':'PASS','copied_constructor_logic':'EXACT_AST_EXCEPT_LOCAL_IMPORTS_AND_OBSERVATION',
  'original_common_bytes_unchanged':True,'original_entry_sha256':sha256(before.read_bytes()).hexdigest(),
  'original_entry_source':before.read_text(encoding='utf-8'),'old_source_validation':'FAIL','reason':reason,
  'conclusion':'Current observation upgrade always checks the immutable old entry class; changing only the candidate cannot make the before-side explicit declaration exist.'})
path=ROOT/'research/S001/experiments/EX002_20261026/others/inherited_declaration_blocker.json'
path.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
print('Candidate declarations PASS; immutable originals unsupported for both S001 versions')
