"""Reproducible recommendation overlay; no backtest, reranking or promotion."""
from pathlib import Path
from hashlib import sha256
import argparse
import json
import shutil
import pandas as pd

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').is_file())
SOURCE=Path(__file__).resolve().parent.parent
BASE=ROOT/'research/S011/stage4/iteration_03'
PERTURB=ROOT/'research/S011/stage4/perturbation_01'
IDS=['S011-CFG-'+n for n in ('000618','000624','000621','000628')]

def read(p):return json.loads(p.read_text(encoding='utf-8'))
def digest(p):return sha256(p.read_bytes()).hexdigest()
def dump(p,value):p.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')

def authenticate(folder):
    manifest=read(folder/'manifest.json')
    for name,h in manifest['files'].items():
        # Both predecessor packages use raw byte file hashes.
        assert digest(folder/name)==h,name

def records(frame):return json.loads(frame.to_json(orient='records',force_ascii=False,double_precision=15))

def calculate():
    authenticate(BASE);authenticate(PERTURB)
    metrics=pd.read_parquet(BASE/'ranking_metrics.parquet').set_index('config_id')
    stats=pd.read_parquet(PERTURB/'diagnostics.parquet')
    definitions={c['config_id']:c for c in read(PERTURB/'configurations.json')['configurations']}
    descriptions=[
        ('收益与联合扰动收益保持优先','收益偏好下优先讨论',
         '中心收益与000624相同；固定2天联合达标5/16对2/16，年化中位数39.10%对36.62%。',
         '单参数达标10/14少于000624的11/14；固定2天联合最差回撤10.51%高于8.24%，频率仍贴原上限。'),
        ('收益组内更关注单参数及扰动回撤','保留为有明确取舍的备选',
         '单参数达标11/14，固定2天联合最差回撤8.24%，均优于000618对应指标。',
         '联合达标仅2/16，年化中位数36.62%；原阅读代表身份不再视作全面更稳健的依据。'),
        ('低回撤组内更关注联合扰动收益','条件性推荐，与000628并列讨论',
         '中心回撤6.15%；固定2天联合年化中位数37.25%，高于000628的34.81%。',
         '联合仅1/16达标；单参数8/14少于000628的9/14，联合最差回撤7.54%高于7.33%。'),
        ('低回撤组内更关注扰动回撤及单参数','条件性推荐，与000621并列讨论',
         '中心回撤6.15%；单参数9/14达标，固定2天联合最差回撤7.33%，优于000621对应指标。',
         '联合仅1/16达标，年化中位数34.81%；原不均匀近邻合格率不足以证明全面更稳健。')]
    items=[]
    for cid,(role,advice,support,adverse) in zip(IDS,descriptions):
        m=metrics.loc[cid];d=stats[stats.center_config_id.eq(cid)&stats.holding_stratum.eq('ALL')].set_index(['scenario','kind'])
        row={'config_id':cid,'config_fingerprint':definitions[cid]['config_fingerprint'],'parameters':definitions[cid]['definition']['parameters'],
             'core_layer':1,'role':role,'advice':advice,'support':support,'counterevidence':adverse,'approved':False,
             'core_metrics':{k:float(m[k]) for k in ('cagr','drawdown_magnitude','fee20_cagr','frequency','worst_rolling60_excess','top3_positive_pnl_share')},
             'perturbation':{}}
        for scenario,kind in d.index:
            r=d.loc[(scenario,kind)]
            row['perturbation'][scenario+'/'+kind]={k:float(r[k]) for k in ('positions','qualified','cagr_median','drawdown_magnitude_max','frequency_above6')}
        row['opportunity_cost_vs_return_group']={'standard_cagr_given_up':float(metrics.loc[IDS[0],'cagr']-m.cagr),
            'stress_cagr_given_up':float(metrics.loc[IDS[0],'fee20_cagr']-m.fee20_cagr),
            'center_drawdown_reduction':float(metrics.loc[IDS[0],'drawdown_magnitude']-m.drawdown_magnitude)}
        items.append(row)
    return {'status':'RESEARCHER_COMPARISON_ONLY_PENDING_USER_DECISION','items':items,
        'method':'POSTHOC_PREFERENCE_CONDITIONAL_JUDGMENT','primary_discussion_if_return_priority':IDS[0],
        'global_total_order':None,'composite_score':None,'core_pareto_changed':False,'automatic_promotion':False,
        'scope':'Recommendation overlay for the four previously selected front configurations only; all other configurations remain available in the original package.',
        'common_risks':['固定2天联合扰动在20bp成本下均0/16达标，低回撤组中心在20bp下也未达原收益目标。',
            '最差60日超额表现为负，少数交易贡献和选择偏差风险仍保留；参数扰动结果不能消除旧不利证据。',
            '原PBO/DSR与重抽样未重算，不能宣称覆盖EX28追加评价；全部为已见开发池。',
            '单尺度局部设计，高阶交互、容量、冲击、延迟及独立前瞻验证仍未充分覆盖。'],
        'preference_warning':'本建议强调收益型研究目标和联合敏感性，同时保留回撤与单参数上的反向证据；不代表统计显著优势或用户确认的新权重。',
        'changes_from_iteration_03':['收益优先讨论对象由000624调整为000618；000624仍有明确取舍价值。',
            '低回撤组由000628单一阅读代表调整为000621/000628条件性并列。',
            '000649连续性对照及其余配置原有层级和证据保留，本轮未对其补做同尺度扰动，不作新稳健性比较。']}

def check_decision(value):
    assert value=={'schema_version':1,'status':'PENDING_USER_DECISION','selected_config_ids':[],
                   'user_approval':None,'stage_five_started':False}

def build(output):
    if output.exists() or not output.is_relative_to(ROOT/'.tmp'):raise ValueError('fresh .tmp output required')
    recommendations=calculate();output.mkdir(parents=True)
    dump(output/'recommendations.json',recommendations)
    legacy=pd.read_parquet(BASE/'diagnostics.parquet');legacy=legacy[legacy.config_id.isin(IDS)]
    dump(output/'risk_profiles.json',{'legacy_diagnostics_scope':'Original iteration_03 observations, including historical irregular-neighbor diagnostics; not updated PBO/DSR.',
        'legacy_diagnostics':records(legacy),'new_balanced_perturbation':records(pd.read_parquet(PERTURB/'diagnostics.parquet')),
        'family_statistics':read(BASE/'family_statistics.json'),'family_statistics_cover_ex28':False})
    for name,origin in [('pareto.json',BASE),('decision.json',PERTURB)]:shutil.copyfile(origin/name,output/name)
    lines=['# 参数扰动后的四配置综合建议','',
        '本包仅更新研究员建议，不新增评价、经济硬门或排序目标。核心帕累托第一层仍为四配置；综合建议按偏好给出，不强排总名次。','',
        '| 配置 | 适合的偏好 | 标准年化/回撤 | 20bp年化 | 单参数达标 | 固定2天联合达标 | 联合年化中位数 | 联合最差回撤 |',
        '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for item in recommendations['items']:
        m=item['core_metrics'];a=item['perturbation']['standard/AXIS'];j=item['perturbation']['standard/JOINT_HOLD2']
        lines.append(f"| {item['config_id']} | {item['role']} | {m['cagr']:.2%}/{m['drawdown_magnitude']:.2%} | {m['fee20_cagr']:.2%} | {a['qualified']:.0f}/14 | {j['qualified']:.0f}/16 | {j['cagr_median']:.2%} | {j['drawdown_magnitude_max']:.2%} |")
    for item in recommendations['items']:
        lines+=['',f"## {item['config_id']}：{item['advice']}",'',item['support'], '',item['counterevidence']]
    lines+=['','## 跨组取舍与共同风险','',
        '选择低回撤组，相对收益组中心年化少6.70个百分点、20bp年化少6.37个百分点，换取中心回撤幅度降低1.10个百分点；不是免费改善，也不代表真实未来交换关系。','',
        *['- '+x for x in recommendations['common_risks']], '', recommendations['preference_warning'], '',
        '保留完整旧风险与新增扰动摘要于[risk_profiles.json](risk_profiles.json)，逐配置建议见[recommendations.json](recommendations.json)。上游[原阶段四](../iteration_03/manifest.json)和[扰动证据](../perturbation_01/manifest.json)只读，全部原配置及000649连续性对照仍保留。','',
        '当前[决定](decision.json)保持待用户确认。建议先确认收益或回撤偏好，再明确选择具体配置晋升、要求继续研究或暂不晋升；研究员建议不构成晋升。','',
        '复算：从仓库根执行 `.venv/Scripts/python.exe -B research/S011/stage4/recommendation_01/src/build.py --output <新的.tmp目录>`；校验使用 `--validate research/S011/stage4/recommendation_01`。无需重新回测。']
    (output/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')
    shutil.copytree(SOURCE/'src',output/'src');shutil.copytree(SOURCE/'tests',output/'tests')
    inputs=[BASE/n for n in ('manifest.json','ranking_metrics.parquet','diagnostics.parquet','family_statistics.json','pareto.json')]
    inputs += [PERTURB/n for n in ('manifest.json','diagnostics.parquet','configurations.json','decision.json')]
    dump(output/'manifest.json',{'inputs':{p.relative_to(ROOT).as_posix():digest(p) for p in inputs},
        'files':{p.relative_to(output).as_posix():digest(p) for p in output.rglob('*') if p.is_file()},
        'entrypoint':'src/build.py','new_evaluations':0,'decision_authority':'USER_ONLY'})
    validate(output)

def validate(package):
    authenticate(package);manifest=read(package/'manifest.json')
    actual={p.relative_to(package).as_posix() for p in package.rglob('*') if p.is_file() and p.name!='manifest.json'}
    assert actual==set(manifest['files'])
    for path,h in manifest['inputs'].items():assert digest(ROOT/path)==h,path
    value=read(package/'recommendations.json');assert value==calculate()
    check_decision(read(package/'decision.json'))
    assert [i['config_id'] for i in value['items']]==IDS and all(not i['approved'] for i in value['items'])
    assert (package/'pareto.json').read_bytes()==(BASE/'pareto.json').read_bytes()
    risks=read(package/'risk_profiles.json');assert len(risks['legacy_diagnostics'])==176 and len(risks['new_balanced_perturbation'])==48
    print(json.dumps({'status':'PASS','reviewed_configs':4,'legacy_risk_rows':176,'perturbation_rows':48,'new_evaluations':0,'promotion':False}))

if __name__=='__main__':
    parser=argparse.ArgumentParser();g=parser.add_mutually_exclusive_group(required=True);g.add_argument('--output',type=Path);g.add_argument('--validate',type=Path)
    args=parser.parse_args();build(args.output.resolve()) if args.output else validate(args.validate.resolve())
