# EX076：相同四日涨跌幅下，价格变化顺序能否帮助识别盈利机会

固定四日曲率衡量最近两日相对前两日是否加速上涨或减速下跌。固定正向收益先验，保留17项控制（含四日总涨跌幅），分别检验全开发池和原策略此前空仓的买入资格池；后续四个完整交易日扣费收益为主要目标，OPEN/CLOSE风险只作诊断。

|范围|完整控制样本|收益部分相关及95%区间|下一年预测数|误差相对原17指标|误差相对过去均值|
|---|---:|---|---:|---:|---:|
|全池|1612|+0.0237，[-0.0082,+0.0576]|1388|减少0.0418%|增加2.7204%|
|原policy-flat买入资格池|145|+0.0020，[-0.1522,+0.1800]|80|增加0.0329%|增加0.7172%|

两个置信区间都包含零，不能确认正向增量，也不能据此认定反向有效。全池略胜原指标，但没有胜过更简单的过去平均值；空仓买入资格池反而略差。固定科学判读两池均NO_INCREMENT。本次没有把统计判读新增为经济硬门。

有利反例完整保留：全池2024年预测同时胜过两个基线；空仓资格池2022年部分相关为+0.2393，相位4为+0.8218。但后者相位只有30个完整样本、12个残差自由度，不选它替代总体。空仓资格池可外推年份仅2022/2023/2024（32/24/24条），2021训练不足、2025/2026测试不足，原始不足状态与空值保留。2023单年部分相关亦因残差自由度不足而不可用，不能填成零。

风险诊断同样没有胜过过去均值：全池误差增加2.3144%，空仓资格池增加0.2755%。没有事前风险交易用途，因此不能把它改称有效退出或减仓机制。

原1635日信号轴保持，原147次空仓买入资格中146次标签已成熟、145次控制齐全。完整1636决策前缀为2019-12-31至2026-09-29，先取前日target再重排到信号日；原执行1636日为2020-01-02至2026-09-30。首次技术认证因把这两条日期轴当成相同而失败，失败完整保留；仅修正日期轴校验，原数学、价格、标签、控制、范围及参数未改变，只有一次真实统计。

独立核验检查4000条重抽样状态、59030项数值和8808条预测，最大预测差异3.32e-16，PASS。根会话另逐日核验1635条曲率、价格标签和成熟日及完整原资格前缀。新增行情请求0、账户0，原四门、只做多、费用、1%执行合同与后复权口径保持。

下一步只考虑已事前冻结的独立完整政策反证：将价格回落、反转买入和回吐退出统一为一个周期。它用于检验简化状态耦合，不声称新增预测优势；先且仅检验一个固定中心，原四门任一失败则停止该路线，无邻域或参数救援。抗扰动策略目标尚未达成。

局限：这是反复使用的开发池，区间未校正多轮研究选择；固定年度外推仍不是独立封存检验。四日标签是理想OPEN及单边0.1%费用代理，不能证明1%限价真实成交、账户收益、回撤或五项自检达标。空仓是原策略target政策状态，并非实际成交持仓。风险只观察O/C；PBO/DSR不可用。两个池各自同样本比较，不能把EX075的18控制结果当成逐点配对比较。


正式证据：

- [component.py](evidence/d46e2958b65e3d127749088eb30601a74b50f430e615a936e9ee16658398b362.py)
- [labels.py](evidence/d44dba8b50de07d2bfa054845e8335a93f0395062199010925623606de96967d.py)
- [curvature_statistics.py](evidence/617d9aa588e1fc5606ef588b841dff957ad57fe0a23d8e1f60b5efe371e9a42d.py)
- [build_source.py](evidence/f54f119f79358f6a1e4aacd901596b9a0fea93e52526503f6bafee4fb50e8606.py)
- [pure_checks.py](evidence/fab695375f32ddcd3544406e98c9519bd9d13f3e00820c0e67d6cccde756192b.py)
- [prospective_plan.json](evidence/e3e0bd389ccb90e4be952b134ff4b7f0068efd667dd29fe04b65a288e20b33bd.json)
- [pureproof.json](evidence/8f27107632820ce5c3b451e698773f71acabb25d7bbaf9e0a55446226f610bf2.json)
- [freeze.json](evidence/aa43e2b3afbc70908941e8ef30a54975c9efcac43a83fc8f4403de7f027ab1b8.json)
- [input_authentication.py](evidence/b64dd5d0fe8efb644b09e4cb1b65241fa33943574dc676a9a29598b9abf7b37c.py)
- [reading.py](evidence/988525c8ca8e350cbfc90cc4651f41200adfb3b4aa76fbea17a6059b09165037.py)
- [driver.py](evidence/b06256637a54da35d30207be0290f3ff5143b40699d7da6e2f9e44876c4c546b.py)
- [execution_checks.py](evidence/01b15d2724e271fe5f290347ed276ba76001f1e5e777e24b21c8f14e711cf76b.py)
- [execution_pureproof.json](evidence/cb0b542aa2212a03c7a3a16757bf72fa3b673b5919851da0def94a1a0efa17a8.json)
- [execution_binding_plan.json](evidence/493184afc3a01c9999e4faab5302ccff29ba77cfbf081a8323a1dd6fd7233349.json)
- [input_references.json](evidence/a3a5b383141b0aece5724b4203a4119578f8322d41a82db827f691487023b450.json)
- [execution_freeze.json](evidence/5d78a36fe638e55f3ecae0e794d28b4fefef159ac2e76b43dfc26632b33410d7.json)
- [method_draft.json](evidence/45380393db802085b45cd1a61aaf39d147a1434b9136830c724434cd1921605d.json)
- [plan.json](evidence/570ab22bb01e945db96e9facf7dff52b8061500245df74e7a76084295d249a05.json)
- [allocation_attempt.json](evidence/718e63f750ae080af84b9bca7686246380f0f3b526a51b2e17cac87a8c53c531.json)
- [independent_independent_curvature_verification.py](evidence/b1cfcab35c0096c810c97f8880252bf998d64a6bac8fe8ffece29c55b757f18c.py)
- [independent_focused_proof.py](evidence/02b55bafa926d3aab0abf17045b7358fc95970cd9cfc737f76a07bc11c7a6147.py)
- [independent_focused_proof.json](evidence/9f25c51f9f7af041f4eb5e041fc3e29ead0dd8ba354851eb480bf4bbe8be9446.json)
- [independent_freeze.json](evidence/5cc196f03485938de2d75f362c4304a3de43e57b3ace6ffd8431e2f948a2ae08.json)
- [root_declaration.py](evidence/a8a53fa8d780d6a1d79550a7589f4e53f2abe34ece8843aff5321bbf778eae05.py)
- [input_authentication_v2.py](evidence/c684d04017edce85947408367ee009c5e67aeca9addd2a9c502b085596328df2.py)
- [driver_v2.py](evidence/6498c8b8a436a96126b48eb1107918e550b167f07f4a4f3bdb0ad5ccb135b74b.py)
- [execution_checks_v2.py](evidence/e18d26b8f80a5dcb55a3103d8fc548747d9e6db7656960a388afb94ce504a007.py)
- [prepare_v2.py](evidence/b90eaf268562597a6cf866d6fbfbccd36ff657de6540ebd2e910b694f08287ba.py)
- [seal_v2.py](evidence/e9cf401015030acaaf65f6f5d5efd28f2fe614a8e651695a78b96e5435e804b6.py)
- [execution_pureproof_v2.json](evidence/47556502a11cc42297fe25a380fda8fc726e83e65400247be1465cce3658f6f5.json)
- [technical_correction_v2.json](evidence/6ba5a57235e3c110c3389b26f90cb7ecda3a672038954c18f093d1ef6bc5fd9e.json)
- [execution_freeze_v2.json](evidence/5123faa7d0473d56a59243e871276595d480779abab4d61563cff6039c466332.json)
- [technical_method_draft_v2.json](evidence/f92208ac03a463d53b5a8961290377aa9a0c9b77ed2c2e178729a90b8d7d10e2.json)
- [technical_method_v2.json](evidence/001cbce9a58c5c8eacaa5761d2e9be81adc5fa895b90b6142e6a02346434fc1b.json)
- [technical_declaration_attempt_v2.json](evidence/fe957a4df36ee67715f307ddbc5deb1c5768c9379447a5731d4a4e7a0d49fb88.json)
- [declaration_check.json](evidence/5a8152f92cf9ec3623ede84b914c3515e1bf2a800dbcf0a5716004799615591b.json)
- [original_authentication_attempt.json](evidence/021c79b20aa0aee7bee5b1dcea26a92f1b81c6cb1d95195c4032ca97558f1f6a.json)
- [original_authentication_failure.json](evidence/b95f76537ccb9135ed1cb791810ae5b4f623c545ae1c8c210c417a48998303f2.json)
- [root_technical_declaration.py](evidence/9d9026b5407f67130c0ab02d145fccbfa088cd59507910731669d57042c10e9a.py)
- [root_declaration_check.py](evidence/19026df1e33cc8ab239261d212ff5dc7cbb41427ead02530d2d30edab2ce7def.py)
- [authentication_attempt.json](evidence/a9df3021efccb76792349273de00fdc3166fc41700172f71cf2af5df0829bfbf.json)
- [authentication.json](evidence/d7dfdd39b66345575891f34099cb0bc3b8daa0701dc1f310c9ba83589ad25562.json)
- [features.csv](evidence/ab15763623665bb676b62d316951a6ccb644f822943779b396c98ed3812a3d38.csv)
- [labels.csv](evidence/37ae5239c6435f9a0c88e634fd48df9c01e91dc7ff4326c4a2dfd4b3794f893e.csv)
- [flat_eligible.csv](evidence/a6fddc36f3668fbf4eac1ff27a41fb211e7fe97ebfb77ec60ce07bc91d3c5a50.csv)
- [price_calendar.csv](evidence/09467f5148d6af5eb3db9c56bd257302ac08b20086150113765fdbd205377757.csv)
- [study_attempt.json](evidence/e7df2020fc073027c4fba20cba899a969a2a0aae3d2922be197ec62b42a9ed2d.json)
- [statistics.json](evidence/452de1e63d40d283d062ed43b13a4fa80991ef605cde2f3a99d784149113358c.json)
- [reading.json](evidence/32989090867a968ea4f4351ff9b4867e3fed9c07352f54d0585a6902cd4d80c8.json)
- [study_completed.json](evidence/ab377ed160832934413cc68f4a3c7345fc5012ff164458d5e9337fe38389afe3.json)
- [verification.json](evidence/5cda6e08e3d36080d0ad8ca4bb5ef371dfc71221628cf9fbcdfeaa07c34ea823.json)
- [verification_attempt.json](evidence/2420e1f9aeb63e1ededaca40247cde274dd80796ab902a7a4e77aedff72e8787.json)
- [root_audit_authorization.json](evidence/51a321145b7946309fb574e1201c8d3ce5754562516afaba50f8f2844ce95519.json)
- [root_audit.py](evidence/31acd30af205ce82970b6ac93f46ac08b2b920a538b911dd0d7b610d494566b7.py)
- [root_review.json](evidence/b147a3e5d114f9e72b34ee803c7954bf8a45f01208bd00d386fbf5a20afa860c.json)
- [root_review.py](evidence/366b750f904a44b4c9ad7d90016cfdd3cdb77a979b8fcb28e766fb45e1ff47a6.py)
- [root_prestudy_check.json](evidence/c44215b9d61f1a3b80deae43c35e02e71cf2e0c52f9b2cd5f76d7bbfcb337a90.json)
- [root_prestudy_check.py](evidence/46cb76c687a3019bd0ab83c323ffffacf9420d401b00dc27d5c8770364960228.py)
- [root_publisher.py](evidence/4f7915e795c35c631b12cd3b29a01473c39591de3302888c23ac50edba7ffea6.py)
- [root_audit_authorizer.py](evidence/95e5f5f60e7709a3134dc3c6ff48c5ffafe5bb1de2c9cbd369fd08a278170b16.py)
- [closeout_postprocess.py](evidence/19825cfd00a7c60a30e216a0199f909291be6c437d5c9f5369f7fad23fed74dd.py)
- [closeout_checks.py](evidence/4624bcc8aed1ec26311f1a995a064b4c8dd5826bd6d547ad733b3735733aeb9f.py)
- [closeout_checks.json](evidence/33b3097c84ec3c6bf2cc98db383ac703b35793752e8bed3224f70acd9be4cb19.json)
- [closeout_freeze.json](evidence/2f5f7e150ce7f5e711ec9f6b1e7ddfba50a633bb60437c17f68310c86fd017d1.json)
- [root_closeout_authorization.json](evidence/a6a94ec3e9044861309417ab2511a2807093e34994eb31867b7b4bb3746b5442.json)
