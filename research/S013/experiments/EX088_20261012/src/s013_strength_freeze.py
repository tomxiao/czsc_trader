"""EX088 prospective causal entry strength, final authorized experiment."""
from pathlib import Path
import sys

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
sys.path.insert(0,str(ROOT/'.tmp'))
import s013_strength_driver as d

checks=d.read(d.WORK/'focused_checks.json')
assert checks['status']=='PASS' and checks['real_inputs']==0
for name,expected in checks['files'].items():
    assert d.digest(d.WORK/name)==expected
p87=ROOT/'research/S013/experiments/EX087_20261012/protocols'
assert d.read(p87/'delivery_validation.json')['status']=='PASS'
previous=d.read(p87/'plan.json')
refs87=d.read(p87/'closeout_references.json')
definition=d.base.load('strength_prospective_definition',d.WORK/'kernel.py')
clock,clock_audit=previous['clock_source'],previous['clock_audit_source']
duplicate={'status':'TARGETED_DUPLICATE_REVIEW','older_confirmation_change':'EX010 replaces score absolute level with one-day rise/fall of raw confirmation score; not net economic forecast or same input/clock',
           'older_two_day_wait':'EX017 raw bull/bear state entry/exit confirmation; not predicted economic intensity or local record',
           'new_difference':'Original14 probability+conditionalgain has EX087 selected net increment; causal local record of actually issued net forecast over h4 conflict span has not been tested by those controls',
           'repeated_CF_warning':'Confirmation-only forecasts are functions of original score and annual coefficients, so not new independent market information; retain as control, no universal novelty claim',
           'source_reports':{name:d.digest(ROOT/name) for name in ('research/S013/deliveries/CANDIDATES/7/report.md','research/S013/deliveries/CANDIDATES/13/report.md','research/S013/deliveries/COMPONENTS/21/report.md')},
           'exhaustive_universe_claim':False,'synthetic_technical_repairs':'Before real inputs: pandas copy-on-write array explicitly copied; mixed bool/NaN prefix comparison uses dataframe equality; no scientific formula changed.'}
d.write(d.WORK/'duplicate_review.json',duplicate)
sources=['.tmp/s013-entry-strength/'+name for name in ('kernel.py','audit.py','focused_checks.py','focused_checks.json','duplicate_review.json')]
sources+=['.tmp/s013_strength_driver.py','.tmp/s013_strength_freeze.py','.tmp/s013_build_strength_audit.py',
          '.tmp/s013_confirm_execution.py','research/S013/experiments/EX058_20261011/src/common.py',
          'research/S013/experiments/EX087_20261012/src/audit.py',clock,clock_audit]
plan={'status':'ROOT_FROZEN_BEFORE_REAL_STUDY','role':'RSCH','stage':2,'quota_slot':10,
      'authorization':'原自主研究和EX079–EX088十轮额度；EX088收尾后暂停，不启动EX089；每实验保存正式报告副本',
      'question':'有净选择增量的概率+赚幅预测，按已知强度提高入场选择是否改善机会占用和下跌年经济余量？',
      'basis':'EX087原14概率背景加入赚幅选中均值改善0.1825pp且条件性区间正，贪心选中均值0.1158%不及被占用的0.1813%；确认对照关系相反。需检验因果可得强度，不事后选好相位或假设被错过都更好。',
      'strongest_prior_counter':'EX010分数改善及EX017等待已暴露收益/频率代价。净预测强度可能只是更高波动、模型年度更新或旧确认变化重表达；先等强度可能错过好机会、减少数量，不保证未来四日最强预测。',
      'original_four_hard_gates_changed':False,'new_economic_hard_gates':False,
      'fixed_design':{'inputs':'仅EX087两族110原概率+赚幅净预测，精确复用，0新拟合、0标签/市场数据扩展',
          'gate':'当前净预测严格>0并严格高于此前4个实际交易T已发布预测的最大值；必须当前和此前完整4个都有限，不足不入场。过去窗口排除当前T、不用未来4天、等于不通过。',
          'lookback_basis':'固定4对应当前入场后四日期限将占用的后续决策跨度，只是因果强度代理，不保证未来竞争预测更差；无窗口/阈值/方向扫描。',
          'controls':'每族保留历史原控制、需要相同过去4完整支持的匹配控制、record4。历史原控制与EX087所有时钟精确一致；比较门作用以匹配控制为主，不把删除暖启动4T当增量。',
          'interpretation':'原净预测不变；decision_scores只为时钟资格适配器，拒绝时0是拒绝标记而非新预测回报，缺完整信息为NaN，不用0作缺失兜底。无新预测MSE统计。',
          'annual_boundaries':'跨年继续用当时实际发布的预测，不年度重置、不用新模型回填旧T；保存年模型切换标记，可能跳变为反证。',
          'labels':'原h4扣费HFQ OPEN标签Open[T+5]/Open[T+1]*.999/1.001-1，2020无预测、尾部缺truth仍保留决策。',
          'primary':'两族各门后选中净均值/相对匹配差、门后贪心净均值/相对匹配贪心差/相对被占用正机会差，共10预先固定；数量、全年度、五相位、所有时钟完整报告，不按一个正值取舍。',
          'quantities':list(definition.QUANTITIES),
          'clocks':'冻结EX083原贪心和i%5五组，两族各3表达×6=36时钟，h4/冷却不变；不选好相位、非标准32点。',
          'bootstrap':'原1635T轴500次重叠40日块seed13，固定实际门和全窗时钟选择，不在拼接块重新模拟时钟；至少20样本、400有效，LINEAR95CI，未校正研究历史和多重比较。',
          'frequency':'原频率硬门按完整1636账户执行T至少110实际闭合交易；本轮机会意图数仅供给诊断，不替代成交/账户频率。'},
      'scope':'原510500已见开发池/HFQ固定锚/无现金分红叠加/原资金费用整手/1%合同；不动平台、PTE或生产',
      'stopping':'没有一致经济支持则停止本固定强度路线；如有新增一致经济依据，可在同EX088另冻结原生账户对照计划后验证，中心四门通过才做最新五自检；不强行用账户填额度。全部收尾后按用户额度暂停，不称目标达成。',
      'source_files':{name:d.digest(ROOT/name) for name in sources},
      'input_references':{'labels.csv':previous['input_references']['labels.csv'],'prices.csv':previous['input_references']['prices.csv'],
          'scores.csv':refs87['forecasts.csv'],'prior_statistics.json':refs87['statistics.json'],'prior_verification.json':refs87['verification.json'],
          'prior_review.json':refs87['root_review.json'],'prior_plan.json':refs87['plan.json'],'prior_budget.json':refs87['budget_receipt.json']},
      'clock_source':clock,'clock_audit_source':clock_audit,'continuation_budget_reference':previous['continuation_budget_reference'],
      'predecessors':previous['predecessors'],'report_copy':previous['report_copy'],
      'resources':{'new_annual_models':0,'component_new_accounts':0,'provider_calls':0,'schedules':36,'bootstrap':500,
                   'native_followup':'Only if supported after review; new prospective account plan required within EX088 before any account'},
      'objective_achieved':False}
d.check(plan)
d.write(d.WORK/'prospective.json',plan)
print({'status':plan['status'],'slot':10,'new_annual_models':0,'component_accounts':0})
