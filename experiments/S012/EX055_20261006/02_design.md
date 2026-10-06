# 前瞻设计

仅a190模型第116行hold_days上限60→120一处字节变化；min_hold上限动态随hold，实际退出仍age>=hold，公开范围1..120与实际四项60/80声明绑定。原native feature8ed/provenance4c334不变。精确EX049 OPTUNA_1011 all_union/-.005与OPTUNA_0607 momentum_union/lookback5/.005原参数各h60/h80，无风险门、止损或仓位变化。新源码h60真实FULL是行为对照；h80未预测。先80隔离一次边界扩展，是否120由实际新信息决定，不自动全域。
