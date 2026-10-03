# 开发运维交接（DEV）

> 本文面向平台开发者（DEV），用于跨机器、跨会话继续开发与运维，只记录系统全貌、关键边界、
> 恢复方法和开发规则。各子包`README.md`说明公共能力的使用，不承担内部维护手册。
> 研究资料导航见`research/README.md`，具体批次结论见`research/SXX/HANDOFF.md`，新研究流程
> 执行契约见`research/RSCH_AGENT.md`；本文维护系统架构、
> 开发环境、测试规则和PTE运维。历史设计与实施过程见`docs/superpowers/`。

> 当前边界：研究员统一使用公开Python API，用户CLI仅保留`backtest run`。新闻抽取、CIO、候选包及旧裁定／冻结写入已删除。当前已提供五阶段交付、候选检验、用户决定绑定及原子冻结。公共入口只接受当前契约；历史原件供人工查阅，不承诺机器复验，不因接口重构而重签。

## 模块与简称

| 简称 | 全称 | 核心职责 |
| --- | --- | --- |
| TDR | CZSC Trader | 研究执行、评价、回测及跨模块公共API |
| DFLS | Dataflows | Tushare数据获取、复权、多频处理和数据发布 |
| FSC | Factor & Signal Catalog | 项目级信息族、因子和信号定义目录 |
| STC | Strategy Template Catalog | 策略函数模板、输入角色和参数边界目录 |
| REX | Research Experiment | 可执行实验声明、能力与回执合同 |
| SM | Strategy Manager | 策略身份、版本、资格、证据和治理审计 |
| SE | Strategy Evaluator | 候选筛选、排名和统计稳健性数值计算 |
| SRT | Strategy Runtime | 候选与冻结策略共用的数据契约、决策计算、执行计划和运行身份 |
| TXE | Trading Execution Engine | 统一成交、费用、现金、持仓和净值计算口径 |
| PTE | Paper Trading Engine | 虚拟账户、模拟交易执行、运行审计和观测 |
| WDG | PTE Watchdog | PTE进程开机自启、探活和故障拉起 |

后续开发、文档和讨论统一使用以上名称。DFLS、FSC、STC、REX、SM、SE、SRT、TXE和PTE
均为仓库内独立包，只通过明确契约协作。研究脚本可以直接使用Optuna、特征提取库及其他研究
依赖；仓库不再维护通用Search、Feature Mining和新闻抽取运行模块。新流程由RSCH执行研究、自检、技术检验及获批冻结；用户保留阶段审批、候选选择及冻结决定权。部署须另行授权。

## 接手时核对的状态

项目使用Python 3.12，默认集成分支为`master`。分支、远端、最新tag、冻结版本、账户资金及
PTE生产活动版本都可能变化，必须在接手时按任务范围分别只读核对，不能从本文推断当前值。
版本发布使用附注tag；PTE生产版本目录不可变，账户、SRT准备数据、配置和日志位于共享运行
目录。PTE控制台仅监听localhost，WDG服务名为`CZSC-PTE-Watchdog`，当前实现的交易渠道是
Futu中国市场模拟交易；实际服务与渠道健康以运行环境状态为准。

当前冻结入口绑定候选身份、技术检验和用户明确批准，只有`COMMITTED`表示完成。普通SRT决策使用`advice.v4`，原子时点计划
使用`advice.v5`；TDR和PTE均消费SRT输出的`strategy_observation.v1`事实，分别统一生成
`tdr_backtest_chart.v1`回测图和`pte_forward_chart.v1`前瞻图。图表结合各自的行情与账户事实，
冻结包不绑定策略绘图代码。

每次接手先执行：

```powershell
git status --short --branch
git log -5 --oneline
git rev-list --left-right --count origin/master...master
```

## 总体架构

```text
研究员 → 公共API → REX受管实验 → SRT + DFLS → TXE账户 → SE数值证据
用户 → backtest run → 同一回测API → 账户、审计、报告
冻结版本 → 获批部署API → SRT部署凭据 → PTE独立运行
候选 → TDR技术检验 → 用户批准 → SM原子冻结 → 当前版本及提交证明
历史原件 → 人工查阅
```

### 模块边界

- **TDR**位于`src/czsc_trader/`。`application`公开完整业务操作，`research_tools`承载实验上下文及评价，`backtesting`承载共同回放。CLI只做用户回测适配。平台校验完备性、一致性与可追溯性，不认证研究结论正确。操作者声明不等于身份鉴权，现有凭据中的身份保证级别仍为`UNVERIFIED`。
- **FSC**位于`packages/factor_signal_catalog/`，定义数据位于`catalog/`。它记录项目级信息族、
  因子和信号的稳定语义、实现入口、参数及因果可用时间；不保存标的计算值、收益证据、实验
  结论或运行状态。TDR只读引用FSC，各研究线拥有自己的物化缓存与证据。
- **STC**位于`packages/strategy_template_catalog/`，定义数据位于`strategy_templates/`。它记录
  策略函数模板、输入职责、参数边界和实现复杂度，并生成确定性实例身份；不读取行情、不搜索
  参数、不回测、不评价候选。TDR只读引用STC，负责交叉核对FSC输入，并在具体研究实现中落实
   模板语义。
- **REX**位于`packages/research_experiment/`。它定义可执行研究实验的声明、能力、输入与
  回执合同，并隔离加载经过源码哈希校验的实验实现；TDR的`research_tools`提供平台上下文、
  受控数据访问及执行适配。REX不替研究员判断机制或改变实验档案。
- **SM**位于`packages/strategy_manager/`。提供研究登记、发布及生命周期契约和存储能力。
  研究注册表位于`research/registrations/`；首次冻结时在`strategies/`登记运行策略族。
  `StrategyVersion`只支持schema 5，候选登记只支持schema 2。TDR保存研究决定和技术检验证据，
  运行注册表保存版本、发布包、资格及生命周期；研究批准不嵌入运行发布身份。
- **SE**位于`packages/strategy_evaluator/`。它接收TDR提供的结构化事实，执行筛劣、Pareto
  排名、PBO、DSR、Bootstrap、参数邻域和成本压力等确定性数值计算；它不读取仓库、不理解
  金融语义，也不签发TDR裁决或改变SM、PTE状态。
- **SRT**位于`packages/strategy_runtime/`。包内只保存策略无关运行框架；候选实现来自显式绑定的研究源码，
  冻结实现及其源码闭包保存在`strategies/SXX/releases/vN/`，部署凭据保存在
  `strategies/deployments/`。`StrategyRuntime`校验候选或已部署冻结版本并创建
  `StrategyInstance`；实例根据交易窗口自主推导信号日、历史范围和全部数据依赖，通过DFLS
  准备并认证数据，再计算目标仓位、参考价与渠道无关的`ExecutionPlan`。源码闭包、候选或冻结
  身份和参数共同形成运行身份。调用方只提供隔离可写的数据目录，不理解或传递策略数据集。
  SRT不实现回测、账户账本或券商渠道。
- **TXE**位于`packages/trading_execution_engine/`。它提供研究、回测和冻结复核共享的成交、
  滑点、费用、现金、持仓与净值计算；`HistoricalExecutor`实现SRT的`WindowExecutor`协议，
  由`StrategyInstance.run_window(...)`逐日驱动并管理隔离的历史账本。它不生成信号、不获取
  策略数据、不管理策略生命周期或真实券商状态。
- **PTE**位于`packages/paper_trading_engine/`。日调度为每个账户创建隔离
  `StrategyInstance`，调用`prepare_data()`后再调用`plan_at(...)`，管理账户分账、决策、订单
  意图、Futu回报、调度、SQLite审计和控制台。前瞻图服务在独立守护线程读取DFLS行情、组装
  决策及账户事实、渲染并缓存HTML，Web请求和PTE主调度线程不等待这些工作。PTE不解析SRT
  私有数据清单，也不导入TDR、SM或SE。策略账户按模型费用记账；经核实的Futu实际费用与模型
  费用差额记入零初始资金的渠道平账账户，不混入策略绩效。未知费用或订单结果不得推断入账。
- **WDG**位于PTE包内。它只负责PTE子进程生命周期和HTTP探活，不包含交易业务逻辑。
- **DFLS**负责单项数据请求的获取、规范化、统一校验、按“供应商＋标的”修复和失败阻断。
  SRT只处理`DataResult`；多输入策略的范围推导、组合认证和实例级数据身份由SRT负责。
  Tushare股票与ETF适配、源时间元数据和历史补丁分别在`packages/dataflows/src/dataflows/`
  的供应商模块、`facade.py`及`history_patches/`维护；补丁只匹配已登记的异常签名，修复后
  必须重新校验，未知异常明确失败。研究正式输入优先走DFLS公共门面。
正式实验档案按`experiments/<策略ID>/<实验ID>/`保存。完整定位键为“策略ID＋实验ID”，
不同策略可有同名实验；存在歧义时必须显式提供策略ID。新实验编号按策略跨日期递增，
目录为`EXxxx_YYYYMMDD`；历史档案保持原位，旧来源字符串不由当前API自动迁移。

依赖方向保持为：`TDR → REX/FSC/STC/SM/SE/TXE/SRT/DFLS`、`REX → SRT`、`TXE → SRT`、
`SRT → DFLS`、`PTE → SRT`、`WDG → PTE进程`。TXE与DFLS同层，TDR和研究脚本可以调用；
PTE的账户事实仍以渠道回报为准。

## 跨模块硬约束

1. SRT拥有策略、价格、费率、目标仓位和委托参数的计算权；PTE只消费SRT决策并负责执行，
   Futu回报是订单与成交状态的事实来源，渠道不得改写策略决策。
2. 虚拟账户是PTE业务归属中心。每个账户绑定一个不可变策略发布、一个交易标的和一个渠道；
   一个渠道可以承载多个账户，渠道本身不绑定策略。PTE独占底层Futu模拟账户。
3. 决策、订单意图、渠道订单、成交和账本变动必须能够追溯到虚拟账户、策略发布及关联ID；
   无法归属的活动订单或账户汇总不一致时必须阻止新单。
4. 只有明确的累计成交增量能够改变现金和持仓。结果未知时保持原账本并持续双向对账；自动
   交易保持单写进程，意图与计划必须幂等、事务化持久，并能在重启后恢复。
5. 研究、回测和运行时决策必须遵守因果时间边界。DFLS对每个请求完成校验、必要修复和重新
   校验，无法提供准确完整数据时返回失败；`StrategyInstance.prepare_data()`负责推导并认证
   全部声明输入。普通回测只指定评价窗口和实例数据目录，不理解策略数据集；窗口或截止日
   无法满足时必须失败，禁止静默截短后返回成功。
6. 正式策略通过SRT运行；SM管理身份和资格，SE执行确定性数值审计，TXE统一研究、回测和
   冻结复核的执行口径，PTE只部署`PAPER_READY`版本。冻结前必须能解析并校验对应SRT实现、
   源码闭包和运行身份；冻结策略的回测与模拟盘均直接走SRT单一路径。研究、模拟盘和未来
   实盘证据分阶段保存，不得相互替代。冻结与PTE账户创建是两个独立授权动作。
7. WDG只负责PTE进程启动、探活和故障拉起，不包含交易、数据发布或账户状态判断。
8. 批处理只有全部目标完成才可更新成功日期或成功状态。部分策略数据准备成功、部分账户决策成功、
   渠道仅受理委托或外部结果未知，都不能汇总成全局成功；失败事实必须进入审计、告警和退避。
9. 当前`StrategyVersion`使用schema 5，`release_hash`覆盖固定运行内容及发布元数据。
   研究侧计划、检验、批准及冻结日志分别绑定登记和请求，不进入运行版本字段。
   冻结流程先完成发布包和研究日志的`committed.json`，再原子写入版本文件作为运行可见性边界。
   查询冻结状态须核验日志、版本和发布包；运行加载、回测及部署核验各自的版本、包和部署身份，
   不读取研究批准目录。旧格式在相应边界明确拒绝。
10. 跨机器文件身份统一复用`src/czsc_trader/identity.py`：普通文本归一化换行为LF，JSON按语义
    计算SHA-256，原始行情与二进制按字节计算SHA-256；既有实验档案保持原样。

### 研究API与治理边界

1. 研究立项和意图更新使用TDR `create_research_batch/update_research_intent`，保留研究批次凭据与授权记录。
2. 正式实验使用REX绑定、预检、受管上下文和执行回执；评价通过`context.evaluation.evaluate`保留实际调用与结果追踪；搜索预算归研究员管理。
3. `run_backtest(context, strategy, request)`接受`StrategyCandidate`或`StrategyVersion`，共用SRT/TXE回放；用户CLI当前解析已登记版本。请求使用`BacktestRequest`，显式提供`lot_size`；候选通过Python API登记和加载。
4. 已登记版本回测仍使用现有SRT部署凭据，缺少时明确失败，不自动部署。
5. `deploy_strategy`仅在独立授权后调用；PTE账户、服务和生产状态不随研究授权开放。
6. 旧CIO、候选包、裁定及冻结执行路径已删除，不提供回退。历史研究证据保持不可变；
   当前API不承担旧格式解码或机器复验，运行发布以当前版本及其认证文件为准。
7. 用户选型后调用`inspect_candidate`；取得绑定检验计划的明确冻结批准后调用`freeze_candidate`。仅`COMMITTED`表示完成，不确定时以同一请求ID查询。

用户决定与确认材料位于`research/<策略ID>/decisions/`；检验证据位于当前正式实验的
`objects/inspection/`；冻结请求及结果位于`research/<策略ID>/freeze_requests/<请求ID>/`。
研究证据使用带归属的`ResearchEvidenceRef`，调用方以仓库根解析返回引用。
发布版本采用schema 5，SRT运行定义采用schema 3，运行绑定采用schema 2；
字段及调用方式见[TDR说明](../src/czsc_trader/README.md)和[SRT说明](../packages/strategy_runtime/README.md)。

研究员直接使用所属模块API或TDR公共业务入口，不拼装CLI。历史实验原件保留供人工查阅，不承诺机器复验；继续研究需生成符合当前契约的新证据。

## 新机器恢复

```powershell
git clone https://github.com/tomxiao/czsc_trader.git czsc_trader
cd czsc_trader
git checkout master
git pull --ff-only origin master
```

### 开发环境安装

项目使用Python 3.12。新建虚拟环境后按包依赖方向安装本地源码：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .\packages\dataflows
.\.venv\Scripts\python.exe -m pip install -e ".\packages\factor_signal_catalog[test]"
.\.venv\Scripts\python.exe -m pip install -e ".\packages\strategy_template_catalog[test]"
.\.venv\Scripts\python.exe -m pip install -e ".\packages\strategy_manager[test]"
.\.venv\Scripts\python.exe -m pip install -e ".\packages\strategy_evaluator[test]"
.\.venv\Scripts\python.exe -m pip install -e ".\packages\strategy_runtime[test]"
.\.venv\Scripts\python.exe -m pip install -e ".\packages\research_experiment[test]"
.\.venv\Scripts\python.exe -m pip install -e ".\packages\trading_execution_engine[test]"
.\.venv\Scripts\python.exe -m pip install -e ".[research,test]"
.\.venv\Scripts\python.exe -m pip install -e ".\packages\paper_trading_engine[test]"
.\.venv\Scripts\czsc-trader.exe --help
.\.venv\Scripts\pte.exe --help
```

从`.env.example`复制出Git忽略的根目录`.env`，仅在本机填写获授权的数据源凭据；不要将Token
写入源码、测试夹具或实验档案。进程环境变量优先于显式凭据文件。DFLS从调用方指定的位置
读取凭据，不假定包自身所在目录就是仓库根目录。

根目录`.venv`是平台开发和策略研究共用的唯一开发环境；`research` extra提供Optuna、tsfresh
等仅在研究阶段使用的依赖，不创建第二套本地虚拟环境。PTE构建不安装该extra，研究依赖不得
进入PTE生产发布闭包。Tushare凭据写入由Git忽略的`.env`；使用Futu模拟交易前
启动Futu OpenD。开发环境恢复后按[测试用例治理](TEST_GOVERNANCE.md)运行相应回归。WDG只
绑定独立PTE生产根目录，不引用开发仓库；迁移开发仓库无需重装WDG。

## 本地状态与跨机边界

以下内容被Git忽略，需要在目标机器单独恢复：

- `.venv/`：解释器和依赖；
- `.env`：本机凭据；
- `data/raw/`、`data/backtest/`及`data/review/`：分别恢复受控研究输入、回测执行数据与封存审核证据；
- `experiments/**/artifacts/`：本机研究制品；公开克隆只承诺人工查阅，不保证历史重放或部署可用；
- `.tmp/`：测试缓存、测试运行目录和业务发布前的暂存工作区；
- `.build/pte/`：可重建的PTE版本构建产物；
- `.tmp/pte-release/`：PTE构建使用的pip、uv-build和临时目录；
- `outputs/`：普通回测输出；
- `state/paper_trading/`：仅在显式运行开发态PTE时生成的数据库、备份、数据、图表缓存和日志；
  未运行开发态PTE时可以删除，生产PTE不会读取该目录；
- PTE生产根目录的`shared/`：生产账户、订单、成交、暂停状态、审计、SRT准备数据、配置与日志；
- Windows服务、Futu OpenD及其登录状态。

跨机继续开发可以创建新的本地状态。跨机延续同一条模拟盘观察序列，需要迁移完整SQLite，
SRT准备数据及配置组成的完整生产`shared/`，并与Futu活动订单、成交和持仓逐笔核对；核对完成
前保持新单阻塞。

## PTE发布与日常运维

PTE生产写入、服务控制和账户变更均须先取得明确授权。生产根目录以
`scripts/pte-publish.ps1`内置的`$ProductionRoot`为唯一配置来源；以下命令中的`$PteRoot`
 取该值。PTE向RSCH展示的观察事实及其边界见[PTE使用说明](../packages/paper_trading_engine/README.md)。

### 构建与发布

构建只读取指定附注tag，产物进入Git忽略的`.build/pte/`，pip、uv-build和临时目录进入
`.tmp/pte-release/`。发布校验构建
身份、安装不可变版本、切换活动版本并等待健康检查；普通版本发布不需要重新安装WDG：

```powershell
$Tag = Read-Host '请输入附注tag'
.\scripts\pte-build.ps1 -Tag $Tag
.\scripts\pte-publish.ps1 -Tag $Tag
Invoke-RestMethod http://127.0.0.1:8080/api/system/status
```

发布构建会把`strategies/`中的冻结发布包和部署凭据完整复制到PTE版本快照，并逐个调用SRT
校验运行时、源码闭包、运行绑定及观察契约。发布脚本拒绝轻量tag、提交不匹配、策略快照漂移、
制品损坏和不完整的既有版本。生产目录只保留`host/`、`releases/`和`shared/`；构建过程与缓存
不写入生产目录。

### 活动版本与账户操作

生产命令必须显式绑定当前活动发布和共享状态。在同一PowerShell会话准备参数：

```powershell
$Active = Get-Content (Join-Path $PteRoot 'shared\config\active-release.json') -Raw |
  ConvertFrom-Json
$ReleaseRoot = Join-Path $PteRoot "releases\$($Active.release_id)"
$Pte = Join-Path $ReleaseRoot '.venv\Scripts\pte.exe'
$RuntimeArgs = @(
  '--repo-root'; $ReleaseRoot
  '--database'; (Join-Path $PteRoot 'shared\state\runtime.db')
  '--data-dir'; (Join-Path $PteRoot 'shared\data')
  '--config-root'; (Join-Path $PteRoot 'shared\config')
  '--release-manifest'; (Join-Path $ReleaseRoot 'release-manifest.json')
)
```

常用账户命令：

```powershell
& $Pte account list @RuntimeArgs
& $Pte account create @RuntimeArgs `
  --account-id s002-v1 --name "S002-v1模拟账户" `
  --strategy S002 --strategy-version v1 `
  --symbol 510500.SH --asset etf --initial-cash 100000
& $Pte account pause @RuntimeArgs --account-id s002-v1
& $Pte account resume @RuntimeArgs --account-id s002-v1
```

需要立即驱动单个虚拟账户决策时，在控制台调用：

```http
POST /api/virtual-accounts/{account_id}/decision
Content-Type: application/json

{}
```

该接口无需控制令牌，返回`DECISION_COMPLETED`、`DECISION_REUSED`、
`DECISION_SUPERSEDED`或`DECISION_AND_INTENTS_SUPERSEDED`。只有尚未提交渠道且没有
`channel_order_id`的订单意图可以随旧决策失效；已有渠道订单或结果未知时返回冲突。

冻结策略不会自动进入SRT或PTE；新版本初始资格为`RESEARCH`。获准的DEV通过SM
`approve_paper_trading(PaperTradingApproval)`绑定发布哈希授予`PAPER_READY`，通过
`deploy_strategy` API写入SRT部署凭据；创建PTE账户仍是独立授权动作。PTE在进程内调用SRT，
不接受`--advice-executable`参数。暂停只阻止新单，已有订单继续对账。PTE日调度为每个账户创建隔离的SRT
实例并调用`prepare_data()`，准备成功后才执行账户决策；`srt-prepare`只用于人工诊断或独立准备。
准备异常必须先于账户决策明确暴露。
需要把模拟盘里程碑写回策略生命周期时，先导出自包含证据，再由获准的DEV通过SM登记：

```powershell
& $Pte performance export @RuntimeArgs `
  --account-id s002-v1 --recorded-by tomxiao `
  --start 2026-09-03 --end 2026-12-03 --output .tmp\paper-forward.json
```

日常净值保留在PTE数据库；导出的里程碑证据须先经过人工复核。获准后通过SM的
`StrategyRegistry.record_evidence`登记生命周期证据；TDR不提供对应CLI。

### WDG、健康检查与故障处理

首次发布完成后，管理员PowerShell从已发布的轻量宿主安装WDG。普通PTE版本和策略发布继续
复用该宿主；只有WDG依赖或服务配置变化时重新执行`install-config`：

```powershell
$Watchdog = Get-ChildItem (Join-Path $PteRoot 'host\releases') `
  -Filter pte-watchdog.exe -Recurse |
  Sort-Object LastWriteTimeUtc -Descending |
  Select-Object -First 1
& $Watchdog.FullName install-config --runtime-root $PteRoot
& $Watchdog.FullName start --wait 30

Get-Service CZSC-PTE-Watchdog
Start-Service CZSC-PTE-Watchdog
Stop-Service CZSC-PTE-Watchdog
Restart-Service CZSC-PTE-Watchdog
& $Watchdog.FullName remove
```

开发调试可以运行`.\.venv\Scripts\pte.exe serve --repo-root .`，它只使用可丢弃的
`state/paper_trading/`。生产环境由WDG托管时禁止再启动第二个`serve`或并发执行`pte once`；
数据库独占锁会拒绝第二个写进程。

日常只读检查：

```powershell
Get-Service CZSC-PTE-Watchdog
Get-NetTCPConnection -LocalPort 8080 -ErrorAction SilentlyContinue
Invoke-RestMethod http://127.0.0.1:8080/api/system/status
Get-Content (Join-Path $PteRoot 'shared\logs\watchdog.log') -Tail 100
Get-Content (Join-Path $PteRoot 'shared\logs\pte.log') -Tail 100
```

生产状态、SRT准备数据、图表、配置和日志统一位于`shared/`。端口冲突、数据库写锁、准备结果
不完整、渠道订单归属不明或持仓不一致都会明确失败或阻止新单。恢复前先核对Futu当前及历史
订单、成交和持仓；禁止直接修改SQLite。只有审计证据满足受保护修复条件时才使用：

```powershell
& $Pte control repair-ledger @RuntimeArgs `
  --account-id s003-v1 --intent-id PTE-XXXXXXXXXXXXXXXXXXXX
```

成功返回`REPAIRED`，重复执行返回`ALREADY_REPAIRED`，证据不完整时明确失败。PTE每次启动
前创建SQLite备份并滚动保留3份；备份不替代Futu事实核对。

## OPC测试用例治理

测试目标是用尽量少的稳定业务场景保护TDR、DFLS、FSC、STC、SM、SE、SRT、TXE、PTE和WDG的
完整能力。TDD最小失败用例可以临时存在；行为稳定后应并入长期功能场景并删除重复用例。
长期用例验证公开入口、关键状态转换、持久化结果和安全约束，不围绕私有实现持续增长。

用例准入、收敛与删除条件、分级回归命令、月度及触发式审查流程统一见
[测试用例治理](TEST_GOVERNANCE.md)。该文档是后续周期性治理的唯一操作规范。

治理和执行链路由根目录及各独立包的长期功能场景验收：TDR覆盖公共API、唯一回测CLI、证据
漂移与失败语义，SRT/TXE覆盖候选和冻结版本的同路径执行，PTE覆盖准备结果、账户、订单、账本与服务
配置。当前契约档案可核验；历史实验原件供人工查看，平台不承诺机器复验。完整命令及版本验收边界见
[测试用例治理](TEST_GOVERNANCE.md)；任何生产部署仍需独立授权。

冻结发布包使用Git属性保留原始字节，避免跨平台换行转换破坏`release_manifest.json`的文件哈希。

最近一次仓库级全量回归结果、治理记录和未覆盖在线检查以
[测试用例治理](TEST_GOVERNANCE.md)的“最近一次治理记录”章节为准，不在本文复制快照。
完整离线回归运行`.\scripts\test-all.ps1`，`TDR_FREEZE/TDR/PTE/PACKAGES`四条任务全部结束后
统一汇总退出码并运行Ruff；包含发布验收用例，日志位于`.tmp/test-regression/`。
日常聚焦验证默认不包含标记为`release_acceptance`的真实冻结包验收；需要时显式传入
`--release-acceptance`。子包聚焦验证可从仓库根目录运行：

```powershell
$PackageName = "dataflows"  # 按需改为目标子包名
.\.venv\Scripts\python.exe -m pytest -q -c pyproject.toml "packages/$PackageName/tests"
.\.venv\Scripts\python.exe -m ruff check "packages/$PackageName/src" "packages/$PackageName/tests"
```

PTE控制台另有Node测试；完整命令、版本验收边界及单模块失败定位见测试治理文档。

仓库内临时文件统一进入根目录`.tmp/`并按用途分区。业务代码通过
`czsc_trader.temp_workspace`创建临时目录；测试与Ruff分别使用`.tmp/pytest`和
`.tmp/ruff`。禁止在根目录、`data/`、`outputs/`、`experiments/`或各包目录新增临时
工作区。

## 开发与交付规则

- 普通改动使用`master`；重量级开发和研究任务先确认是否新建`codex/`分支。
- 不使用本地Git worktree；保留用户的无关修改。
- 分支内可以自主提交；合并`master`和推送远端前取得用户确认。
- 修改研究角色规则时同步`research/RSCH_AGENT.md`；修改具体批次时
  同步对应`research/SXX/HANDOFF.md`和新实验档案；资料入口变化时同步`research/README.md`。
- 修改公共使用方式时同步对应包`README.md`；修改内部运行边界、开发环境或发布方式时同步本文。
- 根目录`README.md`只维护项目介绍和文档索引；`research/README.md`只维护研究资料导航，
  批次状态以各自`HANDOFF.md`为准；RSCH Agent描述维护研究工作流；本文维护架构、开发环境、
  运行边界和PTE运维。调试流水及已完成任务不进入这些文档。

## 研究平台待评审事项

以下是S008工具需求与当前实现对照后保留的缺口，不是DEV实施授权或既定优先级。SRT顶层策略
编写API、跨市场时间对齐和基础`evaluate_strategy`评价接口已有实现；新研究应先复用现有公共
能力，再根据重复出现的失败或效率瓶颈决定是否扩展。S008实验档案及结论保持不变。

| 议题 | 当前缺口与启动条件 | 最小验收 |
| --- | --- | --- |
| 正式实验技术预检 | 已有REX实验合同及`preflight_experiment_archive`、`evaluate_research_request` API；优先复用，新增检查范围另行评审 | 合成夹具在读取真实收益前发现数据集/字段、时间差和评价起点错误；预检输出写入指定实验档案，不替代正式研究证据 |
| 评价路径等价 | 研究与候选侧已复用评价Harness，尚无公开的加速/完整路径逐日等价检查；仅在下一批研究需要加速评价时实施 | 固定参数下逐日对齐目标仓位、账户净值与指标，并保存两侧结果身份（C05/C06） |
| 联合搜索执行器 | 当前没有公共`run_search`；只有重复的大规模搜索确实产生并发、复现或账本问题时再建设 | 固定种子下1与多worker的trial编号、参数和裁决一致；失败trial进入账本（C06） |
| 研究状态与数据能力查询 | `research status`及`data capabilities`入口尚不存在；出现反复的状态误读或数据合同试错时分别评审 | 只读派生权威实验状态或合法数据集/时间语义，不泄露凭据、不改数据 |

原S008的C01-C03已有部分合成夹具和测试；C04-C06应随对应议题补齐，不为维持历史清单单独
开发。断点恢复、worker共享和环境快照仅在出现明确成本或故障证据时另行立项。

`expr_codegen==0.16.6`已在根`research` extra声明，是现有研究工具。使用前核对当前支持后端，
生成代码与参考计算逐值验证；研究依赖不自动进入冻结运行时或PTE发布闭包。

## 详细资料入口

- 项目介绍与文档索引：`README.md`
- 各子包面向RSCH的使用说明：`packages/dataflows/README.md`、
  `packages/factor_signal_catalog/README.md`、`packages/strategy_template_catalog/README.md`、
  `packages/research_experiment/README.md`、`packages/strategy_manager/README.md`、
  `packages/strategy_evaluator/README.md`、`packages/strategy_runtime/README.md`、
  `packages/trading_execution_engine/README.md`、`packages/paper_trading_engine/README.md`
- 研究资料导航：`research/README.md`；批次状态：`research/SXX/HANDOFF.md`
- RSCH执行契约：`research/RSCH_AGENT.md`
- 已批准设计与实施计划：`docs/superpowers/specs/`、`docs/superpowers/plans/`

当前限制：PTE只实现Futu模拟交易渠道；控制台只监听localhost；同一观察序列的SQLite
跨机迁移仍需人工完成渠道核对。未复权正式账本尚未建模ETF现金分红、份额拆分等公司行动；
此类非交易变动发生时必须保持渠道差异告警并人工归属，禁止按交易费用自动调账。长期经济
绩效使用后复权研究口径，待公司行动契约完成后再与PTE账本做完整对齐。
