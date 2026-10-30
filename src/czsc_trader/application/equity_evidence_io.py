"""Resolve content-addressed account dependencies beside their evaluation document."""
from hashlib import sha256
from pathlib import PurePosixPath
import re

from ..research_tools.evidence import managed_path
from ..research_tools.equity_replay import materialize_equity


def materialize_equity_document(root, evaluation_path, value):
    relative = PurePosixPath(evaluation_path)
    managed = (len(relative.parts) == 6 and relative.parts[0] == 'research'
               and relative.parts[2:4] == ('assets', 'evidence'))
    snapshot = len(relative.parts) == 2 and relative.parts[0] == 'evidence'
    if relative.is_absolute() or '..' in relative.parts or not (managed or snapshot):
        raise ValueError('equity dependency owner requires a managed evaluation path')

    def resolve(reference):
        if (type(reference) is not dict or set(reference) != {'kind', 'sha256'}
                or reference['kind'] not in ('equity_input', 'equity_account')
                or type(reference['sha256']) is not str
                or not re.fullmatch('[a-f0-9]{64}', reference['sha256'])):
            raise ValueError('invalid equity dependency reference')
        path = managed_path(root, (relative.parent / (reference['sha256']+'.json')).as_posix())
        content = path.read_bytes()
        if sha256(content).hexdigest() != reference['sha256']:
            raise ValueError('published equity dependency checksum differs')
        return content

    return materialize_equity(value, resolve)
