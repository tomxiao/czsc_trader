"""Root review of fixed public EX073 results; no new fitting or accounts."""
from pathlib import Path
import json
from czsc_trader.research_tools.evidence import EvidenceRef

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').exists())
WORK = Path(__file__).parent
refs = json.loads((ROOT / 'research/S013/experiments/EX073_20261011/protocols/verification_references.json').read_text('utf-8'))
def read_public(name):
    return json.loads(EvidenceRef.from_dict(refs[name]).resolve(ROOT).read_text('utf-8'))
s, v, inputs = [read_public(n) for n in ('statistics.json', 'verification.json', 'input_checks.json')]
assert v['status'] == 'PASS' and v['checks'] == 24128 and v['new_accounts'] == 0
assert inputs['actual_bear_entry_n'] == 64 and inputs['bear_flag_n'] == 15
assert s['models'] == 0 and s['full_axis_n'] == 1635
rows = []
for name, block in s['labels'].items():
    p = block['partial']
    assert p['n'] == 62 and p['flag_n'] == 14 and p['design_rank'] == 15 and p['residual_df'] == 47
    for mode in ('raw', 'partial'):
        b = block['bootstrap'][mode]
        assert b['valid_replicates'] == 500 and b['failure_reasons'] == {}
        ci = b['ic95']
        assert (ci[1] < 0) if name == 'late_return' else (ci[0] > 0)
    assert not block['groups']['flag']['reliable_group_evidence']
    for panels in ('years', 'phases'):
        for part in block[panels].values():
            assert part['raw']['value'] is None and part['partial']['value'] is None
    ci = block['bootstrap']['partial']['ic95']
    rows.append(f'|{name}|{p["value"]:+.5f}|[{ci[0]:+.5f},{ci[1]:+.5f}]|62 / 14 / 47|')
lines = [
    '# EX073：隔夜压力能否识别持有后半段的风险', '',
    '本轮固定统计及独立验证完成，0新账户。原真实bear入场的后半两日出现支持原风险职责方向的组件证据，判为LIMITED_SUPPORT_FOR_FIXED_HOLDING_TEST。它支持一个固定完整账户对照，不证明已经找到稳健达标策略，也不推翻EX072取消买入失败的结论。', '',
    '117次实际首次BUY中bear64次，固定入场前4日隔夜下跌幅度总和大于日内下跌总和的标记15次。63次主标签成熟，其中15标记、48非标记；原14控制完整后62次、14标记、残差自由度47。实际成交发生T+1，本池是条件于实际成交的研究样本；只有标记与控制信息在T已知，不把样本选择当作可在T部署的过滤器。', '',
    '后半收益=Open[T+5]/Open[T+3]-1，比较同数量T+3卖出与T+5卖出，同一卖费抵消，无新买费。风险仅使用T+3/T+4的OPEN/CLOSE及T+5OPEN，不用High/Low，不是账户最大回撤。原退出日不参与挑样本，标签可假设跨越旧退出。', '',
    '|主标签|控制后秩相关|500×40描述区间|有效样本 / 标记 / 残差df|',
    '|---|---:|---|---:|', *rows, '',
    '收益原始相关−0.28487，描述区间[−0.56987,−0.04416]；风险原始相关+0.23167，区间[+0.02115,+0.53609]。四套bootstrap均500有效、0失败，全部记录核验。区间未校正本开发池反复选择，不能解释为未来成功概率或独立验证。', '',
    '描述性分解：标记组前两日均值+0.43277%，后两日−0.16292%，完整四日+0.27883%；非标记后两日+0.78394%。标记组后半OPEN/CLOSE风险0.94053%，非标记0.54709%。各均值只是15/48个反事实价格观察，辅助first2/full4未增加相关、CI或模型；平均数不能直接相乘代替逐笔乘法恒等式。', '',
    '必要反证：标记只有15次，按事前方法分组证据不可靠；控制后14次。2022仅4次、后半均值−1.2764%，2023仅3次、后半均值−0.1120%；这不是已确认跨年稳定优势。2020标记后半均值+1.1453%、2025+1.5710%，提前退出会放弃这些后续盈利。所有年度和五个非重叠相位原始样本不足、控制后自由度不足，均明确null，不能把整体区间当逐年/逐相位确认。', '',
    '17项合成检查及6项拒绝、价格认证补充3项合成及3项拒绝通过，24,128项独立实际核验通过（输入22,042、统计2,086）。技术认证在实际统计前发现原生HFQ研究单位与公共HFQ差一个固定0.2803锚点；原声明、旧源码和失败均保留，补充公开仅修复认证，逐行标签比值及成熟日期的尺度不变已验证；实际标签、群体、控制、方向和统计方法保持。', '',
    '根判断：保留这项期限匹配的有限正证，继续检验一个新固定策略表达：保留原确认和买入，原bear入场的压力标记锁存后，原规则仍会继续持仓时最多持有2信号日，其他原退出优先；这是下一独立实验，EX073自身仍0账户。公开整数参数域和完整扰动维数，固定中心先验收原四门，只有全过才执行标准32点及独立双费用；不调阈值、回溯选年、改变硬门或实施动态仓位。', '',
    '量价交互仅为未检验的新假说，先保留方法审查；当前优先使用本次实际期限证据。保留C8880研究基线，整体稳健策略目标尚未达成。', '',
    '研究范围仍是原S013 510500.SH开发池与原warmup、后复权无分红叠加、固定1%执行合同；无新增provider、封存样本、DEV/PTE/生产操作。'
]
review = {
    'status': 'ROOT_SCIENTIFIC_REVIEWED',
    'component_status': 'LIMITED_SUPPORT_FOR_FIXED_HOLDING_TEST',
    'statistics_reference': refs['statistics.json'],
    'verification_reference': refs['verification.json'],
    'objective_achieved': False,
    'economic_targets_unchanged': True,
    'new_hard_gates': False,
    'new_accounts': 0,
    'judgment': '原冻结风险方向在期限对齐总体相关及区间中得到支持；薄组、逐年和相位不可用、反复选择、反事实标签限制必须完整保留。只支持一个固定中心账户反证，不证明账户改善或稳健达标。',
    'next': '固定保留买入、锁存原bear入场压力并缩短持有的独立完整账户对照；中心4门不过即停，过后标准32与独立双费用，无邻域或阈值救援。',
    'report_markdown': '\n'.join(lines) + '\n'
}
dest = WORK / 'root_review.json'
assert not dest.exists()
dest.write_text(json.dumps(review, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
print({'status': review['status'], 'component': review['component_status'], 'goal_complete': False})
