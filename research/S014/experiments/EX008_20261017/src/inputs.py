"""Read public, hash-bound S014 inputs; no new provider calls."""
import importlib.util
import json
from pathlib import Path
from czsc_trader.application import RepositoryContext, validate_delivery
from czsc_trader.research_tools import DeliveryReference, EvidenceRef, ValidationStatus

ROOT = Path(__file__).resolve().parents[5]
EXPERIMENT = Path(__file__).resolve().parents[1]
RUN = ROOT / "research/S014/assets/runs/EX008_20261017/first"


def load():
    prior_root = ROOT / "research/S014/experiments/EX007_20261017"
    result = json.loads((prior_root / "others/result.json").read_text(encoding="utf-8"))
    if validate_delivery(RepositoryContext.discover(ROOT), DeliveryReference.from_dict(result["delivery"])).status is not ValidationStatus.PASS:
        raise RuntimeError("Predecessor validation failed")
    ref = EvidenceRef.from_dict(result["evidence"]["inputs"])
    path = prior_root / "src/inputs.py"
    if ref.resolve(ROOT).read_bytes() != path.read_bytes():
        raise RuntimeError("Inherited input reader changed")
    spec = importlib.util.spec_from_file_location("s014_bound_inputs", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load()
