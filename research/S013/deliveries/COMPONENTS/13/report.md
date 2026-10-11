# EX078：最近波动变大，能否帮助决定提前退出

本轮固定4日/20日波动比，检验原C8880已经实际持仓、而T当天原策略仍计划继续的样本。两个预定用途均未获支持；没有启动任何新账户、费用压力或32点扰动。

## 目标保持

原四项经济要求与只做多、不加杠杆保持：整体收益、逐年回撤、全开发区间平均每60日不少于4笔闭合交易，以及buyhold亏损年份策略严格正收益。最终改善偏好仍是标准32点扰动收益Q10更高、回撤Q90更低，并报告逐项/联合达标率；不新增32/32硬门。

此项是阶段二信息检验，不能证明账户达标或抗扰动改善。原510500.SH开发区间、2019预热、后复权计价、固定1%执行合同保持；无分红重复计入，无新增数据源。

## 做了什么

固定std4(logCloseReturn,ddof0)/std20(logCloseReturn,ddof0)。控制原EX07122项、恢复late_recovery并加入log-return std20本身，共24项。未来收益比较明早卖出与继续4个完整交易日后卖出：两端同一SELL费用抵消，不错误扣一个新BUY费用；风险只观察同期Open/Close，不等于实际账户最大回撤。

原1635信号日不删日期，唯一因果持仓池390日；388日未来标签已成熟，379日全部特征完整。区间采用500次40日全日期块重抽样；相位在原全日期轴固定。2021—2025年合计316日进入严格标签成熟后的逐年伪样本外预测；2026年只有11日，不满足20日测试样本最低数，按不可用保留，未补零或移除年份。

| 标签 | 控制后秩相关 | 描述性95%区间 | 新组件预测误差相对原控制 | 相对仅用历史均值 |
| --- | ---: | ---: | ---: | ---: |
| 继续4日收益 | -0.012186 | [-0.145356, 0.113759] | +0.2432% | +4.2381% |
| 未来4日观察下行风险 | -0.087649 | [-0.230167, 0.041873] | +0.0988% | +13.8733% |

两项区间均跨过零，两个新增模型整体误差也都更高。按预定方向，将此固定组件记为未支持用途，并停止邻近窗口、翻符号和退出阈值救援。

## 正面线索与反证一起保留

- 收益模型在2021、2022、2025相对原控制有局部改善，但均未超过训练历史均值；2023及2024加入组件更差，不能只挑改善年份。
- 风险模型在2023、2025同时好于原控制与训练均值，这是有限正面线索；2022仅好于控制却差于均值，2021/2024加入组件更差，全组仍差于两基准。
- 2022年按事前训练分位切出的高波动集中组，平均继续收益约+0.2351%，低组约−0.0633%，与“高集中应更早卖”的收益方向相反。两组平均观察风险也为高组1.2887%、低组1.7467%，不是高集中风险更大。这里只是条件价格标签，绝不当作真实交易收益。
- 合并成熟年份的高集中组继续收益约+0.6808%、低组约+1.3473%；高组收益较低仍为正，不能据此认定提前退出有盈利优势。2023等年度分位组人数不足20，均值明确不可用，未把薄组当零。
- 五相位及年度符号不一致；完整数值、缺失理由和独立复算均保留。

## 判断与下一步

当前已检验的价格确认、恢复、压力和退出表达，尚未形成可靠的抗扰动改善依据。这不是全部价格信息无效，也没有证明三个约束不能兼容。EX066的事后正收益机会供给只说明历史有机会，未证明可提前识别并按真实限价、费用和足够交易次数兑现。

保留原候选与历史资格；C8880仍是此前六项复核对照中的参考基准，不能称已解决稳健目标。EX077整策略已在总收益与频率门失败，不用本轮组件改装救援。当前族停止无新依据的连续改窗、加过滤与提前退出账户。

最值得继续的问题是“什么事前信息能可靠区分扣费后值得做的反弹与无效交易”，并验证有足够数量与盈利余量兼顾频率和下跌年份。当前没有足够证据推荐下一个具体因子。后续应从新的、可解释且可证伪的机制依据出发，而非因本轮失败机械添加因子；原目标尚未达成。

## 验证范围

主方法已在真实统计前公开固定；唯一main统计。人工因果/边界检查PASS，原native完整序列化与公开证据完全一致，独立组件/持仓/标签/相关/重抽样/成熟预测复核PASS；0新账户、0provider调用。区间与伪样本外均来自已见开发池，不是封存验证，未纠正反复研究选择偏差。完整账户/五项自检/32点未运行，不填结果。


正式证据：

- [plan.json](evidence/9fcefe932a1a6791d9bee71ff2579dd18a2e35863c5d31f91108e0f399c1465e.json)
- [focused_checks.json](evidence/4391265e4ac8376bafbb59b9e5692c0a40a23dfefeba4c5195999b44167505a5.json)
- [.tmp/s013-vol-concentration/component.py](evidence/fbe438037ab818960439d3f8b003d490fb96aaa4defecbbbcf7b60b8d5a54994.py)
- [.tmp/s013-vol-concentration/focused_checks.py](evidence/dc568327b857b1abc28221a68777e89dc5317c9dc6643ff22f3ec57ccdb57e0f.py)
- [.tmp/s013-vol-concentration/inputs.py](evidence/4ce59f2af95d64b9343d0194434552b74f5f5b65032cbfe88a083a054cff751c.py)
- [.tmp/s013-vol-concentration/vol_statistics.py](evidence/1d961783ad677bd72f9e0e5d04f30787d1e076a8b63362ba428c658fb264a83b.py)
- [.tmp/s013_vol_research.py](evidence/c8709a41ade87f0c952fd05301d964eba579378790f34a1d8fec928da09e9de4.py)
- [research/S013/experiments/EX071_20261011/src/continuation_core.py](evidence/752ebc55ce9cd401645410d57508fc0a2633df3ac1a1f386ae9bcd0df50cc2cf.py)
- [research/S013/experiments/EX058_20261011/src/common.py](evidence/f38c71d3392fb791fdd064f366cc251e33c064d7b88a0cd8b737f2603ccf236b.py)
- [input_checks.json](evidence/7a56d7facdc96bfcb3e5edd88ca7a5d55180f22ae2cf5301ac14649bd3acbe0e.json)
- [features.csv](evidence/9b6d37ca64f20657f0e0b98dc75c3aa3914e3a7e928b13af48a04e001cb85452.csv)
- [labels.csv](evidence/4d2581856d2a1cd92f2dafe005077b2d453a77a0bf2cd3c3b98d6ccae92c69a7.csv)
- [scopes.csv](evidence/13da45bf0cc0dd27bd64fb0bbb1c65002bf97f63826ee3d098119df83d1c0995.csv)
- [known_state.csv](evidence/b2f0d2a1436e14aeb39569f09e68d9bd6dfd02b6c0ecb205396d5aa0682220ba.csv)
- [prices.csv](evidence/499377d8075acbed61555029809b7449dc5703e24ad04bbc6abf8e095c479a0e.csv)
- [statistics.json](evidence/4ab680c5d6eadcdccfe0222a5494f0b83d0f0d7896f9dc6ce580314d8c8269e4.json)
- [study_complete.json](evidence/37e6cc885a89cd54e3ecc2d18bd510e56c27ffcad462ca113505234c86a9fe62.json)
- [verification.json](evidence/aa84ae72ab588cc0978cb8e7711c9af38b11738dd1c3ef6cef7cd0ec0773102b.json)
- [audit_audit.py](evidence/87387d0477ad7534f470ca30db3d5fb4096b4b8e9e5a495275bd36f79c8eae8b.py)
- [audit_synthetic.py](evidence/cde3ad31e0b3ae3b5cddcc694b547c9c4299f083ac73003d4e0b5699b9072be6.py)
- [audit_synthetic.json](evidence/6ed6e5c020f987efbf589bdc3f4be891935c81a5dbfc1988c92f2b59473ff49f.json)
- [audit_freeze.json](evidence/118b9e339c4436066881255b604bf994373190acd5423e240e45ef6ab3f066eb.json)
- [s013_vol_audit_run.py](evidence/d5779c8b49e9325165a3181e860a3d84fdd25e856b918ae1fa82ef3608883e51.py)
- [s013_vol_plan.py](evidence/5787c09c9c10e1458dea08ddb1380c526f1c49f2d73a44be347055e58e16b5d5.py)
- [root_review.json](evidence/1bb3a40d1e2db4e53a5a7a16aaf9324060d1114ffa652c2dfec4e1c5f650bd73.json)
- [closeout.py](evidence/e147651f42461600f3083815fedaf3fc85ba07c23e07b6e4cf13ca1c599b7ffe.py)
- [root_review.py](evidence/dbe8e6ee4b217027250d4ca2974c8621b8d4469c1cd705dd7ea0624da120511d.py)
- [continuation_budget.json](evidence/234191c726d97aff62477d345a340310fefc900d6f23f5b79229dc2dd8b7774c.json)
