"""Reuse identity-checked S014 public data binding and prior execution evidence."""
import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import requests
from czsc_trader.application import RepositoryContext, create_research_context, validate_delivery
from czsc_trader.research_tools import ResearchBatchRef, EvidenceRef, DeliveryReference, ValidationStatus

ROOT = Path(__file__).resolve().parents[5]
EXPERIMENT = Path(__file__).resolve().parents[1]
RUN = ROOT / "research/S014/assets/runs/EX007_20261017/first"


def load():
    repository = RepositoryContext.discover(ROOT)
    prior_root = ROOT / "research/S014/experiments/EX006_20261016"
    prior = json.loads((prior_root / "others/result.json").read_text(encoding="utf-8"))
    if validate_delivery(repository, DeliveryReference.from_dict(prior["delivery"])).status is not ValidationStatus.PASS:
        raise RuntimeError("Predecessor validation failed")
    binding = json.loads((prior_root / "protocols/published_design.json").read_text(encoding="utf-8"))
    for name in ("attribution", "paired", "study"):
        ref = EvidenceRef.from_dict(binding[name])
        if ref.resolve(ROOT).read_bytes() != (prior_root / f"src/{name}.py").read_bytes():
            raise RuntimeError("Prior helper source changed")
    sys.path.insert(0, str(prior_root / "src"))
    spec = importlib.util.spec_from_file_location("s014_prior_study", prior_root / "src/study.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    initial = json.loads((ROOT / "research/S014/experiments/EX004_20261016/others/result.json").read_text(encoding="utf-8"))
    context = create_research_context(repository, ResearchBatchRef("S014"))
    original = requests.sessions.Session.request

    def prohibit(*args, **kwargs):
        raise RuntimeError("New source calls prohibited")

    requests.sessions.Session.request = prohibit
    try:
        data, dates = module.load_inputs(context, initial)
    finally:
        requests.sessions.Session.request = original
    observation = module.observations(data)
    decision_ref = EvidenceRef.from_dict(prior["evidence"]["decisions"])
    decisions = pd.read_csv(decision_ref.resolve(ROOT))
    labels_ref = EvidenceRef.from_dict(initial["evidence"]["labels"])
    labels = pd.read_csv(labels_ref.resolve(ROOT))
    return data, dates, observation, decisions, labels, module
