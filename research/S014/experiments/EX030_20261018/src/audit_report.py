"""Final narrative, arithmetic-table, provenance-link and publication-plan review."""
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[5]
EX=Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    destination=EX/'others/report_review.json'
    if destination.exists():
        raise RuntimeError('Preserve completed report review')
    report_path=EX/'protocols/report.md'
    report=report_path.read_text(encoding='utf-8')
    analysis=read(EX/'others/analysis.json')
    judgment=read(EX/'others/diagnostic_judgment.json')
    audit=read(EX/'others/independent_audit.json')
    bindings=read(EX/'others/input_binding_review.json')
    checks=0
    table_rows=[line for line in report.splitlines() if line.startswith('| ') and not line.startswith('| ---')]
    expected=[]

    def summary(window,population,horizon,state,year='ALL',anchor='local'):
        return next(r for r in analysis['summaries'] if all(r[k]==v for k,v in dict(
            window=window,population=population,horizon=horizon,state=state,year=year,anchor=anchor).items()))

    def contrast(window,population,horizon,anchor='local'):
        return next(r for r in analysis['contrasts'] if all(r[k]==v for k,v in dict(
            window=window,population=population,horizon=horizon,anchor=anchor).items()))

    def pct(value):
        return f'{value*100:+.4f}%'

    for window,title in [('ALL','全期'),('THROUGH_2025','截至2025')]:
        for population,label in [('first_recovery','首次恢复'),('all_qualified','全部合格')]:
            a=summary(window,population,10,'true_reclaim')
            b=summary(window,population,10,'apparent_recovery')
            c=contrast(window,population,10)
            expected.append(f"| {title} | {label} | {a['closed']}/{b['closed']} | {pct(a['returns']['mean'])} | {pct(b['returns']['mean'])} | {c['raw_difference']*100:+.4f} | [{c['block_ci']['low']*100:+.4f}, {c['block_ci']['high']*100:+.4f}] |")
    for window,title in [('ALL','全期'),('THROUGH_2025','截至2025')]:
        for h in (1,3,10):
            a=summary(window,'first_recovery',h,'true_reclaim')
            b=summary(window,'first_recovery',h,'apparent_recovery')
            c=contrast(window,'first_recovery',h)
            expected.append(f"| {title} | {h} | {pct(a['returns']['mean'])} | {pct(b['returns']['mean'])} | {c['raw_difference']*100:+.4f} |")
    for year in range(2020,2027):
        a=summary('ALL','first_recovery',10,'true_reclaim',year)
        b=summary('ALL','first_recovery',10,'apparent_recovery',year)
        expected.append(f"| {year} | {a['closed']}/{b['closed']} | {pct(a['returns']['mean'])} | {pct(b['returns']['mean'])} | {(a['returns']['mean']-b['returns']['mean'])*100:+.4f} |")
    for window,title in [('ALL','全期'),('THROUGH_2025','截至2025')]:
        for state,name in [('true_reclaim','真'),('apparent_recovery','表面')]:
            s=summary(window,'first_recovery',10,state)
            v=s['returns']; space=s['scheduled_spaced']
            expected.append(f"| {title} | {name} | {pct(v['mean'])} | {pct(v['without_top3'])} | {pct(v['without_top5'])} | {space['n']} / {pct(space['mean'])} |")
    groups=defaultdict(list)
    for row in analysis['counterexample_bridge']:
        groups[(row['signal_state']['local_state'],row['signal_state']['persistent_state'])].append(row['original']['R_cycle_log'])
    for (local,persistent),values in sorted(groups.items()):
        names={'true_reclaim':'真','apparent_recovery':'表面'}
        expected.append(f"| {names[local]} | {names[persistent]} | {len(values)} | {sum(v>0 for v in values)} | {sum(v<0 for v in values)} | {sum(values):+.9f} |")
    for row in expected:
        assert row in table_rows,row
        checks+=1
    assert len(table_rows)==len(expected)+5
    checks+=1
    for key in ('conclusion','judgment_update','next_step'):
        assert judgment[key] in report,key
        checks+=1
    # Review these safeguards explicitly rather than allowing high returns to imply readiness.
    safeguards=(
        '未经选择校正','不能宣称真实收复必然更差','不能替代连续账户的自然年收益或回撤验收',
        '不能单独证明过滤后账户会更差','不是过滤后账户的收益','尚不能推进阶段四',
        '新增有效组件0','所有样本均为已见开发数据','不追阈值',
        '信号T后的10个评价交易日','与成交日E起的H10收益区间相差一天',
        '这进一步削弱把“未收复旧位”机械等同于坏交易的解释',
    )
    for text in safeguards:
        assert text in report,text
        checks+=1
    assert audit['status']==bindings['status']=='PASS'
    for receipt in (audit,bindings):
        for item in receipt['manifest']:
            assert sha256((ROOT/item['path']).read_bytes()).hexdigest()==item['sha256']
            checks+=1
    formal_parent=ROOT/'research/S014/deliveries/COMPONENTS/13'
    future={EX/'others/result.json',EX/'protocols/report_copy_verification.json',destination}
    links=[]
    for relative in re.findall(r'\]\(([^)]+)\)',report):
        assert not relative.startswith(('http:','https:','file:'))
        path=(formal_parent/relative).resolve()
        assert path.is_relative_to(ROOT/'research/S014')
        assert path.exists() or path in future,(relative,path)
        links.append(dict(relative=relative,path=path.relative_to(ROOT).as_posix(),
            status='PRESENT' if path.exists() else 'DECLARED_PUBLICATION_OUTPUT'))
        checks+=1
    previous_component=EX.parent/'EX016_20261017/others/result.json'
    previous_accounts=EX.parent/'EX029_20261018/others/result.json'
    component_asset=ROOT/'research/S014/assets/deliveries/COMPONENTS/12/delivery.json'
    account_asset=ROOT/'research/S014/assets/deliveries/CANDIDATES/13/delivery.json'
    component=read(component_asset); accounts=read(account_asset)
    assert read(previous_component)['delivery']['revision']==12
    assert read(previous_accounts)['delivery']['revision']==13
    assert len(component['content']['payload']['components'])==26
    assert len(accounts['content']['payload']['candidates'])==66 and not accounts['content']['payload']['handoff']
    checks+=4
    family=read(ROOT/'research/registrations/S014/family.json')['research_intent']
    budget=family['stage_three_autonomous_budget']
    assert budget['total_rounds']==budget['allocated_rounds']==budget['completed_rounds']==10
    assert budget['remaining_unallocated_rounds']==0
    assert family['strategy_accounts']==66 and family['all_targets_pass_count']==0
    checks+=3
    publisher=EX/'src/publish.py'
    assert sha256(publisher.read_bytes()).hexdigest()=='101b450395f492f460bcea134a6c17727a38929fa28fc333cd77b3283d82551b'
    checks+=1
    paths=(Path(__file__),report_path,EX/'others/diagnostic_judgment.json',publisher,
        EX/'others/analysis.json',EX/'others/independent_audit.json',EX/'others/input_binding_review.json',
        EX/'protocols/published_design.json',previous_component,previous_accounts,component_asset,account_asset)
    output=dict(status='PASS',checks=checks,table_numeric_rows=len(expected),relative_links=links,
        narrative_review='Full report read: sample denominators, true cutoff, descriptive cohorts vs annual NAV, local/persistent anchor distinctions, at-risk persistence, tail and spacing counterevidence, no causal/account/phase4 overclaim. All table numeric rows reconstructed from audited result.',
        publisher_review='Source reviewed without running publication: immutable prior26 components and their facts/evidence inherited, prior66 candidate delivery linked, new evidence manifests checked before assembly, FULL validation default verified, exact byte mirrors verified, account budget re-read and equality-checked before intent update. No new account/candidate registration, no upstream ingestion or changed economic contract.',
        budget_before_publication=budget,
        limits=['Prospective result.json, report_copy_verification.json and formal COMPONENTS/13 report require publication-time verification; this review is not a claim publication already succeeded.',
            'Historical component support and candidate eligibility are retained, not reclassified by diagnostic labels.'],
        new_accounts=0,new_upstream_calls=0,
        manifest=[dict(path=p.relative_to(ROOT).as_posix(),sha256=sha256(p.read_bytes()).hexdigest()) for p in paths])
    destination.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(dict(status='PASS',checks=checks,table_numeric_rows=len(expected),relative_links=len(links),sha256=sha256(destination.read_bytes()).hexdigest())))


if __name__=='__main__':
    main()
