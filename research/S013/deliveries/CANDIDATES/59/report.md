# 隔夜下跌压力买入过滤：固定中心反证

在原C8880自身空仓、熊市原入场资格和原确认均通过时，如果此前4个完整交易日的隔夜下跌幅度总和大于日内下跌幅度总和，就放弃当日买入；保持原退出规则和退出记忆。

固定中心未满足原四门：交易频率未过，其他三门通过。少买确实改善2023年，但整体收益下降、全期回撤变大，因此这条固定表达没有实现研究要求。

|指标|原C8880|过滤后C9072|
|---|---:|---:|
|净年化收益|0.17134559076619493|0.1398506023306998|
|全期最大回撤|0.13618731411686769|0.15041896013474831|
|每60日闭合交易|4.254278728606357|3.924205378973105|
|闭合交易数|116|107|

|自然年|原收益|新收益|原年度回撤|新年度回撤|
|---|---:|---:|---:|---:|
|2020|16.5873%|9.5422%|6.6318%|6.1278%|
|2021|8.2925%|8.8264%|3.5940%|2.9430%|
|2022|19.5931%|12.9823%|6.8793%|8.2177%|
|2023|0.9181%|1.9863%|5.0771%|4.5503%|
|2024|65.0176%|58.3427%|10.0222%|13.1893%|
|2025|11.0762%|7.5860%|3.5334%|3.3999%|
|2026|-0.0388%|-0.0371%|4.5430%|4.5417%|

原116笔闭合交易减少到107笔，低于频率硬门；实际108笔买入、107笔卖出，107个闭合周期和1个仍持有周期。自身新路径31次拒绝，不能将其当作静态15个旧机会或31笔减少的实际交易。

已按事前规则停止，没有执行32点、双倍费用、3/5邻域、参数优化或候选登记。完整五项自检因此没有执行，不能把缺失结果写成通过或零值。

禁用过滤的1636个历史信号每个原字段与原源及旧原生结果精确相同；启用后的压力公式、策略自身状态与退出记忆、完整现金账本和原生身份已独立核验，订单成交通过因果日期、手数、费用、开盘价/日内首触核验。

原公开verification的raw_counts.closed_trades字段误标为108，实际它是含1个OPEN周期的交易行总数；经济闭合数始终正确107。原证据保留，本报告显式更正字段标签。一次只读订单审计pandas.dt列访问技术失败及对应旧源、新源和具体traceback已公开，未复跑财务账户。

这些都是已见开发池结果，不是新封存验证；删除买入会改变后续状态和资金路径，因此不能仅凭被拒绝机会的事后收益解释机制效果。总体稳健目标尚未实现，科学评审由root完成。

根科学评审：EX072固定入场过滤失败。2023净收益由0.9181%提高到1.9863%，但整体净年化由17.1346%降至13.9851%，全期回撤由13.6187%升至15.0419%，闭合交易116降至107、低于110硬门。保留该年局部改善和其他三门通过事实；不把全期回撤变差误称年度回撤硬门失败。停止32点、双费用、整数邻域及参数救援，不登记C9072，保留Candidate58。不能据此泛化此标记为有效入场风险信息；标准扰动与五项新自检未运行，不当成通过或零。整体稳健目标尚未达成。

|自然年|相同买入持有基准净收益|基准年度回撤|
|---|---:|---:|
|2020|22.1693%|14.9712%|
|2021|17.2351%|9.7035%|
|2022|-18.3203%|28.4105%|
|2023|-6.2450%|17.2665%|
|2024|6.9559%|18.5736%|
|2025|32.7098%|13.7975%|
|2026|0.9947%|18.7646%|

原B0最新五自检仅引用EX070已验证的旧33标准+1双费用历史上下文；本EX072未运行32或双费用，没有完整新五自检，缺失不当通过或零。

动态每次入场风险预算目前只有source-only需求和接口可行性反证，未证明能改善；本轮没有DEV实施或替代执行器。

- [证据 overnight-filter-closeout-b9baf657c5d7364d7a1f485c6916b164](evidence/b9baf657c5d7364d7a1f485c6916b1640c0677f303cb99c68ba007f3131243fb.json)
- [证据 overnight-filter-closeout-41993342f93e86c3fb82ccc5be494aa4](evidence/41993342f93e86c3fb82ccc5be494aa4f629d46eb36892c24d5d5ab7a5bc9253.json)
- [证据 overnight-filter-baseline-readonly-order-firsttouch](evidence/e3538e7ce55af4cb023d533f55740243594717174b3d7f410e29765f63572dc9.json)
- [证据 overnight-filter-full-centre-native](evidence/29a7e880e99e08b3c9363211f3d4a6fae8f520cc73af5a335a48aee160b1c958.json)
- [证据 overnight-filter-closeout-9e4d1f7702719ee2db894c2b5092468e](evidence/9e4d1f7702719ee2db894c2b5092468ea58f507c0b967b0b8f3844db9e66d1c8.md)
- [证据 overnight-filter-closeout-link-technical-amendment](evidence/f4aa31646e67953439b5f4c71d933d8504390f7cdb775a6e030365c7bedab24d.json)
- [证据 overnight-filter-negative-closeout-freeze](evidence/80b8140f6faff9b7642c3f831179cc34a0a4933c4767652f74ae23900ea9e35a.json)
- [证据 overnight-filter-order-fill-independent-audit-source](evidence/bf4ac5ec4ecfdb78c4e31533dae0a3adbc80cfe83aa6101b9672557c30b49dc4.py)
- [证据 overnight-filter-closeout-88f80f786a55a30f9cf83c3698181fa8](evidence/88f80f786a55a30f9cf83c3698181fa8f40e9c747e133a63f9154cb56ff0902d.json)
- [证据 overnight-filter-closeout-b7aa3220794b93000cffbde4410c97b9](evidence/b7aa3220794b93000cffbde4410c97b95f3cc798f7348244b4113cbf7d5da198.py)
- [证据 statistics](evidence/064197fc69cc4571fdbe66b82db4e3ea001d832b35131698bd1a1a578517a149.json)
- [证据 verification](evidence/9d007a8bcfea18d85255180b06a60cb88e41d4b80367a54d869600ce5ca25f81.json)
- [证据 statistics](evidence/04f600fc246836bebd2d53c586eea704b0d4a44607d1d2dd4549d1f32942153b.json)
- [证据 verification](evidence/c79a52e2d156347676da78f7bdd69e87f53391c7b1470f8c8520cc26b8671f5c.json)
- [证据 raw-boundary-body-local-bear-recovery-native-center-n0](evidence/2ba4906b271e148a956755df9ba9907457ef0bee726b7a24a13602df4e73fa3e.json)
- [证据 daily-prices](evidence/71319e1c9ea6543849f809a0996bd6978636d76848cbb3c8aaf962f302c27263.csv)
- [证据 overnight-filter-closeout-d430f6f7b2d96dc124b5b85b6f016ade](evidence/d430f6f7b2d96dc124b5b85b6f016ade210bb88a40221de19d11ad8cbfa56cdf.json)
- [证据 overnight-filter-closeout-d3b3a385be91ab5bbf34ccb88e3d0b6b](evidence/d3b3a385be91ab5bbf34ccb88e3d0b6b845ffe8f1174eb8df8923995ad9e0ccd.py)
- [证据 overnight-filter-closeout-ed4ea4c901ec84374d88355db113323f](evidence/ed4ea4c901ec84374d88355db113323f47a798a4e3d52133424c296ad32e0a2a.json)
- [证据 overnight-filter-closeout-560689afbd21a388bbe8337730125a4b](evidence/560689afbd21a388bbe8337730125a4bf805ca20e88e0b377d2402aa39cdb4b6.py)
- [证据 overnight-filter-closeout-5ff553ecaee637b2acb9c3e26cdd308f](evidence/5ff553ecaee637b2acb9c3e26cdd308f4d55a8f2485afbf4f530765fd0541de8.py)
- [证据 overnight-filter-closeout-a78d19f9ae5c56393bbc81f28ea033f3](evidence/a78d19f9ae5c56393bbc81f28ea033f3c889f40efe5f9cd4c49af09e1df5c0b5.py)
- [证据 overnight-filter-closeout-caf12faeededd7f511528545b03fbe40](evidence/caf12faeededd7f511528545b03fbe40fffdd38fa1796b11af6aa47f12d0b877.py)
- [证据 overnight-filter-closeout-03a5d3316a212bafbe2c0f892b3dd467](evidence/03a5d3316a212bafbe2c0f892b3dd467cc786bd1adbe0b084ef471211cb32cba.py)
- [证据 overnight-filter-closeout-97eb806bd0b0c6e02a1e29255b11b2e5](evidence/97eb806bd0b0c6e02a1e29255b11b2e5a214ce298391312c2a05d03185a8a894.py)
- [证据 overnight-filter-closeout-eb26a16d5c7d6f2b655ca12537d73de2](evidence/eb26a16d5c7d6f2b655ca12537d73de28888fe05d016bce8a0b71b34c96eb73a.py)
- [证据 overnight-filter-closeout-f3a8a9e8a69cb61b326c1702bf8b471f](evidence/f3a8a9e8a69cb61b326c1702bf8b471fa49105fd91cc58ec9d09dc27492669e4.py)
- [证据 overnight-filter-closeout-3fc44c4bfe601b26a43cee533303d41e](evidence/3fc44c4bfe601b26a43cee533303d41e54db365f98c526ccfcf004a9b8afdce8.py)
- [证据 overnight-filter-closeout-b1e6b77bd0983791550106c7e468f396](evidence/b1e6b77bd0983791550106c7e468f396371381f58f828cdcaf2c47ce1abf8a4a.py)
- [证据 overnight-filter-closeout-5706ae09daec573a2c2fbf8f7dc75f68](evidence/5706ae09daec573a2c2fbf8f7dc75f682a86a5bcee1489346ba641f0a3b8ae1b.py)
- [证据 overnight-filter-closeout-899522b56a578190c1f254e21c2babc1](evidence/899522b56a578190c1f254e21c2babc1fdce6ece58cc3f947cd5e76065d78dd3.py)
- [证据 overnight-filter-closeout-6dfa9c7d37d8eef604a0dfccb82ebc37](evidence/6dfa9c7d37d8eef604a0dfccb82ebc37ff4e87b44fff04686a27ad8bb7da518c.py)
- [证据 overnight-filter-closeout-4f2a781378f173bbfdf43029a57d62a6](evidence/4f2a781378f173bbfdf43029a57d62a6b009893d2d7c84615d9638956819fbb1.py)
- [证据 preaccount-design-feasibility-plan-json](evidence/668ffb05cccc0abc79586aa7ce5ee08d99bf108241375718a3025fe19f80cfd9.json)
- [证据 preaccount-design-filter-checks-json](evidence/c1b81b6fb4fb7ffb5397e1ff548678205fd85f4ad789ff4745b68218e1ddd641.json)
- [证据 preaccount-design-filter-checks-py](evidence/47909106992625498a3b882f15e66029153ad24c16cb46fda08f056044123a29.py)
- [证据 preaccount-design-trigger-audit-json](evidence/8f15e8c911a38d81e6cdc235281eafb9749f74d9db5ac0f231b23798d90480a7.json)
- [证据 preaccount-design-focused-checks-json](evidence/54862302223a32492c8e9cc0430179a86689344eebde97ae8ee1f0ce1a17d905.json)
- [证据 overnight-filter-prospective-integer-coverage-budget36](evidence/4a004900c0420ae2df4da3606e93b1c8e0ee795a22c08b382376ba156bf5ed83.json)
- [证据 overnight-filter-closeout-1907b2da6293736b27b05d653dda5c36](evidence/1907b2da6293736b27b05d653dda5c361e9768d42ce7d995c2147c8fc3f21e01.csv)
- [证据 overnight-filter-closeout-bb6ca6e84065765771aa9c56595f0b2f](evidence/bb6ca6e84065765771aa9c56595f0b2f978ad71d3f4d738d6283d46357f547c9.csv)
- [证据 overnight-filter-closeout-07b2aeac8e9cbb98172b04c3f7a297b4](evidence/07b2aeac8e9cbb98172b04c3f7a297b40fb7b264ddf6e70865b714adcd2a6487.csv)
- [证据 overnight-filter-closeout-3692d41d57eb5c1bc3f2b1e2ccbe6fb6](evidence/3692d41d57eb5c1bc3f2b1e2ccbe6fb67cfc853c39516da59debc5d4ecf0434a.csv)
- [证据 overnight-filter-closeout-415b995912046c2f4f3e1c460df50e72](evidence/415b995912046c2f4f3e1c460df50e72cc3425996e3114946c7988b64600c527.csv)
- [证据 overnight-filter-closeout-b0abe4096a25ad3c595b17af0dce4020](evidence/b0abe4096a25ad3c595b17af0dce4020c3d8d60cc3817cca50ba2e86d466e410.json)
- [证据 short-alternative-full-centre-native](evidence/d625ceca27e318bc2993df929e7277084b74b772683033d96c633fe2a26c0201.json)
- [证据 short-alt-baseline-authenticated-latest-fivechecks](evidence/9d1e522b6404c4f9ed5ec74bd2178548ec7e2eb7749ffb8dbd84888fb3221d77.json)
- [证据 overnight-filter-closeout-ce83e5e78cee1634879e82e4c1c58b8a](evidence/ce83e5e78cee1634879e82e4c1c58b8ac2cf6822f4359d0d568eaf0fcadfb091.py)
- [证据 overnight-filter-closeout-975a2c7e6b3e88d41beb99df4e2cb1b5](evidence/975a2c7e6b3e88d41beb99df4e2cb1b57ae80d82f3df28421de18b9c4eed54a5.json)
- [证据 overnight-filter-closeout-f299959ec9e2e9f0eb3c8972e020da46](evidence/f299959ec9e2e9f0eb3c8972e020da46d29809af91d67715e8a23c7b4117bc1c.json)
- [证据 overnight-filter-closeout-208f5cf0d875c1be50dee23e0f96b9b2](evidence/208f5cf0d875c1be50dee23e0f96b9b21500cd29737009c2421c658c8478da15.json)
- [证据 overnight-filter-closeout-effc8bbaf06fcea3bdaa5c3c1dfc2c78](evidence/effc8bbaf06fcea3bdaa5c3c1dfc2c788e867322a8ad70e632bcc3ba91f76893.json)
- [证据 overnight-filter-closeout-edfeb7d258218ce38721b04fb3c4b863](evidence/edfeb7d258218ce38721b04fb3c4b8633cf0ce0dc6771cd3cb88d4bded779b76.json)
- [证据 overnight-filter-closeout-68dbba21046bd1c58d8e5468c5e5e16c](evidence/68dbba21046bd1c58d8e5468c5e5e16ceb5867d5f323f81bb34e9693a7af39ee.json)
- [证据 overnight-filter-closeout-d526dc49db991c9de30e8914e146d121](evidence/d526dc49db991c9de30e8914e146d121d15f963539fff54bf5521d71aa818489.json)
- [证据 overnight-filter-closeout-03ac6cf09ff0f63f14f29f09092cd3b6](evidence/03ac6cf09ff0f63f14f29f09092cd3b63e1299f959e17f1f142e7dfb8f67d669.json)
- [证据 overnight-filter-closeout-0c871767badb603b9b9a2fc52270b74a](evidence/0c871767badb603b9b9a2fc52270b74a97210ed446a5c5101a4ab85e0a0d0377.json)
- [证据 overnight-filter-closeout-d7a1e566764824a1b1b949b49e6c5618](evidence/d7a1e566764824a1b1b949b49e6c561822ff2c42e5c0f793dae32b9f66e366d6.json)
- [证据 overnight-filter-closeout-58dfde8c16314f5b70b5beabca764f6e](evidence/58dfde8c16314f5b70b5beabca764f6e2b207ad7fe68fef8be3d153769d867ad.json)
- [证据 overnight-filter-closeout-78f09a9baa18decbb5b636713d1f0827](evidence/78f09a9baa18decbb5b636713d1f0827804f6cf6694d8d852ed4b928524c822a.json)
- [证据 overnight-filter-closeout-ce0a7476f315399d0a5be66501b24a33](evidence/ce0a7476f315399d0a5be66501b24a33c4fb329a0497ac908af4bbf51460f587.json)
- [证据 overnight-filter-closeout-ff19cdd7a30949246edcf374035e2e5e](evidence/ff19cdd7a30949246edcf374035e2e5e0ffafe976692831e9f41cabf1686a8d3.json)
- [证据 overnight-filter-closeout-1f4f243c9b58da2803d25b8f6a2d3a39](evidence/1f4f243c9b58da2803d25b8f6a2d3a39a74bd6219d1590ab28dbc13af3634736.json)
- [证据 overnight-filter-closeout-d3163cffe5be82fa990ce124e5b98d81](evidence/d3163cffe5be82fa990ce124e5b98d81c544f4f4530eb4cf2e2d9dcd67b398a3.json)