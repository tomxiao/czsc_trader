"""Before-real-data EX085 fixed causal current payoff state contrast."""
from pathlib import Path
import sys

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
sys.path.insert(0,str(ROOT/'.tmp'))
import s013_recent_state_driver as d

checks=d.read(d.WORK/'focused_checks.json')
assert checks['status']=='PASS' and checks['real_inputs']==0
for name,expected in checks['files'].items():
    assert d.digest(d.WORK/name)==expected
p84=ROOT/'research/S013/experiments/EX084_20261012/protocols'
assert d.read(p84/'delivery_validation.json')['status']=='PASS'
previous=d.read(p84/'plan.json')
refs84=d.read(p84/'closeout_references.json')
kernel=d.base.load('recent_state_freeze_definition',d.WORK/'kernel.py')
logit='research/S013/experiments/EX084_20261012/src/kernel.py'
clock=previous['clock_source']
clock_audit=previous['clock_audit_source']
sources=['.tmp/s013-recent-payoff-state/'+name for name in ('kernel.py','audit.py','focused_checks.py','focused_checks.json')]
sources+=['.tmp/s013_recent_state_driver.py','.tmp/s013_recent_state_freeze.py','.tmp/s013_build_recent_state_audit.py',
          '.tmp/s013_confirm_execution.py','research/S013/experiments/EX058_20261011/src/common.py',logit,clock,clock_audit]
plan={
    'status':'ROOT_FROZEN_BEFORE_REAL_STUDY','role':'RSCH','stage':2,'quota_slot':7,
    'authorization':'原自主研究及EX079–EX088十轮额度；每轮保存正式report副本',
    'original_four_hard_gates_changed':False,'new_economic_hard_gates':False,
    'question':'T已知的近期已成熟四日净机会盈亏结构，是否提供超出原14项的当前状态信息？',
    'basis':'EX084原确认概率映射2023有有限支持，2022年度历史盈利比例52.16%而实际44.21%，全部入场时钟亏损；需要检验当前可得状态信息，而非移动阈值或假设更新即有效。近期成熟盈亏比例和净均值直接描述匹配交易期限的近期盈利环境。',
    'strongest_prior_counter':'原14已有20日动量、波动、延续性及成交信息，新状态可能只是重复趋势和波动；20个h4代理高度重叠、有效信息少，近期好坏可能反转而不是延续。原概率/均值表达及日期线索没有实现硬门，旧样本长期反复使用，不称新独立样本。',
    'fixed_design':{
        'axis':'原1635T、原14列及原h4净OPEN标签，不扩展2019标签或最新数据',
        'new_state':list(kernel.STATES),
        'causal_window':'每个历史/当前T，只选label_end<=T且target有限的原四日机会，按原signalT顺序取最后20。label_end=T表示当天OPEN已知，可以进入；当前T自己的未来target绝不进入。未满20全窗口则明确缺失，不用短窗口兜底。保存每T完整20个位置、最大成熟日期及可用状态。',
        'window_basis':'固定20，与原ACF/波动/动量的20尺度一致，用于匹配当前状态；不是验证最优窗口，未扫描。二项只用成熟原净价格代理：正净比例与平均净收益，零归非盈利，不另拟合分界或方向。',
        'matched_controls':'原14对照和14＋两状态增广必须使用完全相同的16项共同完整行、成熟训练T和测试T。新窗口使2020最初若干行不可得，旧EX084训练不同，不能精确复用旧模型或将样本变化当组件改善；本轮重新拟合两个14项对照。历史结果保持不变。',
        'training':'2020<=Tyear<testyear，target有限且label_end严格早于本测试年首T，16项共同有限；至少40且正/非正各至少20，两种职责共用该支持。年度2021–2026，不以未来全年测试样本数控制当前预测。',
        'models':'原14/14＋状态分别直接net ridge，以及同两特征集net>0事件logistic。共四类年度模型最多24拟合；恒定训练均值/概率为计算对照，不另训练模型。',
        'transforms':'全部列用同年度成熟训练ECDF中点秩-.5；ridge10且截距不惩罚，logistic固定EX084已核验的总logloss+斜率L2=10、截距不惩罚、收敛显式拒绝，无兜底；不扫描算法/alpha/期限/组件子集。',
        'economic_mapping':'概率表达依同一匹配训练平均gain/loss映射p*gain+(1-p)*loss，正净期望>0才选择。盈亏平衡仅成熟训练决定，不调概率阈值；本轮不更新/条件化盈亏幅度，先检验当前状态信息增量。',
        'forecast':'2020无预测，尾部未来truth缺失仍用已知状态/原T特征预测；测试标签只事后评分和因果已成熟后构造状态，不提前使用。',
        'primary':'两个匹配职责的新状态增量：概率Brier/logloss、直接/映射netMSE、选中净均值增量；全部2020–26年度经济余量及全部五相位/原贪心对照，不以单诊断设新经济门。',
        'clocks':'冻结EX083原贪心＋i%5所有五组，共五个net表达×六时钟=30代理；不选最好起点，不当32点或原生账户。',
        'bootstrap':'共享原1635T轴500次重叠40日块seed13，固定预测不重拟合；原始/重抽样至少20且至少400有效才报LINEAR95CI，否则不可得。全部十项500记录保留，未校正研究历史、多重比较，非未来成功概率。',
        'quantities':list(kernel.QUANTITIES),
    },
    'scope':previous['scope'],'selection_history':'根据年度旧先验反证提出新的近期成熟机会状态，仍同一已见开发池；窗口20与h4固定，无窗口/起点/阈值/方向救援。先匹配控制和验证因果，再评价增量；不称独立验证。',
    'stopping':'本轮组件0账户。若增量或净盈利余量不足，完整交付反证并停止当前状态表达；若有一致经济信息，后续额度再评估原生账户及标准自检，不以更高胜率/MSE替代硬门。',
    'source_files':{name:d.digest(ROOT/name) for name in sources},
    'input_references':{'features.csv':previous['input_references']['features.csv'],'labels.csv':previous['input_references']['labels.csv'],
                        'prices.csv':previous['input_references']['prices.csv'],'prior_statistics.json':refs84['statistics.json'],
                        'prior_verification.json':refs84['verification.json'],'prior_review.json':refs84['root_review.json'],
                        'prior_budget.json':refs84['budget_receipt.json'],'prior_plan.json':refs84['plan.json']},
    'logit_source':logit,'clock_source':clock,'clock_audit_source':clock_audit,
    'continuation_budget_reference':previous['continuation_budget_reference'],'predecessors':previous['predecessors'],
    'report_copy':previous['report_copy'],'resources':{'new_annual_models_maximum':24,'new_accounts':0,'provider_calls':0,'schedules':30,'bootstrap':500},
    'objective_achieved':False,
}
d.check(plan)
d.write(d.WORK/'prospective.json',plan)
print({'status':plan['status'],'slot':7,'annual_models_maximum':24,'accounts':0})
