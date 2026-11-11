"""Open the third authorized development round: seven fixed cost-response pairs."""
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
from czsc_trader import research_tools as d
from czsc_trader.application import (RepositoryContext, create_research_context, create_experiment,
    ExperimentRequest, ResearchIntentUpdate, update_research_intent)
from dataflows import ProviderConfig

ROOT = Path.cwd()
BATCH = ROOT/'research/S019'
TMP = ROOT/'.tmp/s019-stage3-20261111'
OLD = BATCH/'experiments/EX048_20261111'
WORK = BATCH/'experiments/EX049_20261111'


def read(path):
    return json.loads(path.read_bytes())


def save(path,value):
    path.write_bytes((json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode())


def main():
    assert not WORK.exists(), 'Existing experiment requires explicit inspection before recovery'
    recipe = read(TMP/'fee_recipe.json')
    pub = read(OLD/'others/publication.json')
    assert pub['validation']['status'] == 'PASS'
    assert read(OLD/'others/budget_settlement.json')['used_after'] == 2
    intent = read(ROOT/'research/registrations/S019/family.json')['research_intent']
    assert intent['stage'] == 'STAGE_THREE' and not intent.get('active_experiment')
    budget = intent['continuous_stage3_budget']
    assert budget['used_rounds'] == 2 and budget['remaining_rounds'] == 8
    assert budget['rounds'][-1]['experiment'] == OLD.name
    assert recipe['round_budget']['total_round'] == 3
    sources = {'setup.py':Path(__file__),'fee_runner.py':TMP/'fee_runner.py',
        'close_fee_round.py':TMP/'close_fee_round.py','close_stage.py':TMP/'close_stage.py',
        'prepare_fee_recipe.py':TMP/'prepare_fee_recipe.py','prepare_fee_ledger.py':TMP/'prepare_fee_ledger.py',
        'analyze_fees.py':TMP/'analyze_fees.py','fee_ledger.py':TMP/'fee_ledger.py',
        'semantic_audit.py':OLD/'src/semantic_audit.py','strategy.py':OLD/'src/strategy.py'}
    assert all(p.is_file() for p in sources.values())
    old_spec = read(OLD/'protocols/specs.json')
    specs = []
    for pair in recipe['pairs']:
        ref = d.EvidenceRef.from_dict(read(ROOT/pair['standard_account']))
        header = read(ref.resolve(ROOT))
        assert sha256(ref.resolve(ROOT).read_bytes()).hexdigest() == ref.sha256
        assert header['request']['candidate_id'] == pair['candidate_id']
        definition = header['request']['candidate_definition']
        assert definition['state_schema'] == old_spec['state_schema']
        specs.append({'label':pair['label'],'parameters':json.loads(definition['parameters_json'])})
    repo = RepositoryContext.discover(ROOT)
    batch = d.ResearchBatchRef('S019')
    ctx = create_research_context(repo,batch,providers=ProviderConfig(bindings={},equity_bindings={}))
    exp = create_experiment(ctx,ExperimentRequest('连续调仓的费用配对诊断',
        '以少数原型与领先配置解释连续减仓、恢复仓位和参数优化的实际费用反应，决定阶段三后续投入。',date(2026,11,11)))
    assert exp.resolve(ROOT) == WORK
    for name,path in sources.items():
        (WORK/'src'/name).write_bytes(path.read_bytes())
    save(WORK/'protocols/fee_pairs.json',recipe)
    save(WORK/'protocols/specs.json',{'state_schema':old_spec['state_schema'],'specs':specs})
    continuation = {'previous_report':pub['report'],'authorization_decision':budget['authorization_decision'],
        'round_budget':recipe['round_budget'],'recipe_sha256':sha256((TMP/'fee_recipe.json').read_bytes()).hexdigest(),
        'selection_rule':'Common-parameter original exit anchors, highest unrounded standard NAR passing all six gates per family after EX048, plus C0909 as a narrow-width complete-configuration reference.',
        'source_origins':{k:{'path':p.relative_to(ROOT).as_posix(),'sha256':sha256(p.read_bytes()).hexdigest()} for k,p in sources.items()},
        'original_pressure_policy_source':{'path':'research/S019/experiments/EX001_20261110/src/publish_stage1.py',
            'sha256':sha256((BATCH/'experiments/EX001_20261110/src/publish_stage1.py').read_bytes()).hexdigest()},
        'stage_four_advance':False,'standard_accounts_reused':7,'new_pressure_accounts_planned':7,
        'new_shared_buy_hold_accounts_planned':1,'new_parameter_proposals':0}
    save(WORK/'protocols/continuation.json',continuation)
    plan = '''# 新授权第3轮：连续调仓的费用配对诊断

阶段三开发问题：连续目标仓位与恢复仓位改变实际成交，参数优化后提高的收益能否承受原费用压力场景？结果用于决定是否继续完善仓位函数；正式全候选阶段四尚待用户批准。当前两轮已取得中心达标区域和有限参数稳定性证据，本轮用少量完整账户补充可能改变收口决定的成本信息。

事前固定7个代表：共同参数原型C0798（C0720的现源码经济等价控制）、C0801、C0804；截至EX048三族原六门后最高未舍入NAR点C0966、C1010、C1045；可恢复窄退出区间C0909。C0909与领先点有多个参数差异，按完整配置对照；原三族仅退出机制不同。标准账户全部复用，保留原ID/content/definition/source，新增7个相同参数每侧0.2%账户和1个同费用共享买持。7个配置、14个标准/压力场景身份、新策略回放7分别计数。

公共TDR完整账户、同一执行会话及检查点；进程上限12，各1原生线程，本轮7项压力任务并行。当前strategy.py保持EX046原字节。准备后的标准请求与已存请求仅允许实验归属不同；压力只修改费率、场景和测量层级，并核对费用引起的audit输入派生哈希；行情、源定义、时序、初始资金、订单合同保持。7个真实压力账户全部独立语义审计，逐账户基础身份、信号可得性、现金、成交和整数数量核验。

原标准中心六门保持NAR≥55%、Calmar≥5、MDD≤25%且≤同费买持80%、滚动60日闭合中位≥6、至少3笔覆盖≥90%。原压力经济条件为NAR≥50%、Calmar≥4.5、MDD≤25%且严格低于同压力买持；买持MDD为0时策略MDD也须为0。压力频率另列诊断，不追加新硬门。原完整邻域≥80%不变，本轮没有展开完整邻域或全候选自检。

解释采用标准/压力NAR、MDD、Calmar和年度路径、实际成交数、完整周期费用/首次成交时记录权益、成交金额/相同权益以及共同进出场对照。费用绝对金额受资金规模与复利路径影响，归一化比较与完整账户结果共同使用。末端未闭合持仓纳入净值和MDD，闭合周期统计单列。

停止和继续：代表的成本反应与有限敏感性证据连贯，且没有具体值得继续优化的问题时，阶段三收口；发现压力缺口且账本揭示可调整的仓位—退出协作问题时，围绕该问题开展下一轮；仅有泛化的再搜冲动时保留缺口并收口。全部标准中心达标实现继续保留，原六门后NAR排序保持。Optuna用于联合优化；本轮使用固定配对以隔离费用变化，不增加特征提取或拟合工具。

2021预热、2022-01-03至2026-10-30已见开发池；MU/SOXX、HFQ整数模拟单位、10万美元及原限价买入/市价卖出约定保持。新10轮授权第3轮，成功结算后剩7轮；旧授权余额单独保留。
'''
    (WORK/'protocols/plan.md').write_bytes(plan.encode())
    intent.update(active_experiment=exp.to_dict(),active_round_budget={'round':3,'allocated_rounds':10,'remaining_after_completion':7},
        continuous_stage3_status='ROUND_PREPARING',next_action='少数代表费用配对，用实际调仓与完整账户解释成本，再决定优化或阶段三收口。')
    update_research_intent(repo,batch,ResearchIntentUpdate(research_intent=intent),actor='RSCH',
        reason='新10轮阶段三授权内第3轮开发性费用诊断，未推进阶段四。')
    print('FEE_DIAGNOSTIC_OPENED',WORK.name,'round 3','pairs',len(specs))


if __name__ == '__main__':
    main()
