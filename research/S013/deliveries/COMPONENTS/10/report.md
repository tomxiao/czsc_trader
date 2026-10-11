# EX073：隔夜压力能否识别持有后半段的风险

本轮固定统计及独立验证完成，0新账户。原真实bear入场的后半两日出现支持原风险职责方向的组件证据，判为LIMITED_SUPPORT_FOR_FIXED_HOLDING_TEST。它支持一个固定完整账户对照，不证明已经找到稳健达标策略，也不推翻EX072取消买入失败的结论。

117次实际首次BUY中bear64次，固定入场前4日隔夜下跌幅度总和大于日内下跌总和的标记15次。63次主标签成熟，其中15标记、48非标记；原14控制完整后62次、14标记、残差自由度47。实际成交发生T+1，本池是条件于实际成交的研究样本；只有标记与控制信息在T已知，不把样本选择当作可在T部署的过滤器。

后半收益=Open[T+5]/Open[T+3]-1，比较同数量T+3卖出与T+5卖出，同一卖费抵消，无新买费。风险仅使用T+3/T+4的OPEN/CLOSE及T+5OPEN，不用High/Low，不是账户最大回撤。原退出日不参与挑样本，标签可假设跨越旧退出。

|主标签|控制后秩相关|500×40描述区间|有效样本 / 标记 / 残差df|
|---|---:|---|---:|
|late_return|-0.47297|[-0.68318,-0.26365]|62 / 14 / 47|
|late_downside|+0.35371|[+0.00246,+0.65907]|62 / 14 / 47|

收益原始相关−0.28487，描述区间[−0.56987,−0.04416]；风险原始相关+0.23167，区间[+0.02115,+0.53609]。四套bootstrap均500有效、0失败，全部记录核验。区间未校正本开发池反复选择，不能解释为未来成功概率或独立验证。

描述性分解：标记组前两日均值+0.43277%，后两日−0.16292%，完整四日+0.27883%；非标记后两日+0.78394%。标记组后半OPEN/CLOSE风险0.94053%，非标记0.54709%。各均值只是15/48个反事实价格观察，辅助first2/full4未增加相关、CI或模型；平均数不能直接相乘代替逐笔乘法恒等式。

必要反证：标记只有15次，按事前方法分组证据不可靠；控制后14次。2022仅4次、后半均值−1.2764%，2023仅3次、后半均值−0.1120%；这不是已确认跨年稳定优势。2020标记后半均值+1.1453%、2025+1.5710%，提前退出会放弃这些后续盈利。所有年度和五个非重叠相位原始样本不足、控制后自由度不足，均明确null，不能把整体区间当逐年/逐相位确认。

17项合成检查及6项拒绝、价格认证补充3项合成及3项拒绝通过，24,128项独立实际核验通过（输入22,042、统计2,086）。技术认证在实际统计前发现原生HFQ研究单位与公共HFQ差一个固定0.2803锚点；原声明、旧源码和失败均保留，补充公开仅修复认证，逐行标签比值及成熟日期的尺度不变已验证；实际标签、群体、控制、方向和统计方法保持。

根判断：保留这项期限匹配的有限正证，继续检验一个新固定策略表达：保留原确认和买入，原bear入场的压力标记锁存后，原规则仍会继续持仓时最多持有2信号日，其他原退出优先；这是下一独立实验，EX073自身仍0账户。公开整数参数域和完整扰动维数，固定中心先验收原四门，只有全过才执行标准32点及独立双费用；不调阈值、回溯选年、改变硬门或实施动态仓位。

量价交互仅为未检验的新假说，先保留方法审查；当前优先使用本次实际期限证据。保留C8880研究基线，整体稳健策略目标尚未达成。

研究范围仍是原S013 510500.SH开发池与原warmup、后复权无分红叠加、固定1%执行合同；无新增provider、封存样本、DEV/PTE/生产操作。

## 正式证据引用

- [driver.py](evidence/4829abcd3fb6d7683358380a8581c65bf715dd39f47d349e157d3f8b296f24cd.py)
- [entry_core.py](evidence/3b5a73b7c5a6144f782ac056ca33c3c1c2830c23aa665dda6d27d8a14336a855.py)
- [entry_statistics.py](evidence/359f7a72470b9479d1c491f9b39f89960ef701567b16223fb6fbefb385b7ebc1.py)
- [focused_checks.py](evidence/cd7617050d55b2d746506e974e0ce302386f5f4469aacc524afbd2d851d8d430.py)
- [freeze_plan.py](evidence/e2d9237bd9cb8118e8e83868feccb165553a754c41b6adf8af5d706e78978c76.py)
- [independent_checks.py](evidence/781e185987643c543cdf9205230d8493c0252911bcce5abeecc9db366e54b8a3.py)
- [focused_checks.json](evidence/775153d7f6c48d4be606f06b6ec903b46e7048f7fb3291f2f515c2e0ca8d47e4.json)
- [method.json](evidence/a989de22d94017310255e56c2ee283cadcab924b7b9955086a45a1ba26078256.json)
- [prospective_plan.json](evidence/22350ba0769193b54801f8e9b4861c8bbf0d8563cee7ba3fd07e049c87f3d74d.json)
- [plan.json](evidence/56acf70206807a4fcfb08d7b1464f6ee42f9518cfc4206020ffa0b6320368e1a.json)
- [features.csv](evidence/447cb355b7e122f867942c41e58f0d3249e50b20dc0286c240b8cd38e94af83c.csv)
- [labels.csv](evidence/8791586f9a3a063ace73758d2e6d5ec01317de1bc89c2f64877ee60b1b6b1c29.csv)
- [entries.csv](evidence/9d7315619bc472c0765f744fe08044c4999d6de6da4ceb659c3d2ec3f5b7a244.csv)
- [scope.csv](evidence/bb66934f92107ef4765c6f4d3c5e76e582decb6295c5d58f82a7fc5f7cadb830.csv)
- [prices.csv](evidence/499377d8075acbed61555029809b7449dc5703e24ad04bbc6abf8e095c479a0e.csv)
- [input_checks.json](evidence/d4dcda73a2b6ed683552b0cd94a888294caf58d82a80b5f1166b6b464c26193f.json)
- [root_statistics_authorization.json](evidence/d7392cf70b9e9f8c1bb163b4e323e6b3e6ddf2f21aa456ac9de3cc6aa2ac5f20.json)
- [statistics.json](evidence/764859c801574ffebad115aa4e09708b1574912a7fbd2f9d53951b5e02438dfc.json)
- [verification.json](evidence/81896b4a5970fca33ebec43ba558a5069ade0765f5fe026aeafc4a3e1f477838.json)
- [driver_pricefix.py](evidence/fdeb4f4895ce5f67c5d259d9ed22f9f8fef83e1beae26c8b6862ac1f5a7d2674.py)
- [price_authentication.py](evidence/c455e87bf012768910b52c49076255b7908c4a01d51ed759037d9a5e217986b8.py)
- [price_fix_checks.py](evidence/8586baa12dbd52148b0cd70c06665d21edc140d27e976beaa4383fb997d9d5e9.py)
- [price_fix_checks.json](evidence/4544eb4f66867312642eb37b1a795b3b7ed49959f040f2bc2b442d6d0974889a.json)
- [price_technical_amendment.json](evidence/47a89ad296991c238ae5325194af3a5bcf446df16193285410b14358ebe74213.json)
- [C8880_original_native](evidence/2ba4906b271e148a956755df9ba9907457ef0bee726b7a24a13602df4e73fa3e.json)
- [actual_input_old_features.csv](evidence/aa2a816c802ed35932e8d879efcc75cb3876a9280e74b3e188461923bd5736bd.csv)
- [actual_input_pressure_features.csv](evidence/e1e2dc88675e953364369833d1e8731e8c39061e723498e50d46ddefaace764c.csv)
- [actual_input_warm_prices.csv](evidence/71319e1c9ea6543849f809a0996bd6978636d76848cbb3c8aaf962f302c27263.csv)
- [actual_input_predecessor_verification.json](evidence/9d007a8bcfea18d85255180b06a60cb88e41d4b80367a54d869600ce5ca25f81.json)
- [known_counter_EX069_statistics](evidence/064197fc69cc4571fdbe66b82db4e3ea001d832b35131698bd1a1a578517a149.json)
- [known_counter_EX069_verification](evidence/9d007a8bcfea18d85255180b06a60cb88e41d4b80367a54d869600ce5ca25f81.json)
- [known_counter_EX071_plan](evidence/0ab0b925a3300cd870d92ccad7b3d5d3b581e8a4f51eefc5ff591e2966d177fe.json)
- [known_counter_EX071_statistics](evidence/04f600fc246836bebd2d53c586eea704b0d4a44607d1d2dd4549d1f32942153b.json)
- [known_counter_EX071_verification](evidence/c79a52e2d156347676da78f7bdd69e87f53391c7b1470f8c8520cc26b8671f5c.json)
- [known_counter_EX072_plan](evidence/d430f6f7b2d96dc124b5b85b6f016ade210bb88a40221de19d11ad8cbfa56cdf.json)
- [known_counter_EX072_native_centre](evidence/29a7e880e99e08b3c9363211f3d4a6fae8f520cc73af5a335a48aee160b1c958.json)
- [known_counter_EX072_verification](evidence/b0abe4096a25ad3c595b17af0dce4020c3d8d60cc3817cca50ba2e86d466e410.json)
- [execution_receipt.json](evidence/d4cb7de05b732d4c56746c38aa0158a61ccc07a4d4eb4e8f7f070db11592f673.json)
- [root_review.json](evidence/c6f13f90eb4801a163b875c5adf487bb554db470c2743f1c08cfbb2519c28498.json)
- [root_review_writer.py](evidence/4a882a78ad67412557d632acf6d8da93ac2a8cac29abe6e4835f30da6c441833.py)
- [root_delivery_authorization.json](evidence/5d1d71066254888fed0ebf0408945c720a8305600caff8e94e32f49cba063fcf.json)
- [finish.py](evidence/57289c0e1db287f4dc2bc1be82929511a2428367d3131107c1c876392ce407dc.py)
- [closeout_checks.py](evidence/b1629c51c4fedce18ff2d0d9a73bc70fef44bf6c097e25a04d0b409ce124e661.py)
- [closeout_checks.json](evidence/c38b9f5bb98515092ad0acc56c6f3b95ecb5f619f20ce0296da6e2834bcbd1c7.json)
- [report.md](evidence/1fd9909785163ed3402b88d81e30915c432d758f8bf899dbb183b9e90ddc3c0a.md)
