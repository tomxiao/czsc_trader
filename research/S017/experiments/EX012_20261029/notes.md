# 市场恢复中的个股抗跌

固定持有规则，SPY恢复时此前LITE抗跌条件是否比一般恢复启动提供净收益增量？

## 分析启动前的调度调整

2026-10-29，在EX012正式账户发布和分析启动前，公共认证确认事前冻结材料不含analyze.py，候选source_files仅为strategy.py。EX011和EX013分析正常结束后，停止只等待EX012的旧队列父进程，再将三项预定公共诊断改为3个spawn进程并行执行，每进程1个原生线程。主进程仍按原对照顺序串行保存和发布全部诊断；请求、身份、完整审计、摘要、次数和失败语义不变，没有重试、跳审计或私有检查点读取。

合成检查见[analysis_scheduling_check.json](others/analysis_scheduling_check.json)，冻结范围和源码身份见[analysis_scheduling_scope.json](others/analysis_scheduling_scope.json)。检查在候选副本上完成，因此其中active_script_unchanged指检查当时活动路径未修改；其后主流程核对旧源码及候选SHA后才应用。旧队列的人工停止退出码不代表任何实验失败，EX012新等待队列继续等待正式账户发布。正式回放、冻结交易规则和平台代码均未调整；此调度变化不新增实验轮次，不证明任何收益机制。
