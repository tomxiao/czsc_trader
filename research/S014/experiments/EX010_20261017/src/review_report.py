"""Check bounded report claims, links, authorization and unchanged audited files."""
from hashlib import sha256
import json
import re
from inputs import ROOT,EXPERIMENT


def main():
    target=EXPERIMENT/'others/report_review.json'
    if target.exists():
        raise RuntimeError('Preserve report review')
    checks=[]
    for name in ('audit','followup_audit','stock_lag_audit'):
        a=json.loads((EXPERIMENT/f'others/{name}.json').read_text(encoding='utf-8'));assert a['status']=='PASS'
        for item in a['manifest']:
            assert sha256((ROOT/item['path']).read_bytes()).hexdigest()==item['sha256'],item['path']
    checks.append('all_three_audited_manifests_unchanged')
    r=json.loads((EXPERIMENT/'others/upstream_verification_resolved.json').read_text(encoding='utf-8'))
    assert r['source_calls_used']==len(r['source_calls'])==3 and r['remaining_source_calls']==2
    assert r['identity']['symbol']=='000813.CSI' and r['rows']==1642 and all(r['checks'].values())
    checks.append('same_index_identity_and_total_call_budget')
    cash=json.loads((EXPERIMENT/'others/attribution_result.json').read_text(encoding='utf-8'))
    for x in cash['annual']:
        if x['horizon']==1 and x['year']==2025:
            assert x['n']==(76 if x['mode']=='all-filled' else 75)
            assert x['later_cash']<-.0045 and x['both_later']>0 and x['both_later_residual']<x['market_later_residual']
    checks.append('2025_negative_explanatory_result_not_reversed')
    proposal=json.loads((EXPERIMENT/'protocols/next_scope_proposal.json').read_text(encoding='utf-8'))
    assert proposal['status']=='PROPOSED_ONLY_NOT_AUTHORIZED_NOT_QUERIED'
    assert proposal['requested_next_scope']['symbol']=='600722.SH'
    report=(EXPERIMENT/'protocols/report.md').read_text(encoding='utf-8')
    assert '不新增SUPPORTED收益入场组件' in report and '阶段三未获批准' in report and '未查询公告目录' in report
    checks.append('no_fabricated_component_or_next_scope_authorization')
    base=ROOT/'research/S014/deliveries/COMPONENTS/7'
    for link in re.findall(r'\]\(([^)]+)\)',report):
        if link.startswith('https://'):
            continue
        assert not __import__('pathlib').Path(link).is_absolute() and (base/link).resolve().exists(),link
    checks.append('formal_report_relative_links_exist')
    paths=[*(EXPERIMENT/'src').glob('*.py'),*(EXPERIMENT/'protocols').glob('*.json'),EXPERIMENT/'protocols/report.md']
    output={'status':'PASS','checks':checks,'report_sha256':sha256(report.encode('utf-8')).hexdigest(),
        'manifest':[{'path':p.relative_to(ROOT).as_posix(),'sha256':sha256(p.read_bytes()).hexdigest()} for p in paths]}
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n');print('REPORT_REVIEW_PASS',len(checks))


if __name__=='__main__':
    main()
