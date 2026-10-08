"""Fresh parent per sequential batch; abort on any recorded failure."""
import subprocess
import sys
from phase4_common import HERE, CACHE, save


def main():
    log = CACHE / 'batches.log'
    with log.open('a', encoding='utf-8') as stream:
        for batch in range(1, 23):
            result = subprocess.run([sys.executable, str(HERE/'run_batch.py'), str(batch)],
                                    text=True, encoding='utf-8', capture_output=True)
            stream.write(result.stdout + result.stderr)
            stream.flush()
            print(result.stdout, end='', flush=True)
            if result.returncode:
                print(result.stderr, flush=True)
                save('execution_stop.json', {'batch': batch, 'returncode': result.returncode,
                    'status': 'STOPPED_FOR_EXPLICIT_RETRY_REVIEW', 'stderr': result.stderr})
                raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
