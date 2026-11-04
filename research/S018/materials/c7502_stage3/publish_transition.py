"""Publish the C7502 prototype and the user's actual stage-three approval.

Reuses immutable accounts; performs no evaluation or candidate registration.
"""
from pathlib import Path
from hashlib import sha256
import json

from czsc_trader import research_tools as d
from czsc_trader.application import (
    RepositoryContext, create_research_context, publish_evidence,
    assemble_delivery, record_research_decision,
)
from dataflows import ProviderConfig
from strategy_manager import CandidateKey, CandidateEvidence
from strategy_manager import freeze_contracts as f
from strategy_runtime.equity_definition import (
    EquityStrategyDefinition, EquityStrategyCandidate, execution_spec_from_dict,
)


def main():
    root = Path.cwd()
    work = root / 'research/S018/materials/c7502_stage3'
    read = lambda p: json.loads(p.read_text(encoding='utf-8'))
    repo = RepositoryContext.discover(root)
    batch = d.ResearchBatchRef('S018')
    folders = {n: root / f'research/S018/experiments/EX{n:03}_20261104' for n in (45, 47)}
    results = {n: read(p / 'others/results.json') for n, p in folders.items()}
    refs = {n: {r['name']: d.EvidenceRef.from_dict(r) for r in read(p / 'others/evidence_refs.json')}
            for n, p in folders.items()}
    context = create_research_context(repo, batch,
        providers=ProviderConfig(bindings={}, equity_bindings={}),
        execution_spec=execution_spec_from_dict(results[45]['accounts']['C7502']['definition']['execution_spec']))
    owner = d.ExperimentRef('S018', 'EX045_20261104')
    def material(name, payload):
        return publish_evidence(context, d.MaterialEvidenceWrite(owner, name,
            (json.dumps(payload, ensure_ascii=False, indent=2) + '\n').encode('utf-8'),
            'application/json', 'json'))

    authorization = {
        'record_kind': 'actual_user_message', 'recorded_date': '2026-11-04',
        'message': '同意C7502推进至阶段三',
        'subject': 'C7502', 'target_stage': 'CANDIDATES',
        'scope': '承接 C7502 原型，在既有数据、窗口、D、硬约束与执行合同内开展阶段三优化；保留三日试探作为原型对照。',
        'budget_basis': '既有30轮授权使用16轮，剩余14轮；本次交付与批准记录不运行账户、不消耗实验轮次。',
        'exclusions': ['不授权阶段四、自检选型或冻结', '不授权新增财报或其他外部数据范围'],
    }
    (work / 'user_approval.json').write_text(json.dumps(authorization, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    approval = material('C7502-stage3-user-approval', authorization)
    selected = [(45, x) for x in ('C7501', 'C7502', 'C7503', 'C7505', 'C7508')]
    selected += [(47, x) for x in ('C7703', 'C7704')]
    definitions = {}
    evidence = [approval]
    for n in (45, 47):
        evidence.extend(refs[n][k] for k in ('protocol', 'results', 'data_preparation', 'source-strategy', 'source-run'))
        evidence.append(d.EvidenceRef.from_dict(read(folders[n] / 'report_ref.json')['report']))
    evidence.append(refs[47]['analysis_exit_comparison'])
    for n, cid in selected:
        definition = EquityStrategyDefinition.from_dict(results[n]['accounts'][cid]['definition'])
        candidate = EquityStrategyCandidate('S018', cid, definition, folders[n] / 'src')
        candidate.verify()
        definitions[cid] = (candidate, material('prototype-definition-' + cid, candidate.payload))

    sector_test = d.ComponentTestResult('sector-complement', 'EX045_20261104', refs[45]['protocol'],
        d.ComponentTestStatus.SUPPORTED,
        '共同贡献主导组在相同退出下优于个股剩余贡献主导组；支持开发依据，不能证明因果或未来稳定性。',
        tuple(refs[45][x] for x in ('C7502', 'C7503', 'C7505', 'C7508')))
    exit_test = d.ComponentTestResult('exit-interaction', 'EX045_20261104', refs[45]['protocol'],
        d.ComponentTestStatus.SUPPORTED,
        '三日起以信号价决定续持、六日上限的组合优于固定三日与固定六日；代理期限仍需阶段三优化。',
        tuple(refs[45][x] for x in ('C7502', 'C7505', 'C7508')))
    failure_test = d.ComponentTestResult('early-failure-counterevidence', 'EX047_20261104', refs[47]['protocol'],
        d.ComponentTestStatus.INEFFECTIVE,
        '按持仓后个股剩余收益转负提前退出压缩后续修复盈利，卡玛降至0.880；行业修复提前兑现也未提高原型卡玛。',
        tuple(refs[47][x] for x in ('C7502', 'C7703', 'C7704', 'analysis_exit_comparison')))
    common_definition = d.ExperimentDefinitionRef(definitions['C7502'][1], 'strategy:step')
    components = (
        d.ComponentEntry('sector-entry', common_definition, '入场条件', '行业共同卖压识别',
            '最近两日；beta使用此前60日收益', '相同两连跌的全样本及剩余贡献主导组',
            '完整日线收盘后、下一交易日执行', 'MU/SOXX HFQ；账户RAW',
            '仅已见MU开发池', '有开发依据，机会供给和持仓占用限制频率', (sector_test,)),
        d.ComponentEntry('repair-holding', common_definition, '持有与退出', '三日试探、信号线续持、六日上限',
            '实际入场后3至6个交易日', '固定3日、固定6日、提前失败与修复兑现',
            '完整日线收盘后判断并于下一交易日退出', '信号价HFQ，成交及计价RAW',
            '仅已见MU开发池', '支持保留为优化起点，不要求废除三日试探', (exit_test, failure_test)),
    )
    prototypes = []
    for n, cid in selected:
        candidate, definition_ref = definitions[cid]
        config = results[n]['accounts'][cid]['config']
        prototypes.append(d.PrototypeEntry(
            cid, d.CandidateIdentityRef(CandidateKey('S018', cid), candidate.content_identity.content_sha256),
            d.ExperimentDefinitionRef(definition_ref, 'strategy:step'),
            '行业共同卖压可能较个股特有走弱更容易修复；本条配置为 ' + json.dumps(config, ensure_ascii=False),
            (d.PrototypeComponentUse('sector-entry', '识别或对照入场机会', '比较行业分解条件的增量'),
             d.PrototypeComponentUse('repair-holding', '兑现与资金周转对照', '比较修复时间及提前退出的代价')),
            (d.EvaluationEvidenceRef(refs[n][cid]),),
            d.PrototypeDisposition.DEVELOP if cid == 'C7502' else d.PrototypeDisposition.INVESTIGATE,
            '用户已批准作为阶段三主原型' if cid == 'C7502' else '仅保留同合同机制与负面对照，未选择为阶段三主原型',
            ('开发池重复使用，不是独立验证', '行业分解是统计假设，不代表因果确认',
             'C7502双频率不达标；三日试探未增加即时止损'),
            '阶段三联合优化机会利用、持有与风险收益' if cid == 'C7502' else '作为阶段三解释和比较依据',
            (definition_ref, refs[n]['source-strategy'], refs[n]['source-run'], refs[n]['results'])))
    comparisons = []
    for n, control, question, conclusion in (
        (45, 'C7501', '行业入场过滤的收益与代价是什么', '卡玛提高且回撤降低，但63笔较93笔少，双频率失败'),
        (45, 'C7503', '共同卖压与个股剩余走弱是否等价', '互补组卡玛0.845，明显低于主原型4.164'),
        (45, 'C7505', '缩短固定持有能否解决频率', '仅多1笔闭合，频率仍失败，卡玛2.666'),
        (45, 'C7508', '延长固定持有能否保留收益并控险', '回撤33.88%，卡玛2.070，资金占用更重'),
        (47, 'C7703', '即时剩余收益失效能否改善风险收益', '提前退出切断后续盈利，卡玛0.880'),
        (47, 'C7704', '行业修复提前兑现能否改善原型', '卡玛3.329，频率仍失败，未优于主原型'),
    ):
        comparisons.append(d.PrototypeComparison('C7502-vs-' + control, 'C7502', control,
            question, refs[n]['protocol'], (refs[45]['C7502'], refs[n][control]), conclusion))

    table = ['|配置|净年化|最大回撤|净卡玛|闭合笔数|60日中位数|覆盖率|', '|---|---:|---:|---:|---:|---:|---:|']
    for n, cid in selected:
        m = results[n]['accounts'][cid]['candidate']
        table.append(f"|{cid}|{m['annual']:.2%}|{m['dd']:.2%}|{m['calmar']:.3f}|{m['closed']}|{m['median']:.0f}|{m['coverage']:.2%}|")
    report = '''# C7502 原型交付与阶段三承接

## 决定与范围

用户在当前会话明确批准：“同意C7502推进至阶段三”。承接 C7502 开展以达标为目的的优化。阶段二原型依据充分和策略已经达标是不同判断：C7502 经济门通过、双频率失败，已有依据支持进入优化。

保持原开发池 2023-01-03—2026-10-30、2022 年预热、MU 单标的只做多、不加杠杆、MU/SOXX 已授权 HFQ 观察及 RAW 执行。日线完成后次日执行；买限价为上一日原价收盘×1.01并按0.01向下取整，严格触价；市价卖出、整数股、每侧0.1%成本、零额外滑点、初始10万美元。原D为净卡玛，要求至少同合同买持的1.5倍（2.9306183684303985）；最大回撤不高于25%且不高于买持80%；完整60交易日闭合中位数至少6、至少90%窗口有3笔闭合。未新增十月盈亏、逐年盈利或必须取消试探期等硬门。

既有30轮额度使用16轮，剩余14轮用于授权范围内的后续研究。本次只整理既有账户和确认依据，不新增实验。没有新增财报数据、封存样本或阶段四权限。

## 原型函数与金融解释

令 m_t=ln(P_t/P_{t-1})、s_t=ln(Q_t/Q_{t-1})，P、Q为MU和SOXX后复权收盘。beta以t−61至t−2的60个收益率协方差除行业收益方差估计，不含最近两日，无截距或beta截断。G=beta×(s_{t-1}+s_t)，R=m_{t-1}+m_t−G。空仓时仅在P_t<P_{t-1}<P_{t-2}且G<R入场。参数为entry=common、exit=signal_line，完整定义和依赖随条目显式发布。

入场使用全部可用现金；持仓期间维持原有股份，不逐日补仓。anchor是生成实际入场的信号日HFQ收盘价。持有日数不足3时保持持仓；第3至5日仅在收盘高于anchor时继续持有，否则发退出决定；第6日最迟发退出决定，均下一交易日执行。未成交不启动持有计时。三日试探仍在，没有即时止损；anchor也不是买入含费成本。

两日总收益为负时，G<R等价于行业共同负贡献超过总负收益一半。经济假设是行业共同卖压可能具有修复性，而个股特有走弱更可能持续；统计分解支持对照研究，但不能证明卖压来源、均衡价值或未来修复。R不必为负，beta不必为正，也未要求原先处于上涨趋势。三日、六日是等待修复和限制占用的代理期限，尚非已证实的经济常数。

## 同合同账户与组件作用

''' + '\n'.join(table) + '''

C7501为同退出但不过滤行业贡献的两连跌HFQ基线，其与原C6300经济结果一致。C7503是C7502的互补入场组。C7505和C7508分别固定三日、六日退出。C7703在持有后个股剩余收益转负时提前退出；C7704在行业价格修复时提前兑现。正式账户直接列入强类型交付，不以汇总JSON替代。

共同卖压组在固定三日、固定六日和信号线退出下均优于对应剩余贡献主导组，支持行业入场信息的用途。信号线续持使部分回落后修复得以发展，固定短持有并未明显增加闭合数，固定长持有则恶化回撤。EX047配对分析显示，C7502与C7703的61笔共同入场中44笔提前退出，其中23笔原本后来盈利，10笔被改为非正；这23笔平均交易收益差约−9.15个百分点。提前退出并非自动更安全或更高效。

## 最强反证与优化问题

C7502净卡玛4.164、回撤18.26%具有优化余量，但60日交易中位数4、覆盖81.49%明确未达标。收益集中于部分时期，2024年约−0.26%；十月2日至15日观察段约−12.74%。这表明行业共同下跌仍可持续，入场逻辑更有依据不能解释为风险消失。全部为反复使用的开发证据，不能宣称样本外有效。

阶段三首先区分可交易信号不足、重叠信号、未成交及持仓占用，再在原D与硬约束内联合优化入场筛选、机会利用和持有期限。保留C7502完整配置和既有基线作为对照；不把取消三日试探设成前提，也不把放宽到原基线后达标误称为行业识别增益。保留全体配置、负面结果与选择历史。阶段三成果完成后再请用户批准后续阶段。

本交付COMPLETE表示原型与授权整理完成，不表示C7502频率达标或阶段四稳健性检查通过。实现恢复使用条目定义、同名source-strategy材料及明确依赖；公开接口发布时核验来源与账户身份。报告路径均相对研究批次，精确材料由引用定位。
'''
    (work / 'prototype_report.md').write_text(report, encoding='utf-8')
    evidence.append(publish_evidence(context, d.MaterialEvidenceWrite(owner, 'C7502-transition-source',
        Path(__file__).read_bytes(), 'text/x-python', 'py')))
    content = d.DeliveryContent(d.PrototypePanel(tuple(prototypes), components, tuple(comparisons),
        'C7502具备继续发展的原型依据；用户批准阶段三优化，原经济与频率门槛不变。'),
        d.DeliveryStatus.COMPLETE, (), (), report=report, evidence=tuple(dict.fromkeys(evidence)))
    assembled = assemble_delivery(repo, d.DeliveryDefinition(batch, d.DeliveryStage.PROTOTYPES, 1), content)
    receipt_path = root / 'research/S018/deliveries/PROTOTYPES/1/receipt.json'
    receipt_ref = CandidateEvidence(receipt_path.relative_to(root).as_posix(), sha256(receipt_path.read_bytes()).hexdigest())
    approval_path = work / 'user_approval.json'
    decision = record_research_decision(repo, f.ResearchDecision(
        'C7502-STAGE3-20261104', 'S018', f.DecisionAction.APPROVE,
        f.StageAdvanceSubject(receipt_ref, 'CANDIDATES'),
        CandidateEvidence(approval_path.relative_to(root).as_posix(), sha256(approval_path.read_bytes()).hexdigest()),
        '用户明确批准C7502推进至阶段三；承接原型，保持原目标、硬约束和授权数据范围。'))
    output = {'delivery': assembled.receipt.reference.to_dict(), 'validation': assembled.validation.to_dict(),
              'decision': decision.to_dict(), 'new_account_runs': 0, 'experiment_rounds_consumed': 0}
    (work / 'transition_receipt.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(output, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
