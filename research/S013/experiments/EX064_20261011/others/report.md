# 固定缺口非线性表达检验

EX064完成固定缺口非线性表达检验：原1635日全池及512日原事前资格机会池、14项对照、6个标签均保留；150项独立核验通过，0新账户。两个预声明组件均没有足够一致的增量证据支持直接交易化，全部局部正面证据、反证、零值与分组重叠、年度及相位失败保留。停止这两条固定路线，不反转方向或挑期限补救。本轮没有获得新的中心硬门达标且抗扰动更强的策略，目标保持未达成。已见开发池的描述性统计不是封存独立验证，费用代理不是完整账户利润。

- negative_gap_repair: 停止本轮预声明的正向买入假说：全池3/5日原始相关均为负；5日控制后相关−0.05445，描述性95%块区间[−0.09950,−0.00640]，六个不重叠相位中五个为负，构成直接反证。保留最强正面证据：原C8880机会池3日高组收益比低组高0.03039个百分点，费用代理均值仍为正，且2023/2025/2026部分相关为正；但机会池控制后区间跨零、年份/相位不稳，新增组件使3/5日年度顺序模型误差增加。全池5日模型误差仅微小下降，原正向收益方向不成立，不能把反向线索直接改成已证实交易规则。
- positive_gap_fade: 停止直接交易化：全池5日控制后相关−0.03096，六个不重叠相位均为负，且单加组件使全池5日模型误差下降约4.60e−7，是保留的局部正面证据；但描述性95%块区间[−0.08132,0.01867]跨零，3日没有稳定改善，机会池5日模型误差反而增加。风险相关的区间也跨零，机会池3/5日风险相关与预期相反。全池84.04%、机会池85.74%观测为零，年度Q75常为零使高低组大量重叠，组均值不能当作独立交易优势。尚不足以支持稳定的回吐过滤或盈利机制。

统计检验不等于完整账户收益，原四门与32参数诊断目标尚未证明改善。

- [plan.json](evidence/cdcaf5e700cc1e1bac5266a2b9da08bdbd6059f88596ab547d389daf9bca1006.json)
- [.tmp/s013-gap-expression/focused_checks.py](evidence/98389acdfefff920651575a866fc25c0b7832fed04d0d3131b3c5885f1f0b3ec.py)
- [.tmp/s013-gap-expression/gap_expression.py](evidence/189f576340f6148b13d5bfae743aba0c7aae6855ac85afca0faf709ee3bb917f.py)
- [.tmp/s013-gap-expression/seal_source.py](evidence/bb706272ef1b18edec186cb0acc72488c2674bf88cf828dec658b4892f8f2d43.py)
- [.tmp/s013-gap-statistics/opportunity_statistics.py](evidence/7d9915eff4a7f6a61ddc7de8444567aab3ca487e606b8c4e7ec153d28d5c5f77.py)
- [.tmp/s013-gap-statistics/statistics_checks.py](evidence/3dadef70e76ac8101c119661ab029e45928fd895070c1211d5694188a3ddb951.py)
- [.tmp/s013-gap-statistics/adapt_source.py](evidence/8c5ddaee2f417dc031809ca8464976f08efd71044d3f3654f18a36fa15d18280.py)
- [.tmp/s013-gap-driver/driver.py](evidence/ae639e85ef4b7d61a92f7bf89fcf156fe1317db64f0cc19095b883d112519aa0.py)
- [.tmp/s013-gap-driver/focused_checks.py](evidence/16b79be21e3a290b8ac6df348b8282e745c54407f51fbb39e5e126f44f3d4aae.py)
- [.tmp/s013-gap-driver/seal_source.py](evidence/2defb6af182199a17c3595df368778d13b877c138ee0ab7f57a0d3d893359e21.py)
- [.tmp/s013-gap-driver/verification.py](evidence/9154fdbd92c6dcd30f860fda80997334d614b30bbfd42662608b6c10b93e6492.py)
- [research/S013/experiments/EX058_20261011/src/common.py](evidence/f38c71d3392fb791fdd064f366cc251e33c064d7b88a0cd8b737f2603ccf236b.py)
- [feature_method](evidence/1fb9ead823a4bd9e8e1bac9e5580ef4924b931e8783a31f4cde77ded5dc35cd9.json)
- [feature_proof](evidence/ca50b286133df72787ecc37cb9cdcc103b5b0e22a3af782bd80eebec3ea5064e.json)
- [statistics_proof](evidence/f2f6a616a10c4f5bda8cdd07e02865dce58cb30dabec9965ea9f060ef797418d.json)
- [driver_proof](evidence/36a3dbe5cedd7cc2d7dc3e93b2d0ad9dcdc487b36a1cd1a3545c36ce5a76afe3.json)
- [actual_predecessor_full_certificate](evidence/9e1462fbc77e9d85fbe9005340dbf5b6a2157df5fbdc12681242580e2750ab3b.json)
- [input_checks.json](evidence/1013fc2a3dd63a23f352605be941149db0508b759db1bc7d9770cb4a9b5c7538.json)
- [features.csv](evidence/7379ac9feb836b5c9a794284683f073ba4ec67dfcc30b8cad39ccf6b5bc00fae.csv)
- [labels.csv](evidence/93f4b58fdfbdeef844922137302d8f457c4cb1deb3d927ea667f4fac7651e40b.csv)
- [opportunity.csv](evidence/090742cf2ffbbc15d382569717debb45898ee5eb877d0310fab48899047133d1.csv)
- [gap_observations.csv](evidence/f7d55dce6cfc9efe2088004edcefcbf513b8c16560b7691da472857a22821c2d.csv)
- [daily_snapshot.csv](evidence/4eee6d1b9a362239c06ca8235a7de9ec7606ce74b9a78dd224a6810737c9adb2.csv)
- [statistics.json](evidence/1f24f113c9d46c1d2ff61f0afdad8dffeb283abf9ee202e1234f99f8a5873a1a.json)
- [compact_results.json](evidence/34ea6360057fe31bb704afbf5fccc7e59d426bb082446b51706f85afc426be47.json)
- [summarize_results.py](evidence/fbd075c1047a7a5ae17d056bea8db9482525526f2ce0166762028e3723e5a8d6.py)
- [config.json](evidence/8cd6f27d8e147e385d31fd2d1da61ef2272f44321861549cb69e6893731d79d9.json)
- [feature_source](evidence/189f576340f6148b13d5bfae743aba0c7aae6855ac85afca0faf709ee3bb917f.py)
- [verification.json](evidence/035fbace4bfe425afe9034a2378322cd18450c99224d6b9daeb84b0e9c145166.json)
- [judgment.json](evidence/cdea74787df87b6e91e5c7ed27e7dcca7af89c90b6449e8c47349c8e98e21b55.json)
