"""Stop the verified research process tree after a complete published batch."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import time

import psutil

ROOT = Path('D:/CodeBase/czsc_trader')
WORK = ROOT/'research/S019/experiments/EX050_20261111'
RESULT = WORK/'others/account_results.json'
ATTEMPTS = WORK/'others/account_attempts.json'
TARGET_BATCHES = 3
MAIN_PID = 32604


def read(path):
    return json.loads(path.read_bytes())


def main():
    process = psutil.Process(MAIN_PID)
    argv = process.cmdline()
    assert any('EX050_20261111/src/run_accounts.py' in arg.replace('\\', '/') for arg in argv), argv
    birth = process.create_time()
    started = time.monotonic()
    while True:
        assert process.is_running() and process.create_time() == birth
        state = read(RESULT)
        if len(state['batches']) >= TARGET_BATCHES:
            break
        assert time.monotonic()-started < 1200, 'No complete batch boundary within 20 minutes'
        time.sleep(.05)
    suspended = []
    stopped = False
    try:
        process.suspend()
        suspended.append(process)
        children = process.children(recursive=True)
        assert len(children) == 61
        for child in children:
            assert '--multiprocessing-fork' in child.cmdline(), child.cmdline()
            child.suspend()
            suspended.append(child)
        state, attempts = read(RESULT), read(ATTEMPTS)
        assert len(state['batches']) == TARGET_BATCHES
        expected = {f'C0966_P{i:03}' for i in range(183)} | {
            f'{cid}_{label}' for cid in ('C0966', 'C1010', 'C0909') for label in ('CENTER', 'STRESS')}
        assert set(state['accounts']) == expected
        assert all(len(batch['statuses']) == 61 and all(s['status'] == 'SUCCEEDED' for s in batch['statuses'])
            for batch in state['batches'])
        attempt = attempts[-1]
        assert attempt['equity_statistics']['candidate_runs'] == 183
        assert attempt['equity_statistics']['benchmark_runs'] == 1
        assert attempt['execution_stats']['submitted'] == attempt['execution_stats']['completed'] == 184
        assert attempt['execution_stats']['failed'] == attempt['execution_stats']['unknown'] == 0
        checkpoints = ROOT/'.tmp/research-execution/S019/ex050-three-complete-neighborhoods/results'
        assert len(list(checkpoints.glob('*.json'))) == 183
        snapshot = {'status': 'PAUSED_AT_COMMITTED_BATCH', 'user_instruction': '请执行至一个合适的可续断点，然后暂停',
            'observed_at_utc': datetime.now(timezone.utc).isoformat(), 'completed_batches': 3,
            'published_neighbors': 183, 'reused_scenarios': 6, 'remaining_neighbors': 1515,
            'main_pid': MAIN_PID, 'main_create_time': birth, 'worker_pids': [p.pid for p in children],
            'process_method': 'Suspend verified parent and workers immediately after the third committed batch; terminate that verified tree only.',
            'checkpoint_results': 183, 'account_results_sha256': sha256(RESULT.read_bytes()).hexdigest(),
            'account_attempts_sha256': sha256(ATTEMPTS.read_bytes()).hexdigest(),
            'account_statistics': attempt['equity_statistics'], 'execution_stats_at_committed_batch': attempt['execution_stats'],
            'source_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
            'note': 'Statistics describe the last committed batch; fourth-batch account preparation may have begun before suspension. No fourth-batch account result exists.'}
        for child in children:
            child.kill()
        process.kill()
        stopped = True
        _, alive = psutil.wait_procs([*children, process], timeout=10)
        assert not alive, [p.pid for p in alive]
        snapshot['verified_processes_terminated'] = True
        destination = WORK/'others/process_pause.json'
        assert not destination.exists()
        destination.write_bytes((json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode())
        print('PAUSED_AFTER_BATCH_3', '183 published neighbors; 1515 pending; 61 workers terminated', flush=True)
    finally:
        if not stopped:
            for item in reversed(suspended):
                if item.is_running():
                    item.resume()


if __name__ == '__main__':
    main()
