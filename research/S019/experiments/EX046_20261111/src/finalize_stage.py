"""Close the delivered stage-two work while retaining the original goals and budget."""
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader import research_tools as d
from czsc_trader.application import (
    RepositoryContext, ResearchIntentUpdate, get_research_overview, update_research_intent,
)

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'research/RSCH_AGENT.md').is_file())
WORK = Path(__file__).resolve().parents[1]
BATCH = ROOT/'research/S019'


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode())


def main():
    output = WORK/'others/stage_closeout.json'
    assert not output.exists(), 'Inspect existing closeout before any recovery'
    publication = read(WORK/'others/prototype_publication.json')
    assert publication['validation']['status'] == 'PASS'
    delivery = d.DeliveryReference.from_dict(publication['receipt']['reference'])
    assert delivery.stage is d.DeliveryStage.PROTOTYPES and delivery.revision == 3
    assert read(BATCH/'deliveries/PROTOTYPES/3/receipt.json')['reference'] == delivery.to_dict()
    family_path = ROOT/'research/registrations/S019/family.json'
    intent = read(family_path)['research_intent']
    assert intent['stage'] == 'STAGE_TWO'
    assert not intent.get('active_experiment') and not intent.get('active_round_budget')
    budget = intent['joint_search_budget']
    assert budget['used_rounds'] == 8 and budget['remaining_rounds'] == 2
    assert [r['experiment'] for r in budget['rounds'] if r['round'] > 4] == [
        'EX043_20261110', 'EX044_20261110', 'EX045_20261111', 'EX046_20261111']
    counts = []
    for name in ('EX043_20261110', 'EX044_20261110', 'EX045_20261111', 'EX046_20261111'):
        others = BATCH/'experiments'/name/'others'
        data = read(others/('execution.json' if name.startswith('EX045') else 'results.json'))
        assert data['status'] == 'COMPLETE' and data['replay_statistics_complete']
        assert read(others/'publication.json')['validation']['status'] == 'PASS'
        assert read(others/'budget_settlement.json')['status'] == 'SETTLED_ONCE'
        counts.append({'experiment': name, 'candidate_runs': data['workload']['candidate_runs'],
            'benchmark_runs': data['workload']['benchmark_runs']})
    assert sum(r['candidate_runs'] for r in counts) == 166
    assert sum(r['benchmark_runs'] for r in counts) == 4
    repo = RepositoryContext.discover(ROOT)
    batch = d.ResearchBatchRef('S019')
    intent.update(mechanism_research_status='STAGE_TWO_COMPLETE',
        mechanism_research_delivery=delivery.to_dict(), mechanism_completed_rounds=4,
        mechanism_remaining_authorized_rounds=2,
        mechanism_frontier=[d.PrototypeReference(delivery, pid).to_dict()
                            for pid in ('C0804', 'C0801', 'C0720')],
        next_action='向用户交付PROTOTYPES/3；建议批准阶段三后使用剩余2轮研究仓位与连续宽度的达标区域。原目标和完整自检标准保持，当前未推进阶段三。')
    update_research_intent(repo, batch, ResearchIntentUpdate(research_intent=intent), actor='RSCH',
        reason='已完成获准机制研究四轮及PROTOTYPES/3交付，保留剩余2轮；阶段二收口，下一阶段等待用户批准。')
    retained = read(family_path)['research_intent']
    assert retained['stage'] == 'STAGE_TWO' and retained['joint_search_budget'] == budget
    assert retained['mechanism_research_delivery'] == delivery.to_dict()

    handoff = BATCH/'HANDOFF.md'
    text = handoff.read_text(encoding='utf-8')
    old_top = text.split('\n\n')[1]
    assert old_top.startswith('2026-11-10，RSCH') and 'EX041报告' in old_top
    new_top = ('2026-11-11，RSCH，分支 `codex/mu-independent-research`。恢复阶段二后的四轮机制研究已完成，'
        '最新[PROTOTYPES/3](deliveries/PROTOTYPES/3/report.md)发布校验PASS，保存8个精确原型及7组比较。'
        'C0804为主要发展原型，C0801为较平缓对照，C0720保留硬退出收益对照。原硬门目标、80%完整邻域和费用压力标准保持；'
        '新原型的正式阶段四自检待执行。累计已用8/10轮，剩余2轮；当前阶段二完成，阶段三等待用户批准。')
    text = text.replace(old_top, new_top, 1)
    section = '''## 阶段二恢复：退出与参与仓位机制

用户批准以C0355为对照、在剩余6轮内研究ATR退出与参与阈值跳变。已完成4轮，共166个策略账户（含控制复算）及4个共享买持；EX042前置技术失败的8项UNKNOWN、0有效账户、0研究轮独立保留。各轮报告、独立业务审计及预算均已结算留证：[EX043](experiments/EX043_20261110/report.md)、[EX044](experiments/EX044_20261110/report.md)、[EX045](experiments/EX045_20261111/report.md)、[EX046](experiments/EX046_20261111/report.md)。

|原型|NAR|MDD|Calmar|作用|
|---|---:|---:|---:|---|
|C0720|67.2761%|12.2465%|5.493510|连续参与与硬退出收益对照|
|C0801|64.7443%|12.3975%|5.222378|单向渐进退出，ATR三档反应较平缓|
|C0804|66.3048%|12.6141%|5.256417|价格修复后恢复部分仓位，主要发展原型|

在C0720共同参数锚点下，硬退出ATR低/中/高Calmar为4.605738/5.493510/5.114659；单向渐进为5.119182/5.222378/5.158350；可恢复渐进为5.412563/5.256417/5.098477。渐进两类六个配置均通过原中心六门。该三档证据只覆盖ATR方向，六有效连续轴的正式完整邻域和费用压力尚待后续阶段。

C0804在11个闭合周期发生40笔恢复BUY；相对C0801的周期净损益/入场权益6项改善、5项恶化，首次恢复后至退出的标记账户收益另为6正5负。收益增量主要集中于2025年，2022和2026的相对差额为负。其最大回撤为2026-10-07至样本末10-30，期末未修复。原参数锚点的恢复机制降低Calmar，完整反例及归一化成本均保留。全部结果继续属于已见历史开发证据。

[正式原型面板](deliveries/PROTOTYPES/3/report.md)与[发布回执](experiments/EX046_20261111/others/prototype_publication.json)绑定精确身份、参数、源码和账户。原ASSESSMENT/2三个失败结果、其余18个未检状态及21个历史中心达标集合保持。

'''
    assert text.count('## 下一步') == 1
    text = text.replace('## 下一步', section+'## 下一步', 1)
    old_next = '建议回阶段二，优先比较ATR硬退出及参与阈值仓位跳变的替代表达，保留C0355作为完整账户对照；原硬门目标和剩余6轮额度保持，等待用户批准研究方向。'
    assert old_next in text
    text = text.replace(old_next, '建议以C0804为主、C0801和C0720为对照，经用户批准进入阶段三后使用剩余2轮，研究仓位与连续宽度的达标参数区域；原硬门、完整80%邻域及费用压力标准保持。当前未启动下一阶段。', 1)
    handoff.write_bytes(text.encode())
    overview = get_research_overview(repo, batch)
    assert any(x.stage is d.DeliveryStage.PROTOTYPES and x.revision == 3 for x in overview.deliveries)
    save(WORK/'others/final_overview.json', overview.to_dict())
    save(output, {'status': 'STAGE_TWO_COMPLETE', 'delivery': delivery.to_dict(), 'completed_rounds': 4,
        'budget_used': 8, 'budget_remaining': 2, 'account_counts': counts,
        'goals_changed': False, 'stage_advanced': False,
        'source_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
        'handoff_sha256': sha256(handoff.read_bytes()).hexdigest(),
        'overview_snapshot_sha256': overview.snapshot.content_sha256})
    print('STAGE_TWO_CLOSED', delivery.content_sha256, 'budget 8/10; remaining 2')


if __name__ == '__main__':
    main()
