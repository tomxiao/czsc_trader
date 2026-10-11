"""Root scientific review after independent EX076 arithmetic verification."""
from pathlib import Path
from hashlib import sha256
import json,sys
root=Path.cwd();w=root/'.tmp/s013-cross-day-curvature';a=w/'actual_v2'
def read(p):return json.loads(p.read_text('utf-8-sig'))
def digest(p):return sha256(p.read_bytes()).hexdigest()
def write(p,v):
 with p.open('x',encoding='utf-8') as f:json.dump(v,f,ensure_ascii=False,indent=2,allow_nan=False)
from czsc_trader.research_tools.evidence import EvidenceRef
refs=read(w/'active_result_references.json');refs.update(read(w/'verification_references.json'))
for v in refs.values():assert digest(EvidenceRef.from_dict(v).resolve(root))==v['sha256']
assert refs['plan.json']['sha256']=='570ab22bb01e945db96e9facf7dff52b8061500245df74e7a76084295d249a05'
assert refs['statistics.json']['sha256']=='452de1e63d40d283d062ed43b13a4fa80991ef605cde2f3a99d784149113358c'
verification=read(EvidenceRef.from_dict(refs['verification.json']).resolve(root))
assert verification['status']=='PASS' and verification['new_accounts']==0 and verification['provider_calls']==0
sys.path.insert(0,str(w));import reading
stats=read(a/'statistics.json');fixed=reading.summarize(stats);assert fixed==read(a/'reading.json')
assert all(v['return4_net']['status']=='NO_INCREMENT' for v in fixed['scopes'].values())
summary={}
for scope,pa in stats['scopes'].items():
 summary[scope]={}
 for label,p in pa['labels'].items():
  m=p['walk_forward']['aggregate']
  summary[scope][label]=dict(raw_n=p['raw']['n'],partial_n=p['partial']['n'],rank=p['partial']['design_rank'],df=p['partial']['residual_df'],
   raw_ic=p['raw']['value'],raw_ci=p['raw_bootstrap']['ic95'],partial_ic=p['partial']['value'],partial_ci=p['partial_bootstrap']['ic95'],
   raw_valid=p['raw_bootstrap']['valid'],partial_valid=p['partial_bootstrap']['valid'],
   pooled_oos={n:m[n] for n in ('n','reason','mse_controls','mse_augmented','mse_pastmean','delta_controls','delta_pastmean')},
   mse_vs_controls_percent=100*(m['mse_augmented']/m['mse_controls']-1),mse_vs_pastmean_percent=100*(m['mse_augmented']/m['mse_pastmean']-1),
   years={k:{n:v['partial'][n] for n in ('n','value','reason','design_rank','residual_df')} for k,v in p['years'].items()},
   phases={k:{n:v['partial'][n] for n in ('n','value','reason','design_rank','residual_df')} for k,v in p['phases'].items()},
   annual_oos={k:dict(train_n=v['train_n'],test_n=v['test_n'],reason=v['reason'],metrics={n:v['metrics'][n] for n in ('n','reason','mse_controls','mse_augmented','mse_pastmean')}) for k,v in p['walk_forward']['yearly'].items()})
judgment='固定四日价格曲率的正向收益信息假设在全池与原策略空仓资格池都未观察到可靠增量。停止该固定用途，不反转方向、不换窗口、不移除控制、不挑2024或相位4救援；风险只作诊断，不转为买卖规则。尚未证明当前获利目标不可行，也没有抗扰动达标策略。'
report='''# EX076：相同四日涨跌幅下，价格变化顺序能否帮助识别盈利机会

固定四日曲率衡量最近两日相对前两日是否加速上涨或减速下跌。固定正向收益先验，保留17项控制（含四日总涨跌幅），分别检验全开发池和原策略此前空仓的买入资格池；后续四个完整交易日扣费收益为主要目标，OPEN/CLOSE风险只作诊断。

|范围|完整控制样本|收益部分相关及95%区间|下一年预测数|误差相对原17指标|误差相对过去均值|
|---|---:|---|---:|---:|---:|
|全池|1612|+0.0237，[-0.0082,+0.0576]|1388|减少0.0418%|增加2.7204%|
|原policy-flat买入资格池|145|+0.0020，[-0.1522,+0.1800]|80|增加0.0329%|增加0.7172%|

两个置信区间都包含零，不能确认正向增量，也不能据此认定反向有效。全池略胜原指标，但没有胜过更简单的过去平均值；空仓买入资格池反而略差。固定科学判读两池均NO_INCREMENT。本次没有把统计判读新增为经济硬门。

有利反例完整保留：全池2024年预测同时胜过两个基线；空仓资格池2022年部分相关为+0.2393，相位4为+0.8218。但后者相位只有30个完整样本、12个残差自由度，不选它替代总体。空仓资格池可外推年份仅2022/2023/2024（32/24/24条），2021训练不足、2025/2026测试不足，原始不足状态与空值保留。2023单年部分相关亦因残差自由度不足而不可用，不能填成零。

风险诊断同样没有胜过过去均值：全池误差增加2.3144%，空仓资格池增加0.2755%。没有事前风险交易用途，因此不能把它改称有效退出或减仓机制。

原1635日信号轴保持，原147次空仓买入资格中146次标签已成熟、145次控制齐全。完整1636决策前缀为2019-12-31至2026-09-29，先取前日target再重排到信号日；原执行1636日为2020-01-02至2026-09-30。首次技术认证因把这两条日期轴当成相同而失败，失败完整保留；仅修正日期轴校验，原数学、价格、标签、控制、范围及参数未改变，只有一次真实统计。

独立核验检查4000条重抽样状态、59030项数值和8808条预测，最大预测差异3.32e-16，PASS。根会话另逐日核验1635条曲率、价格标签和成熟日及完整原资格前缀。新增行情请求0、账户0，原四门、只做多、费用、1%执行合同与后复权口径保持。

下一步只考虑已事前冻结的独立完整政策反证：将价格回落、反转买入和回吐退出统一为一个周期。它用于检验简化状态耦合，不声称新增预测优势；先且仅检验一个固定中心，原四门任一失败则停止该路线，无邻域或参数救援。抗扰动策略目标尚未达成。

局限：这是反复使用的开发池，区间未校正多轮研究选择；固定年度外推仍不是独立封存检验。四日标签是理想OPEN及单边0.1%费用代理，不能证明1%限价真实成交、账户收益、回撤或五项自检达标。空仓是原策略target政策状态，并非实际成交持仓。风险只观察O/C；PBO/DSR不可用。两个池各自同样本比较，不能把EX075的18控制结果当成逐点配对比较。
'''
review=dict(status='ROOT_SCIENTIFIC_REVIEWED',experiment=read(w/'experiment.json'),
 evidence_references={n:refs[n] for n in ('plan.json','statistics.json','verification.json')},
 roles={scope:dict(status='INEFFECTIVE',judgment=judgment) for scope in fixed['scopes']},
 return_direction='positive',risk_role='DIAGNOSTIC_ONLY',scientific_reading=fixed,summary=summary,
 judgment=judgment,report_markdown=report,objective_achieved=False,new_accounts=0,original_four_hard_gates_changed=False,
 root_review_source_sha256=digest(Path(__file__)))
write(w/'root_review.json',review)
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef
sys.path.insert(0,str(root/'research/S013/experiments/EX058_20261011/src'));import common
exp=ExperimentRef.from_dict(review['experiment']);published={}
paths=[('root_review.json',w/'root_review.json'),('root_review.py',Path(__file__)),('root_prestudy_check.json',a/'root_prestudy_check.json'),('root_prestudy_check.py',root/'.tmp/s013_precheck_curvature.py'),('root_publisher.py',root/'.tmp/s013_publish_curvature_phase.py'),('root_audit_authorizer.py',root/'.tmp/s013_authorize_curvature_audit.py')]
for n,p in paths:
 published[n]=publish_evidence(common.context(1),MaterialEvidenceWrite(exp,'curvature-'+n.replace('.','-'),p.read_bytes(),'text/x-python' if p.suffix=='.py' else 'application/json',p.suffix[1:])).to_dict()
 if p.suffix=='.py':
  with (exp.resolve(root)/'src'/n).open('xb') as f:f.write(p.read_bytes())
write(w/'root_review_references.json',published);write(exp.resolve(root)/'protocols/root_review_references.json',published)
assert not common.SOURCE_CALLS
print({'status':'ROOT_SCIENTIFIC_REVIEWED','scopes':{k:v['return4_net']['status'] for k,v in fixed['scopes'].items()},'new_accounts':0})
