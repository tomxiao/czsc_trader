"""Build the two complementary first-break conditional-exit candidates."""
import json
from pathlib import Path
from strategy_runtime import StrategyCandidate,StrategyRuntime,implementation_sha256

ROOT=Path(__file__).resolve().parents[5]
EX=Path(__file__).resolve().parents[1]
OLD=EX.parent/'EX023_20261018'
PACKAGE=EX/'src/strategy_runtime'
VARIANTS=('support_first_profit_exit_H10','support_first_nonprofit_exit_H10')
EXTENSIONS=VARIANTS


def main():
    lock=json.loads((EX/'protocols/comparison_lock.json').read_text(encoding='utf-8'))
    assert tuple(lock['new_variants'])==VARIANTS
    files=('strategies/repair.py',)
    assert all(b'\r' not in (PACKAGE/name).read_bytes() for name in files)
    digest=implementation_sha256(files,source_root=PACKAGE)
    rows=[]
    for number,variant in enumerate(VARIANTS,57):
        path=EX/f'protocols/payload_{variant}.json'
        if path.exists():
            raise RuntimeError('Preserve '+path.name)
        payload={'runtime':{'module':'strategy_runtime.strategies.repair','qualname':'RepairStrategy',
                            'contract_version':1,'source_files':list(files),'source_sha256':digest},
                 'parameters':{'variant':variant}}
        candidate=StrategyCandidate('S014',f'C{number:04}',payload,PACKAGE)
        assert candidate.reference_id==lock['candidate_ids'][variant]
        description=StrategyRuntime().describe(candidate)
        path.write_text(json.dumps(payload,indent=2)+'\n',encoding='utf-8',newline='\n')
        rows.append({'variant':variant,'candidate':candidate.reference_id,'runtime_sha256':description.runtime_sha256,
                     'source_sha256':digest})
    print(json.dumps({'status':'PASS','candidates':rows,'source_files':files,'account_runs':0,'source_calls':0}))


if __name__=='__main__':
    main()
