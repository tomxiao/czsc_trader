"""Reproduce all retained native direction counts and their interpretation."""
from common import ROOT, SRC, PROTOCOLS, read, write


def main():
    output = read(ROOT / '.tmp/ex039-diagnosis/direction.json')
    assert output['status'] == 'PASS' and output['new_account_evaluations'] == 0
    text = '''# S013：完整既有账户下跌入场价格方向诊断

RSCH阶段三，用户授权自主推进，无需逐轮评审。原S013数据、四项经济门和13维完整参数域保持。本轮零新增账户，精确复用原C2132及32个原域联合扰动账户、均值居中自相关C8701和附加上涨转换BODY门C8481，共35个原生账户。原33账户使用同一市场路径，不能当作33个独立样本；另两中心单列。

每个账户原有1636个信号日保留，包含用于2020执行的2019信号。原生正式身份、参数来源、绑定、基准和完整现金/数量账本核对；独立重算自相关、量额秩、确认分、范围位置、路由和全持仓状态。只在原生空仓资格机会与原生买入上，统计两个严格不等式：Close>前一实际信号日Close，表示较前收上涨；Close>当日Open，表示当日收盘高于开盘。等于和下跌单列，不增加数值阈值。

|账户组|信号年|路线|原生集合|数量|原确认通过|较前收上涨|等于前收|较前收下跌|收高于开|等于开盘|收低于开|
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
'''
    groups = {'原中心': output['summary']['center_statistics'],
              '原33账户合计（非独立样本）': output['summary']['pooled_original33_statistics'],
              **output['summary']['additional_center_statistics']}
    for group, rows in groups.items():
        for row in rows:
            close, body = row['close_direction'], row['body_direction']
            text += f"|{group}|{row['year']}|{row['route']}|{row['set']}|{row['count']}|{row['score_pass_count']}|{close['up']}|{close['equal']}|{close['down']}|{body['up']}|{body['equal']}|{body['down']}|\n"
    decision = read(PROTOCOLS / 'decision.json')
    text += '\n' + '\n\n'.join(decision['conclusions']) + '\n\n' + decision['next_action'] + '\n'
    text += '''
这些是原路径的谓词计数，不是删除交易后的盈利预测。拒绝一次买入会改变以后持仓、退出、机会和成交，不能把被拒绝交易的盈亏相加当作新账户结果。机会年按信号日期分组，经济年度仍按实际执行日期。原始全部35账户每日信息、方向交叉计数和身份/账本审计保留在正式诊断中。

最强已有反证：原策略112笔闭合交易，仅比最低110笔多两笔；2023收益仅+0.2841%。此前所有上涨路线价格门降至97/99笔，转换日价格门也曾降至108/109笔。限制买入可能损害交易次数或删掉后续恢复机会。均值居中背景虽123笔，仍不满足2024年度回撤。本轮计数不能推断下跌门会解决这些问题。

反复使用同一已见开发池具有选择偏差，不是独立验证或未来保证。FULL只核验声明证据完整性，不证明经济达标或参数改善。本轮诊断已完成，总体参数敏感性改善目标仍未达成。未推进正式阶段四、冻结、PTE或生产。
'''
    path = SRC.parent / 'others/report.md'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8', newline='\n')
    write(PROTOCOLS / 'report_validation.json', {'status': 'PASS', 'groups': len(groups),
        'all_native_signal_rows': 35 * 1636, 'new_account_evaluations': 0, 'objective_achieved': False})


if __name__ == '__main__':
    main()
