# 研究平台工具优化技术方案评审

状态：已确认研究员掌握研究控制流程，平台实现被调用的业务操作并保证技术契约；正式研究经TDR／REX受管入口执行。具体契约和API方案待评审。
所有“拟新增／拟修改”接口尚未实现。

批次A的字段、调用顺序、单次执行留证及并发验收详见[批次A详细设计](RESEARCH_TOOLS_BATCH_A_DESIGN.md)。
与本概览同一事项的更细约束以该详细设计为评审对象。

日期：2026-10-01。身份：DEV。评审分支：`codex/research-tools-design-review`。
实现基线：`b9bc8442`。需求依据：[RSCH Agent](../research/RSCH_AGENT.md)、
[交付与候选契约需求](RESEARCH_DELIVERY_CONTRACT.md)及本会话已确认的平台边界。
本轮仅形成方案；不修改研究协议、平台实现、历史证据或冻结版本。

## 1. 评审结论与优先级

建议以“受管实验语义 → 稳定候选及评价身份 → 阶段交付 → 自检排序 → 技术检验及批准冻结”
为依赖顺序实施。复用已完成的DFLS本地缓存、SRT执行合同、SE账本比较和增强预检。
Optuna保持独立使用；可选适配器延后，根据实际重复代码与性能收益另行评审。

| 优先级 | 当前事实与风险 | 建议修改 |
| --- | --- | --- |
| P0 | REX的`FORMAL`强制封存验证且禁止搜索／选参；与RSCH阶段四正式执行开发池自检的要求冲突 | 分离受管执行模式和数据使用范围；两者分别强类型声明 |
| P0 | `StrategyCandidate`是不可变运行输入，但相同族内ID可在不同进程绑定不同内容；运行身份哈希包含候选ID | 增加独立内容指纹；汇总和登记时拒绝同ID异内容；持久登记用于交接与冻结，不要求每个trial登记 |
| P0 | 新冻结API已删除旧依赖但尚未提供；`StrategyVersion`仍只解码历史schema 1/2/3治理结构 | 新增候选技术检验、批准绑定及事务冻结；同步升级版本读取与治理验证 |
| P1 | 阶段二至五依赖研究代码手工组装交付，机器事实和报告缺少统一引用约束 | TDR提供薄产物抽象及统一组装、校验入口 |
| P1 | SE旧筛选／排序会行为去重、采用非劣门槛和中位分数；与当前RSCH七项顺序不同 | 新增明确的研究比较契约；复用纯数值函数，禁止直接套用旧排序政策 |
| P1 | TDR持有评价预算并在成功后才记评价追踪，混合研究停止政策和执行记录 | 删除平台评价预算控制；增加每次调用的输入、状态、耗时、错误及结果留证 |
| P2 | CAP占位部分落后于实现或已确认决定 | 实现验收后按真实状态回填，不把占位当作可调用API |

证据入口：REX [定义合同](../packages/research_experiment/src/research_experiment/contracts.py)、
TDR [实验上下文](../src/czsc_trader/research_tools/experiment.py)、
SRT [候选模型](../packages/strategy_runtime/src/strategy_runtime/models.py)、
SE [既有排序](../packages/strategy_evaluator/src/strategy_evaluator/evaluator.py)、
SM [版本模型](../packages/strategy_manager/src/strategy_manager/models.py)和
[治理读取](../packages/strategy_manager/src/strategy_manager/registry.py)。

本轮用合成值调用公共接口复核了三项事实：`FORMAL`缺少后续验证截止日时被拒绝，
声明搜索能力时被拒绝；同一候选ID可构造两个不同payload的运行对象；`pareto_layers`
接受指标键集合不同的候选并按交集分层。前两项分别体现当前语义和未持久登记的边界，
并非绕过现有校验。复核没有读取行情、执行研究或写入治理区。

## 2. CAP需求校准与模块边界

| 需求 | 已有可复用能力 | 本方案增量与归属 |
| --- | --- | --- |
| CAP-01 | REX定义、结果、回执、受管产物；TDR文件化评价发布 | TDR阶段产物、目标合同、证据引用及双产物组装；SM持久候选身份 |
| CAP-02 | FSC信息族、因子、信号定义及目录查询 | FSC仅补定义指纹；REX保留检验证据，TDR组件面板承载职责和研究判断 |
| CAP-03 | 独立Optuna；REX执行配置；SRT候选spawn传输 | 独立进程评价及可序列化执行记录；研究代码控制搜索预算和调度；不向TDR/REX引入Optuna依赖 |
| CAP-04 | `LocalCacheConfig`、三种缓存策略、SRT准备结果校验、DFLS依赖注入 | 复用当前接口；先量测命中率、准备耗时和内存，再决定是否做内部性能优化 |
| CAP-05 | 完整SRT/TXE评价、显式整手回测、`compare_ledgers`及独立账本审计 | 补评价身份、归因的成对上下文校验和证据引用；不新增通用归因框架 |
| CAP-06 | 参数邻域、压力、Bootstrap、PBO、DSR、帕累托数值函数 | SE强类型自检面板和明确排序算法；TDR组合执行和派生候选关联 |
| CAP-07 | `StrategyCandidate`、历史`StrategyVersion`查询和包校验 | SM登记／决定／冻结事务，TDR技术检验及操作编排，SRT读取新版本 |
| CAP-08 | 已更新的六模块README、公共导出和研究库说明 | 跟随每批实现更新签名、示例和能力状态；暂不增加独立能力查询服务 |

需要修订的需求文字：RSCH附录CAP-03“REX/TDR适配Optuna”及研究库说明的统一搜索协调占位，
改为独立第三方调用、通用留证和可选独立适配包。CAP-04、CAP-05标识为已具备基础能力、
剩余增强待验收。本次保持需求原文，待方案批准及相应实现后同步。

依赖方向保持：TDR调用各模块；SM使用自身标准库值对象，避免反向依赖SRT或TDR；
REX不导入TDR；SE只接收数值及身份合同。FSC不保存每次实验的绩效结论。
不增加阶段四／五流程基类，不恢复候选包或CIO裁定对象，不新增DFLS snapshot API。

### 2.1 已确认原则与RSCH导入范围

用户已确认：正式研究执行统一通过TDR／REX受管入口。具体落实为：REX定义实验及端口合同，
TDR创建平台上下文、按显式配置执行调用、认证输入并生成回执；研究员仍可直接组合公共定义类型、
纯计算函数和已授权第三方库。研究员负责机制、方法、搜索空间、预算、调度、重试、剪枝、停止及
结论解释；用户批准阶段推进、候选选择与冻结。平台验证输入、数据范围、身份、结果和证据，
按明确授权完成持久化。平台不新增研究阶段状态机，不自动判定研究充分、完成或进入下一阶段。

| RSCH可导入模块 | 允许直接处理的工作 | 正式执行或写入入口 |
| --- | --- | --- |
| `dataflows` | `Dataset/DataRequest/DataResult/DataIdentity`等合同及`LocalCacheConfig`配置 | 正式输入通过`context.data.fetch`；缓存配置交给上下文工厂，研究代码不绕过端口访问供应商 |
| `factor_signal_catalog` | 信息族、因子、信号定义与只读目录查询 | 定义引用进入实验和组件面板；公共目录修改属于另行授权的平台维护 |
| `strategy_template_catalog` | 模板定义、查询和构造策略原型 | 模板实例进入源码绑定；自定义策略仍允许 |
| `research_experiment` | 实现`ResearchExperiment`，构造定义、合成预检和结果，读取认证前驱 | 实验通过TDR `execute_experiment`；研究代码不自行构造平台回执 |
| `strategy_runtime` | 实现`StrategyImplementation`，构造候选、参数、输入和执行合同 | 正式实验用`context.runtime.describe/create`，完整账户用`context.evaluation.evaluate` |
| `trading_execution_engine` | 执行结果类型；合成测试与专门执行诊断 | 正式账户由TDR驱动SRT／TXE，独立调用产生的诊断不能直接充当正式评价回执 |
| `strategy_evaluator` | 账本审计、比较、统计、自检、排序等公开纯计算 | 可在`ResearchExperiment.execute`内直接调用；输入评价身份、协议和结果纳入实验产物及回执 |
| `strategy_manager` | 身份类型及候选／版本／生命周期只读查询 | 候选登记、决定记录和冻结统一从TDR `application`进入 |
| `czsc_trader.research_tools` | 实验工厂、预检和执行、评价与产物类型 | 正式账户只用上下文评价端口；模块级`evaluate_strategy`保留给平台适配和明确的非正式调用 |
| `czsc_trader.application` | 登记、查询、回测、交付、技术检验、决定记录与获批冻结 | 入口按操作校验合同和引用；独立回测不自动产生REX正式实验回执 |
| 已授权第三方库 | Optuna搜索；tsfresh特征提取；expr_codegen表达式生成；pandas／NumPy等计算 | 在实验定义中声明实际依赖和能力，账户评价仍回到受管端口 |

RSCH使用各模块的顶层公共导出；私有实现和文件布局不作为调用合同。以上是研究员调用规范及
平台受管路径的验证要求，不声称普通Python能够阻止任意import、文件读取或恶意代码执行。
本次不引入Python安全沙箱或任意代码隔离系统。

### 2.2 正式执行链与各入口责任

```text
RSCH编写ResearchExperiment与StrategyImplementation
  → TDR加载绑定、预检、创建正式上下文
  → TDR execute_experiment
      → context.data.fetch：校验数据范围，记录输入身份
      → context.runtime.describe/create：校验候选和运行范围
      → context.evaluation.evaluate：认证实际候选，校验本次配置，执行SRT／TXE，记录调用事实
      → SE／第三方纯计算：研究员组合，协议、输入引用和结果写入ExperimentResult
  → 平台核验结果及产物，生成实验回执
  → TDR组装阶段交付；SM写入由TDR业务入口调用
```

`ResearchExperiment.execute(context)`内不得另建`Dataflows`、裸调用`evaluate_strategy`或启动
独立`run_backtest`来替代正式输入和账户评价。正式上下文保留平台拥有的适配器，禁止注入研究员
自定义评价器；探索上下文允许已声明的测试适配。第三方计算函数不逐个增加同义TDR包装。

直接调用`SE.assess_candidates/compare_candidates`属于实验内部数值计算；正式交付要绑定其
输入评价身份、冻结协议和实验产物引用。独立诊断结果如需进入正式证据，须在正式实验中按相同
合同复算或验证已受管的来源，不允许通过补填身份字段把非受管运行标成正式运行。

预检及受管端口校验调用合同；回执和交付校验认证来源及结果完整性。源码扫描只能提示绕行风险，
不把“未扫描到违规导入”作为执行隔离证明。用户决定来源及具体冻结批准继续独立核验。

### 2.3 公共导出与实现约束

- `czsc_trader.research_tools.__all__`暴露RSCH需要的实验、评价和产物合同；
  现有`evaluate_strategy`保留明确的平台适配用途，不复制成第二个正式评价入口。
- `czsc_trader.application.__all__`选择性导出业务操作；新增操作返回具体强类型结果，
  不再套一层内容无约束的同义服务。
- SM `register_candidate/record_research_decision/freeze_version`是TDR调用的模块公共API；
  不列入RSCH可直接执行的写操作清单。SM仍自行校验身份和事务，不能只依赖TDR前置检查。
- SRT作者接口和SE纯计算接口保持各自顶层导出；DFLS供应商、TDR内部评价实现及SM文件写入函数
  不因本轮重构新增为RSCH接口。
- 批次验收增加公开导入示例及跨模块主链测试：正式上下文拒绝自定义适配、数据范围越界、
  候选错绑、非法执行配置及伪造结果引用；正式交付保留SE计算协议和原始证据身份。

## 3. 先修正执行和数据范围契约

### 3.1 REX：`ExperimentDefinition`及正式上下文

拟修改REX顶层导出的`ExperimentDefinition`，新写入使用schema 2，新增必填
`data_scope: ExperimentDataScope`，枚举为`DEVELOPMENT`、`SEALED_VALIDATION`。
保留`ExperimentMode.DISCOVERY/FORMAL`；`FORMAL`只表示平台受管、预检、绑定及回执要求。
这里的schema 2指实验定义；源码绑定`ExperimentBinding`继续使用现有schema 3，版本号相互独立。

| 执行模式／范围 | 搜索及选参 | 数据上界与前置条件 |
| --- | --- | --- |
| `DISCOVERY + DEVELOPMENT` | 按声明能力校验，研究代码控制搜索 | `development_cutoff` |
| `FORMAL + DEVELOPMENT` | 按声明能力校验，研究代码控制搜索 | `development_cutoff`；正式源码绑定、预检和回执 |
| `FORMAL + SEALED_VALIDATION` | 禁止 | 显式`validation_cutoff`、封存区读取能力及相应用户授权来源 |
| `DISCOVERY + SEALED_VALIDATION` | 拒绝 | 不提供此组合 |

同步修改TDR `create_formal_experiment_context(...)`、`create_experiment_context(...)`的校验，
使`data.fetch`、`runtime.create`和`evaluation.evaluate`的实际范围由`data_scope`决定。
预检只探测开发区，封存区访问在正式执行授权后发生。不得因传了cache、已有目录或缺字段推断数据范围。
读取开发池并完成正式归档的结果，仍标识为开发证据。

历史schema 1按原字段解码并校验原始哈希；不改写绑定、回执或实验。新提交只接受schema 2，
禁止把旧`FORMAL`自动解释为新开发池正式实验。模式迁移不授予任何新数据权限。

### 3.2 REX端口与TDR评价尝试

现有`ExperimentDataPort.fetch(object) -> object`改为`fetch(DataRequest) -> DataResult`；
REX声明对DFLS的直接类型依赖。`ExperimentRuntimePort.describe/create`使用现有SRT输入／输出类型。
评价端口使用请求／结果类型参数，在TDR绑定为`EvaluationRequest/EvaluationResult`，避免REX导入TDR。

保留`context.evaluation.evaluate(request)`这一调用入口，拟作以下修改：

- 删除TDR `_EvaluationBudget`及扣减调用；REX新`ExperimentResources`删除`max_evaluations`；
  上下文工厂、预检及TDR `preflight_experiment_archive`同步删除预算必填检查和参数转传。
  历史资源字段仅在旧证据解码中按原算法验真，新公共调用不接受该字段。
- 增加强类型单次执行记录：attempt ID、请求及实际候选身份、状态、开始／结束时间、耗时、
  已完成坐标数、错误及结果引用。状态只表达调用事实，不提供任务调度、重试或研究停止控制。
- 出参及持久化成功后记录`SUCCEEDED`；异常记录`FAILED`；明确取消记录`CANCELLED`；
  中断后无法核实结果的记录呈现`UNKNOWN`。平台不静默重试，研究员决定是否再次调用。
- 支持研究代码自行建立进程池：各进程创建绑定同一实验身份的正式上下文并隔离工作目录，
  返回可序列化执行记录。平台校验提交记录的身份、文件哈希、重复ID和结果覆盖。

`max_workers/native_threads_per_worker`保留为单次执行配置，不作为整个研究搜索的并发配额。
搜索预算、Optuna Study、sampler、ask/tell、任务分发、剪枝与接续均由研究代码控制；
预算和实际搜索轨迹可作为协议及证据留存，平台不据此自动停止搜索。
记录使用每次调用独立的产物及原子发布，不建设共享预算数据库或全局调度器。
归档校验已声明的记录集合，不声称掌握研究进程之外未提交的全部尝试。

## 4. 候选、评价、派生和批准的强类型身份

### 4.1 SRT：维持一个可执行候选对象

保留`StrategyCandidate`及其现有`runtime_identity_sha256`算法；该哈希含族及候选ID，不能直接
用作独立于ID的内容指纹。拟在`StrategyRuntime`增加：

```python
def identify(self, candidate: StrategyCandidate, *,
             dependencies: tuple[ImplementationDependency, ...]) -> CandidateContentIdentity: ...
```

`CandidateContentIdentity`包含`schema_version`、`content_sha256`、`source_sha256`和
`dependency_sha256`。指纹来自已验证源码闭包、运行合同、固定标的和输入绑定、完整生效参数、
固定执行政策及声明依赖；排除候选ID、机器绝对路径、报告、评价窗口、资金和压力场景。
依赖记录区分策略声明依赖与本次评价实际环境，未声明代码或依赖不得被目录碰巧存在所掩盖。
默认参数须先由运行定义物化；不能直接对未解析的payload做哈希就宣称“有效参数相同”。

### 4.2 SM：登记身份，TDR：认证源码及装配候选

拟新增SM值对象：

| 类型 | 必填内容／约束 |
| --- | --- |
| `CandidateKey` | `strategy_id`、族内`candidate_id`；格式校验，ID不可回收 |
| `CandidateRegistration` | key、内容指纹、payload哈希、受管源码／依赖清单引用、来源实验及登记记录哈希 |
| `CandidateDerivation` | parent、child、派生类型、变化参数和协议引用；父子不能相同，归属和实际执行对象分开 |
| `EvidenceRef` | 受管根目录标识、相对路径、SHA-256、格式／schema版本；拒绝绝对路径、越界、逃逸链接及缺失文件 |

`CandidateRegistration`只承载身份登记信息，运行输入仍为SRT `StrategyCandidate`。
源码按内容哈希放入受管不可变文件区，多个候选可引用同一源码闭包；不复制一套独立候选包对象。
候选元数据建议由SM管理在`research/registrations/<family>/candidates/`，与既有族登记相邻；
注册写入由公共API完成，SM的查询索引可重建，不能成为第二份内容真相。

拟新增公共入口：

| 模块／公共API | 行为 |
| --- | --- |
| TDR `application.register_candidate(context, request: CandidateRegistrationRequest) -> CandidateRegistration` | 输入现有候选、来源实验定义／绑定及预检引用、依赖和可选派生关系；通过SRT认证后委托SM登记；用于持久查询、跨阶段交接和冻结 |
| TDR `application.load_candidate(context, key: CandidateKey) -> StrategyCandidate` | 验证登记、文件哈希、依赖和运行定义，返回同一候选身份 |
| SM `StrategyRegistry.register_candidate(record: CandidateRegistration) -> CandidateRegistration` | TDR平台适配调用；原子创建，同key同内容返回既有记录，同key异内容抛`CandidateIdentityConflict` |
| SM `StrategyRegistry.get_candidate(key: CandidateKey) -> CandidateRegistration` | 只读查询；缺失抛明确错误 |

无变化的重复提议可引用既有候选；不同ID即使内容相同仍保留。参数、源码或固定规则变化必须新ID。
研究登记不表示达标、被选择或已批准冻结。

评价直接认证不可变候选及内容指纹，不要求每个trial预先写入SM。研究代码负责并发候选ID分配；
实验汇总、交付及登记拒绝同key异内容。尚未登记或汇总的独立进程之间不提供全局实时唯一性保证。
结果始终绑定key和内容指纹，持久登记前后保持候选身份，不能通过重新编号改变证据归属。

### 4.3 TDR：评价身份与派生归属

拟扩展`EvaluationResult`和`EvaluationRun`，保留已有`request_hash/result_hash/data_identity`，
增加强类型`EvaluationIdentity`：实际候选key及内容指纹、评价协议哈希、实际输入身份、执行与指标
语义版本、运行环境身份、评价ID。按每个候选／窗口／场景保存评价身份，不能只给整个批次一个ID。

请求身份表达输入意图，评价ID绑定实际认证后的输入与语义，attempt ID区分同一评价的重复尝试。
费用、初始资金或窗口变化产生新评价ID；修改候选固定交易规则产生新候选ID。
不通过修改候选payload表达临时成本压力。`BacktestRequestV2.lot_size`继续必填且与候选一致。

`EvaluationRequest`拟增加`lineage: EvaluationLineage | None`：中心和实际候选的key及内容指纹、
研究员声明的派生关系与来源证据引用；无须提前登记父子候选。
普通评价使用`None`；扰动评价必须核对实际请求候选为child，汇总归属为parent。
正式排序集合由阶段三交付显式确定，不能通过收集全部评价行推断。

行为分组引用同一评价上下文和`compare_ledgers(ECONOMIC)`结果，保留全部候选成员。
带容差的等价关系不保证传递，不能直接作为哈希或连通分量去重；首版只对精确相同行为分组，
近似行为以成对比较单列。归因由研究员提出对照，平台核对差异因素和同口径账户，并保留反事实标签。

## 5. TDR阶段交付及组件面板

### 5.1 薄产物抽象与统一组装

拟在`czsc_trader.research_tools`导出`ResearchDeliverable[T]`抽象基类，仅要求只读
`definition: DeliveryDefinition`与`build() -> DeliveryContent[T]`。它描述交付内容，不调度实验、
不审批阶段、不执行冻结。TDR仅提供一组公共组装与读取校验入口：

```python
def assemble_delivery(context: RepositoryContext,
                      deliverable: ResearchDeliverable) -> DeliveryReceipt: ...
def validate_delivery(context: RepositoryContext,
                      reference: DeliveryReference) -> DeliveryValidation: ...
```

拟在`czsc_trader.application`导出这两个业务入口；同一个实现，不再加同义包装。
`DeliveryDefinition`绑定族、阶段、修订号、父交付、目标合同、输入批准和来源实验回执。
`DeliveryContent[T]`包含强类型阶段事实、证据引用、解释、覆盖、复算入口及未完成事项。
五个具体内容类型分别承载任务合同、组件面板、候选集合、候选比较、技术检验与冻结交付。
研究方法的扩展区采用显式schema及版本验证，不能用无约束`dict[str, Any]`替代核心身份和状态字段。

`ResearchMandate`明确标的、可投资基准、期限、用户目标与约束、默认执行规则、数据／资源范围，
逐项绑定`ConfirmationRecord`；建议项与已确认项使用不同状态。目标验证只使用已确认项目，
诊断字段不能被自动提升为经济否决条件。阶段一允许带未确定项交付，进入后续阶段所需项必须明确。

产物状态使用`COMPLETE/PARTIAL/BLOCKED`，与`ValidationStatus.PASS/FAIL`分别记录。
完整的负面研究或空组件面板可以是`COMPLETE`；缺失关键证据为`PARTIAL/BLOCKED`，不填零。

机器文件和报告由同一`FactValue`及`EvidenceRef`渲染；报告数值通过事实引用生成。
`Explanation`明确`FACT/HYPOTHESIS/STATISTICAL_EVIDENCE/RESEARCH_JUDGMENT`、依据和不利证据。
平台保证引用字段一致，无法证明自由文字没有事实错误；自由解释仍由研究员复核，不能宣称全文自动认证。
报告同时保留方法限制、样本重叠、已见数据、搜索选择历史和未完成事项。

组装过程先写`.tmp/`暂存目录，校验完整后发布不可变修订；所有依赖应已复制或引用受管正式证据，
拒绝发布仍依赖`.tmp/`缓存的交付。重复相同内容幂等返回；同修订异内容拒绝。
批准后追加决定记录，保留原“待决定”交付和原排名。

### 5.2 FSC定义与研究证据分工

拟为FSC `FactorDefinition/SignalDefinition`增加只读`definition_sha256`属性，基于现有规范化
定义字段计算，不引入组件资格状态，也不把一次实验结论写入共享目录定义。

TDR `ComponentPanel`包含`ComponentEntry`及完整`ComponentTestResult`序列：
定义引用（FSC ID／版本／指纹，或实验源码绑定的自定义定义）、职责、标签、期限、对照协议、
数据可用时点、价格口径、适用边界、研究判断及证据。
结果状态为`SUPPORTED/INEFFECTIVE/NOT_APPLICABLE/INSUFFICIENT_DATA/TECHNICAL_FAILURE/REDUNDANT`；
状态由研究员依据检验解释给出，平台验证字段和依据，不自动授予有效组件资格。
标签、期限及对照绑定执行前实验定义；全部已执行检验与尝试台账对账，包括失败和无效结果。

无需新增“组件认证服务”。组件面板与第三阶段`SearchRecord`都通过统一交付API组装。
`SearchRecord`只定义参数域、sampler名称／版本、预算、种子、调度、proposal ID、
trial状态、评价引用及后继关系；Optuna对象不进入跨模块合同。

## 6. SE标准自检与研究排序

### 6.1 明确公共计算入口

拟在SE新增两个纯计算API：

```python
def assess_candidates(request: CandidateAssessmentRequest) -> AssessmentPanel: ...
def compare_candidates(request: CandidateComparisonRequest) -> CandidateComparison: ...
```

研究代码调用现有`context.evaluation.evaluate`产生账户事实，再直接调用SE纯计算API。
参数扰动计划、不可变child候选及父子关系由研究员生成；需要持久交接时再登记。
阶段四的实验安排和结果解释由研究员负责，TDR提供评价及交付组装操作。

`CandidateAssessmentRequest`绑定显式中心集合、全部派生关系、评价身份及`SelfCheckProtocol`。
协议包括扰动域／尺度／权重、窗口长度／步长、分位算法、压力场景、单位、最低覆盖和缺失语义。
每项计算返回`DiagnosticValue`，状态为`AVAILABLE/NOT_APPLICABLE/INSUFFICIENT_DATA/FAILED`；
非AVAILABLE必须有原因和证据，禁止将缺失值填零。

五项自检主指标严格沿用RSCH第3.4节：

| 自检 | 固定计算口径 |
| --- | --- |
| 参数敏感性 | `max(0, 中心净年化 - 联合扰动净年化Q10)`；`max(0, 联合扰动回撤幅度Q90 - 中心回撤幅度)` |
| 时间稳定性 | 同窗口策略累计收益减同口径基准累计收益，再取Q10；不是先分别取分位数后相减 |
| 收益集中性 | 按净损益排序的前`ceil(0.1 × 盈利闭合交易数)`笔盈利／全部盈利闭合交易正净损益；无盈利为不适用 |
| 执行敏感性 | 标准净年化减指定压力净年化，保留负值；未测执行条件单列 |
| 统计不确定性 | 配置超额收益区间与研究族选择偏差分开；PBO、DSR与重叠数据限制不进入配置排名 |

复用现有Bootstrap、邻域和压力计算前核对公式；旧函数返回的风险门槛不能直接用作新排序。
闭合交易净损益需与账户及未平仓损益对账；分红等未支持的执行条件要明确标识覆盖限制。
辅助指标相关性、恒等关系和共享分母进入诊断记录，不自行更换主指标或合成分数。

### 6.2 排序合同及现有API修订

`CandidateComparisonRequest`含已确认`ResearchTargets`、面板和`ComparisonPolicy`。
SE只接收数值目标，用户确认来源由TDR在调用前验证，避免SE依赖治理模块。
`ComparisonPolicy`固定指标方向和七项优先级；可配置版本化精度、原点、舍入、缺失处理及敏感性集合。

执行顺序：目标核验 → 达标且可比分组 → 净年化／最大回撤幅度帕累托层 → 七项字典序 → 行为分组展示。
频率区间内同等达标；七项依次为净年化、回撤幅度、扰动年化退化、扰动回撤恶化、滚动超额Q10、
执行压力年化损失、盈利集中度，方向按RSCH原文。ID只用于稳定展示，全部同档必须并列。
分层使用原始有限值的支配关系；分箱用于层内同档判定，避免模糊容差破坏排序传递性。
分箱边界、精度及相邻优先级交换作为独立敏感性结果，不改写基准排名。

输出保留每个候选的`TARGET_NOT_MET/INCOMPARABLE/RANKED`及原因，未达标或缺失项不会消失。
无盈利导致集中度不适用时仍保留其他自检；若影响七项完整比较则按协议标为不可比。
不得把某候选另一源码的指标补入面板，不得自动将扰动候选加入中心集合。

现有`pareto_layers`保持签名，增加输入指标键完全一致、有限数值、候选ID唯一的校验；
不再按交集静默比较。现有`screen_candidates/rank_candidates`保持其既有语义，
在文档中明确适用的旧比较合同；新RSCH流程不调用它们，不用悄然改义制造兼容假象。

## 7. 技术检验、用户决定与冻结

### 7.1 最少业务入口

拟在TDR `application`新增：

| 公共API | 强类型输入 → 输出 |
| --- | --- |
| `inspect_candidate(context, request: CandidateInspectionRequest) -> CandidateInspectionReport` | 阶段四选择决定、候选key、证据清单、技术检验协议 → 逐项检验、覆盖、差异、环境和拟冻结内容摘要 |
| `record_research_decision(context, decision: ResearchDecision) -> DecisionReference` | 确认来源、作用域、目标交付／候选／检验摘要 → 追加的不可变决定引用 |
| `freeze_candidate(context, request: FreezeCandidateRequest) -> FreezeReceipt` | 已登记候选、技术报告、冻结批准、请求ID、父版本和版本说明 → 版本身份及事务状态 |
| `get_freeze_result(context, request_id: FreezeRequestId) -> FreezeReceipt` | 同一请求ID → 权威实际状态和已提交版本引用 |

`ResearchDecision.scope`区分`STAGE_ADVANCE/CANDIDATE_SELECTION/FREEZE`，
`action`区分`APPROVE/REJECT/DEFER`；冻结仅接受精确绑定key、内容指纹、技术报告哈希和拟冻结
内容摘要的`FREEZE + APPROVE`。方案通过、阶段推进或选择某候选都不能替代冻结批准。
接口记录用户决定来源，不凭一段调用方自填文字证明操作者已获授权；宿主负责取得并核对真实确认。

SM新增`StrategyRegistry.record_research_decision(decision: ResearchDecision) -> DecisionReference`
持久化不可变决定；由TDR验证阶段交付、文件和计算证据后调用，RSCH使用TDR入口。
决定记录不回写原排名。
技术报告区分`PASS/FAIL/INCOMPLETE`；其必检项由版本化技术协议声明，缺项不能PASS。
冻结只接受必检项通过；剩余非阻断风险须进入呈现给用户的同一报告。

### 7.2 技术检验内容及执行成本

技术协议覆盖源码／依赖闭包、SRT加载及能力、数据与评价身份、当前结果复算、独立账本审计、
信号与经济账本等价、拟冻结文件闭包。复用已认证证据须满足身份、方法版本和覆盖一致，
身份或方法变化则重新检验。调用方显式提交复算范围、执行配置及允许误差；
研究员依据自己的预算选择调用范围，平台按本次检验合同执行并报告覆盖。

当前`compare_ledgers(ECONOMIC)`仍比较附加诊断字段，调用方必须提交同口径完整证据；
不通过删除差异列或改写身份绕过失败。信号等价另行比较，账本等价不能替代信号与独立审计。
既有版本回测依赖部署凭据，新候选检验直接走候选SRT/TXE链路；不为检验自动部署。

### 7.3 SM事务与新版本合同

拟新增SM `StrategyRegistry.freeze_version(request: FreezeVersionRequest) -> FreezeReceipt`及
`get_freeze_result(request_id)`；TDR负责先认证并暂存文件，SM负责候选、批准、版本号和提交原子性。
冻结请求绑定文件清单哈希，SM再次核对文件及引用，不能接受任意调用方传`passed=True`。

`StrategyVersion`新增schema 4，使用强类型`CandidateOrigin`及`FreezeGovernance`记录来源候选、
内容指纹、技术报告、批准及冻结请求引用。新记录的release哈希覆盖规范化内容和治理来源，
明确排除哈希自身；文件manifest再绑定release哈希，避免互相包含形成循环。
同一提交统一修改SM读写／`validate_version_governance`、SRT `StrategyRelease.from_mapping`、
TDR `validate_release_package/strategy_info`及PTE版本读取测试。
历史schema 1/2/3沿原规则只读，不回填、不重签、不让schema 4落入当前“非3即旧接纳”分支。

冻结使用族级写锁、暂存校验和持久事务提交标记。提交标记是可见性边界，目录和索引出现不代表已冻结。
同请求ID同内容返回既有回执，同ID异内容拒绝；版本号冲突拒绝，不擅自换号。
查询状态为`NOT_FOUND/IN_PROGRESS/COMMITTED/FAILED/UNKNOWN`；只有`COMMITTED`可返回成功版本。
进程在提交前／后崩溃由查询区分；不在结果未知时重新发起不同请求，也不实现静默自动恢复。
正式版本、文件和治理记录完整且哈希一致后才能形成提交标记；暂存孤儿不计作成功版本。
现有查询、`validate_all`及部署可用性判断必须遵守该提交边界，避免读到半成品。

冻结不创建部署凭据或PTE账户，不改变prod；这些操作继续单独授权。

## 8. 实施分批、验收与待决定项

| 批次 | 交付边界 | 最小验收证据 |
| --- | --- | --- |
| A：受管实验及身份 | REX数据范围拆分并移除预算控制；SRT内容指纹；SM持久登记；TDR评价身份及失败留证 | 未登记候选可正式评价；独立进程并发与证据汇总；封存范围校验；同ID冲突、内容变化、失败attempt均覆盖 |
| B：阶段交付及组件 | 目标合同、薄产物抽象、双产物组装、组件面板、决定记录 | 空面板／无达标候选可完整交付；未确认目标不作硬门；引用逃逸／文件缺失／机器报告差异被拒绝；决定追加不改原件 |
| C：阶段四计算 | 派生候选关系、自检面板、显式排序合同、严格帕累托输入 | 已知支配／并列／缺失／边界分箱；压力改善保留负值；无盈利不填零；扰动不进中心池；全部达标候选覆盖；容差非传递不误分组 |
| D：检验及冻结 | 技术报告、新版本schema、批准绑定、SM事务和查询 | 错候选／过期指纹／缺批准／不完整检验拒绝；并发同版本冲突；提交前后断进程；同请求幂等；旧五个版本原哈希与读取行为保持 |
| E：可选性能 | 数据准备与并行性能优化；独立Optuna适配包可行性评估 | 相同研究侧搜索协议及输入的正确性对照、并发收益和内存指标；依据收益决定是否增加适配包 |

批次A需验证独立进程中的受管评价；后续性能优化仍遵守研究员控制搜索预算和编排的边界。
每批仅运行受影响模块和跨模块主链测试；版本验收再跑`scripts/test-all.ps1`。
本轮方案检查仅验证代码证据、公共导出、相对链接和接口归属；不以此前全量回归通过证明拟议API可用。

已确认的设计原则：研究员控制研究流程；正式研究执行通过TDR／REX受管入口保证技术契约；
平台不管理搜索预算、调度、剪枝或重试；评价不要求逐trial登记。模块导入及调用路径见第2.1—2.3节。
该原则确认不等于批准全部新增API或批次实施。

待评审的设计选择：

1. 采纳REX执行模式／数据范围拆分，使正式开发池研究与封存验证分开表达。
2. 采纳SM持久登记和事务冻结的具体契约，SRT保持单一运行候选对象；TDR完成单次业务操作的跨模块认证与调用。
3. 采纳薄产物抽象和SE两个明确计算入口；Optuna适配器及额外加速放到最后按收益决定。
4. 按A→B→C→D推进；已存在的缓存、整手执行及账本比较作为基础，不重复建设。

方案批准后先实施批次A。方案批准仅授权相应平台开发，不代表批准推进任何研究阶段、冻结具体候选、
合并、推送、创建版本tag或变更生产环境。
