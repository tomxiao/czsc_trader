from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from research_experiment import experiment_source_sha256


FAILED = Path(__file__).resolve().parent.parent / "20260925_S008_EX86"
FAILED_SOURCE_SHA256 = "41a0d63246e9eae06758d74f0a7c4c2509780435444a7e88299299cc4b69b260"
FAILED_MANIFEST_SHA256 = "979a7ff63b2cf93adb12a784fb34bbb24942ba10cbba4aa2c4ffb6ff5c3907a6"
if experiment_source_sha256(FAILED, ("experiment.py", "run_experiment.py")) != FAILED_SOURCE_SHA256:
    raise ValueError("EX86 frozen source differs")
if sha256((FAILED / "experiment_manifest.json").read_bytes()).hexdigest() != FAILED_MANIFEST_SHA256:
    raise ValueError("EX86 technical failure manifest differs")
source = (FAILED / "experiment.py").read_text(encoding="utf-8")
old_identity = 'experiment_id="20260925_S008_EX86"'
old_alignment = 'opens = prices["open"].reindex(positions.index).astype(float)'
if source.count(old_identity) != 1 or source.count(old_alignment) != 1:
    raise ValueError("EX86 technical correction locations differ")
source = source.replace(old_identity, 'experiment_id="20260925_S008_EX87"')
source = source.replace(old_alignment, 'opens = prices.set_index("dt")["open"].reindex(positions.index).astype(float)')
exec(compile(source, str(FAILED / "experiment.py"), "exec"), globals())
