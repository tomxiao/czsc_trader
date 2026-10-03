# 技术失败

合成预检通过；9个实际数据请求均READY，包括已修正的VIX。
正式tsfresh以8进程启动时，Windows沙箱在multiprocessing.connection.Pipe的CreateFile调用拒绝访问：
`PermissionError: [WinError 5]`。失败发生在实际特征矩阵生成前，无收益诊断结果可用于选择。
工作空间中已取得的数据和平台留下的执行事实原样归档至artifacts/rex。
