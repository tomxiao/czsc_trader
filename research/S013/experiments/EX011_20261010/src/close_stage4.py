"""Publish a closure supplement without duplicating the original assessment."""
# ruff: noqa: E402
from hashlib import sha256
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT/'research/S007/experiments/EX004_20261010/src'))
from aligned_common import context
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite, EvidenceRef
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools import delivery as d

EXPERIMENT = ExperimentRef('S013', 'EX011_20261010')
BASE = EXPERIMENT.resolve(ROOT)
PROTOCOLS = BASE/'protocols'


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8', newline='\n')


def main():
    assert not (PROTOCOLS/'closure_reference.json').exists(), 'Closure supplement already published'
    research = context('S013', 1)
    receipt_path = ROOT/'research/S013/deliveries/ASSESSMENT/2/receipt.json'
    receipt = d.DeliveryReceipt.from_dict(read(receipt_path))
    assert receipt.reference.content_sha256 == '8e575d33f5173cdddbdbbb49125fc97255ac58f1a2f0ecd2e4a6a44c6c958464'
    validation = read(ROOT/'research/S013/materials/stage4_assessment_20261010.json')
    assert validation['status'] == validation['validation']['status'] == 'PASS'
    assert validation['reference'] == receipt.reference.to_dict()
    # Check current retained bytes against the immutable receipt. This is a
    # manifest check, not a new FULL semantic validation or account replay.
    package = ROOT/'research/S013/assets/deliveries/ASSESSMENT/2'
    for entry in receipt.files:
        assert sha256((package/entry.path).read_bytes()).hexdigest() == entry.sha256
    assert (package/'receipt.json').read_bytes() == receipt_path.read_bytes()
    assert (package/'report.md').read_bytes() == (receipt_path.parent/'report.md').read_bytes()
    references = {}

    def material(name, path, mime='application/json'):
        ref = publish_evidence(research, MaterialEvidenceWrite(EXPERIMENT, name, path.read_bytes(), mime, path.suffix[1:]))
        references[name] = ref.to_dict()
        return ref

    messages = [
        '扰动5%的距离，C2132的收益和回撤分别退化9.57和11.35。相当于收益减少了一大半，回撤几乎翻倍。这个点明显处于参数平面的某个尖峰，稳健性太差，我认为不值得为此投入PTE资源。你说呢？',
        '认同，可以先收尾阶段四。然后先解决以下两个问题：\n1、固化阶段四的参数扰动评估方法，目标是不同研究族的策略对照可比\n2、分析参数扰动评估的耗时，我的直观感觉是运算太慢了',
        '先评审方案再执行',
        '1、认同\n2、告诉我研究员Agent描述及平台分别要做哪些修改\n3、做完2再继续',
        '我认为可以默认只做5%这一档，用于排序。另外两个档位由用户单独提出再执行']
    write(PROTOCOLS/'closure_authorization.json', {'captured_date': '2026-10-10',
        'source': 'Direct human messages in this conversation', 'exact_messages': messages,
        'decision': 'Close stage four; current C2132 not selected for PTE. Do not advance stage five.',
        'method_policy_confirmed': 'Default one normalized total radius .05, 32 joint points for ranking. Additional .10/.20 only on separate user request.',
        'implementation_status': 'Agent/platform method changes under review; no performance controls, platform edits, inspection or freeze authorized by this supplement.'})
    material('stage4-closure-human-confirmation', PROTOCOLS/'closure_authorization.json')
    source_refs = {}
    for name, relative in (
        ('aligned-results', 'research/S007/experiments/EX004_20261010/protocols/results_reference.json'),
        ('aligned-package', 'research/S007/experiments/EX004_20261010/protocols/package_reference.json'),
        ('aligned-package-validation', 'research/S007/experiments/EX004_20261010/protocols/package_validation_reference.json'),
        ('aligned-report', 'research/S007/experiments/EX004_20261010/protocols/report_reference.json')):
        ref = EvidenceRef.from_dict(read(ROOT/relative))
        path = ref.resolve(ROOT)
        source_refs[name] = ref.to_dict()
        material('stage4-closure-'+name, path, ref.media_type)
    numerical = read(ROOT/'research/S007/assets/runs/EX004_20261010/numeric-comparison.json')
    assert numerical['status'] == 'PASS' and numerical['comparison_count'] == 2067 and numerical['difference_count'] == 0
    material('stage4-closure-numeric-audit', ROOT/'research/S007/assets/runs/EX004_20261010/numeric-comparison.json')
    provenance = {'status': 'PASS', 'source_assessment': receipt.reference.to_dict(),
        'current_manifest_files_checked': len(receipt.files), 'source_receipt_sha256': sha256(receipt_path.read_bytes()).hexdigest(),
        'source_full_validation': validation['validation'], 'current_check': 'Retained bytes match immutable publication manifest; no new FULL semantic validation is asserted.',
        'supplementary_source_refs': source_refs,
        'snapshot_scope': 'Exact-byte material snapshots; original native account ownership and references remain unchanged. Native source assets must still be retained.',
        'coverage': 'Original 79 centers unchanged. New aligned supplement concerns only C2132 and S007-v1; not substituted into original eight-point ranking.',
        'closure_format': 'Explicit public material supplement to ASSESSMENT/2; not a new typed ASSESSMENT/3 delivery or stage-five candidate-selection record.',
        'technical_attempts': 'Two caller attempts stopped during source loading/prevalidation, before publication. No new accounts or changes to historical evidence. Full original machine package is retained instead of duplicating 265MB embedded assessment facts.'}
    write(PROTOCOLS/'closure_provenance.json', provenance)
    material('stage4-closure-provenance', PROTOCOLS/'closure_provenance.json')
    report = '''# S013阶段四收尾补充报告（2026-10-10）

阶段四已收尾。用户明确同意当前C2132不投入PTE，本轮不选择候选进入阶段五。S013研发方向保留，下一轮策略研究方向另行决定。

本报告是原ASSESSMENT/2的正式材料补充，不是新的完整ASSESSMENT/3机器交付。原79中心资格、自检和排序保持；C2132仍为原政策首位，但用户依据新的稳健性反证决定暂不推进。既有经济硬门不变，其余78个中心未被视为完成同等新补测。

## 选择依据

|统一总距离|S007年化下降|C2132年化下降|S007回撤增加|C2132回撤增加|
|---|---:|---:|---:|---:|
|5%|1.8208|9.5670|1.3962|11.3476|
|10%|3.7784|11.9601|1.5081|14.9889|
|20%|5.9399|11.7609|5.4009|14.6497|

单位为百分点。每格来自事前固定32个联合点的LINEAR Q10收益或Q90回撤，两项可能来自不同配置；5%是标准化总距离，不是每项参数都改5%。C2132中心年化16.1572%、回撤14.1599%；小档收益Q10约6.5902%、回撤Q90约25.5075%。三档都显示明显参数脆弱性，支持当前候选不投入PTE的资源判断，但没有证明整个参数平面的尖峰形状。

C2132费用翻倍年化损失3.9156个百分点，小于S007的5.1479；前一成盈利交易贡献44.7919%，小于48.7283%。这些优势保留，未抵消用户对参数稳健性的担忧。S007时间诊断的整手基准主表口径仍待确认，不作为本次决定的必要依据。

原生标的、时期、资本及价格合同不同，统一量尺支持条件下的参数稳定性比较，不直接证明总体赢家。行为配对三档均0/32，不影响参数稳健性判断，但没有建立等量持仓变化的收益对照。开发池重复用于研究，没有新增独立样本。

## 证据与检查范围

原ASSESSMENT/2已发布完整79中心自检及869账户坐标，并有FULL校验PASS记录；本次对原包清单逐文件核对当前哈希，公开报告及回执与原完整包一致。此为当前字节完整性核对，不冒称重新执行FULL语义验证。

统一扰动补测300个不同配置、302份新完整账户；主分析与独立复算2067项精确对照，0差异；原材料目录391个唯一引用哈希校验PASS。关键补证逐字节快照及用户原文通过公开证据API保存。正式资产与完整原生账户仍须保留，Git及摘要不能替代这些资产。

## 已确认的后续安排

默认只做5%总距离、32个联合点，用于排序；10%和20%仅在用户单独提出后执行。本轮已完成的三档证据保留，不能事后删掉其他档位或改写原排序。

接下来先评审研究员Agent描述与SE/TDR平台的具体修改，再实施获批方法。完成第2项后才继续耗时诊断。当前没有启动性能控制复算、平台改动、阶段五、冻结或PTE。研究状态不擅自改成暂停或停止。

- [原完整阶段四报告](../../../deliveries/ASSESSMENT/2/report.md)。
- [统一扰动完整报告](../../../../S007/experiments/EX004_20261010/others/report.md)。
- [用户确认原文](../protocols/closure_authorization.json)。
- [完整性核对与补证出处](../protocols/closure_provenance.json)。
'''
    report_path = BASE/'others/stage4_closure.md'
    report_path.write_text(report, encoding='utf-8', newline='\n')
    ref = material('stage4-closure-report', report_path, 'text/markdown')
    write(PROTOCOLS/'closure_reference.json', {'status': 'PASS', 'report': ref.to_dict(), 'materials': references,
        'original_assessment': receipt.reference.to_dict(), 'new_accounts_executed': 0})
    print({'status': 'PASS', 'manifest_files_checked': len(receipt.files), 'report': ref.to_dict(), 'new_accounts_executed': 0}, flush=True)


if __name__ == '__main__':
    main()
