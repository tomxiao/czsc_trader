# V4账户回放合成基准

`equity_replay_benchmark.py`仅构造CN/US合成日历、RAW行情、显式规则和当前V4策略，
不读真实研究批次、不连接供应商、不发布研究证据。旧EX027/V3比较脚本和专用策略夹具已退役，
历史研究原件保留，不承诺旧schema机器复算。

从仓库根目录运行：

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:OMP_NUM_THREADS = '1'
$env:OPENBLAS_NUM_THREADS = '1'
.venv/Scripts/python.exe scripts/benchmarks/equity_replay_benchmark.py --market US --rows 25000 --repeats 3
```

`--market CN`使用合成午休交易段、整手及次日可卖规则；默认US。日历仅取工作日，不是交易所真实历史。
输出限于根目录 `.tmp/`，默认 `.tmp/equity-replay-benchmark/result.json`；需要保留多次结果时
显式选择不同的 `--output`，不能覆盖为真实研究证据。非法规模或输出越界直接失败。

准备时间单独计量；每次账户时间包含执行器构造、策略启动装载、策略／特征计算、执行与七张结果表。
不含DFLS取数、SE认证、JSON哈希和发布。报告全部重复及中位数，并比较重复运行的七表内容哈希。
账户必须满足 `source_checks=0`和 `module_loads=1`，不会逐步检查或重新装载源码。
新结果不能与旧脚本不同工作量、口径和并发负载的耗时直接计算加速比。

聚焦测试位于 [合成基准验收](../../tests/functional/test_equity_replay_benchmark.py)。
需要精确定位执行器成本时，另用预构造中立计划计时；这种纯执行时间不包含策略和准备，必须分别报告。

## 阶段四自检接口基准

`stage4_selfcheck_benchmark.py`串行测量当前公开准备、计划绑定、投影、自检、比较、证据发布及阶段四交付接口；检查点内部存取单独列出。复用现有离线集成夹具，所有生成文件留在`.tmp/`。需安装项目`test`依赖组（包括psutil），原生计算线程固定为1。

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
.venv/Scripts/python.exe -B scripts/benchmarks/stage4_selfcheck_benchmark.py --repeats 3
```

`--output`接受尚未存在的`.tmp/`子目录；`--account-path`可指定已有、受管的V4参数邻点证据路径，仅只读测量其物化和投影。脚本不会重跑真实研究账户。

### 2026-11-11 实测

环境：Windows 11、Python 3.12.10、16个逻辑CPU、约128 GiB内存。执行器1进程、原生库1线程，常规项3次取中位数，明确标为冷调用的项各1次。首次调用未清空操作系统页缓存。导入和夹具搭建位于计时边界外；Bootstrap复用项的已有统计计算也位于边界外。

准备与账户夹具为26根合成行情、1中心及2邻点；SE自检为1000日、1中心、2邻点、1000次重抽样。邻域生成另测5/6个可变轴和9个固定轴；交付测当前CN混合参数完整集成场景。

| 接口／操作 | 工作量／条件 | 中位耗时（ms） |
| --- | --- | ---: |
| `prepare` | 首次，1次 | 251.878 |
| `prepare` | 同会话输入复用 | 18.404 |
| `ParameterEvaluationPlan.create` | 1中心+2邻点 | 3.486 |
| `ParameterEvaluationPlan.bind_point` | 绑定1邻点，直接返回执行句柄 | 1.491 |
| `build_parameter_neighborhood_design` | 5可变轴+9固定轴，242邻点 | 64.942 |
| `build_parameter_neighborhood_design` | 6可变轴+9固定轴，728邻点 | 202.060 |
| `assess_candidates` | 完整事实输入，含重抽样 | 135.588 |
| `assess_candidates` | 轻量邻点输入，含重抽样 | 142.713 |
| `assess_candidates` | 轻量邻点+已有Bootstrap | 4.933 |
| `compare_candidates` | 3候选 | 0.521 |
| `paired_stationary_bootstrap` | 1000日×1000次，完整三指标 | 174.521 |
| `evaluate_many` | 每批3个合成账户 | 220.087 |
| `build_assessment_evidence` | FULL，已完成结果 | 4.490 |
| `build_assessment_evidence` | PARAMETER_PERFORMANCE，已完成结果 | 3.249 |
| `publish_evidence_many` | 3结果首次发布，1次 | 367.588 |
| `publish_evidence_many` | 3结果同会话复用 | 20.243 |
| `publish_evidence` | 1结果同会话复用 | 6.719 |
| `CheckpointStore.save_equity_result` | 3结果首次保存，1次 | 325.518 |
| `CheckpointStore.save_equity_result` | 3结果共享材料复用 | 16.183 |
| `CheckpointStore.load_equity_result` | 新store恢复3结果，1次 | 26.795 |
| `CheckpointStore.load_equity_result` | 3结果有界材料缓存复用 | 20.739 |
| `materialize_equity` | 闭包已有内存字节 | 0.290 |
| `materialize_equity(...).payload` | 完整独立可变快照 | 3.523 |
| `build_equity_assessment` | FULL | 4.515 |
| `build_equity_assessment` | PARAMETER_PERFORMANCE | 3.587 |
| `assemble_delivery` | ASSESSMENT / INTEGRITY | 63.279 |
| `validate_delivery` | ASSESSMENT / INTEGRITY | 24.839 |

完整与轻量自检都包含同一Bootstrap成本；此小邻域规模下两者差异受测量波动影响。使用匹配的已有Bootstrap后，自检直接复用区间；不据此承诺全研究提速倍数。

### 已发布 S019 邻点只读样本

C0966_P000三份依赖合计125,028,804字节，另有约1.95 MB结果头。下列计时从已加载的不可变字节开始，包含JSON解码、校验及对象构造，排除磁盘读取和材料对象首次哈希；3次中位数。

| 接口 | 耗时（ms） | 大材料JSON解码次数／调用 |
| --- | ---: | --- |
| `materialize_equity` | 26.404 | 0，仅结果头 |
| `materialize_equity(...).payload` | 2401.839 | 3：输入+候选+基准 |
| `build_equity_assessment(FULL)` | 2169.288 | 2：候选+基准 |
| `build_equity_assessment(PARAMETER_PERFORMANCE)` | 1999.753 | 2：候选+基准 |

整个串行基准进程峰值工作集为806.5 MiB；这是进程累计峰值，各接口另记录调用前后RSS，不将其当作单接口峰值。真实轻量投影仍以两份大型JSON的解析为主要成本。

逐次耗时、输入规模、JSON解码字节及内存记录见[本次原始结果](../../.tmp/stage4-interface-benchmark/final/metrics.json)。这是当前接口延迟基线，没有将不同规模、不同缓存状态的数字当作旧版对照。

邻域优化通过结果等价测试保持旧设计SHA、点序及剔除计数；固定轴的512倍重复中间组合采用重复次数汇总。普通发布和汇总的零账户重放、Bootstrap复用的零重采样、共享材料读取次数通过聚焦测试验证。

### 当前接口迁移

- 使用`plan.bind_point(reference, index, prepared, execution=execution)`直接获取绑定句柄；已绑定请求再次`prepare`会明确拒绝。
- 邻点使用`AssessmentProjection.PARAMETER_PERFORMANCE`；中心所需完整观察使用`FULL`，两者共享优化后的投影实现。
- 历史自检／比较复算函数和旧球面生成器别名已删除；历史类型仅保留只读解析。
- 单项与批量证据发布共用当前实现，活动会话显式传入`execution`。
- 平台源码指纹变化会使旧执行检查点与新实现不同；已有账户证据保持原身份，真实研究续跑由RSCH迁移调用后单独执行。

### 2026-11-11 回放热路径整改复测

对照版本为`dc2d114ce`，整改版本为本节随附实现，源码快照见[文件哈希清单](../../.tmp/stage4-e2e-v2-12/source_manifest.json)。Windows 11、Python 3.12.10、8物理核/16逻辑CPU、约128 GiB内存；12工作进程，原生库1线程，单个进程池执行两批各12账户。复用同24个C0966已发布邻点，每账户1212交易日、15702次M30决策，额外计算1个共享基准账户。两版均使用同一轻量投影及发布流程。

| 操作 | 整改前（秒） | 整改后（秒） | 耗时变化 |
| --- | ---: | ---: | ---: |
| 一次性准备 | 20.01 | 19.20 | -4.0% |
| `evaluate_many`，两批合计 | 309.40 | 231.34 | -25.2% |
| `publish_evidence_many`，两批合计 | 14.41 | 2.55 | -82.3% |
| 材料校验及轻量统计提取 | 42.24 | 44.15 | +4.5% |
| 账户批量处理全流程 | 366.12 | 278.11 | -24.0% |
| 完整进程，含准备与收尾 | 386.84 | 298.55 | -22.8% |

执行器内部COMPUTE墙钟从264.02秒降至204.81秒，CHECKPOINT从33.94秒降至12.78秒；内部阶段计时存在流式处理嵌套，须以接口外层计时计算总耗时。24账户的输入、交易、权益、NAR、Calmar、MDD及引用关联逐项一致；实现指纹引起的所有者和决策标识变化按决策顺序归一后比较完整经济内容。校验见[对照结果](../../.tmp/stage4-e2e-v2-12/comparison.json)，原始耗时见[整改前](../../.tmp/stage4-e2e-v2-12/before-metrics.json)和[整改后](../../.tmp/stage4-e2e-v2-12/after-metrics.json)。

整改包含有界历史窗口缓存、同进程强类型直接转换、共享输入一次二进制编码及工作进程复用、账户JSON单次编码、原始材料检查点和发布硬链接。实测50份材料及结果头复用同一文件实体；检查点与发布目录按文件实体去重后合计1,626,413,437字节，见[存储检查](../../.tmp/stage4-e2e-v2-12/storage-check.json)。逐决策计算保留内存处理，按完成账户提交可恢复检查点并保留必要的flush/fsync；正式证据继续使用规范JSON。

本次为单次顺序对照，操作系统页缓存未清空，24个样本均采用C0966硬退出。剩余1515账户按第二批稳态吞吐外推约4.53小时，样本均值外推约4.88小时；其他候选的渐进退出、调用迁移及最终自检交付另计。真实S019保持暂停，本次输出全部在隔离的`.tmp/`目录。聚焦验证共129项通过，覆盖经济等价、类型边界、缓存隔离、共享内存取消释放、检查点损坏、发布失败及冻结/前瞻入口。
