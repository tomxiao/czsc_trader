# V4账户回放合成基准

`equity_replay_benchmark.py`仅构造CN/US合成日历、RAW行情、显式规则和当前V4策略，
不读真实研究批次、不连接供应商、不发布研究证据。旧EX027/V3比较脚本和专用策略夹具已退役，
历史研究原件保留，不承诺旧schema机器复算。

从仓库根目录运行：

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:OMP_NUM_THREADS = '1'
$env:OPENBLAS_NUM_THREADS = '1'
.venv/Scripts/python.exe scripts/benchmarks/equity_replay_benchmark.py --market US --rows 25000 --repeats 3
```

`--market CN`使用合成午休交易段、整手及次日可卖规则；默认US。日历仅取工作日，不是交易所真实历史。
输出限于根目录 `.tmp/`，默认 `.tmp/equity-replay-benchmark/result.json`；需要保留多次结果时
显式选择不同的 `--output`，不能覆盖为真实研究证据。非法规模或输出越界直接失败。

准备时间单独计量；每次账户时间包含执行器构造、策略启动装载、策略／特征计算、执行与七张结果表。
不含DFLS取数、SE认证、JSON哈希和发布。报告全部重复及中位数，并比较重复运行的七表内容哈希。
账户必须满足 `source_checks=0`和 `module_loads=1`，不会逐步检查或重新装载源码。
新结果不能与旧脚本不同工作量、口径和并发负载的耗时直接计算加速比。

聚焦测试位于 [合成基准验收](../../tests/functional/test_equity_replay_benchmark.py)。
需要精确定位执行器成本时，另用预构造中立计划计时；这种纯执行时间不包含策略和准备，必须分别报告。
