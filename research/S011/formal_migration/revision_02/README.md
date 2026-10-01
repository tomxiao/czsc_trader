# S011 显式基准与阶段二至四正式迁移

目标已达成：显式BuyHold执行契约已实现，阶段二、三、四的正式交付产物已补齐并通过公共校验。
阶段二、四保留PARTIAL研究状态，缺失证据及历史问题见下文；校验PASS不表示这些研究缺口已消除。

| 交付 | 当前修订／状态 | 人工报告 |
| --- | --- | --- |
| 阶段一 | 2／COMPLETE | [原目标与显式基准](../../deliveries/MANDATE/2/report.md) |
| 阶段二 | 2／PARTIAL | [4个职责组件](../../deliveries/COMPONENTS/2/report.md) |
| 阶段三 | 2／COMPLETE | [36配置及完整搜索记录](../../deliveries/CANDIDATES/2/report.md) |
| 阶段四 | 1／PARTIAL | [自检、排序与待决定事项](../../deliveries/ASSESSMENT/1/report.md) |

## 平台修改

- TDR `EvaluationRequest.benchmark`必填；`EvaluationBenchmark.execution`必须为
  `NextOpenBuyHold`或`LimitBuyHold`，均显式传入lot_size。限价契约另声明premium、price_tick、
  price_limit_ratio、maximum_order_quantity，非法值在构造时拒绝。
- 限价基准复用SRT的资金预占、整手及订单拆分，TXE负责成交和五张实际账本。
- 请求与结果身份绑定完整基准合同及执行语义版本；新评价产物schema 4保存实际基准证据。
  环境身份另绑定基准、SRT计划和TXE源码。
- SE `EvaluationScenarioContext.benchmark_contract_sha256`阻断不同基准混比。
- 阶段一使用`BenchmarkRequirement`；阶段四以`benchmark_mandate_item_id`绑定已确认合同。
  新交付schema 3，旧schema 1/2按原语义只读校验；旧交付字节和哈希保留。
- 平台提交：`b2960a89`、`7edc9bf2`。[聚焦验证记录](platform_validation.json)；本轮未做仓库全量回归。

## 执行与验收

- [EX30失败原件](../../../../experiments/S011/20261001_S011_EX30/experiment_manifest.json)：
  1次调用完成2份策略账户后，基准决策对账因action列缺失停止。失败、原请求和实际结果全部封存。
- [EX31后继执行](../../../../experiments/S011/20261001_S011_EX31/03_execution.md)：
  100次受管调用、135份策略账户及对应基准账户；675张策略账本、675张基准账本与历史对账通过。
  标准基准恢复938000股，期末权益1461437.844；标准与20bp压力均核对全账本。
- 36中心沿用原登记内容，64个既定扰动点通过公共API保存独立身份及本次父评价派生证据。
- 36配置恢复原目标判断：108项通过、72项条件不适用；000244恢复原判定。
- 原16层、全部成对关系、9对不可比、15个名次区间及10个敏感性方案核对通过。
  第一层仍为618→624→621→628；621保持第3位及历史用户偏好。
- 502份历史来源哈希不变；EX29及revision_01阻断材料保留；原三份旧版交付公共校验PASS。
  [验收结果](focused_verification.json)、[排序验证](comparison_verification.json)、[身份映射](identity_mapping.json)。

## 保留的研究限制

32配置缺少主联合扰动，000193缺同源码20bp压力；9对不可比与15配置名次区间仍保留。
EX12对EX01 manifest的历史引用差异仍未解释。旧PBO/DSR按原搜索范围引用，不能宣称覆盖EX28扩展。
新SE区间为当前公式诊断，不扩大独立样本；全部输入属于已见开发池。本轮新增参数提议和独立样本均为0。

621的联合邻域仅1/16达原目标，滚动超额和联合回撤恶化等不利证据保留。
历史选择映射见[记录](historical_selection_mapping.json)，不补造用户已审阅本次新交付的决定。

## 复核与后续

用[验收脚本](verify_deliveries.py)核对原件哈希、登记、受管回执和公共阶段交付；
[构建脚本](build_deliveries.py)保留全部映射和排序核对。重新执行须新建后继实验编号。
实验数据制品与交付中的实验副本沿用仓库本地存储约定，不提交Git；跨机器恢复须另行同步受回执认证的制品。

建议先做仓库全量回归，再同步模块README和研究员Agent文档。进入阶段五技术检验须核对本次新交付及用户授权；
冻结、合并、tag、推送与生产操作按各自授权边界推进。
