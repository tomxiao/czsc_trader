from dataclasses import replace
from datetime import date
import json
from pathlib import Path
from czsc_trader.application import publish_evidence, assemble_delivery, validate_delivery
from czsc_trader.research_tools import MaterialEvidenceWrite, EvaluationEvidenceWrite
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.context import ExperimentRef
from common import ROOT, BASE, context, request, save, cache_write, PROTOCOLS
from economics import summarize
from search import configuration_hash


def main():
    research = context()
    experiment = ExperimentRef('S013', 'EX004_20261007')
    confirmation = {
        'date': '2026-10-07', 'source': '本主会话用户原文',
        'messages': ['批准，请你主导推进阶段三', '价格使用后复权口径，就不需要考虑派息的收益了',
                     '批准DEV补齐口径后重跑S013（推荐）',
                     '还要考虑SRT在PTE决策链路中，仍然需要输出未复权价格',
                     '我选择方案A，100表示100个研究单位', '继续使用当前 codex/s013-research'],
        'decision': '采用后复权研究账户；100个研究单位整手；PTE固定使用未复权价格和真实份额',
        'platform_commit': '9caede79', 'focused_test_nodes_passed': 95,
        'full_regression': '本轮未请求，未执行',
    }
    auth = publish_evidence(research, MaterialEvidenceWrite(experiment, 'hfq-user-confirmation',
        json.dumps(confirmation, ensure_ascii=False, indent=2).encode(), 'application/json', 'json'))
    save('authorization_reference.json', auth.to_dict(), directory=PROTOCOLS)
    old = json.loads((ROOT / 'research/S013/assets/deliveries/MANDATE/2/delivery.json').read_text(encoding='utf-8'))
    content = d.DeliveryContent.from_dict(old['content'])
    confirmed = d.ConfirmationRecord(d.ConfirmationStatus.CONFIRMED, auth)
    statements = {
        'lot_size': '100个研究单位整手；研究单位不解释为始终相同的真实ETF份额',
        'cost': '每侧成交额10bp（0.1%），费用、现金和净值统一使用后复权研究价格',
        'benchmark': 'BuyHold相同后复权价格、归一化锚点、研究单位、期间、费用及资金；首个可执行交易日开盘买入并持有，期末不人为卖出',
    }
    items = tuple(replace(item, statement=statements[item.item_id], confirmation=confirmed)
                  if item.item_id in statements else item for item in content.payload.items)
    items += (d.MandateItem('price_basis', d.MandateItemKind.EXECUTION,
        '后复权研究价格=原始价格×当日复权因子÷开发池前最后一个已可用交易日的因子；同一锚点贯穿全池及逐年账本，按供应商复权口径计入权益影响，不重复添加派息；PTE保持未复权价格和真实份额', confirmed),)
    predecessor = d.DeliveryReference.from_dict(json.loads(
        (ROOT / 'research/S013/materials/stage1_mandate_reference_r2_20261007.json').read_text(encoding='utf-8')))
    report = '''# S013研究约定修订三：后复权研究账户

用户已选择方案A，100表示100个研究单位。策略与BuyHold使用同一归一化后复权价格账户，费用、成交金额、现金、持仓估值及收益保持同一单位。PTE继续按未复权价格及真实ETF份额决策。

标的510500.SH、开发池2020-01-01至2026-09-30、100万元资金、每侧10bp、T信息可得后T+1执行、只做多及不加杠杆沿用已确认约定。净年化至少为BuyHold的1.5倍；每个自然年最大回撤幅度严格小于该年BuyHold；1636个实际交易日内至少110笔闭合交易。2026年只评价至9月30日，现金和持仓跨年连续。

归一化锚点取开发池前最后一个已可用交易日，价格乘当日因子除锚点因子。因子来源与原始/HFQ行情身份进入评价契约；研究单位含供应商复权处理所对应的经济敞口，不另行加入重复派息收益。该账户是研究模型，不能直接视为PTE真实份额账户收益。

原始价格网格上形成T日参考限价，再按T日因子转换研究价格；T+1按同口径历史行情撮合。限价使用T日收盘参考，而非提前读取T+1开盘价。该说明修正旧阶段三协议的文字描述，旧证据原件保留。

EX004重算既有270个独立配置，以新账本重新计算BuyHold、逐年回撤与达标结果。阶段二组件定义及同标的最小必要历史权限沿用。整个指定窗口已经用于研究和选择，逐年比较不构成独立样本外验证；供应商因子历史发布日期与修订未得到重建。
'''
    receipt = assemble_delivery(research.repository,
        d.DeliveryDefinition(research.batch, d.DeliveryStage.MANDATE, 3, (predecessor,)),
        d.DeliveryContent(d.ResearchMandate(items), d.DeliveryStatus.COMPLETE, (), (),
                          report=report, evidence=(auth,)))
    validation = validate_delivery(research.repository, receipt.reference)
    save('mandate_reference.json', receipt.reference.to_dict())
    save('mandate_validation.json', validation.to_dict())
    protocol = '''# S013阶段三后复权重算协议

前驱MANDATE/3和COMPONENTS/1。仅S013和510500.SH；复用既有Tushare/DFLS及已安装依赖。
先重算旧口径全部270个独立成功配置，旧收益阈值与旧排名不参与新达标判定；再基于新结果进行有依据的局部反证及扩边。使用Optuna管理评价及采样、种子13、最多8个spawn进程、每进程1原生线程、单请求workers=1。
采用100个研究单位整手，100万元，单侧10bp。价格在开发池前最后交易日归一化，账户保持1636日连续；BuyHold同口径开盘买入并持有。按完整净年化、逐自然年严格回撤、每60交易日平均闭合次数三项同时核验，最低110笔闭合。
特征仍来自T日17:00可用的后复权日线；限价根据T日未复权收盘参考加20bp，原始报价网格取整后转换为研究价格，再在T+1历史研究行情撮合；卖出市价。计划形成时不读取下一交易日复权因子或开盘价。
旧EX003原件不改动。新结果使用新实验、新账户与证据身份。整个窗口用于开发；实际份额交易与复权研究单位存在差异；因子历史发布时间及修订未重建。年度回撤是用户硬门，其他诊断不增加经济否决条件。
'''
    (PROTOCOLS / 'protocol.md').write_text(protocol, encoding='utf-8', newline='\n')
    proto = publish_evidence(research, MaterialEvidenceWrite(experiment, 'hfq-stage3-protocol',
        protocol.encode(), 'text/markdown', 'md'))
    save('protocol_reference.json', proto.to_dict(), directory=PROTOCOLS)
    bound = research.evaluation.prepare(request(1, BASE))
    result = research.evaluation.evaluate(bound)
    cache_write(ROOT / '.tmp/s013-stage3-hfq/precheck.pkl.gz', (bound, result))
    row = {'candidate_id': 'C0001', 'parameters': BASE, 'config_hash': configuration_hash(BASE),
           'search': 'hfq_initial', 'trial': 0, 'status': 'SUCCEEDED', **summarize(result)}
    save('search_results.json', {'rows': [row]})
    ev = publish_evidence(research, EvaluationEvidenceWrite(experiment, 'hfq-initial-range-account', bound, result))
    save('initial_account_reference.json', ev.to_dict())
    print(json.dumps({'mandate': receipt.reference.to_dict(), 'validation': validation.to_dict(),
        'pricing': bound.execution_data.pricing.to_dict(),
        'baseline': {k: row[k] for k in ('net_cagr', 'buyhold_cagr', 'return_threshold', 'closed_trades', 'gates')},
        'evidence': ev.to_dict()}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
