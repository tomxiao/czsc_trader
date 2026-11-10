Source: `.tmp/ex042_20261110-accounts/recovery_v2.log`

Original SHA256: `9c4ce6bbfd8f08a222293db79d8a60f856539336b15e2cc0b35375f081cfe20f`

日志文本保留；仓库绝对路径规范为相对路径。

```text
PREFLIGHT_PASS EX042_20261110 jobs 19 ids 622 640 controls ['hard_low', 'hard_center', 'hard_high'] resources {'workers': 12, 'native_threads': 1, 'batch_size': 12, 'random_seed': 19}
ExecutionProgress(phase=<ExecutionPhase.COMPUTE: 'COMPUTE'>, completed=1, total=4, failed=0, unknown=1, elapsed_seconds=4.37257249999675)
ExecutionProgress(phase=<ExecutionPhase.COMPUTE: 'COMPUTE'>, completed=2, total=4, failed=0, unknown=2, elapsed_seconds=4.3736846999963745)
ExecutionProgress(phase=<ExecutionPhase.COMPUTE: 'COMPUTE'>, completed=3, total=4, failed=0, unknown=3, elapsed_seconds=4.373743300006026)
ExecutionProgress(phase=<ExecutionPhase.COMPUTE: 'COMPUTE'>, completed=4, total=4, failed=0, unknown=4, elapsed_seconds=4.3737680000049295)
Traceback (most recent call last):
  File " .\research\S019\experiments\EX042_20261110\src\batch_runner.py", line 333, in <module>
    main()
  File " .\research\S019\experiments\EX042_20261110\src\batch_runner.py", line 313, in main
    assert all(r['status'] == 'SUCCEEDED' for r in statuses), 'Inspect failed accounts before explicit recovery'
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: Inspect failed accounts before explicit recovery

```
