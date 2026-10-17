"""Encode two Boolean diagnostic series as numeric 0/1 for SRT observation."""
from pathlib import Path
import ast
import json
from strategy_runtime import StrategyCandidate, StrategyRuntime, implementation_sha256
EX=Path(__file__).resolve().parents[1];PACKAGE=EX/'src/strategy_runtime'
def main():
    old=PACKAGE/'strategies/repair_v2.py';target=PACKAGE/'strategies/repair_v3.py'
    if target.exists():raise RuntimeError('Preserve corrected candidate')
    text=old.read_text(encoding='utf-8');new=text.replace('        return out.loc[sessions]',
        "        out[['parent','high']]=out[['parent','high']].astype(float)\n        return out.loc[sessions]")
    assert new!=text
    funcs=lambda s:{n.name:ast.dump(n) for n in ast.parse(s).body if isinstance(n,ast.FunctionDef)}
    assert funcs(text)==funcs(new)
    target.write_text(new,encoding='utf-8',newline='\n')
    files=('strategies/repair_v3.py','strategies/calibration_samples.csv');digest=implementation_sha256(files,source_root=PACKAGE)
    for i,variant in enumerate(('parent_H1','parent_H3','high_H3','high_H3_low_H1'),9):
        p={'runtime':{'module':'strategy_runtime.strategies.repair_v3','qualname':'RepairStrategy','contract_version':1,
            'source_files':list(files),'source_sha256':digest},'parameters':{'variant':variant}}
        StrategyRuntime().describe(StrategyCandidate('S014',f'C{i:04}',p,PACKAGE))
        (EX/f'protocols/payload_v3_{variant}.json').write_text(json.dumps(p,indent=2)+'\n',encoding='utf-8')
        binding=EX/f'others/binding_{variant}.json'
        binding.rename(EX/f'others/binding_v2_{variant}.json')
    (EX/'others/account_results.json').rename(EX/'others/account_v2_failed.json')
    note={'reason':'SRT numerical observation rejects bool; encode parent/high as 0.0 or 1.0 only at display projection',
        'economic_function_ast_identical':True,'failed_evaluation_attempts':4,'complete_accounts_before_fix':0,
        'fees_targets_execution_unchanged':True,'new_candidate_ids':['C0009','C0010','C0011','C0012']}
    (EX/'protocols/observation_contract_correction.json').write_text(json.dumps(note,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':main()
