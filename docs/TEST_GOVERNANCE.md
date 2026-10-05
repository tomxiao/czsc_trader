# 测试用例治理

本文规定CZSC Trader仓库的测试用例如何创建、收敛、执行和周期性审查。目标是在保护
TDR、DFLS、FSC、STC、SM、REX、SE、SRT、TXE、PTE和WDG关键业务能力的同时，控制TDD带来的
用例数量、回归耗时和维护成本。

这是一份面向个人量化团队（OPC）的操作规范。判断标准是业务风险和维护价值，不追求用例
数量、代码覆盖率或测试金字塔形式上的完整。

## 1. 治理原则

1. **稳定业务场景是长期测试资产。** 长期用例覆盖公开入口、核心数据流、关键失败路径、
   持久化结果和安全约束。
2. **每条独立风险有明确的主要所属模块和承接用例。** 模块用例保护计算语义、类型及数值边界；
   集成用例保护跨模块身份传播、调度、原子发布及失败状态。新风险优先复用合适的主例，
   同时保持独立失败的可定位性。
3. **TDD用例可以临时存在。** 最小失败用例用于快速定位和驱动实现；行为进入长期场景后，
   删除重复的细粒度用例。
4. **公开契约是主要验证目标。** CLI、公开业务API、强类型构造器及明确导出或文档化的
   模块API均可直接测试，断言可观察输出、异常、状态和持久化事实。私有辅助夹具及具体
   故障点注入可支持真实目标链；不要整体替换目标执行链，也不要为测试新增公共API。
   常量涉及公开序列化时通过序列化契约验证；机制断言作为必要的补充诊断。
5. **保持确定性和离线性。** 使用固定小数据、临时目录和本地模拟适配器，不连接Tushare、
   Futu OpenD、实时网络或Windows服务，不修改PTE生产共享状态。
6. **研究档案与功能回归分开。** 日常回归不重算历史候选全集；当前契约实验可校验
   清单、结构和哈希。历史原件供人工查阅，平台不承诺机器复验。
7. **用例规模是观测项。** 关注新增原因、重复程度、运行时间和诊断价值，不设置僵硬的数量
   或覆盖率门槛。

### 契约、参数和夹具

- 类型及纯计算使用最小合法输入；集成场景运行所属真实链路。供应商边界可替换底层
  HTTP或客户端响应，默认路由、转换、认证和发布逻辑保留实际执行。合法基线先通过，
  再单独变异目标字段，避免其他错误提前拒绝而造成假覆盖。
- 参数是否等价按业务风险、类型、执行分支、单位及时点判定。同为失败不能证明等价；
  不可用值与有限数值、bool与int、大小写、Unicode和换行差异分别核对。临界点及
  资金、费用、整手、因果时点、未知结果、证据认证和真实进程竞争独立保留。
- 参数保持独立可定位的测试节点，不改为循环隐藏数量。数学穷举的参考计算及需要
  共享状态的真实交互序列可以使用循环，并明确其观察范围。
- 昂贵不可变种子可在进程内复用；每个用例使用独立数据库、目录和执行状态副本，
  不修改共享种子。计算公式由所属模块负责，平台集成避免重复验证整套数值矩阵。
- 治理记录同时统计函数、参数节点和实际准备、回放、加载及子进程成本。迁移到其他
  模块不计为全仓降本；不同范围、并发负载或启动条件的耗时不直接比较。

### 临时目录约定

- 仓库内临时产物统一写入根目录`.tmp/`，该目录整体由Git忽略；
- Pytest每个进程使用`.tmp/pytest/run-<随机ID>`，结束时清理；Ruff缓存写入
  `.tmp/ruff/cache`；完整回归日志写入`.tmp/test-regression/run-<随机ID>`；
- TDR发布前暂存目录通过`czsc_trader.temp_workspace`创建，并按`backtest`、
  `market-data`、`backtest-update`、`intraday-data`和`evaluation`分区；
- 禁止新建`.pytest-*`、`.test-tmp`、包内`.pytest_cache`，也禁止把暂存目录放进
  `data/`、`outputs/`或实验档案目录；
- 操作系统及第三方库自行管理的系统临时目录不属于仓库资产。实验正式产物必须进入实验
  清单，不能放在`.tmp/`充当证据。

## 2. 用例类型与生命周期

### 2.1 临时TDD用例

临时TDD用例服务于当前功能或缺陷，生命周期为：

```text
复现失败 → 驱动实现 → 验证修复 → 并入长期场景 → 删除重复用例
```

使用要求：

- 先证明用例能因目标问题失败，再实现修复；
- 尚未完成收敛时，在用例旁标注`TEMP-TDD`及其目标行为；
- 修复完成后，检查已有功能场景能否承载该断言；
- 能承载时扩展主用例并删除临时用例；
- 只有满足长期准入条件时，临时用例才转为长期用例。

### 2.2 长期功能用例

长期功能用例归属单一模块，保护一个完整且稳定的业务场景。当前长期测试集中在：

- TDR：`tests/functional/`；
- SM：`packages/strategy_manager/tests/functional/`；
- REX：`packages/research_experiment/tests/functional/`；
- SE：`packages/strategy_evaluator/tests/functional/`；
- FSC：`packages/factor_signal_catalog/tests/functional/`；
- STC：`packages/strategy_template_catalog/tests/functional/`；
- DFLS：`packages/dataflows/tests/functional/`；TDR与SRT保留各自调用DFLS的集成场景；
- SRT：`packages/strategy_runtime/tests/functional/`；
- TXE：`packages/trading_execution_engine/tests/functional/`；
- PTE：`packages/paper_trading_engine/tests/functional/`。

每个场景应尽量从模块公开入口发起，并在一次流程中验证输入、主要状态转换、输出和关键
失败语义。测试名称描述业务行为，避免绑定内部类名或实现步骤。

### 2.3 跨模块端到端用例

端到端用例只保留少量关键调用链，例如TDR候选注册、交付、检验和冻结链路、SRT与TXE回放，以及PTE消费SRT决策并写入虚拟账户审计。
它用于发现契约断裂，不重复模块内部已经覆盖的所有边界条件。

涉及真实行情、Futu或Windows服务的在线检查属于交付验证，不进入默认自动回归套件。

## 3. 长期用例准入

新增用例至少满足以下一项：

- 保护新的独立业务能力或公开契约；
- 覆盖资金、订单、成交、策略身份、数据不可变性等高风险安全约束；
- 现有主场景无法清晰表达的重要失败路径；
- 曾发生且容易复发、现有场景无法捕获的缺陷；
- 跨模块边界需要独立验证，并且失败定位仍然清晰。

以下情况通常不新增长期用例：

- 仅验证私有函数、常量、内部调用次数或重构后的类结构；
- 同一业务行为换一组等价输入再次执行完整流程；
- 已由更高层场景稳定覆盖的薄封装；
- 只为提高覆盖率数字而触达无业务风险的分支；
- 依赖实时网络、当天行情、外部账户状态或执行顺序的脆弱检查。

新增长期用例时，在提交说明中回答：**现有哪个场景无法承载它，以及它保护什么独立风险。**

## 4. 用例收敛与删除

功能或缺陷进入稳定状态后执行一次收敛：

1. 明确本轮新增或修复的业务行为；
2. 找到该行为所属模块和现有主场景；
3. 列出原风险、所属公开契约、具体承接节点及预期观察，复用合适的夹具和数据准备；
4. 先运行承接用例，确认合法基线和目标边界通过，再删除已证明重复的用例；
5. 运行修改后的用例，并核对风险映射、当前节点清单及实际准备或回放成本；
6. 按受影响行为运行最小聚焦测试；用户要求全量验收后，通过统一入口执行完整回归。

可以删除的典型对象：

- 已被长期场景覆盖的`TEMP-TDD`用例；
- 输入和断言均高度重复的参数组合；
- 随实现重构而失去意义的内部结构测试；
- 永远跳过、依赖废弃接口或无法稳定复现的用例；
- 被一个更完整场景包含、失败时也不能提供额外诊断价值的用例。

删除测试必须说明覆盖迁移到哪里。若目标行为没有其他用例承接，应先补入主场景再删除。

## 5. 按风险运行回归

| 时机 | 最低验证范围 |
| --- | --- |
| TDD开发中 | 当前失败用例和直接相关场景 |
| 功能完成或缺陷修复后 | 覆盖受影响行为、输入输出边界、异常及必要跨模块契约的最小聚焦测试 |
| 提交前 | 聚焦测试及变更范围Ruff；实现未变化时复用本轮有效结果 |
| 用户要求全量版本或架构验收 | 全部模块功能用例、真实发布验收、PTE前端用例及Ruff；按变更范围增加完整链路验收 |
| 已验收后的纯文档提交、合并或推送 | 检查文档、链接和差异；实现未变化时复用已验收测试结果 |
| 服务或外部渠道变更交付 | 完整离线回归后，再执行明确授权的在线验证 |

完整离线回归默认使用仓库级并行入口：

```powershell
.\scripts\test-all.ps1
# 可显式降低活动通道上限，完整测试范围保持不变。
.\scripts\test-all.ps1 -MaxParallel 6
```

日常Pytest默认排除标记为`release_acceptance`的昂贵验收场景；显式传入
`--release-acceptance`时包含这些场景。完整回归脚本为所有Pytest进程传入该参数。

脚本固定划分八组：`TDR_FREEZE`、`TDR_1`、`TDR_2`、`PTE_1`、`PTE_2`、`TDR_RUNTIME`、
`DFLS`和`PACKAGES`。`MaxParallel`默认为8，允许1至8；较低上限使剩余组排队，不减少测试范围。
该参数限制同时活动的通道Job数量；用例内部创建的子进程和线程不计入此上限。

冻结及评估交付测试保持同组；其余TDR和PTE各按完整测试文件划分为两组，保留组内夹具复用。
第一组选择明确文件，第二组通过目录发现其余文件并排除已分组文件，新增TDR或PTE文件仍自动发现。
`TDR_RUNTIME`独立覆盖候选运行、SRT桥接、批量评价和输入绑定四个文件；这些文件从其他TDR组排除。
`DFLS`独立运行；其余七个子包在`PACKAGES`内串行运行，控制台Node测试仅在`PTE_2`执行一次。
各进程使用独立Pytest工作区、禁用Python字节码写入，并将BLAS等原生计算线程数设为1。
所有通道结束后统一运行Ruff、输出每条通道的耗时和退出码，
并把完整日志写入`.tmp/test-regression/`。每组保存`*-selection.json`选择清单，每个Python步骤
保存独立JUnit XML，记录逐项结果及耗时；完整验收核对收集清单与JUnit无遗漏或重复。
任一通道、Node测试或Ruff失败时，脚本整体返回失败。

需要定位失败模块时，使用以下串行命令单独复现：

```powershell
.\.venv\Scripts\python.exe -m pytest -c pyproject.toml tests -q
.\.venv\Scripts\python.exe -m pytest -c pyproject.toml packages\dataflows\tests -q
.\.venv\Scripts\python.exe -m pytest -c pyproject.toml packages\strategy_manager\tests -q
.\.venv\Scripts\python.exe -m pytest -c pyproject.toml packages\research_experiment\tests -q
.\.venv\Scripts\python.exe -m pytest -c pyproject.toml packages\strategy_evaluator\tests -q
.\.venv\Scripts\python.exe -m pytest -c pyproject.toml packages\factor_signal_catalog\tests -q
.\.venv\Scripts\python.exe -m pytest -c pyproject.toml packages\strategy_template_catalog\tests -q
.\.venv\Scripts\python.exe -m pytest -c pyproject.toml packages\strategy_runtime\tests -q
.\.venv\Scripts\python.exe -m pytest -c pyproject.toml packages\trading_execution_engine\tests -q
.\.venv\Scripts\python.exe -m pytest -c pyproject.toml packages\paper_trading_engine\tests -q
node --test-isolation=none --test packages\paper_trading_engine\tests\functional\console_state.test.mjs
.\.venv\Scripts\python.exe -m ruff check `
  src tests packages\factor_signal_catalog packages\strategy_template_catalog `
  packages\strategy_manager packages\research_experiment packages\strategy_evaluator `
  packages\dataflows packages\strategy_runtime packages\trading_execution_engine `
  packages\paper_trading_engine\src packages\paper_trading_engine\tests
```

上述Pytest命令执行日常范围；复现验收场景时补充`--release-acceptance`。
沙箱权限导致的管道、进程或本地Git失败，应与业务断言失败分开记录。

## 6. 周期性治理

活跃开发期间每月检查一次。当月没有测试变更时可以跳过。出现以下任一情况时提前触发：

- 全量回归耗时相对上次记录明显增长；
- 单个模块新增多个测试文件或大量相似场景；
- 经常出现一个行为修改导致多处测试同步修改；
- 大量用例失败，却由同一个根因造成；
- 测试开始依赖外部服务、正式状态或不稳定时间条件；
- 准备进行较大重构、版本冻结或重要交付。

每次治理按以下步骤执行：

1. **盘点**：记录各模块的用例文件数、测试项数、耗时和失败情况；
2. **归类**：区分长期场景、临时TDD、重复场景、实现细节测试和在线检查；
3. **收敛**：合并同一业务行为的准备与断言，清除残留`TEMP-TDD`；
4. **删除**：移除重复、废弃、脆弱且无独立风险价值的用例；
5. **验证**：执行完整离线回归，确认各模块关键场景仍通过；
6. **记录**：保存治理前后数量、耗时、删除原因和覆盖承接位置。

盘点命令示例：

```powershell
rg -n "TEMP-TDD" tests packages -g "*.py" -g "*.mjs"
.\.venv\Scripts\python.exe -m pytest -c pyproject.toml tests packages\strategy_manager\tests `
  packages\dataflows\tests packages\strategy_evaluator\tests packages\factor_signal_catalog\tests `
  packages\strategy_template_catalog\tests packages\research_experiment\tests `
  packages\strategy_runtime\tests packages\trading_execution_engine\tests `
  packages\paper_trading_engine\tests `
  --release-acceptance --collect-only -q
Measure-Command { .\.venv\Scripts\python.exe -m pytest -c pyproject.toml tests -q }
Measure-Command { .\.venv\Scripts\python.exe -m pytest -c pyproject.toml packages\dataflows\tests -q }
Measure-Command { .\.venv\Scripts\python.exe -m pytest -c pyproject.toml packages\strategy_manager\tests -q }
Measure-Command { .\.venv\Scripts\python.exe -m pytest -c pyproject.toml packages\research_experiment\tests -q }
Measure-Command { .\.venv\Scripts\python.exe -m pytest -c pyproject.toml packages\strategy_evaluator\tests -q }
Measure-Command { .\.venv\Scripts\python.exe -m pytest -c pyproject.toml packages\factor_signal_catalog\tests -q }
Measure-Command { .\.venv\Scripts\python.exe -m pytest -c pyproject.toml packages\strategy_template_catalog\tests -q }
Measure-Command { .\.venv\Scripts\python.exe -m pytest -c pyproject.toml packages\strategy_runtime\tests -q }
Measure-Command { .\.venv\Scripts\python.exe -m pytest -c pyproject.toml packages\trading_execution_engine\tests -q }
Measure-Command { .\.venv\Scripts\python.exe -m pytest -c pyproject.toml packages\paper_trading_engine\tests -q }
```

耗时和数量用于发现趋势。只要新增场景保护了独立的重要风险，就可以接受合理增长；若耗时
增长主要来自重复准备或重复回放，应优先合并场景和夹具。

## 7. 模块审查清单

逐个模块回答以下问题：

- 每个测试文件保护哪个稳定业务场景？
- 是否存在多个用例重复验证同一行为？
- 是否还有`TEMP-TDD`未收敛？
- 是否直接测试了可由公开入口覆盖的私有实现？
- 是否依赖实时网络、系统时间、执行顺序或正式状态？
- 是否存在过大的数据夹具或重复的昂贵初始化？
- 删除该用例后，哪个主场景继续保护其业务风险？
- 失败信息能否直接指向模块、契约或状态转换？

审查范围包括TDR、DFLS、FSC、STC、SM、REX、SE、SRT、TXE和PTE（含WDG）。一次可以只治理一个
模块，完成验证和记录后再进入下一模块，避免大规模删除导致覆盖范围难以复核。

## 8. 治理记录模板

治理记录可以放入当次提交说明；涉及大范围收敛时，在`docs/superpowers/`保留实施记录。

```text
日期：YYYY-MM-DD
范围：TDR / DFLS / FSC / STC / SM / REX / SE / SRT / TXE / PTE
触发原因：月度检查 / 耗时增长 / 重构前 / 其他

治理前：测试文件__个，测试项__个，完整耗时__秒
治理后：测试文件__个，测试项__个，完整耗时__秒

保留：
- 场景：__；保护风险：__

合并或删除：
- 原用例：__；承接场景：__；原因：重复 / 实现细节 / 废弃 / 脆弱

验证结果：
- 模块功能测试：PASS / FAIL
- 完整离线回归：PASS / FAIL / 未要求
- 已知未覆盖在线检查：__
```

## 9. 完成标准

一次测试治理只有同时满足以下条件才算完成：

1. 所有删除行为都有明确的长期场景承接，或确认已无业务价值；
2. 没有无说明残留的`TEMP-TDD`；
3. 覆盖受影响行为和边界的聚焦测试通过；
4. 用户要求完整离线验收时，通过统一入口执行，并核对完整收集清单与JUnit逐项一致；
   尚未执行的全量或真实发布范围明确列为待验收，不以聚焦通过替代；
5. 治理前后数量、耗时和关键取舍已有简短记录。

## 10. 治理与执行链路验收

重大版本验收采用三层证据，日常小改按风险运行受影响范围：

- **离线功能回归**：根目录`tests/functional/`覆盖TDR公开API、实验评价、证据漂移、统一回测与失败语义；
  各包`tests/functional/`覆盖模块契约、候选与冻结SRT、TXE账本、PTE发布代次和服务配置。
- **档案完整性**：调用公开API `validate_archives(context, archives=(...,))`核验当前契约实验的受管文件、结构和
  哈希。全库扫描遇到不支持的旧格式时明确失败；历史原件保留供人工查阅，不要求其通过当前机器复验。
- **发布验收**：PTE构建验证附注tag、提交、策略快照和制品身份；发布前置检查验证目标版本及
  数据库兼容性。取得生产写入授权后，再检查服务、健康接口、活动版本和关键账户读取。

验收以结果文件、业务状态和账本断言为准，不能只看进程退出码。合成夹具通过只证明软件流程，
不形成真实策略研究证据。真实数据和本机实验制品不随Git分发，缺失时明确报告未验收范围。
执行器发生语义变更时，应为当前支持的SRT/TXE链路增加有明确承接位置的迁移测试；仓库不再
保留独立人工验收脚本。任何PTE部署或运行状态变更需要独立授权。

## 11. 最近一次治理记录

### 2026-10-05八组并行调度验收

脚本提交为`4d4c6ad4`。测试、断言和发布验收范围保持不变；八组调度分别以并行上限6、8
执行完整离线验收，两轮均通过1298项Python、7项Node及Ruff，JUnit与完整收集清单逐项一致，
无遗漏、重复、失败或跳过。

| 配置 | 总耗时 | 记录 |
| --- | ---: | --- |
| 此前四通道 | 241.34秒 | 前一轮同测试范围验收 |
| 八组、并行上限6 | 222.64秒 | 本轮第一次完整验收 |
| 八组、并行上限8 | 212.46秒 | 本轮第二次完整验收，选为默认上限 |

本次八并行实测较此前四通道少28.88秒，约12%；冻结组耗时211.05秒，仍为主要瓶颈。
两轮顺序执行，耗时受文件系统、缓存和机器负载影响，单轮差异不代表稳定加速比例。
并行优化只调整分组与调度，保留完整文件、隔离工作区、BLAS单线程、选择清单及失败汇总。

六并行日志位于`.tmp/test-regression/run-89bf4890adf043b48b5b1dc23ab8cb58/`，八并行日志位于
`.tmp/test-regression/run-f44fe7cb0f6a4707b1bf23a87ca75b29/`；对比与清单核验记录位于
`.tmp/test-parallelism-20261005/`。这些是本机临时证据，不随Git分发。
本次文档同步复用上述验收结果，未重复运行全量测试，未执行生产或在线变更。

### 2026-10-05公共契约治理四批实施验收（此前记录）

验收代码为`f83775c7`，统一入口`scripts/test-all.ps1`通过：1298项Python、7项Node及Ruff，总耗时241.34秒。完整收集清单与各步骤JUnit逐项一致，无遗漏、重复、失败或跳过。

当前Python节点分布：TDR 341、DFLS 240、FSC 42、STC 3、SM 60、REX 27、SE 165、SRT 134、TXE 45、PTE 241。四通道耗时为`TDR_FREEZE` 164.89秒、`TDR` 239.40秒、`PTE` 200.49秒、`PACKAGES` 228.96秒。

本轮四批围绕公开契约修复假覆盖、补充独立风险、重写私有目标和默认适配器场景，
再收敛昂贵准备、完整回放、全目录加载及等价参数。审查基线1255项最终为1298项；
数量净增加来自新发现的独立风险覆盖，不作为降本结论。第三批实际准备、回放及
目录加载次数下降；第四批1307项收敛至1298项，关键数值、身份及异常边界保留。

全量证据位于`.tmp/test-regression/run-dd53f1cde01b45b6a70a05fd7bfb13a5/`，清单核验和文档复审位于`.tmp/test-contract-wave5-20261005/`；此前四批承接记录位于对应的`.tmp/test-contract-wave1-20261005/`至`.tmp/test-contract-wave4-20261005/`。这些是本机临时证据，不随Git分发。
本次为单轮实测，含机器负载影响，不外推全仓加速比例。未执行在线取数、生产变更或历史研究复算。

### 2026-10-05契约修复后的测试收敛（此前记录）

治理基线为`4df2b453`的完整离线验收：1141项Python、7项Node、Ruff通过，269.16秒。
相较2026-10-04记录，新增258项主要来自DFLS数据空间、原始行情、TDR输入契约及PTE／TXE
安全边界；其中重复准备和同源验证场景予以合并，独立资金、身份和并发风险保留。

| 范围 | 治理前 | 治理后 | 覆盖承接 |
| --- | ---: | ---: | --- |
| TDR | 444 | 441 | 完整冻结主场景承接运行注册表隔离；REX成功场景承接错误回执及失败终态污染拒绝 |
| PTE | 234 | 229 | 发布主场景承接篡改拒绝；暂停／恢复承接审计回滚；健康及清单场景合并 |
| DFLS | 237 | 206 | 同一真实发布生命周期承接独立源数据／元数据变异，失败后复核旧引用；共用日历校验去除重复组合 |
| 其余七个子包 | 226 | 226 | 保留独立契约与数值风险，包含TXE的34项测试 |
| Python合计 | 1141 | 1102 | 合并39项重复测试，没有新增跳过或放宽断言 |

档案和临时目录场景改用最小仓库，删除无人使用的`functional_repo`及其真实行情／研究文件
复制逻辑。回测使用独立复制的真实冻结种子；检验、冻结和部署种子链统一，每个用例仍拥有
自己的文件副本。DFLS保留真实SQLite发布、身份核验与独立变异，未模拟掉事务提交或持久化。

四通道重新分配独立TDR运行场景，保留全量范围与40项发布验收。治理后全量1102项Python、
7项Node及Ruff通过，总耗时214.50秒，比基线减少54.66秒（20.3%）。通道耗时为
`TDR_FREEZE`196.13秒、`TDR`200.22秒、`PTE`181.02秒、`PACKAGES`212.34秒。
完整收集清单与JUnit结果逐项比对一致，无遗漏、重复执行、失败或跳过。

全量日志和JUnit位于`.tmp/test-regression/run-62706ea49a6d44abb0a3a7ba4e262e62/`；
覆盖承接与收集核验位于`.tmp/test-governance-20261005/`。这些是本机临时验证证据，不随Git分发。
耗时包含机器负载与并发I/O影响，当前仍高于历史104.10秒；后续根据逐项报告定位重复准备，
不以删减独立风险或隐藏参数化数量换取预算。未更改产品实现或执行生产、在线取数及研究复算。

### 2026-10-04测试分层与执行预算验收

本地既有验收日志记录：`scripts/test-all.ps1`全量离线回归通过，883项Python测试、
7项控制台JavaScript测试和Ruff全部通过，总耗时104.10秒。Python测试包含843项日常场景及
40项`release_acceptance`场景。模块数量为TDR 378、PTE 172、DFLS 148、FSC 2、STC 3、
SM 7、REX 10、SE 81、SRT 72、TXE 10。

四条通道耗时分别为`TDR_FREEZE` 102.96秒、`TDR` 98.60秒、`PTE` 93.61秒、
`PACKAGES` 33.88秒。日志位于`.tmp/test-budget/full-final.log`及
`.tmp/test-regression/run-53eed5aedd274b81a6733e10b7f91949/`。
这些是此前实现验收的历史证据；本次文档修订只验证文档链接、示例和契约，未重跑完整回归。
日志均为本地临时证据，不随Git分发。

### 2026-10-02多线程DSR复验修复验收（此前记录）

2026-10-02多线程DSR复验修复验收：`scripts/test-all.ps1`全量离线回归通过，646项Python测试、
3项控制台JavaScript测试和Ruff全部通过，总耗时246.42秒。模块数量为TDR 244、PTE 99、
DFLS 148、FSC 2、STC 3、SM 8、REX 10、SE 81、SRT 41、TXE 10。
日志位于`.tmp/test-regression/run-1767f9a8ac934016a581beb0ea9bc03d/`。

首轮沙箱内运行出现DFLS/SRT多进程管道权限错误、TDR本地Git克隆失败及PTE图表响应耗时
断言超限；在获准的沙箱外环境完整重跑后全部通过，未调整测试阈值或跳过用例。
首轮日志位于`.tmp/test-regression/run-7e0073d534e24e94b96aca575f9fb700/`。

本轮新增覆盖`DSR_EFFECTIVE`相对误差边界、1/2/8/16原生线程复算、其余字段严格比较和
文件字节篡改拒绝。另有真实S011 EX37阶段四及前驱交付链通过默认16线程OpenBLAS的只读
`validate_delivery`核验，记录位于`.tmp/s011-dsr-recomputation-fix-validation.json`；该专项
验证独立于合成夹具回归，未改写实验或交付证据。本轮未执行在线数据、Windows生产服务或
PTE部署验收。上述日志均为本地临时证据，不随Git分发。

### 2026-10-02当前契约清理验收（此前记录）

2026-10-02当前契约清理验收：`scripts/test-all.ps1`全量离线回归通过，625项Python测试、
3项控制台JavaScript测试和Ruff全部通过，总耗时206.41秒。模块数量为TDR 223、PTE 99、
DFLS 148、FSC 2、STC 3、SM 8、REX 10、SE 81、SRT 41、TXE 10。
日志位于`.tmp/test-regression/run-866da4352a954162ba57e61ca1a0671e/`。

PTE发布、账户准备及服务恢复测试改用当前契约的合成冻结版本，保留账户隔离、持久化、
失败和提交认证断言；不再依赖仓库内的旧冻结策略。Git对冻结发布包保留原始字节，发布测试
覆盖从冻结、Git归档到加载的文件哈希闭环。本次未执行真实研究档案复验、在线数据或生产发布验收。

以下保留当时的测试治理记录。2026-10-01接口收敛已删除旧三道治理闸门及专属测试，当前测试规则与验收范围见本文前述章节。

- 日期：2026-09-22
- 范围：TDR、DFLS、FSC、STC、SM、SE、SRT、TXE、PTE（含WDG）
- 触发原因：SRT重构、TDR治理链和PTE调度/发布连续变更后的仓库级审查

- 治理前：42个测试文件，252个Python测试项和3个Node测试项，串行完整回归约221.80秒。
- 治理后：42个测试文件，252个Python测试项和3个Node测试项，串行完整回归215.89秒。

本轮取舍：

- 未发现`TEMP-TDD`残留、默认在线外部服务访问或生产状态写入；Tushare和Futu均由固定数据或
  模拟适配器替代，HTTP测试只访问测试进程启动的本机临时端口；
- 将PTE交易日推导从私有方法断言改为通过账户级数据准备公开契约验证，继续覆盖交易日、休市日
  和最新已完成信号日；
- 删除PTE调度闭环中无效的旧发布文件准备，并把场景名称改为当前账户级准备格式；该场景继续
  承接“调度器准备数据后立即执行决策”的跨模块风险；
- 保留TDR真实评估与三道治理闸门端到端场景。该场景单项约51秒，但同时保护隔离评审快照、
  真实SE报告、证据防篡改、冻结幂等和候选/冻结实现等价，目前没有其他主场景完整承接；
- 曾验证能否降低上述场景的Bootstrap重复次数；缩减后统计证据不足并被治理闸门正确阻断，
  因此撤销该尝试，保留正式统计强度；
- 其余测试按业务风险审查后保留。本轮没有为了降低数量而删除仍保护独立契约或安全约束的用例。

验证结果：

- TDR：67项通过，103.82秒；
- DFLS、FSC、STC、SM、SE：共55项通过；
- SRT：48项通过，23.44秒；TXE：2项通过；
- PTE：80项通过，78.46秒；PTE控制台：3项通过；
- Ruff：通过；
- 默认并行回归入口连续两轮通过，总耗时分别为140.65秒和137.68秒；相对215.89秒串行基线
  缩短约35%至36%；
- 增加父进程精确清理后再次通过，耗时145.83秒；本轮Pytest工作区和Python字节码缓存均已清除；
- 未执行在线Tushare、Futu OpenD、Windows服务或PTE生产环境检查，这些仍属于独立授权的交付验收。

### 2026-09-23 v0.5.15发布回归

策略治理区迁移、研究注册回填、PTE前瞻图职责调整、TDR/SRT/PTE审查修复、历史PTE发布
快照切换、预备数据空间迁移和Windows治理事务回滚加固完成后，标准入口
`.\scripts\test-all.ps1`再次通过。该轮是`v0.5.15`的发布基线：

- TDR：61项通过；
- DFLS：31项通过；FSC：2项通过；STC：3项通过；SM：13项通过；SE：6项通过；
- SRT：62项通过；TXE：2项通过；
- PTE：96项通过；PTE控制台：3项通过；
- Python合计276项，Node合计3项，Ruff通过；三条并行通道汇总耗时133.34秒；
- 回归日志位于`.tmp/test-regression/run-69b6f0a567114b80b2c3c00cf996402f/`，该目录是本地临时
  证据，不随Git分发；
- 未执行在线Tushare、Futu OpenD、Windows服务或PTE生产环境检查。
