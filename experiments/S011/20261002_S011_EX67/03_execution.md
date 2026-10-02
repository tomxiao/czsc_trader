# 执行

Traceback (most recent call last):
  File "D:\CodeBase\czsc_trader\packages\strategy_manager\src\strategy_manager\write_lock.py", line 35, in hold
    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
PermissionError: [Errno 13] Permission denied

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "D:\CodeBase\czsc_trader\experiments\S011\20261002_S011_EX67\run_experiment.py", line 91, in main
    result = execute_experiment(loaded, context)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\CodeBase\czsc_trader\src\czsc_trader\research_tools\experiment.py", line 685, in execute_experiment
    result = experiment.implementation.execute(context)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\CodeBase\czsc_trader\experiments\S011\20261002_S011_EX67\experiment.py", line 282, in execute
    record = register_candidate(
             ^^^^^^^^^^^^^^^^^^^
  File "D:\CodeBase\czsc_trader\src\czsc_trader\application\candidate_service.py", line 193, in register_candidate
    return registry.register_candidate(record, experiments_root=context.experiments_root)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\CodeBase\czsc_trader\packages\strategy_manager\src\strategy_manager\write_lock.py", line 58, in guarded
    with self._write_lock.hold():
         ^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\tomxiao\AppData\Local\Programs\Python\Python312\Lib\contextlib.py", line 137, in __enter__
    return next(self.gen)
           ^^^^^^^^^^^^^^
  File "D:\CodeBase\czsc_trader\packages\strategy_manager\src\strategy_manager\write_lock.py", line 40, in hold
    raise RegistryError(f"cannot acquire registry write lock: {self.path}") from exc
strategy_manager.errors.RegistryError: cannot acquire registry write lock: D:\CodeBase\czsc_trader\research\registrations\.registry.lock

