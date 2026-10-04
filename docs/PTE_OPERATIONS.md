# PTE发布与运维

本文说明获授权后的生产发布、账户操作、服务管理和恢复方法。
DEV职责与工程决策见[DEV Agent](DEV_AGENT.md)，公共观察能力见
[PTE使用说明](../packages/paper_trading_engine/README.md)。所有命令从仓库根目录执行。
命令示例不构成生产操作授权；操作前确认具体目标、活动发布和共享状态。

## 发布、账户与服务操作

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
暂停只阻止新单，已有订单继续对账。PTE日调度为每个账户创建隔离的SRT
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

PTE当前只实现Futu中国市场模拟交易渠道，控制台只监听localhost，WDG服务名为
`CZSC-PTE-Watchdog`。实际活动版本、服务健康及渠道状态必须只读核对。
未复权正式账本尚未建模ETF现金分红、份额拆分等公司行动；此类非交易变动发生时，
保持渠道差异告警并人工归属，禁止按交易费用自动调账。
长期经济绩效使用后复权研究口径，待公司行动契约完成后再与PTE账本完整对齐。
