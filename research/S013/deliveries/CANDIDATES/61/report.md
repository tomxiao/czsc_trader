# EX077：统一价格周期政策的单中心检验

固定政策在下跌年份可以盈利，但没有同时解决整体收益和交易频率。它不是新的达标候选，研究目标尚未达成。

规则为：价格从已知高点回落后等待恢复再买入，持有后按回撤退出；整个周期使用触发时锁定的波动幅度。只检验预先固定的L20/k1，未优化参数。

| 原硬门 | 本次结果 | 判断 |
|---|---:|---|
| 整体净年化至少买入持有的1.5倍 | 7.8887%，要求10.8290% | 未达标 |
| 每自然年回撤严格小于买入持有 | 七个年份均满足 | 达标 |
| 平均每60交易日至少4笔闭合交易 | 2.8606笔；全区间78笔，至少需要110笔 | 未达标 |
| 买入持有亏损年份策略严格盈利 | 2022 +1.9082%；2023 +1.2940% | 达标 |

全区间最大回撤18.6261%。2026年截至9月30日策略收益−13.2460%，同期买入持有+0.9947%；这说明下跌年份盈利和年度回撤过门，仍可能伴随其他年份较大的收益损失。

原C8880账本经身份核验后复用：净年化17.1346%、全区间回撤13.6187%、116笔闭合交易。新政策的2023年收益比原中心+0.9181%略高，但整体收益、全区间回撤和交易频率都更差，不能据此称为改进。

本次证据支持“减少规则也能保留下跌年份盈利”的有限观察，不支持“规则简单就会更稳健”。固定中心已失败，按事前停止规则不扫L/k、不增加过滤或持有上限，也不运行32扰动及双费账户。新政策的收益Q10、回撤Q90和完整五项自检均未取得，不能与旧13维扰动逐点配对。仅报告中心正收益交易前10%利润占比54.2313%，不把它当作新增硬门。

只新增一个完整账户；旧基准比较不重算账户。政策状态、原生意图、逐笔订单/成交、费用、现金、持仓、连续年度边界及四门已独立核验。额外数学核验覆盖1636信号日、12字段、6099数值比较，状态和目标精确一致。

准备阶段因新的日历请求身份无法命中旧资产而失败，禁止访问设置拦住了一次provider尝试，没有取新数据或运行账户。技术修订恢复C8880原日历及180日预热的精确请求，保留最低121观察及完整L2..120域；额外预热不初始化状态，政策字节和参数不变。初始C9077保留，新适配实现使用C9078身份，同一EX077没有再次分配。后复权、资金、费用、1%买入合同和执行日期均保持原口径。

同一开发池已经反复使用，存在选择偏差；未使用封存样本。SRT运输时间及Timestamp证据按日期序列化的限制单独披露，不能把运输字段当作T17数学时钟。原OHLC异常保持原样，成交按原生盘中首次触价核验。本实验不能证明所有价格机制无效或原目标不可能。

下一步应围绕“哪些因果可知条件能带来足够的扣费盈利机会”研究独立组件，分别报告机会数量与每笔收益余量；不能用强行提高交易次数或继续修补失败的固定政策代替证据。当前保留原合格候选资格，不冻结、不投入PTE。


- [plan.json](evidence/25ac380500e0967d21de79a654d59124cabccfce0a62b17b08ae71a9f1540e8e.json)
- [native.json](evidence/3ef6e001ebf6036be97daf8bb961ef0da2acae3fd38d4df49fbe9712109ef41a.json)
- [independent_audit.json](evidence/7b4ee82aad1c5d27c9c10ccf2113cbbeb92492390289495fca0ef41ea91e3ea3.json)
- [mathematical_audit.json](evidence/d1d5826fc6fccac9ed82b66f33822b2ec302a3e0bb5301558a877b50f75baeeb.json)
- [baseline_native.json](evidence/2ba4906b271e148a956755df9ba9907457ef0bee726b7a24a13602df4e73fa3e.json)
- [root_review.json](evidence/97fb112fcf8faaa7946d51462f135fa41a2140cdf2d81b164adaf81a984f51e4.json)
- [original_plan](evidence/41aa5b6aa3ec796b0b285d01bf91bfbc9dd173e97e52158a6de2e0c2c7fd9ff2.json)
- [original_baseline_native](evidence/2ba4906b271e148a956755df9ba9907457ef0bee726b7a24a13602df4e73fa3e.json)
- [original_centre_audit.py](evidence/2fb89f8017d85eb1ac47d79c5579762f0be74970e386e187e467866d545b1822.py)
- [original_centre_driver.py](evidence/4df75cd72be214119c53d5e2b350ffd146683d51efd24bb19b82f2733880168e.py)
- [original_strategy_runtime/strategies/policy.py](evidence/1fba931ae8c0a8322594d8fa684c7dc092a70796eb43659df0262b2be92b5a6b.py)
- [original_strategy_runtime/strategies/price_event.py](evidence/d604b1d16c476c7c247ec0354cc1e7cbc4da68d4d4037bc98b08b2e993baa160.py)
- [original_centre_source_freeze.json](evidence/12fc8e22e6713c17ff6c87f02b0812066c86ffbf8924c40f1df6437db2132f54.json)
- [original_centre_source_proof.json](evidence/eac6321f148852959ea90d4f3d08be26274ce84c974d33ff3092ae2a15b26c1d.json)
- [original_root_declare_authority.json](evidence/48246c69b0f1a89dc6dd11fbe0a909dd2ac24b0d87fc6b48f694d988b54de813.json)
- [original_source_freeze.json](evidence/81eb75aebe8ba786ad02974364ad94da0a195ec87028ba0a090b0a95c51120a6.json)
- [original_prospective_plan.json](evidence/556e1750f0ff1d114fae0570369c6e6dcca64e3b0d3662632ad46617790e8722.json)
- [original_root_route_decision.json](evidence/c61ff03e6f258ee22667f681041190f30caef4522ae89eafa5eb47cdd12f0798.json)
- [original_independent_policy_freeze.json](evidence/3055c8478a873a798094719daf55db18eff7c79ee0ba47d4dd5045cc1d360016.json)
- [original_independent_policy_audit.py](evidence/c344a48f8d2e4986679fec22875e60e09cfbb8c56a07db99e734e89000eca631.py)
- [original_independent_policy_proof.json](evidence/d668126609b3516762dbafaf4bc0972b36bd0a7342774bf6d7566a9e1e2af5d4.json)
- [original_centre_source_checks.py](evidence/9fcbc801b15f8dfa35602a2fe3a57ce663f7f9970a5112ebad82e792bc919f07.py)
- [original_common.py](evidence/f38c71d3392fb791fdd064f366cc251e33c064d7b88a0cd8b737f2603ccf236b.py)
- [original_economics_reference.py](evidence/caf12faeededd7f511528545b03fbe40fffdd38fa1796b11af6aa47f12d0b877.py)
- [original_account_reference.py](evidence/560689afbd21a388bbe8337730125a4bf805ca20e88e0b377d2402aa39cdb4b6.py)
- [original_execution_links.py](evidence/b7aa3220794b93000cffbde4410c97b95f3cc798f7348244b4113cbf7d5da198.py)
- [technical_plan](evidence/25ac380500e0967d21de79a654d59124cabccfce0a62b17b08ae71a9f1540e8e.json)
- [technical_original_plan](evidence/41aa5b6aa3ec796b0b285d01bf91bfbc9dd173e97e52158a6de2e0c2c7fd9ff2.json)
- [technical_baseline_native](evidence/2ba4906b271e148a956755df9ba9907457ef0bee726b7a24a13602df4e73fa3e.json)
- [technical_adapter.py](evidence/ba2bb7d5cecd07b3605e4338482d17812f109024f6a6b0cb94b419fed7cef4d5.py)
- [technical_proof.json](evidence/d11103f21f79d81595102bdcfeea6103d59aee2cb89d4e6b25830b185945588f.json)
- [technical_centre_source_freeze.json](evidence/c30e487fdee12a44ffa1237cfe896f18ebf4b036f0f97dc1ea1bea28f0748114.json)
- [technical_technical_driver.py](evidence/29e1f747acb6c76336e7ab650de6154189717cb80658f019bcb05cb93ced87d7.py)
- [technical_prepare_failure.json](evidence/1b0a9ffa7c59918cc53190671a41f16e23a8d7bef8811a9a3f57d34bd3305645.json)
- [technical_reuse_r2_checks.py](evidence/44534e82449f2d63cb8fb787c56cf19fadde1ef056ffacd4f6fa9f645f772bcb.py)
- [technical_reuse_r2_freeze.json](evidence/145bc16ac1a1712995e9899b5e93ac4d120afd5ff09d8c0af00aa6faa95be0ba.json)
- [technical_root_declare_authority.json](evidence/7c1c5d375b95f8d309d7fd84f4da5023659bfedc654e86e4660af8184dbc5305.json)
- [technical_centre_audit.py](evidence/2fb89f8017d85eb1ac47d79c5579762f0be74970e386e187e467866d545b1822.py)
- [technical_strategy_runtime/strategies/policy.py](evidence/1fba931ae8c0a8322594d8fa684c7dc092a70796eb43659df0262b2be92b5a6b.py)
- [technical_strategy_runtime/strategies/price_event.py](evidence/ba2bb7d5cecd07b3605e4338482d17812f109024f6a6b0cb94b419fed7cef4d5.py)
- [math_verification](evidence/d1d5826fc6fccac9ed82b66f33822b2ec302a3e0bb5301558a877b50f75baeeb.json)
- [math_source](evidence/66e328c237f4bc0bf179d949b4650c289fde525d115fca5047b3a7d567248d9e.py)
- [prepare.json](evidence/ebc8e376270461202a8fc1b277eb8ac7d0570ae5f2835902887783688d8b206a.json)
- [closeout_postprocess.py](evidence/ed474e6ffd6c4da50821e78f6c60e6ddefd57af5b2161e53749274416797648f.py)
- [closeout_checks.py](evidence/8beb5c66685ecc838837b8aa0b7aff2835528ec0411981e3cbc4868f66c773b7.py)
- [closeout_checks.json](evidence/33824024054d21ada262e9bb7128092392aa92824fc953d7b5ae82a418df6af3.json)
- [closeout_freeze.json](evidence/cda1ce564d1d54d73853f885a03f342665f81abba0461648c3f755bc67267f8d.json)
- [closeout_root_authority.json](evidence/679cb8e3e9884860801536b852a551d2752d285f40c5fd463919164a9a5743dd.json)
