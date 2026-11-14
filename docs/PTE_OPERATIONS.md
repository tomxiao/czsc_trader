# PTE发布与运维

本文说明获授权后的生产发布、账户操作、服务管理和恢复方法。
DEV工作方法与工程约束见[DEV 工作指南](DEV_AGENT.md)，公共观察能力见
[PTE使用说明](../packages/paper_trading_engine/README.md)。所有命令从仓库根目录执行。
命令示例不构成生产操作授权；操作前确认具体目标、活动发布和共享状态。

## 发布、账户与服务操作

PTE生产写入、服务控制和账户变更均须先取得明确授权。生产根目录以
`scripts/pte-publish.ps1`内置的`$ProductionRoot`为唯一配置来源；以下命令中的`$PteRoot`
 取该值。PTE向RSCH展示的观察事实及其边界见[PTE使用说明](../packages/paper_trading_engine/README.md)。

### 构建与发布

构建前按[测试治理规范](TEST_GOVERNANCE.md)完成聚焦验证；需要全仓验收时运行
`pwsh -NoProfile -File scripts/test-all.ps1`。脚本覆盖各模块、实际登记发布包、前端及 Ruff，
结果保存在 `.tmp/test-regression/run-<运行ID>/`。首次失败须保留日志、测试选择清单及 JUnit XML；
修复后仅补测受影响用例，并关联补测结果，不能将局部通过描述为重新跑过全仓。

比较测试治理前后耗时时，固定测试文件、单进程／并发设置和原生线程数，使用新进程及
新的隔离目录；不可变种子的首次构建也计入耗时。合并重复用例应记录风险承接位置，
不得裁掉 CN／US 规则差异、资金、未知订单结果或迁移恢复边界。聚焦提速不代表全仓提速。

构建只读取指定附注tag，产物进入Git忽略的`.build/pte/`，pip、uv-build和临时目录进入
`.tmp/pte-release/`。发布校验构建
身份、安装不可变版本、切换活动版本并等待健康检查；普通版本发布不需要重新安装WDG：

```powershell
$Tag = Read-Host '请输入附注tag'
.\scripts\pte-build.ps1 -Tag $Tag
.\scripts\pte-publish.ps1 -Tag $Tag
Invoke-RestMethod http://127.0.0.1:8080/api/system/status
```

发布构建会把`strategies/`中的冻结发布包和部署凭据完整复制到PTE版本快照。当前发布集合由
`strategies/deployments/`根目录凭据决定，调用SRT校验运行时、源码闭包、运行绑定及观察契约。
`strategies/deployments/history/`保存退出集合的凭据原件，仍验证凭据与冻结包的精确哈希和文件
完整性，不要求旧包通过新版运行合同。尚未部署且未转入历史集合的V4包仍执行技术校验。
同一版本同时出现在当前和历史集合会阻断发布。发布脚本拒绝轻量tag、提交不匹配、策略快照漂移、
制品损坏和不完整的既有版本。生产目录只保留`host/`、`releases/`和`shared/`；构建过程与缓存
不写入生产目录。

S002-v1、S003-v1已退出当前发布集合；S001-v1、S001-v2、S007-v1、S011-v1、S015-v1、S018-v1
保留在当前集合。历史包、版本、资格日志和部署凭据原件随快照保留，原有研究和账户记录不变。
发布前若生产仍有绑定历史策略的账户，须经授权在原版本暂停；发布预检允许其处于`PAUSED`
或`RETIRING`，核对精确发布哈希和选型截止日，拒绝仍为`RUNNING`的历史账户。预检的账户数
和发布身份列表包含这些已核对的暂停／退役中绑定，不表示它们可以恢复策略计算。
升级后按下文市价清仓退役流程处理剩余持仓和资金；调整发布集合本身不改变生产账户状态。

### 活动版本与账户操作

生产命令必须显式绑定当前活动发布和共享状态。在同一PowerShell会话准备参数：

```powershell
$Active = Get-Content (Join-Path $PteRoot 'shared\config\active-release.json') -Raw |
  ConvertFrom-Json
$ReleaseRoot = Join-Path $PteRoot "releases\$($Active.release_id)"
$Pte = Join-Path $ReleaseRoot '.venv\Scripts\pte.exe'
$PteConfig = Get-Content (Join-Path $PteRoot 'shared\config\pte.json') -Raw |
  ConvertFrom-Json
$RuntimeArgs = @(
  '--repo-root'; $ReleaseRoot
  '--database'; (Join-Path $PteRoot 'shared\state\runtime.db')
  '--data-dir'; (Join-Path $PteRoot 'shared\data')
  '--data-space'; $PteConfig.data_space
  '--config-root'; (Join-Path $PteRoot 'shared\config')
  '--release-manifest'; (Join-Path $ReleaseRoot 'release-manifest.json')
)
```

`account list`为只读查询，可在服务运行时执行。`account create/pause/resume/create-reconciliation`
为离线写操作，必须取得该数据库的单写锁；服务运行时明确拒绝。生产离线维护须先取得停服
授权，停止WDG并确认写进程退出。常用账户命令：

```powershell
& $Pte account list @RuntimeArgs
& $Pte account create @RuntimeArgs `
  --account-id s002-v1 --name "S002-v1模拟账户" `
  --strategy S002 --strategy-version v1 `
  --symbol 510500.SH --asset etf --initial-cash 100000
& $Pte account pause @RuntimeArgs --account-id s002-v1
& $Pte account resume @RuntimeArgs --account-id s002-v1
```

两市新账户按 `{发布版本}模拟账户` 生成显示名。升级后若需统一既有 MU 账户的名称，在已获授权的停服维护窗口执行：

```powershell
& $Pte channel normalize-account-name @RuntimeArgs `
  --channel-account-id futu-us-default --account-id s018-v1
```

确认显示名为 `S018-v1模拟账户`，账户 ID、策略全名和账本仍对应原账户。名称变更可在 `ACCOUNT_DISPLAY_NAME_UPDATED` 审计事件中核对。

服务运行期间，在控制台顶部选择 A 股或美股。虚拟账户、模拟渠道、审计、比较和活动告警使用同一市场范围；切换市场保留当前页签。
账户暂停和恢复使用控制台，或向`/api/virtual-accounts/{account_id}/pause`、
`/resume`发送`Content-Type: application/json`、正文`{}`的POST请求。在线创建渠道平账账户使用
`pte control create-reconciliation`；控制令牌由CLI只读取得，实际变更由运行中的服务执行。

渠道操作通过 `/api/channel-accounts/{channel_account_id}/` 下的暂停、恢复和两次撤单确认入口。确认时核对市场、渠道账户、虚拟账户及订单。侧栏展示事件影响对象、原因和关联身份，原始字段供排查。
前瞻图由后台生成，按账户配置的行情来源读取后复权日线，并使用该市场实际交易日历和数据可用时点。
美股提前收市按纽约本地时段核对。执行文案来自原决策发布包，说明快照与账户库相邻保存。
图表缺数据时，详情显示当前原因。字段与验收方法见
[PTE 前瞻事实契约](../packages/paper_trading_engine/README.md#前瞻事实怎样产生)。

验收虚拟账户页时，核对总资产、可用现金、冻结资金、持仓和账户累计收益率同排展示。前瞻起点取首个已记录决策的信号日，选型截止和日终绩效估值窗口各自独立。MU 的 2026-11-06 应显示“等待”、目标 0 股、无需下单及历史判断。事件详情同时列出生成时刻与生效日。嵌入图可展开信号解释，独立大图定位至当前选中日期并展示完整事件说明。发布后首次访问会由后台重建旧契约缓存。

需要立即驱动单个虚拟账户决策时，使用既有 Web 入口：

```http
POST /api/virtual-accounts/{account_id}/decision
Content-Type: application/json

{}
```

旧合同账户返回`DECISION_COMPLETED`、`DECISION_REUSED`、
`DECISION_SUPERSEDED`或`DECISION_AND_INTENTS_SUPERSEDED`。只有尚未提交渠道且没有
`channel_order_id`的订单意图可以随旧决策失效；已有渠道订单或结果未知时返回冲突。
V4 双市场账户必须健康且为 `RUNNING`，暂停账户禁止人工和自动数据准备、决策。日线决策从 T 交易日实际收盘满 5 小时后开始，准备完整 T 日数据，生成下一个交易日生效的决策；双市场按实际日历处理周末、节假日、夏令时及提前收盘。调用会写入正式决策、账户状态及审计，并可生成待提交订单意图，需取得生产操作授权；仅验证决策时先按授权暂停对应渠道。结果可通过账户快照和事件核对，`DECISION_REUSED` 表示已有决策被复用。

“正常未成交”表示限价买单已按执行时窗结束且确认零成交，不需要人工解除阻塞；
同日再次驱动相同计划返回`DECISION_REUSED`，下一交易日按新的策略决策执行。核验时关联
`CANCEL_REQUESTED`的`planned_deadline`原因、渠道`CANCELLED_ALL`零成交回报和意图
`termination_reason=NORMAL_UNFILLED`。仅看到撤单请求或收盘时间不足以认定安全终结。
明确拒单、已确认渠道现金／可卖量不足、本地未提交过期及有到期依据的部分成交撤余，
均终结本次尝试并保存实际效果，不要求解除账户阻塞；下一周期仍由策略产生新决策。
无明确终结依据的取消和人工撤单仍需核实，结果未知保留冻结资金并等待对账，账本异常继续阻断。
账户详情的执行效果使用当前确认账户及该决策的RAW参考价，不是实时估值或历史账户重建。
升级不会自动解除历史阻塞；完整语义见[PTE尽力执行与账户异常](../packages/paper_trading_engine/README.md#尽力执行与账户异常a-股美股渠道)。

冻结策略不会自动进入SRT或PTE；新版本初始资格为`RESEARCH`。获准的DEV通过SM
`approve_paper_trading(PaperTradingApproval)`绑定发布哈希授予`PAPER_READY`，通过
`deploy_strategy` API写入SRT部署凭据；创建PTE账户仍是独立授权动作。PTE在进程内调用SRT，
账户暂停停止数据准备、决策和新单提交，已有订单和渠道账户继续对账。PTE日调度为每个运行账户创建隔离的SRT
实例并调用`prepare_data()`，准备成功后才执行账户决策；`srt-prepare`只用于人工诊断或独立准备。
准备异常必须先于账户决策明确暴露。
需要把模拟盘里程碑写回策略生命周期时，先导出自包含证据，再由获准的DEV通过SM登记：

```powershell
& $Pte performance export @RuntimeArgs `
  --account-id s002-v1 --recorded-by tomxiao `
  --start 2026-09-03 --end 2026-12-03 --output .tmp\paper-forward.json
```

`--start`、`--end`使用`YYYY-MM-DD`，筛选端点均包含。数据库读取使用一致性只读快照，
导出文件写入显式`--output`；数据库缺失或schema不符时失败。`initial_capital`为所选区间期初
资产，期初来源、快照及统计状态保存在`source`并参与哈希。

日常净值保留在PTE数据库；导出的里程碑证据须先经过人工复核。获准后通过SM的
`StrategyRegistry.record_evidence`登记生命周期证据；TDR不提供对应CLI。

### 策略账户市价清仓退役

获得目标账户的生产退役授权后，在运行中的 PTE 上使用既有控制接口；无须升级待退役
策略，也不应手工改账或直接把状态改为 `RETIRED`。命令须指定账户当前的发布哈希：

若待退役旧策略不支持新版计算合同，须先在原运行版本中经授权暂停该账户，再升级平台。
新版启动不加载 `PAUSED` 账户的策略实现，保留订单及账户对账；恢复后才能手动决策，并须通过
完整的策略校验。`RUNNING` 账户不通过校验时仍阻断启动，不能静默跳过。

```powershell
pte control retire-account --database <运行数据库路径> --port <PTE端口> `
  --account-id <账户ID> --expected-release-hash <当前发布哈希> `
  --actor <操作者> --reason <退役原因>
```

CLI 从指定数据库只读取得控制令牌，经本机 Web API 发起请求。`ACCEPTED` 表示已受理，
`BLOCKED` 表示需根据返回原因处理，只有 `PASS` 且结果为 `RETIRED` 才表示完成。
底层 `POST /api/virtual-accounts/{account_id}/retire` 在未完成时返回 202，完成时返回 200；
请求体为 `expected_release_hash`、`actor`、`reason`，请求头为 `X-PTE-Control-Token`。
相同账户、发布哈希重复请求用于读取或继续同一次退役，不能引发重复卖单或重复回笼。

受理后账户为 `RETIRING`，不再运行策略数据准备或决策，也不能恢复交易。订单轮询持续
推进 EC 退役：先处理旧订单与未决回报，再等待可交易时段和实际可卖数量，以市价清仓，
最后等待实际成交入账、结算及对账通过，将资金回到所属渠道资本池。A 股、美股采用
同一流程，由各自渠道处理交易规则；市价委托不保证即时或全量成交。

通过 `GET /api/virtual-accounts/{account_id}/snapshot` 的 `retirement` 字段跟踪：

| 状态 | 运维含义 |
| --- | --- |
| `DRAINING` | 处理旧订单、撤单及未决回报 |
| `WAITING_MARKET` | 等待实际交易日历中的交易时段 |
| `WAITING_SELLABLE` | 等待渠道确认可卖数量 |
| `LIQUIDATING` | 市价清仓订单处理中 |
| `WAITING_SETTLEMENT` | 等待清仓成交结算、余额核实与资金回笼 |
| `BLOCKED` | 读取 `reason`，处理明确的日历、费率、订单或对账问题 |
| `RETIRED` | 清仓和回笼完成，保留历史账本、成交及审计 |

有持仓的退役由 PTE 独立通过 DFLS 准备日历，不依赖冻结策略可否被新版 SRT 加载。
V4 沿用账户运行绑定；旧账户要求环境 `equity-sources.json` 中有该市场唯一的正式日历源，
且最后持久决策保存明确模型费率。缺失时保留阻断原因并继续渠道对账，禁止用自然日、
工作日推算或默认费率代替。A 股午休和美股提前收市按日历分段执行；美股结算按明确的
下一交易日处理。空仓回笼不要求日历。若出现订单结果未知，应先核实券商回报，不能另发
一笔卖单试探；实际执行须等待渠道事实。上线本接口与实际退役某一生产账户是两项授权。
明确拒单会形成待处理执行异常；核实原因后，可用既有执行缺口确认接口
`acknowledge_execution_gap` 留存处置说明，再由正常订单轮询继续清仓，禁止自动循环重发。

### 已重绑账户更新数据配方

在获准维护窗口内停止 PTE 写入进程后，使用 `pte channel bind-inputs` 或 `bind-recipe`，
显式指定渠道账户、运行数据库、数据目录、已安装发布根目录及 `--definition`。
定义字段为 `account_id/release_hash/fee_rate/binding/execution_reference`；PTE 将其构造为
当前 schema 3 配方并验证冻结声明及独立 RAW 执行参考价。更新不能改变账户发布、交易标的、
执行规则或模型费率；这些变更应使用对应的账户维护流程。

已重绑账户采用数据库原子更新，保留原生效区间、历史配方和资金持仓，无须手工改库或迁移旧记录。
提示旧快照不符时，重新读取当前绑定并核对其他维护操作，禁止覆盖他人刚保存的配置。
失败时原配方保持不变。维护后执行只读发布预检，再按授权启动服务、恢复账户并通过决策 Web API
核对新数据身份；暂停账户仍禁止数据准备与人工决策，配方登记本身不会运行策略。

### WDG、健康检查与故障处理

重启验收要求健康接口返回HTTP 200、`runtime=RUNNING`、`watchdog_healthy=true`，并确认
`instance_id`已改变；版本切换验收还须确认目标`release_id`。超时或健康条件未满足时明确失败。
进程健康与账户、渠道业务告警分别核对；重复发布同一活动版本的身份查询不替代健康验收。

### Web API 在线验收

运维脚本使用 `/api/health`、`/api/system/status?market=CN|US` 和具体资源查询。旧聚合 `/api/status` 已移除。渠道控制使用 `/api/channel-accounts/{channel_account_id}/` 下的现行路由。

旧合同迁入 V4 如需保留同一交易日执行机会，停机期间通过正式 `update_account_bindings` 事务换绑：仅无渠道订单、成交及提交不确定性的旧本地计划可以取消并释放预占；旧 `NO_ORDER` 决策保留原态。事务保留历史决策、采纳证据和周期预算，不能伪造过期、成交或替代决策。新版本启动后按授权恢复账户，再使用在线决策接口产生该交易日的新计划；渠道暂停可用于仅验证决策。已采纳的 V4 状态区间仍禁止重叠，不能沿用此旧合同迁移例外。

周期预算按新冻结执行政策处理：仍使用 `signal_cash_fraction` 则延续；目标政策不使用周期预算时，事务结束旧预算并清理空 pending 状态，绑定审计保留原值及原因，不改变持仓和策略周期。非空 pending 私有字段须显式迁移。换绑后必须验证在线重新决策能够完成，预算状态不能成为隐藏阻断。

历史集合的 `PAUSED`／`RETIRING` 账户如仍绑定旧安装中的精确冻结包，发布预检核验该安装快照及包清单，不强制旧合同升级；须保留对应旧安装目录，直到账户不再依赖该身份核验。

1. 发布前在隔离 DEV 用待发布实现验证 A 股与美股闭环。固定时点和模拟回报用于核对决策、订单、成交和入账，确认重复回报不重复入账。真实供数和重绑事务按发布计划分别留证。
2. 发布启动后、恢复账户前，在 PTE 宿主运行 `python -m paper_trading_engine.online_verify --port <端口> --plan <清单> --json-output <新报告>`。清单填写待验发布的版本、提交及制品清单哈希，以及本次要求的渠道与账户。工具默认只读，检查运行身份、调度心跳、渠道对账、账户状态和发布绑定。清单格式见 [PTE 模块说明](../packages/paper_trading_engine/README.md#web-api-在线验证)。
3. 若发布窗口已满足实际收盘满 5 小时的日线门槛且数据齐备，可经单独授权恢复指定账户为 `RUNNING`，再调用 `POST .../decision`，检查实际采用的发布哈希、决策及数据身份。如只验证决策，按授权保持对应渠道暂停以阻止提交；账户本身暂停时不能驱动决策。当前无到期周期时保留 `BLOCKED`，按获准计划在首个真实周期复验。既有决策复用与本次新增分别记录。
4. 账户按批准顺序恢复。首个真实周期按清单追加决策预期，核对数据准备、决策采纳、订单成交及对账。若本周期预期不交易，明确校验仓位和订单预期。归档 JSON 报告，并记录各渠道的验收结论。

### WDG 服务管理

首次发布完成后，管理员PowerShell从已发布的轻量宿主安装WDG。普通PTE版本和策略发布继续
复用该宿主；只有WDG依赖或服务配置变化时重新执行`install-config`。

WDG配置为`shared/config/watchdog.json`，PTE配置为`shared/config/pte.json`，两者当前均为
schema 1。WDG按`shared/config/active-release.json`选择并核验PTE发布，再调用该发布的
`pte serve-runtime --runtime-root`；PTE在自己的解释器内读取配置并校验发布、策略及数据空间。
WDG宿主独立版本化，普通PTE升级不要求发布相同版本号的WDG。首次安装及服务控制命令：

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
`state/paper_trading/`。`serve`、`once`和离线账户写命令使用同一数据库所有权锁，第二个写进程
将被拒绝。服务运行期间通过现有HTTP/control入口提交在线操作；账户列表与绩效导出使用只读连接。

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

成功返回`REPAIRED`，重复执行返回`ALREADY_REPAIRED`，证据不完整时明确失败。

## 数据目录与备份保留

以下路径相对于生产根目录。`shared/data/`整体保留，按用途管理：

| 路径 | 用途与保留要求 |
| --- | --- |
| `shared/data/market/` | 当前配置的DFLS数据空间，包含行情、日历及准备引用关联的数据资产；由DFLS管理。 |
| `shared/data/input-bindings/` | SRT共享输入绑定，记录请求范围、数据身份及准备引用；用于重试和重启复用。 |
| `shared/data/accounts/` | 各账户准备索引、历史准备记录及计算上下文；支持账户运行与审计追溯。 |
| `shared/data/`根目录旧文件 | 旧CSV、压缩数据及发布清单。当前版本不将其作为行情来源，历史审计仍有引用，继续保留。 |

数据资产、输入绑定和账户记录不适用数据库备份的滚动保留规则。清理时须区分当前引用、历史
审计材料及可重建的临时内容；保留旧数据不要求实现旧格式兼容。后续如需归档或删除历史文件，
应先明确追溯影响及目标清单，再按生产变更授权执行。

PTE每次启动前使用SQLite备份接口创建一致性备份，存入`shared/state/backups/`。当前源码
默认仅保留最新1份同名运行库的启动前备份；新备份成功完成并关闭后，才清理超出保留数量的
旧备份。启动前备份不替代Futu事实核对，也不包含数据目录及配置；跨机恢复仍须完整迁移共享状态。

截至2026-10-05，prod活动版本为v0.6.5，其自动备份默认仍保留3份。保留1份的源码修改尚未
发布；文档及本地提交不改变prod行为，须在后续获授权发布后生效。

## 生产状态与跨机恢复

生产目录按`host/`、`releases/`和`shared/`组织。PTE发布目录不可变；账户、订单、成交、
暂停状态、SQLite审计、SRT准备数据、配置、图表及日志位于`shared/`。
WDG绑定生产根目录，迁移开发仓库无需重装WDG。Windows服务、Futu OpenD及登录状态单独核对。

跨机延续同一条模拟盘观察序列，需要迁移完整SQLite、SRT准备数据及配置组成的完整`shared/`，
并与Futu活动订单、成交和持仓逐笔核对；核对完成前保持新单阻塞。
重建开发环境或创建新的开发态状态不等于恢复原生产观察序列。

## 账户事实与已知限制

PTE按模型费用记录策略账户。经核实的Futu实际费用与模型费用差额，记入零初始资金的
渠道平账账户，不混入策略绩效；未知费用和订单结果不得推断入账。
日调度与Web请求不等待前瞻图的独立后台构建，图表缓存不能代替账户和渠道事实。

当前代码支持 Futu A 股和美股模拟渠道，Web 服务只监听 localhost，WDG 服务名为
`CZSC-PTE-Watchdog`。实际部署版本和已接通的渠道以运行宿主的只读核对为准。
V4 按可用的正式公司行动事实入账。旧合同或事实不足的账户遇到无法解释的非交易变动时，
保留渠道差异告警并人工核对，费用差额仅按已确认的归因规则记录。
