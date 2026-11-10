Source: `.tmp/ex042_20261110-accounts/run.log`

Original SHA256: `c79754cfdb24f9d96859631513bcde5367aaf965046a72ebdf9aefd6e8544ef5`

日志文本保留；仓库绝对路径规范为相对路径。

```text
PREFLIGHT_PASS EX042_20261110 jobs 19 ids 622 640 controls ['hard_low', 'hard_center', 'hard_high'] resources {'workers': 12, 'native_threads': 1, 'batch_size': 12, 'random_seed': 19}
ExecutionProgress(phase=<ExecutionPhase.COMPUTE: 'COMPUTE'>, completed=1, total=4, failed=0, unknown=1, elapsed_seconds=4.245015000007697)
ExecutionProgress(phase=<ExecutionPhase.COMPUTE: 'COMPUTE'>, completed=2, total=4, failed=0, unknown=2, elapsed_seconds=4.245989700008067)
ExecutionProgress(phase=<ExecutionPhase.COMPUTE: 'COMPUTE'>, completed=3, total=4, failed=0, unknown=3, elapsed_seconds=4.246037100005196)
ExecutionProgress(phase=<ExecutionPhase.COMPUTE: 'COMPUTE'>, completed=4, total=4, failed=0, unknown=4, elapsed_seconds=4.246056500007398)
Traceback (most recent call last):
  File " .\research\S019\experiments\EX042_20261110\src\batch_runner.py", line 331, in <module>
    main()
  File " .\research\S019\experiments\EX042_20261110\src\batch_runner.py", line 311, in main
    assert all(r['status'] == 'SUCCEEDED' for r in statuses), 'Inspect failed accounts before explicit recovery'
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: Inspect failed accounts before explicit recovery

```
