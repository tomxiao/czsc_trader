"""Root scientific review of the completed fixed centre; no new account."""
import importlib.util
import json
from pathlib import Path
import sys
from czsc_trader.research_tools import delivery as types

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'.tmp/s013-price-event-binding-r2'
OLD=ROOT/'.tmp/s013-price-event-policy'
spec=importlib.util.spec_from_file_location('price_event_review_driver',WORK/'technical_driver.py')
w=importlib.util.module_from_spec(spec);sys.modules[spec.name]=w;spec.loader.exec_module(w)
d=w.d;exp,plan,path=w.stage();c=d.common();ctx=c.context(1)
audit_ref=d.read(path/'protocols/verification_reference.json')
audit=d.read(d.public(audit_ref));economic=audit['economics']
math_refs=d.read(path/'protocols/independent_policy_references.json')
assert d.read(d.public(math_refs['verification']))['status']=='PASS'
assert economic['gates']=={'return':False,'annual_drawdown':True,'frequency':False,'negative_buyhold_year_profit':True}
baseline,baseline_ref,cache=d.native()
assert d.digest(cache)==plan['baseline_cache_sha256']
helper=d.load('price_event_review_economics',d.GENERAL/'economics_reference.py')
baseline_economics=helper.economic_native(*baseline)
refs={'plan.json':d.read(path/'protocols/plan_reference.json'),'native.json':d.read(path/'protocols/centre_reference.json'),'independent_audit.json':audit_ref,'mathematical_audit.json':math_refs['verification'],'baseline_native.json':baseline_ref}
conclusion='固定价格周期政策在2022/2023盈利且年度回撤达标，但年化7.8887%低于10.8290%、78闭合交易少于110；停止这条固定政策，无新合格候选，尚未达成硬门达标且抗扰动能力强的总体目标。'
report='''# EX077：统一价格周期政策的单中心检验

固定政策在下跌年份可以盈利，但没有同时解决整体收益和交易频率。它不是新的达标候选，研究目标尚未达成。

规则为：价格从已知高点回落后等待恢复再买入，持有后按回撤退出；整个周期使用触发时锁定的波动幅度。只检验预先固定的L20/k1，未优化参数。

| 原硬门 | 本次结果 | 判断 |
|---|---:|---|
| 整体净年化至少买入持有的1.5倍 | 7.8887%，要求10.8290% | 未达标 |
| 每自然年回撤严格小于买入持有 | 七个年份均满足 | 达标 |
| 平均每60交易日至少4笔闭合交易 | 2.8606笔；全区间78笔，至少需要110笔 | 未达标 |
| 买入持有亏损年份策略严格盈利 | 2022 +1.9082%；2023 +1.2940% | 达标 |

全区间最大回撤18.6261%。2026年截至9月30日策略收益−13.2460%，同期买入持有+0.9947%；这说明下跌年份盈利和年度回撤过门，仍可能伴随其他年份较大的收益损失。

原C8880账本经身份核验后复用：净年化17.1346%、全区间回撤13.6187%、116笔闭合交易。新政策的2023年收益比原中心+0.9181%略高，但整体收益、全区间回撤和交易频率都更差，不能据此称为改进。

本次证据支持“减少规则也能保留下跌年份盈利”的有限观察，不支持“规则简单就会更稳健”。固定中心已失败，按事前停止规则不扫L/k、不增加过滤或持有上限，也不运行32扰动及双费账户。新政策的收益Q10、回撤Q90和完整五项自检均未取得，不能与旧13维扰动逐点配对。仅报告中心正收益交易前10%利润占比54.2313%，不把它当作新增硬门。

只新增一个完整账户；旧基准比较不重算账户。政策状态、原生意图、逐笔订单/成交、费用、现金、持仓、连续年度边界及四门已独立核验。额外数学核验覆盖1636信号日、12字段、6099数值比较，状态和目标精确一致。

准备阶段因新的日历请求身份无法命中旧资产而失败，禁止访问设置拦住了一次provider尝试，没有取新数据或运行账户。技术修订恢复C8880原日历及180日预热的精确请求，保留最低121观察及完整L2..120域；额外预热不初始化状态，政策字节和参数不变。初始C9077保留，新适配实现使用C9078身份，同一EX077没有再次分配。后复权、资金、费用、1%买入合同和执行日期均保持原口径。

同一开发池已经反复使用，存在选择偏差；未使用封存样本。SRT运输时间及Timestamp证据按日期序列化的限制单独披露，不能把运输字段当作T17数学时钟。原OHLC异常保持原样，成交按原生盘中首次触价核验。本实验不能证明所有价格机制无效或原目标不可能。

下一步应围绕“哪些因果可知条件能带来足够的扣费盈利机会”研究独立组件，分别报告机会数量与每笔收益余量；不能用强行提高交易次数或继续修补失败的固定政策代替证据。当前保留原合格候选资格，不冻结、不投入PTE。
'''
identity=types.CandidateIdentityRef(types.CandidateKey('S013',plan['candidate_id']),plan['content_sha256']).to_dict()
review={'status':'ROOT_SCIENTIFIC_REVIEWED','objective_achieved':False,'original_four_hard_gates_changed':False,'candidate_identity':identity,'whole_formal_native_exact':True,'financial_roles':{'centre_new':1,'baseline_reused':1,'standard_new':0,'fee_new':0,'technical_new':0},'economics':economic,'baseline_economics':baseline_economics,'evidence_references':refs,'prospective_plan_sha256':refs['plan.json']['sha256'],'conclusion':conclusion,'report_markdown':report,'fixed_route_status':'STOPPED_AS_PREDECLARED','new_robust_candidate_found':False,'provider_calls_in_review':c.SOURCE_CALLS}
assert not c.SOURCE_CALLS
target=WORK/'root_review.json';d.write(target,review)
reference=d.put(ctx,exp,target)
d.write(path/'protocols/root_review_reference.json',reference)
print(json.dumps({'status':review['status'],'reference':reference,'four_gates':economic['gates'],'baseline_cagr':baseline_economics['net_cagr'],'objective_achieved':False},ensure_ascii=False))
