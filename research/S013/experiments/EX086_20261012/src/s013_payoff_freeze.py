"""EX086 prospective conditional-mean decomposition, before actual data analysis."""
from pathlib import Path
import sys

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
sys.path.insert(0,str(ROOT/'.tmp'))
import s013_payoff_driver as d

checks=d.read(d.WORK/'focused_checks.json')
assert checks['status']=='PASS' and checks['real_inputs']==0
for name,expected in checks['files'].items():
    assert d.digest(d.WORK/name)==expected
p84=ROOT/'research/S013/experiments/EX084_20261012/protocols'
p85=ROOT/'research/S013/experiments/EX085_20261012/protocols'
assert all(d.read(p/'delivery_validation.json')['status']=='PASS' for p in (p84,p85))
previous=d.read(p84/'plan.json')
refs84=d.read(p84/'closeout_references.json')
refs85=d.read(p85/'closeout_references.json')
definition=d.base.load('payoff_prospective_definition',d.WORK/'kernel.py')
literature={'kind':'METHOD_ONLY_NOT_ALPHA_EVIDENCE','source':'https://www.statsmodels.org/stable/generated/statsmodels.genmod.families.family.Gamma.html',
            'accessed':'2026-10-12','primary_fact':'Gamma GLM permits a log mean link; default is inverse, not log',
            'actual_method':'Explicit convex conditional-mean criterion sum(eta+m*exp(-eta))+5*sum(slopes^2); positive mean exp(eta)',
            'derivation':'For fixed x, expected eta+m exp(-eta) is minimized at exp(eta)=E[m|x]. Thus estimates arithmetic conditional mean, not exp(mean(log m)).',
            'zero_magnitudes':'m=0 allowed by this mean criterion. Do not claim Gamma density at zero or a fitted true distribution. A group mean <=0 is explicitly refused, not epsilon-filled.',
            'market_data_imported':False,'new_dependency_installed':False,'guarantees_profitability':False}
d.write(d.WORK/'method_basis.json',literature)
duplicate={'status':'TARGETED_DUPLICATE_REVIEW','searched':'S013 formal COMPONENTS reports plus earlier gap/BULL price report references',
           'patterns':['盈亏幅','收益幅','两部','two.part','Gamma','条件盈利/亏损','概率幅度'],
           'gap_route':'EX064 already tested negative_gap_repair and positive_gap_fade; no repeat',
           'gap_report':'research/S013/deliveries/COMPONENTS/4/report.md','gap_report_sha256':d.digest(ROOT/'research/S013/deliveries/COMPONENTS/4/report.md'),
           'closest':'EX084 predicts probability but uses unconditional historical mean gain/loss; EX085 adds recent matured state but explicitly leaves amplitudes unconditioned',
           'difference':'Only current-feature-conditional expected gain/loss magnitudes are new; EX084 probabilities and exact same row support remain',
           'does_not_claim_exhaustive_universe_search':True}
d.write(d.WORK/'duplicate_review.json',duplicate)
clock,clock_audit=previous['clock_source'],previous['clock_audit_source']
sources=['.tmp/s013-conditional-payoff/'+name for name in ('kernel.py','audit.py','focused_checks.py','focused_checks.json','method_basis.json','duplicate_review.json')]
sources+=['.tmp/s013_payoff_driver.py','.tmp/s013_payoff_freeze.py','.tmp/s013_build_payoff_audit.py',
          '.tmp/s013_confirm_execution.py','research/S013/experiments/EX058_20261011/src/common.py',
          'research/S013/experiments/EX084_20261012/src/kernel.py','research/S013/experiments/EX085_20261012/src/audit.py',clock,clock_audit]
plan={'status':'ROOT_FROZEN_BEFORE_REAL_STUDY','role':'RSCH','stage':2,'quota_slot':8,
      'authorization':'原自主研究和EX079–EX088十轮额度，每实验保存正式报告副本',
      'question':'给定同一盈利概率，特征条件化赚/亏幅度能否改善扣费后净盈利选择？',
      'basis':'EX084原14概率映射较直接收益MSE改善约1.9997%且条件性区间正，但选中净均值负；确认概率2023有限正支持而2022失败。两者使用历史固定赚亏幅度，尚不能排除盈利概率与金额关系误判。EX085近期成熟状态没有解决此问题。',
      'strongest_prior_counter':'原14直接净均值模型、固定概率幅度映射和近期状态均无稳健经济支持。拆成赢/亏幅度使训练更少且极端样本影响大，错误概率仍可能支配结果；非线性可能加重过拟合。已见开发池反复选择，不是封存验证。',
      'original_four_hard_gates_changed':False,'new_economic_hard_gates':False,
      'fixed_design':{'axis':'原1635T、原14列、原h4扣费HFQ OPEN标签，完全复用EX084的成熟年度训练支持',
          'labels':'Open[T+5]/Open[T+1]*.999/1.001-1；y>0为盈利，y<=0非盈利；幅度分别y和-y，不丢零值',
          'models':'确认单列/原14各自正/非正幅度，4模型×2021–2026=最多24新拟合；12原盈利概率模型及5净表达精确复用EX084，非新拟合',
          'ranks':'以本年完整成熟训练的各列ECDF中点秩-.5为共同坐标，不按赢/亏子集重新标定秩；确认用列8，14用全部原列',
          'objective':'eta=intercept+x*slope，正均值exp(eta)。最小化sum(eta+m*exp(-eta))+.5*10*||slope||²。固定alpha10，不惩罚截距；不是对数幅度回归，不用后验截断。',
          'numerical':'100 Newton steps /40 Armijo backtracks /maxgradient<=1e-10；不收敛/非有限/全零幅度组显式拒绝，无模型兜底、epsilon或预测裁剪',
          'training':'2020<=signalyear<testyear，label_end严格早于本年首T，原14完整、target有限，至少40且正/非正各20，日期与EX084逐条一致，不用未来年度测试数量做门',
          'economic':'保持旧概率p，新的净期望=p*G(x)-(1-p)*L(x)，仅>0选择；历史幅度映射为配对控制，无概率阈值/方向/期限/alpha扫描',
          'primary':'两族各盈利幅度/非盈利幅度MSE增量、净MSE相对固定幅度、选中净均值及相对固定幅度均值差，共10项；原控制和全年度/相位/时钟完整呈现',
          'clocks':'EX083原贪心和i%5五组，7净表达×6时钟=42；不选最好组，不替代32标准扰动或原生账户',
          'bootstrap':'同一原1635T轴500次重叠40日块seed13，预测固定不重拟合；原始/重抽样至少20、至少400有效、LINEAR95CI；10项全部留证，非未来概率/未经研究历史及多重比较校正',
          'quantities':list(definition.QUANTITIES),'forecast':'2020无预测，尾部缺truth仍以已知原特征预测；无最新数据或扩展2019标签'},
      'scope':'原510500.SH已见开发池，原HFQ锚点、无现金分红叠加，原资金、费用、整手及1%合同；0新账户/provider/市场数据',
      'stopping':'本轮仅信息机制。若经济余量或下跌年份支持不足，完整保留反证并停止固定条件幅度路线；有一致支持才用剩余额度进入账户/最新五自检，不把胜率/MSE设为新硬门。',
      'source_files':{name:d.digest(ROOT/name) for name in sources},
      'input_references':{'features.csv':previous['input_references']['features.csv'],'labels.csv':previous['input_references']['labels.csv'],
          'prices.csv':previous['input_references']['prices.csv'],'prior_probabilities.csv':refs84['probabilities.csv'],
          'prior_forecasts.csv':refs84['forecasts.csv'],'prior_statistics.json':refs84['statistics.json'],
          'prior_verification.json':refs84['verification.json'],'prior_review.json':refs84['root_review.json'],
          'prior_budget.json':refs85['budget_receipt.json'],'previous_round_review.json':refs85['root_review.json']},
      'clock_source':clock,'clock_audit_source':clock_audit,'continuation_budget_reference':previous['continuation_budget_reference'],
      'predecessors':previous['predecessors'],'report_copy':previous['report_copy'],
      'resources':{'new_annual_models_maximum':24,'reused_probability_models':12,'new_accounts':0,'provider_calls':0,'schedules':42,'bootstrap':500},
      'objective_achieved':False}
d.check(plan)
d.write(d.WORK/'prospective.json',plan)
print({'status':plan['status'],'slot':8,'annual_models_maximum':24,'accounts':0})
