# 阶段四迭代02交付核验

本目录保存已封存[决策包](../iteration_02/manifest.json)的外部核验记录，不改变包内证据。核验状态为PASS，用户决定仍为PENDING_USER_DECISION。

- [统计核验](statistics.json)：独立支配矩阵、322个PBO切分、72组DSR、9组重抽样抽查。
- [账户回放](replay_CFG000649.json)：公共SRT/TXE同候选受管数据准备，五张账本一致；不代表独立行情源验证。
- 13项聚焦单元测试通过；平台代码未变，框架基准提交为`6d4a8a4c`。
- 原实验按原始字节校验；其他文本输入按清单声明规范化CRLF到LF；包内文件始终按原始字节校验。历史实验不改写。
- 本轮重算既有账户的统计与比较，没有新增参数搜索或均衡联合扰动。包中`first_reference`是登记来源，阅读视图的“首次试验”列亦应按登记来源解释，实际继承候选身份见evaluations表。

## 从仓库根复核

使用项目既有环境，不安装额外依赖。下列输出目录必须尚不存在；再次运行时选择新的`.tmp/`子目录。完整重建最多使用8个进程；若沙箱阻止进程通信，须申请本地执行授权，不切换计算口径。

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:OMP_NUM_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
.venv/Scripts/python.exe -B -m unittest discover -s research/S011/stage4/iteration_02/tests -v
.venv/Scripts/python.exe -B research/S011/stage4/iteration_02/src/build.py validate --package research/S011/stage4/iteration_02
.venv/Scripts/python.exe -B research/S011/stage4/iteration_02/src/verify.py --package research/S011/stage4/iteration_02 --output .tmp/s011-stage4-v2-user-audit
.venv/Scripts/python.exe -B research/S011/stage4/iteration_02/src/build.py build --output .tmp/s011-stage4-v2-user-rebuild
```

账户重放另需原候选的受管数据准备目录，显式指定，不以其他候选缓存替代。本轮使用的目录属于临时资源；若已清理，应通过公共数据准备流程恢复原候选对应输入，并核对身份后运行。

```powershell
.venv/Scripts/python.exe -B research/S011/stage4/iteration_02/src/replay.py --config-id S011-CFG-000649 --data-dir .tmp/s011-ex25-execution/S011EX25T014_159326_260930 --output .tmp/s011-stage4-v2-user-replay
```

下一步由用户指定配置晋升、补证或暂不晋升。核验通过不构成候选批准。
