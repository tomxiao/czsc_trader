# 业务审计保存精度修正

首次审计使用未舍入目标仓位与已保存JSON数值直接比较，绝对容差为1e-12。下列差异超过该容差，审计停止；当次未产生PASS。

经核验，公共账户记录由 `src/czsc_trader/research_tools/equity_evaluation.py` 的 `_records` 通过 pandas `DataFrame.to_json` 保存，默认 `double_precision=10`。本地实际复现 `0.16417603125000002` 保存为 `0.1641760313`。

修正后的审计先检查十位小数的舍入误差界限5.01e-11（含浮点运算裕量），再将独立重建的完整目标仓位序列按相同JSON格式保存，与原账户逐值严格相等比较。策略、账户、参数和经济验收标准均保持。最终结果另见 [semantic_audit.json](semantic_audit.json)。以下首次失败栈仅将绝对路径改为仓库相对路径。

```text
Traceback (most recent call last):
  File "research/S019/experiments/EX041_20261110/src/semantic_audit.py", line 138, in <module>
    main(Path(sys.argv[1]), Path(sys.argv[2]))
  File "research/S019/experiments/EX041_20261110/src/semantic_audit.py", line 104, in main
    assert np.isclose(expected, decision["target"], atol=1e-12, rtol=0), (day, slot, expected, decision["target"])
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: ('2022-04-04', 1, 0.16417603125000002, 0.1641760313)
```
