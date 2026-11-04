"""Bind the selected family column to the current EX064 center without replay."""
import json
import numpy as np
from family_audit import ROOT,OUT,read,save,extract


def main():
    family=read(OUT/'family_returns.json')
    summary=read(OUT/'family_statistics.json')
    result=read(ROOT/'research/S018/experiments/EX064_20261104/others/recovery_01/results.json')
    center=result['accounts']['CENTER']
    days,returns,identity=extract({'reference':center['account_ref']},{})
    column=family['candidates'].index(family['selected'])
    checks={'candidate_content_matches':center['content_hash']==family['selected']['content_sha256'],
        'calendar_matches':list(days)==family['sessions'],
        'context_metric_scenario_matches':identity==summary['context'],
        'daily_returns_exact':np.array_equal(returns,np.asarray(family['returns'])[:,column])}
    assert all(checks.values()),checks
    save('family_current_center_check.json',{'status':'PASS','checks':checks,
        'current_center_reference':center['account_ref'],'family_selected':family['selected'],
        'family_matrix_binary_f64_le_sha256':summary['matrix_binary_f64_le_sha256'],
        'new_strategy_accounts':0})
    print(json.dumps(checks),flush=True)


if __name__=='__main__':
    main()
