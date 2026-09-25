from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from research_experiment import experiment_source_sha256


FAILED_EXPERIMENT = "20260925_S009_EX01"
FAILED_SOURCE_SHA256 = "a594c8ccc9d950ba7dc24f268e70ed74aa631be04645ff98f6b33ae12aa3cae8"
FAILED_MANIFEST_SHA256 = "2dcc8f3d0f746d3c6cb725b6c3f426db3d5bcb61ac3fa4aea5dd98e285acd13e"

failed_root = Path(__file__).resolve().parent.parent / FAILED_EXPERIMENT
if experiment_source_sha256(failed_root, ("experiment.py", "run_experiment.py")) != FAILED_SOURCE_SHA256:
    raise ValueError("EX01 frozen implementation differs")
if sha256((failed_root / "experiment_manifest.json").read_bytes()).hexdigest() != FAILED_MANIFEST_SHA256:
    raise ValueError("EX01 technical-failure manifest differs")

source = (failed_root / "experiment.py").read_text(encoding="utf-8")
identity_old = 'EXPERIMENT_ID = "20260925_S009_EX01"'
identity_new = 'EXPERIMENT_ID = "20260925_S009_EX02"'
check_old = '''    if not panel.loc[:, required].dropna().gt(0).all().all():
        raise ValueError("positive aligned price/share contract failed")'''
check_new = '''    panel = panel.loc[panel.loc[:, required].notna().all(axis=1)].copy()
    if not panel.loc[:, required].gt(0).all().all():
        raise ValueError("positive aligned price/share contract failed")'''
if source.count(identity_old) != 1 or source.count(check_old) != 1:
    raise ValueError("EX01 technical-successor patch locations differ")
source = source.replace(identity_old, identity_new).replace(check_old, check_new)
exec(compile(source, str(failed_root / "experiment.py"), "exec"), globals())

