# S011 阶段二与四完整交付

本轮目标已完成。阶段二、阶段四均为`COMPLETE`，公开契约和研究局限分别披露；阶段五继续暂停。优先阅读[研究结论与全部36中心结果](COMPLETION_REPORT.md)，精确引用见[交付索引](delivery_index.json)。

| 阶段 | 状态 | 人工报告 | 机器产物 |
| --- | --- | --- | --- |
| 一：研究合同，沿用原件 | COMPLETE | [任务书](../../../research/S011/mandates/1/report.md) | [契约](../../../research/S011/mandates/1/delivery.json) |
| 二：4项职责组件，完整性审查 | COMPLETE | [组件报告](deliveries/COMPONENTS/1/report.md) | [面板](deliveries/COMPONENTS/1/delivery.json) |
| 三：原36中心，更新前驱引用 | COMPLETE | [候选报告](deliveries/CANDIDATES/1/report.md) | [候选集合](deliveries/CANDIDATES/1/delivery.json) |
| 四：补齐自检与扩展族统计 | COMPLETE | [自检报告](deliveries/ASSESSMENT/1/report.md) | [评估契约](deliveries/ASSESSMENT/1/delivery.json) |

阶段二承接EX34的9定义、63检验、189折和945留月诊断，审查185字段完整台账及历史反证。旧格式未全量重跑、旧manifest引用差异及已见开发池限制保留，不自动等同当前交付缺失。

EX37完成513次受管调用、514份账户，512个新联合点及000193同源码压力缺口补齐；配套标准重复账户与EX33逐项一致，不增加搜索计数。36中心各16个联合点、36份成本压力，正式自检合计648份去重坐标账户。000137原源码受lookback上限约束，预声明为110/120单侧设计；000664保持3天持有，其他中心2天。设计差异随比较披露。

原经济目标全部保持：108项通过、72项条件不适用，仍为16层；0个配置因缺证保留部分顺序、0对不可比。第一层：S011-CFG000618R2 → S011-CFG000624R2 → S011-CFG000621R2 → S011-CFG000628R2。621联合点仍仅1/16达标，完整交付不代表其局部稳健性已充分。

扩展族统计覆盖1284/1381次提议口径，1034条非恒定独特收益路径；PBO为8块82.86%、10块81.35%。统计只解释开发池选择风险，不表示未来获利概率。当前612份受管标准账户子族另以强类型FamilyReturnEvidence提供，未替代完整历史搜索统计。

## 执行资源

本机16个逻辑核，项目默认并发预算为8个工作进程。本轮实际采用单进程、`InMemoryStorage`、主进程唯一Study、`workers=1`及内部线程1，详见[环境记录](environment.json)。本轮没有先完成多进程受管评价与目录隔离验证，因此没有证据断言默认并行方案不可行；后续执行应先补此核验。`EvaluationRequest.workers`控制单请求内部场景/窗口线程并行，单窗口单场景不能靠增大该值实现候选间多进程。

## 验证与原件

[聚焦验收](focused_verification.json)包括当前回执、512项登记与父源码、8项×36中心独立指标核对、全部322个PBO分割、72组DSR及相关矩阵有效次数、四阶段引用链和错误哈希拒绝。未执行仓库级全量回归，未修改平台模块。

[EX35](../20261002_S011_EX35/experiment_manifest.json)预检发现8个非法参数点；[EX36](../20261002_S011_EX36/experiment_manifest.json)因首个压力请求缺标准场景被拒绝，均未产生账户。失败原件封存；EX37按后继合同执行。阶段四首次组装遇到NumPy标量与强类型float不匹配，[原记录](publication_failure.json)和原脚本保留，`publish_assessment.py`在契约边界显式转换后承接，账户结果未改变。新编写的实验与交付脚本Ruff通过；保存的策略源码沿用原字节，保留历史格式问题。

封存后可在仓库根目录运行：

```powershell
.venv/Scripts/python.exe experiments/S011/20261002_S011_EX37/verify_completion.py --sealed
```

验证输出位于`.tmp/s011-completion-postseal.json`，不改写封存证据。[实验manifest](experiment_manifest.json)覆盖当前实验及交付。机器制品及交付的实验副本按Git规则只保存在本地，未执行外部备份、合并、推送、tag、冻结或部署。

下一步：审阅本轮完整证据，再明确是否继续研究或进入阶段五技术检验。
