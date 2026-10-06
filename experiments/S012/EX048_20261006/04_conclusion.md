# EX048 阶段三趋势原型结论

完整REX已生成，8/8 FULL账户成功，缺失0，原三门同时达标0。阶段三尚未完成。

绑定输入/账户独立审计：PASS；真实信号及语义账本等价验证：PASS。原件、账户恒等式和汇总指标核对通过。审计与等价比较分别由独立验证产物支持，完整原件保存于实验artifacts。

518850.SH，完整上市后开发池2020-06-05至2026-09-30；实际账户2020-06-08至2026-09-30共1534会话。初始10万元，每侧0.1%成本，限价买入/市价卖出。BuyHold净年化14.2867%，回撤幅度30.2906%。

三个硬门同时要求：净年化≥21.4300%；回撤幅度严格<30.2906%；闭合周期×60/1535≥5（至少128个闭合周期）。收益优先排序依次为净年化降序、回撤幅度升序、真实频率降序；排序不替代三门同时验收。

收益门0/8，回撤门5/8，频率门2/8。

|候选|净年化|回撤幅度|闭合周期|每60日频率|持仓会话比|实际费用/元|收益/回撤/频率门|
|---|---:|---:|---:|---:|---:|---:|---|
|C4507|9.0546%|18.4388%|29|1.1336|84.2243%|5059.84|未过/通过/未过|
|C4502|5.6662%|18.6194%|73|2.8534|43.2203%|15888.11|未过/通过/未过|
|C4505|3.0121%|23.2089%|27|1.0554|35.3977%|5406.65|未过/通过/未过|
|C4501|2.1109%|27.6857%|109|4.2606|66.4276%|19407.17|未过/通过/未过|
|C4500|-0.8029%|39.0932%|218|8.5212|62.0600%|32740.31|未过/未过/通过|
|C4504|-0.9382%|32.6499%|71|2.7752|34.3546%|12160.35|未过/未过/未过|
|C4506|-3.4411%|22.5073%|103|4.0261|13.9505%|9155.74|未过/通过/未过|
|C4503|-7.6945%|38.9734%|173|6.7622|47.7184%|24245.79|未过/未过/通过|

## 收益机制与反面证据

收益最高C4507：净年化9.0546%、回撤幅度18.4388%，29个闭合周期、频率1.1336。收益及频率两门未过：距收益门12.3754个百分点，距最低闭合周期数99个。

最高收益项持仓会话比84.2243%，实际费用5059.84元。持仓会话比只描述有持仓的会话比例，不等于资金加权仓位。费用为真实fills合计，不能直接加回终值作为零成本策略。

最高收益项采用10日动量、最长60日持有、5%计划跟踪止损、3%买入限价溢价、75%配置。较长持有和较少交易呈现收益研究机会；参数共同变化，当前证据无法把差异归因于单一动量长度或止损。

频率达标的C4500、C4503均为负净年化且回撤不合格。C4506的短持有与确认组合也为负净年化。保留这些反面结果，不能通过筛去坏年份、重设开发池、增加虚假闭合或放宽收益门获得通过。

八项参数、策略与features字节闭包及汇总经济指标与EX047对应原型一致；EX048是调度修正后的正式重执行，不计作新增独立经济发现。EX047保留自身技术失败和真实8账户证据，EX048使用自身真实attempt、输入身份与完整receipt。

## 最高收益项连续年度账户

年度按上年实际收盘权益连续计算，2026仅至9月30日。

|年份|期间净收益|权益增量/元|期末权益/元|持仓会话比|
|---:|---:|---:|---:|---:|
|2020|-5.3253%|-5325.29|94674.71|75.1773%|
|2021|-3.3631%|-3183.98|91490.73|82.3045%|
|2022|8.3215%|7613.39|99104.11|85.9504%|
|2023|5.5966%|5546.48|104650.60|95.0413%|
|2024|13.5797%|14211.28|118861.88|92.9752%|
|2025|36.5335%|43424.45|162286.33|89.3004%|
|2026|4.4406%|7206.43|169492.76|58.5635%|

利润集中2025，2020与2021为负；所有已观察开发年份继续纳入证据，不能声明独立样本外。

正式等价证据只授权其确切模型、features、市场输入、订单政策及经济协议所覆盖的研究比较；后继域和gate仍需显式绑定这些身份。

## 后继研究与交付缺口

保留最高净收益前沿及EX046 C4309回撤＋频率可行前沿，围绕同源码的持有、退出和入场贡献进行必要单因素与交互对照；同时核对风险与确认职责，不因频率合格而降低收益优先级。

阶段三仍需适用且批准的等价gate、预先声明参数域及资源/停止规则、完整提案状态与选择历史、边界与有依据扩边反证、全部筛选达标及选中前沿的真实FULL覆盖、全部达标handoff、完整CandidateSet和人工报告。固定八项对照不足以自行收口。

## 原件引用

- `experiments/S012/EX048_20261006/artifacts/rex/trials.json`，SHA256 `c1aba6543e47009d3df81f8f59ab4194ffbaf13490d2ab77d6cbd09508ed4061`。
- `experiments/S012/EX048_20261006/experiment_binding.json`，SHA256 `a79bfa5ee04bf3b2aa106d94949590f07e4ac7aaf473b2b294355a6a2cc7763a`。
- `experiments/S012/EX048_20261006/experiment.py`，SHA256 `8e86a18eda85f98214f1bf251ca10ebbb67baf3930b2bc7e8185d1ed5afdaae2`。
- `experiments/S012/EX048_20261006/strategy_runtime/strategies/s012.py`，SHA256 `a19077a4e490ff000ee1db1567e01e8b5dfa8847be914d6ea45310f0448cadf7`。
- `experiments/S012/EX048_20261006/strategy_runtime/resources/features.csv`，SHA256 `8ed38c5eb10fd15d112500b90b8871403554b41a77a9f1d71c9e897b24864192`。
- `experiments/S012/EX048_20261006/feature_provenance.json`，SHA256 `4c33418cb0da1e21e0bea973dcd24698d545b0e3925e6476ece7159fdd028858`。
- `experiments/S012/EX048_20261006/01_goal.md`，SHA256 `00fd2b44bd200b79ea80e9f8ede547477e3140e25f3190ed00c5eecb935b31bd`。
- `experiments/S012/EX048_20261006/02_design.md`，SHA256 `f7491e52e2393bccab03218260c2b748ccc7d00999569b2e7d1ab0be33ae7498`。
- `experiments/S012/EX048_20261006/03_execution.md`，SHA256 `898765b175e835c24d4cb98f36f03d25d5bf69ce2f91723d2e9ffaac9a5c7fb3`。
- `experiments/S012/EX048_20261006/artifacts/preflight.json`，SHA256 `c6cf28cc550b1f3ec8c8a5014db4597126a3cf67c3ff71c7dd0d9365bd2361f4`。
- `experiments/S012/EX048_20261006/artifacts/rex/execution_receipt.json`，SHA256 `d67d5f83054cb4d4ccc80b78bb88ed246f465e035b8ea725a59c5c93cbf517f8`。
- `experiments/S012/EX048_20261006/artifacts/rex/evaluations/e177a540633f4745b8fb7fc2d542f24f/result.json`，SHA256 `2d5e7ba3991b1731da2be7f213da639c1b72e4c913d8da159d321dcea5b10f2d`。
- `experiments/S012/EX048_20261006/artifacts/rex/evaluations/f78122bfc91f45898a2402c5d18eeb04/result.json`，SHA256 `15e31ee776a16e296fa5cc7d9e6163db1eccf2d76fa715ee0ce29caa2b0bdc1a`。
- `experiments/S012/EX048_20261006/artifacts/rex/evaluations/7c51492cda7b4a3d866c5298b9393bbe/result.json`，SHA256 `468e8a560fb073154e4daa34b46a97015912f0a2d547be90d647ac6518b65568`。
- `experiments/S012/EX048_20261006/artifacts/rex/evaluations/1d53f9ed540743bcbeca75745314497f/result.json`，SHA256 `99d5da712d6cb6837b61c706fc81cc2916ad70059ee5415be53c6e3345a3e538`。
- `experiments/S012/EX048_20261006/artifacts/rex/evaluations/45bb6d2df54046d681ed2ffdaca85fdf/result.json`，SHA256 `9cb18e9167e2d07542071ad8bfab7505eb2be0decc6c4055d1a84081912f733d`。
- `experiments/S012/EX048_20261006/artifacts/rex/evaluations/f87d31458f9d4383aff2ca3f54ad995f/result.json`，SHA256 `6ed799593c2eaa2a1d45e25bbb43d5e1d2caa4cd6f5781269bfb270e66bac6c9`。
- `experiments/S012/EX048_20261006/artifacts/rex/evaluations/95d4e2164e5a4e3486fab324c12430c7/result.json`，SHA256 `5839d2d80aaa6f2a5c60da23e8f15ffeb426888e8f4961ffb481fbfe1334c76e`。
- `experiments/S012/EX048_20261006/artifacts/rex/evaluations/f511c7022b13419f96ba158554471083/result.json`，SHA256 `b0950a1610bca16fc4cdc3d3851a9c91ca3a9ad4dae02f8a61576e226d6f2c8e`。
- `experiments/S012/EX048_20261006/artifacts/independent_account_audit.json`，SHA256 `8dc4c385d6e6af00d60e275f8df59cdb438d2f87af1e80a699f255897c00832d`。
- `experiments/S012/EX048_20261006/artifacts/rex/search.json`，SHA256 `783c2ba8b7b771077b16046cb12c86537cbf4e0a64ebb47a43aaa4b0195996d6`。
- `experiments/S012/EX047_20261006/artifacts/rex/trials.json`，SHA256 `fa7ce5c746bc153bde98ad1cbfb97dc871ad5a84c439c86ce54eccd06a96fce1`。
- `experiments/S012/EX048_20261006/artifacts/operational_equivalence.json`，SHA256 `457c9ce0818a2f2218ec9a44d5ac6b3199a2c85ceef3c7e8846855c477ee4ce7`。
- `experiments/S012/EX048_20261006/artifacts/supplementary/build_ex048_reports.py`，SHA256 `37f03e38d99f747589bbd13fa7859cc09d0884938783287ddbaad6b10fa6e5cd`。
- `experiments/S012/EX048_20261006/artifacts/supplementary/build_ex046_ex047_reports.py`，SHA256 `62182e6faa8377914bd5ccbc050514ccb4d225975fef4a455aff6ec59f84a347`。

## 独立复算

从仓库根执行，保留封存原件，复算结果仅写入`.tmp/`；需保留本机DFLS受管资产及实际REX制品。

```powershell
.venv/Scripts/python.exe experiments/S012/EX048_20261006/supplementary/independent_account_check.py --experiments EX048_20261006 --output .tmp/s012-audit48-reproduction.json
.venv/Scripts/python.exe experiments/S012/EX048_20261006/supplementary/compare_accelerator48.py --experiment EX048_20261006 --output .tmp/s012-equivalence48-reproduction.json
```
