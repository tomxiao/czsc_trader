"""EX087 prospective P/G/L attribution frozen before actual statistics."""
from pathlib import Path
import sys

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
sys.path.insert(0,str(ROOT/'.tmp'))
import s013_legs_driver as d

checks=d.read(d.WORK/'focused_checks.json')
assert checks['status']=='PASS' and checks['real_inputs']==0
for name,expected in checks['files'].items():
    assert d.digest(d.WORK/name)==expected
p86=ROOT/'research/S013/experiments/EX086_20261012/protocols'
assert d.read(p86/'delivery_validation.json')['status']=='PASS'
previous=d.read(p86/'plan.json')
refs86=d.read(p86/'closeout_references.json')
definition=d.base.load('legs_prospective_definition',d.WORK/'kernel.py')
clock,clock_audit=previous['clock_source'],previous['clock_audit_source']
sources=['.tmp/s013-payoff-legs/'+name for name in ('kernel.py','audit.py','focused_checks.py','focused_checks.json')]
sources+=['.tmp/s013_legs_driver.py','.tmp/s013_legs_freeze.py','.tmp/s013_build_legs_audit.py',
          '.tmp/s013_confirm_execution.py','research/S013/experiments/EX058_20261011/src/common.py',
          'research/S013/experiments/EX086_20261012/src/audit.py',clock,clock_audit]
plan={'status':'ROOT_FROZEN_BEFORE_REAL_STUDY','role':'RSCH','stage':2,'quota_slot':9,
      'authorization':'原自主研究和EX079–EX088十轮额度，每实验保存正式报告副本',
      'question':'有用的赚幅预测是否被概率/亏幅抵消，拆项净收益能否解释当前组合失败并提供可执行线索？',
      'basis':'EX086原14盈利幅度MSE约改善6.02%，条件性区间正且五相位点估计正；合成净MSE却更差、两下跌年未解决。保留局部支持，需要匹配拆项归因，不能把整体失败当所有组成无效或事后选择phase3。',
      'strongest_prior_counter':'两个原14赚幅反证年份2022/2026更差；选中真实盈利子集的幅度预测不能识别哪笔会盈利。固定历史概率仍可能漏掉下跌年变化；拆项改善也可能只是少交易/大涨交易/时钟选择，原样本长期反复使用。',
      'original_four_hard_gates_changed':False,'new_economic_hard_gates':False,
      'fixed_design':{'reuse':'精确复用EX084概率和EX086赚/亏幅、固定年度幅度及控制净预测，0新拟合，不更新训练支持或数据',
          'axis':'原1635T/原h4净HFQ OPEN标签，原训练成熟身份和尾部缺标签保持',
          'coordinates':'每信息族所有P/G/L三位组合000..111，0=当年成熟训练固定概率或固定幅度，1=冻结的当前特征条件预测；确认单列及原14各8',
          'new_values':'16表达坐标，000在两族完全相同为共享对照，实际15不同表达，其中10新增净预测列；非16新候选/账户/模型或独立样本',
          'combination':'p*gain-(1-p)*loss，严格>0选择；000精确复用training_mean，100复用旧固定幅度净预测，111复用旧条件双幅度净预测，先核对恒等再精确赋旧控制，非兜底',
          'matched':'所有组合共享相同预测T、过去成熟年度训练、资金费用/标签。每个年度、五相位、24条相同背景仅切换一项的边都完整报告；背景不当独立样本',
          'primary':'每族固定7量：赚幅单独/加入概率/概率加入赚幅的净MSE增量，赚幅单独/概率+赚幅选中净均值，加入赚幅/最后加入亏幅的选中均值差；共14，不根据结果换量',
          'quantities':list(definition.QUANTITIES),
          'edges':'全24单项替换边，原始全窗、全部年和五相位都报告净MSE和选中均值增量；这是模型诊断，非账户因果利润',
          'clocks':'冻结EX083贪心和i%5所有五组，共16×6=96坐标；重复000时钟不重复计独立信息，不挑赢家相位/组，不是32标准扰动',
          'bootstrap':'原1635T轴500次重叠40日块seed13，固定预测不重拟合；原始/重抽样至少20、至少400有效、LINEAR95CI；14量全部留证，未经研究历史和多重比较校正',
          'forecast':'2020无预测，尾部未来truth缺失仍保留已知输入预测；不增加未来全年数量门，不用未来标签更换组合'},
      'scope':'原510500已见开发池/HFQ固定锚/无现金分红叠加/资金费用整手/1%合同；0模型拟合、账户、provider、新市场数据、平台或生产变更',
      'stopping':'完整识别有利和不利，若只是少数时钟/薄余量/下跌年仍负，不升级为账户；若有一致净经济支持，剩余最后额度可进入最小原生验证。无参数、方向、期限或相位救援。诊断不新增经济硬门。',
      'source_files':{name:d.digest(ROOT/name) for name in sources},
      'input_references':{'labels.csv':previous['input_references']['labels.csv'],'prices.csv':previous['input_references']['prices.csv'],
          'probabilities.csv':previous['input_references']['prior_probabilities.csv'],'magnitudes.csv':refs86['magnitudes.csv'],
          'constants.csv':refs86['constant_magnitudes.csv'],'prior_forecasts.csv':refs86['forecasts.csv'],
          'prior_statistics.json':refs86['statistics.json'],'prior_verification.json':refs86['verification.json'],
          'prior_review.json':refs86['root_review.json'],'prior_plan.json':refs86['plan.json'],'prior_budget.json':refs86['budget_receipt.json']},
      'clock_source':clock,'clock_audit_source':clock_audit,'continuation_budget_reference':previous['continuation_budget_reference'],
      'predecessors':previous['predecessors'],'report_copy':previous['report_copy'],
      'resources':{'new_annual_models':0,'new_accounts':0,'provider_calls':0,'schedules':96,'bootstrap':500,'new_net_prediction_columns':10},
      'objective_achieved':False}
d.check(plan)
d.write(d.WORK/'prospective.json',plan)
print({'status':plan['status'],'slot':9,'new_annual_models':0,'accounts':0})
