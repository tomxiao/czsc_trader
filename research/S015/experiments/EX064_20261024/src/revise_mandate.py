"""Publish the approved finite-neighborhood mandate; preserve economic targets."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence, assemble_delivery
from czsc_trader.research_tools import ResearchBatchRef, ExperimentRef, ExecutionResources, MaterialEvidenceWrite
from czsc_trader.research_tools import delivery as d
from strategy_evaluator import research_models as m

ROOT = Path(__file__).resolve().parents[5]
EX = ExperimentRef('S015', 'EX064_20261024')
HOME = EX.resolve(ROOT)
OUT = HOME / 'others'
OLD_HASH = '5563c98c1a2ed876b6d75b775437f35ec2c31777818ad0f9b67e89c90d30d90a'


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def main():
    repo = RepositoryContext.discover(ROOT)
    research = create_research_context(repo, ResearchBatchRef('S015'), resources=ExecutionResources(1, 1, 13))
    old_path = ROOT / 'research/S015/assets/deliveries/MANDATE/3'
    predecessor = d.DeliveryReceipt.from_dict(read(old_path / 'receipt.json')).reference
    assert predecessor.content_sha256 == OLD_HASH
    assert (old_path / 'receipt.json').read_bytes() == (ROOT / 'research/S015/deliveries/MANDATE/3/receipt.json').read_bytes()
    preserved = {p: sha256(p.read_bytes()).hexdigest() for p in (
        old_path / 'delivery.json', old_path / 'receipt.json',
        ROOT / 'research/S015/deliveries/MANDATE/3/report.md',
        ROOT / 'research/S015/deliveries/MANDATE/3/receipt.json')}
    old = d.DeliveryContent.from_dict(read(old_path / 'delivery.json')['content'])
    assert type(old.payload) is d.ResearchMandate
    authorization = {
        'confirmed_date': '2026-10-24', 'source': 'human message in this Codex conversation',
        'user_confirmation_verbatim': '同意，切换RSCH，按新参数邻域契约修订S015研究约定，自主补做并完成阶段四，汇报结论。',
        'scope': 'Revise parameter evaluation method; complete stage four for CANDIDATES/6. No stage five selection, freeze, PTE, production or new data authority.',
        'unchanged': 'All nonparameter economic targets, inner point economic conditions, 434-session development window and separate 415-session fixed S011 dual-superiority gate.',
    }
    method = {
        'version': 'S015-finite-neighborhood-v1', 'source_mandate': predecessor.to_dict(),
        'purpose': 'LOCAL_SENSITIVITY', 'enumeration': 'Complete declared Cartesian product; remove center and invalid domain/constraint points before outcomes; no sampling, clipping, padding or post-outcome deletion.',
        'axes': {
            'allocation': {'kind': 'REAL', 'unit': 'fraction', 'domain': '(0,1]', 'offsets': [-0.05, 0.05]},
            'lookback': {'kind': 'INTEGER', 'unit': 'trading_sessions', 'domain': [2, 10], 'offsets': [-1, 1]},
            'hold': {'kind': 'INTEGER', 'unit': 'trading_sessions', 'domain': [1, 30], 'offsets': [-1, 1]},
            'confirmation': {'kind': 'INTEGER', 'unit': 'trading_sessions', 'domain': [1, 5], 'offsets': [-1, 1], 'applicability': 'confirmed_guard only; retained when a joint neighbor activates it'},
        },
        'feasibility': 'Keep original source and full payload. Require hold <= max_hold <= 30 where max_hold exists; all other original runtime constraints remain applicable.',
        'fixed': ['mode', 'exit_mode', 'center_kind', 'rearm_mode', 'start', 'inactive parameters', 'execution contract', 'data window'],
        'point_gate': {'minimum_numerator': 13, 'minimum_denominator': 16, 'required_passes': 'ceil(13*N/16)', 'all_N_valid_required': True, 'economic_conditions': 'Exactly inherit old joint_targets and all_point_targets.'},
        'scope': '434-session parameter evaluation only; 415-session S011 comparison and frequency conditions remain center gates, not additional parameter-point gates.',
        'expected_design_counts': {'17': 4, '26': 7, '53': 4, '80': 1}, 'expected_noncenter_points': 542,
        'interpretation': 'Configuration count is not independent hypothesis or distinct behavior count. New outcomes do not revise old qualifications. No outcome available at method publication.',
        'comparability': 'Use generated comparison_sha256; distinct shapes or constraints are not forcibly pooled for ranking.',
    }
    save(OUT / 'mandate_authorization.json', authorization)
    save(HOME / 'protocols/parameter_method.json', method)
    refs = []
    def publish(path):
        media = {'.json': 'application/json', '.md': 'text/markdown', '.py': 'text/x-python'}[path.suffix]
        ref = publish_evidence(research, MaterialEvidenceWrite(EX, path.stem, path.read_bytes(), media, path.suffix[1:]))
        refs.append(ref)
        return ref
    auth_ref = publish(OUT / 'mandate_authorization.json')
    method_ref = publish(HOME / 'protocols/parameter_method.json')
    confirmation = d.ConfirmationRecord(d.ConfirmationStatus.CONFIRMED, auth_ref)
    items, replacements = [], 0
    for item in old.payload.items:
        if isinstance(item.requirement, d.PerformanceRequirement):
            targets = []
            for target in item.requirement.targets:
                if isinstance(target, m.ParameterGroupTarget):
                    assert (target.required_points, target.minimum_joint_passes) == (32, 26)
                    revised = m.ParameterNeighborhoodTarget(target.target_id, 13, 16,
                        target.joint_targets, target.all_point_targets)
                    assert revised.joint_targets == target.joint_targets
                    assert revised.all_point_targets == target.all_point_targets
                    targets.append(revised)
                    replacements += 1
                else:
                    targets.append(target)
            if tuple(targets) != item.requirement.targets:
                item = replace(item, statement='保留既有中心经济、双频率和费用压力条件；参数检验采用事前完整自然尺度邻域，全部N点有效、至少ceil(13*N/16)联合经济达标且全部点满足原绝对风险上限。',
                    confirmation=confirmation, requirement=d.PerformanceRequirement(tuple(targets)))
        elif item.item_id == 'current-authorization':
            item = replace(item, statement='用户批准按新参数邻域契约修订S015约定，并自主补做及完成阶段四；仅承接CANDIDATES/6全部16中心。阶段五具体选型、冻结、PTE、生产及新增数据另行确认。此前阶段授权的历史记录保留。', confirmation=confirmation)
        items.append(item)
    assert replacements == 1
    payload = d.ResearchMandate(tuple(items))
    changed = [a.item_id for a, b in zip(old.payload.items, payload.items, strict=True) if a != b]
    assert changed == ['performance', 'current-authorization']
    old_targets = {t.target_id: t for i in old.payload.items if isinstance(i.requirement, d.PerformanceRequirement) for t in i.requirement.targets}
    new_targets = {t.target_id: t for i in payload.items if isinstance(i.requirement, d.PerformanceRequirement) for t in i.requirement.targets}
    assert old_targets.keys() == new_targets.keys()
    assert all(old_targets[k] == new_targets[k] for k in old_targets if k != 'parameters')
    save(OUT / 'mandate.json', payload.to_dict())
    publish(OUT / 'mandate.json')
    publish(Path(__file__))
    report = '''# S015研究约定修订4：完整参数邻域

用户已批准依据新参数邻域契约修订S015约定，并补做完成阶段四。本修订只改变参数敏感性检验的方法及当前授权状态，不改变中心或邻点的经济门槛。

## 目标与范围

[MANDATE/3](../3/report.md)的434日开发池、独立415日S011比较窗口、固定基线哈希、中心收益与回撤、60日双频率、双倍费用压力条件全部保留。参数点的收益条件仍为基准净年化为正时至少1.25倍，否则严格大于0；回撤不高于基准90%；所有点绝对回撤不高于25%。415日严格双优仅评价中心，不扩张到邻点。

## 参数检验方法

以各中心自身源码、载荷和参数语义为准。allocation按资金比例±0.05，即±5个百分点，合法域(0,1]；lookback按±1交易日，整数域[2,10]；hold按±1交易日，整数域[1,30]；confirmed_guard另包含confirmation±1日，整数域[1,5]。各轴包括中心值，枚举完整联合组合，去除中心及事前声明的非法点。越过边界的点排除，不裁剪、不填充；结构参数和非活跃参数保持固定。组合中的活跃性必须考虑，例如确认期在中心无作用，但在联合邻点生效时仍需覆盖。

N为预先生成的全部合法非中心点数。必须全部N点具有有效且同口径的正式账户证据，至少ceil(13*N/16)点同时满足原收益及相对回撤条件，且全部N点满足25%绝对回撤上限。缺失或技术失败不缩小分母。原32/26比例保持为13/16，取消强凑32点的要求。N=17/26/53/80时分别至少14/22/44/65点联合通过。

全部16中心预计542个邻点。完整映射、域、生成规则、可行性证明、计划和账户绑定在本次实验事前发布；不同邻域形状依据生成器比较身份分组，不强行共同排序。参数配置数、不同收益路径数及独立机制数分别解释，不因结果重复而删除参数点。

## 判断与授权

旧MANDATE/3、ASSESSMENT/2和全部历史实验保持不变。本修订不追认旧策略合格，也不提前宣布新阶段四结论。阶段四完成与策略满足全部研究目标分别报告。开发池已经反复观察和用于选择，不是新独立样本。

当前授权为按本方法完成阶段四，不包含阶段五选择、冻结、PTE、生产或新增数据。旧约定的交易时点、输入可得性和执行限制仍需在实际研究结果中如实说明，方法修订不替代这些证据。
'''
    (HOME / 'protocols/mandate_revision.md').write_text(report, encoding='utf-8')
    publish(HOME / 'protocols/mandate_revision.md')
    definition = d.DeliveryDefinition(ResearchBatchRef('S015'), d.DeliveryStage.MANDATE, 4, (predecessor,))
    assert definition.schema_version == 11
    content = d.DeliveryContent(payload, d.DeliveryStatus.COMPLETE, (), (), report=report,
        evidence=tuple(dict.fromkeys((*old.evidence, *refs))))
    assembled = assemble_delivery(repo, definition, content, resources=ExecutionResources(1, 1, 13))
    assert assembled.validation.status.value == 'PASS' and assembled.validation.scope.value == 'FULL'
    assert all(sha256(p.read_bytes()).hexdigest() == digest for p, digest in preserved.items())
    save(OUT / 'mandate_reference.json', assembled.receipt.reference.to_dict())
    save(OUT / 'mandate_revision_summary.json', {
        'source': predecessor.to_dict(), 'reference': assembled.receipt.reference.to_dict(),
        'schema_version': definition.schema_version, 'validation': assembled.validation.to_dict(),
        'changed_items': changed, 'parameter_economic_conditions_unchanged': True,
        'other_targets_exactly_unchanged': True, 'other_items_exactly_unchanged': True,
        'old_publication_files_unchanged': len(preserved), 'authorization': auth_ref.to_dict(),
        'method': method_ref.to_dict(), 'new_target': new_targets['parameters'].to_dict(),
    })
    print('MANDATE_4_FULL_PASS', assembled.receipt.reference.content_sha256, flush=True)


if __name__ == '__main__':
    main()
