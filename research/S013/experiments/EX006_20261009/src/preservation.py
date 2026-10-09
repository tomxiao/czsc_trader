"""Read-only verification of original DFLS records against their retained snapshot."""
from hashlib import sha256
import sqlite3

from common import ROOT, RUNS, read, write


def main():
    migration = read(ROOT / 'research/S013/assets/runs/EX004_20261007/contract_migration/migration.json')
    backup = ROOT / migration['backup']
    assert sha256(backup.read_bytes()).hexdigest() == migration['original_database_sha256']
    counts = {}
    with sqlite3.connect(backup.as_uri() + '?mode=ro', uri=True) as original:
        with sqlite3.connect((ROOT / migration['space'] / 'assets.sqlite3').as_uri() + '?mode=ro', uri=True) as current:
            assert original.execute('SELECT * FROM space_metadata').fetchall() == current.execute('SELECT * FROM space_metadata').fetchall()
            for table, column in (('assets', 'asset_id'), ('preparations', 'preparation_id')):
                old = original.execute(f'SELECT * FROM {table}').fetchall()
                for row in old:
                    assert current.execute(f'SELECT * FROM {table} WHERE {column}=?', (row[0],)).fetchone() == row
                counts[table] = len(old)
    write(RUNS / 'preservation.json', {'status': 'PASS', 'original_records': counts,
                                     'comparison': 'every original SQLite row exact; original snapshot hash unchanged'})
    print({'status': 'PASS', 'original_records': counts})


if __name__ == '__main__':
    main()
