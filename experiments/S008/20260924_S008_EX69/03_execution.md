# S008 EX69 执行

实验按预注册合同执行到能力审计证据封装阶段后失败。`capability.to_dict(orient="records")`保留了
Pandas `Timestamp`，标准JSON编码器拒绝序列化，异常为`TypeError: Object of type Timestamp is not
JSON serializable`。执行器未签发REX receipt，`.tmp/`中的中间结果不构成研究证据。

