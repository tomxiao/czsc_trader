"""Private disk-backed stores sharing only a real immutable empty WAL schema.

Use this for consumer setup. Initialization, migration, malformed-store and
restart tests must construct PaperStore directly for their target operation.
"""
from pathlib import Path
from threading import Lock
from uuid import uuid4

from execution_channels.futu.inspection import InspectionAccountPermit
from execution_channels.futu.store import PaperStore


_TEMP_ROOT = Path(__file__).resolve().parents[2] / '.tmp'
_EMPTY_DATABASE: bytes | None = None
_SEED_LOCK = Lock()


def _empty_database_bytes(directory: Path) -> bytes:
    global _EMPTY_DATABASE
    with _SEED_LOCK:
        if _EMPTY_DATABASE is None:
            path = directory / f'empty-schema-{uuid4().hex}.db'
            store = PaperStore(path)
            try:
                assert store._connection.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
                assert store._connection.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0] == 0
            finally:
                store.close()
            _EMPTY_DATABASE = path.read_bytes()
            path.unlink()
        return _EMPTY_DATABASE


def new_paper_store(path: Path, *, inspection_permit: InspectionAccountPermit | None = None,
                    seed: Path | None = None) -> PaperStore:
    """Copy setup bytes exclusively, then run all normal constructor checks."""
    path = Path(path)
    if not path.resolve().is_relative_to(_TEMP_ROOT):
        raise ValueError('test databases must stay under the repository .tmp')
    path.parent.mkdir(parents=True, exist_ok=True)
    # Never overwrite a live database, including an existing restart fixture.
    with path.open('xb') as target:
        content = _empty_database_bytes(path.parent) if seed is None else Path(seed).read_bytes()
        target.write(content)
    return PaperStore(path, inspection_permit=inspection_permit)
