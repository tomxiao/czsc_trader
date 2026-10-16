"""Verify report quantities and descriptive outputs beyond bootstrap audits."""
from hashlib import sha256
import json
import numpy as np
import pandas as pd
from inputs import ROOT,EXPERIMENT,RUN


def main():
    target=EXPERIMENT/'others/summary_audit.json'
    if target.exists():
        raise RuntimeError('Preserve summary audit')
    checks=[]
    m=pd.read_csv(RUN/'mechanism_predictions.csv')
    annual=pd.read_csv(EXPERIMENT/'others/mechanism_annual.csv')
    for row in annual.to_dict('records'):
        p=m.loc[m.horizon.eq(row['horizon'])].sort_values('signal').reset_index(drop=True)
        a=p[f'selected_{row["name"]}'].to_numpy();b=p[f'control_{row["name"]}'].to_numpy()
        keep=np.ones(len(p),dtype=bool)
        if row['mode']=='decluster':
            retained=[]
            for s in p.loc[a|b,'signal']:
                if not retained or int(s)>retained[-1]+20:
                    retained.append(int(s))
            keep=p.signal.isin(retained).to_numpy()
        g=p.loc[p.year.eq(row['year'])]
        mask=np.ones(len(g),dtype=bool) if row['scope']=='all' else g.gap_down_repair.eq(1).to_numpy()
        sa=(a&keep)[g.index]&mask;sb=(b&keep)[g.index]&mask
        y=g.net_return.to_numpy()
        if row['mode']=='residual':
            y=y-g.stock_prediction.to_numpy()
        assert row['selected']==sa.sum() and row['control']==sb.sum() and row['filled']==g.loc[sa,'entry_filled'].sum()
        for selection,field in [(sa,'selected_mean'),(sb,'control_mean')]:
            if selection.any():
                assert abs(y[selection].mean()-row[field])<1e-12
            else:
                assert pd.isna(row[field])
    checks.append('all_mechanism_descriptive_counts_means_decluster')
    cash=pd.read_csv(RUN/'cash_attribution.csv')
    result=json.loads((EXPERIMENT/'others/attribution_result.json').read_text(encoding='utf-8'))
    for row in result['annual']:
        p=cash.loc[cash.horizon.eq(row['horizon'])&cash.year.eq(row['year'])]
        if row['mode']=='open-endpoints':
            p=p.loc[p.synchronous_open_endpoints]
        assert len(p)==row['n']
        for name in ('first_cash','later_cash','fees','net_return','market_first_proxy','market_later_proxy','first_residual','later_residual'):
            assert abs(p[name].mean()-row[name])<1e-12
    checks.append('all_cash_annual_aggregation_and_timing_subset')
    new=pd.read_csv(RUN/'followup_predictions.csv')
    contribution=pd.read_csv(EXPERIMENT/'others/followup_contributions.csv')
    for identity,rows in contribution.groupby(['horizon','algo','mode','left','right']):
        h,algo,mode,left,right=identity
        p=new.loc[new.horizon.eq(h)].sort_values('signal').reset_index(drop=True)
        a=p[f'{mode}_{algo}_{left}'].to_numpy()
        b=np.ones(len(p),dtype=bool) if right=='all' else p[f'{mode}_{algo}_{right}'].to_numpy()
        change=a.astype(float)-b.astype(float)
        retained=[]
        for s in p.loc[change!=0,'signal']:
            if not retained or int(s)>retained[-1]+10:
                retained.append(int(s))
        keep=p.signal.isin(retained).to_numpy()
        category=np.select([p.gap.lt(0)&p.intraday.gt(0),p.gap.lt(0)&p.intraday.le(0),p.gap.ge(0)&p.intraday.gt(0)],
            ['A-lowgap-repair','B-lowgap-nonrepair','C-upgap-upcandle'],default='D-other')
        for row in rows.to_dict('records'):
            g=p.loc[p.year.eq(row['year'])];gi=g.index
            mask=category[gi]==row['category'];delta=change[gi];y=g.net_return.to_numpy()
            assert row['added']==((delta>0)&mask).sum() and row['removed']==((delta<0)&mask).sum()
            assert abs((y*delta*mask).mean()-row['contribution_per_origin'])<1e-12
            assert abs((y*delta*mask*keep[gi]).mean()-row['decluster_contribution_per_origin'])<1e-12
    checks.append('all_participation_category_and_decluster_cash_contributions')
    report=(EXPERIMENT/'protocols/report.md').read_text(encoding='utf-8')
    # Particular numerical claims in the prose, beyond generated contrast tables.
    original=pd.read_csv(RUN/'predictions.csv')
    p=original.loc[original.horizon.eq(3)&original.selected_ridge_relative]
    assert len(p)==237 and p.entry_filled.sum()==235 and abs(p.net_return.mean()-.0117652)<1e-7
    p=original.loc[original.horizon.eq(3)&original.year.eq(2025)&original.gap_down_repair.eq(1)]
    assert p.selected_ridge_relative.sum()==33 and len(p)==76
    assert abs(p.loc[p.selected_ridge_relative,'net_return'].mean()+.018009)<1e-6
    p=new.loc[new.horizon.eq(3)&new.frozen_ridge_relative]
    assert len(p)==219 and abs(p.net_return.mean()-.009743)<1e-6
    checks.append('key_report_means_counts_and_2025_counterexample')
    proposal=json.loads((EXPERIMENT/'protocols/next_scope_proposal.json').read_text(encoding='utf-8'))
    assert proposal['status']=='PROPOSED_NOT_APPROVED_NOT_INGESTED' and proposal['minimum_request']['symbol']=='000813.SH'
    assert '未获批、未取数' in report and '阶段二保持进行中' in report
    checks.append('proposal_not_misrepresented_as_ingested_or_approved')
    manifest=[]
    for p in [*(EXPERIMENT/'src').glob('*.py'),*(EXPERIMENT/'protocols').glob('*'),
              *(EXPERIMENT/'others').glob('*.json'),*(EXPERIMENT/'others').glob('*.csv'),*RUN.glob('*.csv')]:
        if p.is_file():
            manifest.append({'path':p.relative_to(ROOT).as_posix(),'sha256':sha256(p.read_bytes()).hexdigest()})
    value={'status':'PASS','checks':checks,'source_calls':0,'strategy_accounts':0,'manifest':manifest}
    target.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print('SUMMARY_AUDIT_PASS',len(checks))


if __name__=='__main__':
    main()
