"""S013 stage-four helpers; formal facts use public TDR and SE APIs."""
from pathlib import Path
import json
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import ROOT, DEPENDENCIES, context, cache_read, cache_write  # noqa: E402,F401
from common_adaptive import request, candidate  # noqa: E402,F401
from czsc_trader.research_tools import delivery as d  # noqa: E402
from czsc_trader.research_tools.context import ExperimentRef  # noqa: E402
from czsc_trader.application import publish_evidence  # noqa: E402
from czsc_trader.research_tools import MaterialEvidenceWrite  # noqa: E402

EXPERIMENT = ExperimentRef('S013', 'EX004_20261007')
CACHE = ROOT / '.tmp/s013-stage4'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(name, value):
    (HERE / name).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                      allow_nan=False) + '\n', encoding='utf-8', newline='\n')


def source(stage, revision):
    return d.DeliveryContent.from_dict(read(ROOT / f'research/S013/deliveries/{stage}/{revision}/delivery.json')['content'])


def reference(stage, revision):
    return d.DeliveryReceipt.from_dict(read(ROOT / f'research/S013/deliveries/{stage}/{revision}/receipt.json')).reference


def material(research, name, filename, media='application/json'):
    path = HERE / filename
    return publish_evidence(research, MaterialEvidenceWrite(EXPERIMENT, name,
        path.read_bytes(), media, path.suffix[1:]))


def centers():
    payload = source('CANDIDATES', 3).payload
    return tuple(entry for entry in payload.candidates if entry.identity.key in payload.handoff)
