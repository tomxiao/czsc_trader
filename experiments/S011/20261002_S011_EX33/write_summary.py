"""Produce the review navigation from verified current deliveries before sealing."""
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parents[2]

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def main():
    assert not (ROOT/'experiment_manifest.json').exists(), 'sealed archive'
    proof=read(ROOT/'focused_verification.json')
    assert proof['status']=='PASS'
    panel=read(ROOT/'assessment_panel.json')
    row=next(x for x in panel['rows'] if x['candidate']['candidate_id']=='S011-CFG000621R2')
    values={x['metric']:x['value'] for x in row['diagnostics']}
    text=f'''# S011 阶段一至四当前契约交付

本次重新生成已完成。四阶段交付均使用schema 4，公共校验通过；候选登记使用schema 2，当前受管实验定义／回执使用schema 2。研究范围、原经济目标、策略源码和参数、截止日2026-09-28保持不变。

| 阶段 | 研究状态 | 人工报告 | 机器产物 |
| --- | --- | --- | --- |
| 一：研究任务与评价合同 | COMPLETE | [任务书](../../../research/S011/mandates/1/report.md) | [契约](../../../research/S011/mandates/1/delivery.json) |
| 二：职责组件 | PARTIAL | [组件报告](../20261002_S011_EX34/deliveries/COMPONENTS/1/report.md) | [组件面板](../20261002_S011_EX34/deliveries/COMPONENTS/1/delivery.json) |
| 三：策略候选 | COMPLETE | [候选报告](deliveries/CANDIDATES/1/report.md) | [候选集合](deliveries/CANDIDATES/1/delivery.json) |
| 四：自检与排序 | PARTIAL | [自检报告](deliveries/ASSESSMENT/1/report.md) | [评估契约](deliveries/ASSESSMENT/1/delivery.json) |

阶段二至四产物随归属实验保存；阶段一位于研究治理区。精确归属及内容哈希见[交付索引](delivery_index.json)，不能仅凭修订号跨实验引用。

## 本次执行与结论

- EX34经DFLS重新取得授权数据，复算9个固定信息定义、7种标签、63条角色检验、189折和945条留月诊断，数值与原证据一致。4个组件分别提供机会背景、入场时点、风险状态及外部确认信息。旧广泛筛选及二元路径保留为历史附件。
- EX33完成100次受管评价、135份策略账户及相应限价BuyHold账户；675张策略账本及675张基准账本逐项对照通过。lot_size=100，标准每侧10bp，已有压力每侧20bp。
- 显式登记36个中心和64个扰动候选，使用R2登记键。36个中心内容哈希与原候选一致；[身份映射](identity_mapping.json)保留旧配置、来源、当前候选键及评价身份。R2不代表新策略或独立样本。
- 阶段三保留573条完成提议及3条失败提议的历史搜索记录，并披露其他实验级失败；本轮新增参数提议为0。全部36个既有达标中心进入handoff，扰动候选不进入中心排序。
- 原目标108项通过、72项条件不适用。16层、9对不可比关系、15个名次区间及10种敏感性方案与历史结果一致。第一层仍为618→624→621→628。

## 621的研究判断

当前键为`S011-CFG000621R2`，内容哈希`{row['candidate']['content_sha256']}`。原用户对621的选择保留为历史决定，本轮没有补造用户已审阅新交付的批准记录。

| 指标 | 当前复算 |
| --- | --- |
| 标准净年化 | {values['NET_ANNUAL_RETURN']:.4%} |
| 最大回撤幅度 | {values['DRAWDOWN_MAGNITUDE']:.4%} |
| 每60交易日折算闭合交易数 | {values['FULL_SAMPLE_FREQUENCY']:.4f} |
| 20bp压力净年化 | {values['NET_ANNUAL_RETURN']-values['STRESS_ANNUAL_LOSS']:.4%} |
| 联合扰动年化退化 | {values['PARAMETER_RETURN_DEGRADATION']*100:.4f}个百分点 |
| 60日滚动超额累计收益Q10 | {values['ROLLING_EXCESS_Q10']:.4%} |

621保留较低回撤及原用户偏好；完整开发池年化低于618／624的机会成本仍存在。既定16点联合邻域仅1点达到原目标，滚动超额低分位为负，联合回撤恶化及近期亏损等反证未消除。用户选择不改变其原第一层第3位，也不能解释为统计显著优胜。

## 保留限制与失败路径

32个中心缺少主联合扰动，000193缺同源码20bp压力；旧PBO／DSR只覆盖原搜索族，不能代表EX28扩展后的完整搜索。原EX12引用EX01 manifest的差异仍保留。阶段二、四因此继续PARTIAL，技术PASS只证明当前契约、身份、引用和声明计算成立。

EX32数值执行成功，但交付组装独立加载因相邻模块导入失败；[原记录](../20261002_S011_EX32/publication_failure.json)和原档案保留，EX34以单模块源码闭包承接。EX30等旧失败路径仍作为历史附件。全部本次及历史数据均属已见开发池，新增独立样本为0。

## 核验与保存

[聚焦验收](focused_verification.json)核对当前回执、候选源码／载荷、原件哈希、四阶段引用链、全部排序指标及错误内容哈希拒绝。封存后从仓库根目录运行：

```powershell
.venv/Scripts/python.exe experiments/S011/20261002_S011_EX33/verify_deliveries.py --sealed
```

该命令只读核验正式原件，输出写入`.tmp/`。本轮未做仓库级全量回归，未修改平台模块。验收与汇总脚本的Ruff检查通过；对三份新实验全部研究源码的额外Ruff检查报告245项多语句同行、导入位置、重复／未用名称问题，统计见[静态检查](validation/research_lint.txt)。这些问题不改写已通过的数值对照，已绑定及封存源码保持原字节，本轮不宣称全部静态检查通过。

原始回执和计算制品在各实验`artifacts/`，交付副本在`deliveries/*/*/experiments/`，按仓库规则仅保存在本地且被Git忽略。当前没有统一外部备份目的地；本次未执行外部备份或跨机器同步，恢复责任由仓库维护者按实验档案说明落实。Git提交不包含完整机器制品。

下一步由用户审阅本次交付，决定是否以当前621身份进入阶段五技术检验。阶段五、冻结、部署、合并、tag和推送均未执行。
'''
    (ROOT/'README.md').write_text(text,encoding='utf-8',newline='\n')
    print('review navigation written')

if __name__=='__main__':
    main()
