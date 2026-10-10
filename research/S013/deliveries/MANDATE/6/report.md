# S013研究约定修订六：后续统一1%执行合同

用户确认“采用统一1%合同”，随后指示“不用复验了，后续实验照此执行即可”，并批准12配置机制对照。

仅修改后续实验基准为LimitBuyHold(100,0.01,0.001,0.1,1000000)，策略买入溢价固定1%。510500.SH、原开发池、100万元、HFQ研究单位、单侧10bp、T决策T+1执行及四项经济目标沿用MANDATE/5。负基准年度按新基准实际连续账户收益确定；不写死年份。

历史MANDATE/5、CANDIDATES/6、ASSESSMENT/2及账户不改写，不开展历史配置批量复验。本次新标准对照用于机制比较；未批准阶段四、选型、冻结或PTE。

旧MANDATE/5是schema 6，当前交付API要求schema 7，不能作为机器前驱直接解析。本修订使用当前强类型重新声明相同目标及获批新执行合同；旧交付精确字节作为关联材料保存，不补签或修改旧schema，不声称已重新语义校验旧交付。原引用：{"type": "DeliveryReference", "batch": {"type": "ResearchBatchRef", "strategy_id": "S013"}, "stage": "MANDATE", "revision": 5, "content_sha256": "292a126a99c899c2ad88af9eb4039c5141758dbccf1cb659ed9895620e07857f"}
