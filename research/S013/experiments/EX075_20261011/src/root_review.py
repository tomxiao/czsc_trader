"""Root scientific review of the unique independently verified EX075 result."""
from pathlib import Path
from hashlib import sha256
import json
import sys

root = Path.cwd()
work = root / '.tmp/s013-volume-body-interaction'
def read(p): return json.loads(p.read_text('utf-8-sig'))
def digest(p): return sha256(p.read_bytes()).hexdigest()
def write(p, value):
 with p.open('x', encoding='utf-8') as f: json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)

from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
sys.path.insert(0, str(work))
import reading_classifier_v3 as classifier
assert digest(work / 'reading_classifier_v3.py') == 'e2af27e514ef9fb9d5f50dbfd46581ccc1efb2e6746a0d92b715d895571ea7b9'
results, verifies = read(work/'result_references.json'), read(work/'verification_references.json')
refs = {k:results[k] for k in ('plan.json','statistics.json','component_draft.py')}
refs['verification.json'] = verifies['verification.json']
for ref in refs.values(): assert digest(EvidenceRef.from_dict(ref).resolve(root)) == ref['sha256']
assert refs['plan.json']['sha256'] == 'c213535e04d7a9289132cbf02961e0ebbe80e2d6c17348698847132bed88d1da'
assert refs['statistics.json']['sha256'] == '68e3f5b9cf22c6db61a79423f9fd6593254af8387fddf2622914216edb6782a4'
verification=read(EvidenceRef.from_dict(refs['verification.json']).resolve(root))
assert verification['status']=='PASS' and verification['provider_calls']==0
stats=read(EvidenceRef.from_dict(refs['statistics.json']).resolve(root))
classified={k:classifier.classify(k,p) for k,p in stats['labels'].items()}
assert all(p['status']=='NO_INCREMENT_OBSERVED' for p in classified.values())
summary={}
for label,p in stats['labels'].items():
 a=p['walk_forward']['aggregate']
 yearly=p['walk_forward']['yearly']
 summary[label]={
  'raw_n':p['raw']['n'],'partial_n':p['partial']['n'], 'rank':p['partial']['design_rank'],
  'residual_df':p['partial']['residual_df'],'raw_ic':p['raw']['value'],
  'raw_ci':p['raw_bootstrap']['ic95'],'partial_ic':p['partial']['value'],
  'partial_ci':p['partial_bootstrap']['ic95'], 'valid_bootstrap_raw':p['raw_bootstrap']['valid'],
  'valid_bootstrap_partial':p['partial_bootstrap']['valid'],
  'oos':{k:a[k] for k in ('n','reason','mse_controls','mse_augmented','mse_pastmean','delta_controls','delta_pastmean')},
  'mse_worse_controls_percent':100*(a['mse_augmented']/a['mse_controls']-1),
  'mse_worse_mean_percent':100*(a['mse_augmented']/a['mse_pastmean']-1),
  'all_year_partial_ic':{k:v['partial']['value'] for k,v in p['years'].items()},
  'all_phase_partial_ic':{k:v['partial']['value'] for k,v in p['phases'].items()},
  'yearly_oos':{k:dict(train_n=v['train_n'],test_n=v['test_n'],reason=v['reason'],metrics={n:v['metrics'][n] for n in ('n','reason','mse_controls','mse_augmented','mse_pastmean')}) for k,v in yearly.items()},
 }
judgment='固定放量负实体协方差在18控制、4日持有标签和事前年度外推下，两项用途均未观察到增量；停止该固定假设，不反转方向、不扫描阈值或窗口，也不进入账户实验。此结论不排除其他成交量用途。'
report='''# EX075：下跌K线是否集中了更多成交量

在相同的原开发池中，检查当日成交量是否偏向负实体K线，并检验它能否在原18项观察指标之外，更好地预测随后四个完整交易日的扣费收益和观察风险。

两项用途均未观察到增量。控制其他指标后，收益关联为+0.0533，95%区间[-0.0065,+0.1030]；风险关联为-0.0342，区间[-0.0883,+0.0221]。两个区间都包含零，不能据此认定相反方向成立。

严格用过去年份已成熟标签训练、预测下一年，合并1388个可用预测后，加入新指标的收益预测误差比原18指标高0.49%，比过去平均值高3.21%；风险误差分别高0.32%和1.94%。收益预测没有任何一个固定测试年同时胜过两个比较对象；风险预测在2024至2026三年胜过两者，但合计仍更差。这些有利反例完整保留，不挑选年份救援。

原1635日信号轴不变，1631日原始标签、1611日完整控制样本，设计秩19、剩余自由度1592。四组各500次完整日历分块抽样全部有效，所有年份、五个相位及逐年预测保留。量时钟剔除前20日不足历史，而非补零。独立算术核验及真实价格/成熟日认证通过。

下一步检验相同四日涨跌幅下，最近两日下跌是否减速的固定时间结构；先进行组件验证，有依据才进入完整账户。原四项经济硬门、只做多、1%执行合同及后复权口径不变。本次新增账户0，尚未实现抗扰动策略目标。

局限：本次为已反复观察的开发池，置信区间未校正多轮研究选择；成交量不等于真实卖方流。标签为理想OPEN及单边0.1%费用代理，风险只观察OPEN/CLOSE，不能替代实际限价成交、账户收益、账户最大回撤或五项自检。PBO/DSR不可用。
'''
review=dict(status='ROOT_SCIENTIFIC_REVIEWED', experiment=read(work/'experiment.json'),
 evidence_references={k:refs[k] for k in ('plan.json','statistics.json','verification.json')},
 roles={k:dict(status='INEFFECTIVE',judgment=judgment) for k in classified},
 scientific_classification=classified, summary=summary, judgment=judgment, report_markdown=report,
 objective_achieved=False,new_accounts=0,original_four_hard_gates_changed=False,
 root_review_source_sha256=digest(Path(__file__)))
write(work/'root_review.json',review)
sys.path.insert(0,str(root/'research/S013/experiments/EX058_20261011/src'))
import common
exp=ExperimentRef.from_dict(read(work/'experiment.json'))
published={}
for name,path in [('root_review.json',work/'root_review.json'),('root_review.py',Path(__file__))]:
 published[name]=publish_evidence(common.context(1),MaterialEvidenceWrite(exp,'ex075-'+path.stem,path.read_bytes(),'text/x-python' if path.suffix=='.py' else 'application/json',path.suffix[1:])).to_dict()
write(work/'root_review_references.json',published)
write(exp.resolve(root)/'protocols/root_review_references.json',published)
with (exp.resolve(root)/'src/root_review.py').open('xb') as f: f.write(Path(__file__).read_bytes())
print({'review':'ROOT_SCIENTIFIC_REVIEWED','classifications':{k:v['status'] for k,v in classified.items()},'new_accounts':0})
