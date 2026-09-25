# 策略研究总入口

本文是策略研究领域的共享事实与索引入口。它记录用户、策略研究员Agent、首席投资官Agent之间的
协作关系、当前研究项目、共同证据边界和跨会话恢复方法。角色执行细则分别由以下文档维护：

- [策略研究员Agent](RSCH_AGENT.md)：探索、不可变实验、策略实现和候选交付；
- [首席投资官Agent](CIO_AGENT.md)：候选受理、评价合同、独立体检、裁决、冻结和SRT部署。

具体策略的目标和当前结论读取`research/<策略ID>/HANDOFF.md`；不可变研究事实读取
`experiments/`；正式策略身份、冻结版本和治理证据读取`strategies/`。开发环境、平台架构、
测试规则和PTE运维见[开发运维交接](../docs/DEVELOPMENT_HANDOFF.md)，候选结构见
[策略候选包](CANDIDATE_PACKAGE.md)。

## 角色与授权关系

用户是业务目标、风险偏好和角色授权的最终来源。策略研究员和首席投资官均由独立LLM Agent会话
承担，在用户授权的工作空间和任务范围内使用仓库资料及平台工具：

| 角色 | 简称 | 主要职责 | 不承担的职责 |
| --- | --- | --- | --- |
| 用户 | Principal | 确认业务目标、硬约束、角色切换以及冻结、部署和生产授权 | 不由Agent推断未表达的风险偏好 |
| 策略研究员Agent | RSCH | 建立假设、预注册实验、实现策略、形成候选包 | 正式裁决、冻结、部署和PTE操作 |
| 首席投资官Agent | CIO | 锁定评价合同、独立体检、形成裁决，并按授权冻结和部署 | 替候选调参、改实验、改平台或默认操作生产 |
| 平台开发者 | DEV | 维护TDR及独立包、测试、发布与运维能力 | 在未切换角色时作研究或投资裁决 |

每个Agent会话在同一阶段只持有一个角色，开始工作时必须声明身份、目标和授权范围。角色切换
需要用户确认和显式交接，不能在一次执行中由同一Agent同时提交候选并批准自己的候选。

当前平台记录操作者声明，但尚不识别或鉴权真实用户或Agent身份；治理印章中的
`actor_identity_assurance`为`UNVERIFIED`。因此角色隔离依赖用户授权、独立会话、不可变证据和
平台哈希链共同保证。

## 策略身份与交接链路

```text
用户授权RSCH
    ↓
SXX策略族 → SGC研究批次 → 不可变实验 → SXX-CXXX候选包
                                              ↓ 角色交接
                                         用户授权CIO
                                              ↓
                    candidate review → evaluate → CIO裁决
                                              ↓ 按当前任务授权范围
                                      SXX-vN冻结版本
                                              ↓ 授权范围包含部署
                                        SRT部署凭据
                                              ↓ 独立的生产/账户授权
                                          PTE虚拟账户
```

同一批次可以形成多个候选，但冻结版本必须绑定完整证据并原样保存同一实现和参数。冻结、SRT部署
和PTE账户创建是三个独立动作。冻结版本进入模拟盘后禁止原地调参；任何公式或参数变化都必须
形成新候选并重新经过研究及治理链路。

## 当前研究项目

| 策略族 | SM名称 | 标的 | 当前阶段 | 交接入口 |
| --- | --- | --- | --- | --- |
| S001 | 科创50多因子趋势策略 | 588080.SH | `PAPER_READY`，v1/v2在PTE观察 | [S001](S001/HANDOFF.md) |
| S002 | 中证500三连跌修复策略 | 510500.SH | `PAPER_READY`，v1在PTE观察 | [S002](S002/HANDOFF.md) |
| S003 | 中证500成分资金流早盘延续策略 | 510500.SH | `PAPER_READY`，v1在PTE观察 | [S003](S003/HANDOFF.md) |
| S004 | 尾盘流动性错位修复 | 588080.SH | `RESEARCH_PAUSED`，候选保留作标杆 | [S004](S004/HANDOFF.md) |
| S005 | 588080中频增强策略 | 588080.SH | `TERMINATED_NO_CANDIDATE` | [S005](S005/HANDOFF.md) |
| S006 | 588080全量信息策略研究 | 588080.SH | `TERMINATED_NO_CANDIDATE` | [S006](S006/HANDOFF.md) |
| S007 | 科创50多源机会风险门控策略 | 588080.SH | `PAPER_READY`，v1在PTE观察 | [S007](S007/HANDOFF.md) |
| S008 | 黄金ETF中期趋势突破策略 | 518880.SH | `TERMINATED_NO_CANDIDATE`，研究注册已终止 | [S008](S008/HANDOFF.md) |

策略族名称以`strategies/SXX/family.json`为准。研究批次由SGC区分；候选工作名称和冻结版本名称
分别由候选快照、HANDOFF和正式版本记录维护。

冻结版本的前瞻监测方案与PTE账户一一绑定：

| 冻结版本 | PTE账户 | 监测方案 |
| --- | --- | --- |
| S001-v1 | `s001-v1` | [S001-v1](S001/candidates/S001-v1_MONITORING.md) |
| S001-v2 | `s001-v2` | [S001-v2](S001/candidates/S001-v2_MONITORING.md) |
| S002-v1 | `s002-v1` | [S002-v1](S002/candidates/S002-C001_MONITORING.md) |
| S003-v1 | `s003-v1` | [S003-v1](S003/candidates/S003-C001_MONITORING.md) |
| S007-v1 | `s007-v1` | [S007-v1](S007/candidates/S007-C001_MONITORING.md) |

S008已于2026-09-25无候选终止，当前没有活跃的S008研究任务；最终证据与重启边界见
[S008研究交接](S008/HANDOFF.md)。S007-v1保持冻结并在PTE前瞻观察，固定v1收益归因批次已经
收口，不继续使用既有开发池搜索S007-v2。准确状态、最近权威实验和禁止事项始终以各策略
`HANDOFF.md`为准。

## 共享研究模型

完成态策略是在既定数据、成本和执行约束下工作的确定性函数`y = f(x)`：

- `x`是决策时点因果可得的行情、资金、宏观、事件、因子和信号；
- `F`是尚未确定参数的策略结构，规定输入职责、组合、门控、退出和仓位；
- `f`是通过联合搜索、平台审查和稳定平台代表点选择得到的具体函数；
- `y`是目标仓位、调仓决策或原子执行计划，收益是对完整执行结果的评价，不是策略输出本身。

模块职责为：FSC复用`x`的定义，STC复用`F`的结构，研究实例化`f`，SRT计算`y`，TXE生成统一
成交与账户事实，SE执行确定性数值审计，TDR组织正式评审，SM保存身份及治理事实，PTE在独立
授权后执行前瞻模拟。

## 共同证据规则

### 用户目标与硬门

跨策略偏好只能作为新批次立项目标的输入，不能自动成为所有策略的硬门。只有用户明确确认并在
最终EvaluationMandate锁定的目标和约束，才能决定正式资格；年度分解、PBO、DSR、Bootstrap、
参数邻域等未被锁定时均为诊断证据。

### 不可变实验

正式实验路径为`experiments/SXX/YYYYMMDD_SXX_EXnn/`。实验在读取结果前预注册问题、数据、协议
和裁决规则；有效manifest生成后保持只读。发现错误时创建新实验并声明继承关系，失败实验和
不利结果同样保留。目录契约见[实验档案说明](../experiments/README.md)。

### 宽进严出

RSCH采用探索模式与正式实验模式。探索模式主动扩大金融假设、数据维度、因子和原型空间，允许
根据中间结果调整方向，但结论必须标记为`DISCOVERY_ONLY`并记录已见数据边界，一次性数据、代码
和试算产物只能存放在`.tmp/`。值得验证的线索必须另建不可变正式实验；只有正式实验可以形成
候选证据。

Tushare是默认且优先的数据源。研究员应充分利用8000积分等级接口和当前有效的独立数据权限；
未经用户明确授权，不得接入、采购、抓取或依赖其他外部数据源。具体权限、探索试取、正式入档
和凭据保护规则见[RSCH Agent](RSCH_AGENT.md)。

### 数据与污染

- 开发池：已用于查看、比较、调参或接受决策的数据；
- 内部验证：开发池内的年度、滚动、留一和walk-forward窗口，仍属于开发证据；
- 前瞻观察：版本选择完成后新产生且未反向参与该版本选择的数据。

一旦根据截止日后行情修改参数、筛选候选或作接受决定，该区间就进入新候选的开发池。发生污染
时更新新候选截止日并保留说明，禁止删除不利结果或回写历史档案。

### 执行与裁决

正式候选的成交、费用、现金、持仓和净值必须由TXE按EvaluationMandate独立复算。信号收益只
用于解释；候选PK和冻结使用完整账户执行口径。`FAVORABLE`、`MIXED`、`WEAK`、`ADVERSE`是
证据标签，不等于人工投资决定。首个候选没有在位策略时，以相同窗口、资金和执行口径的BuyHold
作为明确对手。

### 严格成功语义

数据缺失、截止不足、部分账户成功、渠道仅受理委托或外部结果未知都不能汇总为成功。输入或
身份不完整时不产生决策；没有实际意义的胜者时保持原状态或终止批次。

## 研究环境与公共查询

策略研究与平台开发共用仓库根目录的唯一`.venv`。按
[开发环境安装](../docs/DEVELOPMENT_HANDOFF.md#开发环境安装)安装`.[research,test]`；Optuna和
tsfresh只服务候选搜索与特征发现，不进入冻结SRT和PTE生产依赖闭包。正式实验必须在manifest中
记录实际研究依赖及版本。

所有角色均可使用只读查询和验证入口：

```powershell
.\.venv\Scripts\czsc-trader.exe catalog validate
.\.venv\Scripts\czsc-trader.exe catalog list --kind factor --status READY
.\.venv\Scripts\czsc-trader.exe template validate
.\.venv\Scripts\czsc-trader.exe template list --status READY
.\.venv\Scripts\czsc-trader.exe strategy list
.\.venv\Scripts\czsc-trader.exe archive validate --all
```

角色专属写入命令和阶段授权见对应Agent描述。

## 跨会话恢复

### RSCH恢复

1. 阅读[RSCH Agent描述](RSCH_AGENT.md)；
2. 进入目标`SXX/HANDOFF.md`，核对批次目标、开发截止、权威实验和禁止事项；
3. 验证研究数据、注册表及档案；
4. 只在已有协议允许时继续，否则创建新的预注册实验；
5. 完成后更新当前结论、风险和唯一下一步，不把HANDOFF写成历史流水账。

### CIO恢复

1. 阅读[CIO Agent描述](CIO_AGENT.md)；
2. 核对用户授权覆盖受理、体检、冻结或部署中的哪一阶段；
3. 读取候选包、最终Mandate、源实验和既有治理事实；
4. 通过TDR公开入口工作，禁止人工修改治理区；
5. 每完成一个阶段单独报告结果和下一授权门。

## 资料权威边界

| 路径 | 权威内容 |
| --- | --- |
| `research/RSCH_AGENT.md` | RSCH角色、授权边界、研究流程和交付格式 |
| `research/CIO_AGENT.md` | CIO角色、授权门、体检、冻结和部署流程 |
| `research/SXX/HANDOFF.md` | 批次目标、当前结论、风险、下一步和禁止事项 |
| `research/registrations/` | 研究身份、可修订意图、预注册凭据和研究事件 |
| `research/SXX/materials.json` | 批次绑定的标的、数据和材料身份 |
| `experiments/SXX/` | 不可变实验、失败路径和机器证据 |
| `strategies/` | 正式策略身份、候选封存、冻结版本、资格和治理证据 |
| `catalog/` | FSC信息族、因子和信号定义 |
| `strategy_templates/` | STC策略函数模板 |
| `data/raw/` | 受控研究数据 |
| `data/backtest/` | 可更新的普通回测数据 |
| `outputs/` | 可再生回测输出，不参与策略接受 |

PTE生产状态属于独立运行环境，不是研究资料来源。需要把模拟盘表现纳入策略生命周期时，先由PTE
导出自包含证据，再经人工复核写入`strategies/`；研究文档不直接读取或解释生产数据库。

普通文本身份统一归一化LF，JSON规则使用语义SHA-256，行情CSV和二进制使用原始字节SHA-256。
新实现统一复用`src/czsc_trader/identity.py`，历史实验档案保持原样。
