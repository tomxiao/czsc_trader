from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from research_experiment import experiment_source_sha256


FAILED_EXPERIMENT = "20260924_S008_EX80"
FAILED_SOURCE_SHA256 = "9f5a29ac10c7c1e3d4a292514038714d0d3f666c807d0b3bdcda0cf378bcc33f"
FAILED_MANIFEST_SHA256 = "04efe4eb30eb039b5d59c1437f7cd4b9c375b80a8a4cd2a46597af46f249a8ac"

failed_root = Path(__file__).resolve().parent.parent / FAILED_EXPERIMENT
if experiment_source_sha256(failed_root, ("experiment.py", "run_experiment.py")) != FAILED_SOURCE_SHA256:
    raise ValueError("EX80 frozen implementation differs")
if sha256((failed_root / "experiment_manifest.json").read_bytes()).hexdigest() != FAILED_MANIFEST_SHA256:
    raise ValueError("EX80 technical-failure manifest differs")
source = (failed_root / "experiment.py").read_text(encoding="utf-8")
identity_old = 'experiment_id="20260924_S008_EX80"'
receipt_old = 'EX79_RECEIPT = "9b523167ec93271e2d2dbf13473cd925db30c0b50a3293d1e79e331f20547"'
receipt_new = 'EX79_RECEIPT = "9b523167ec93271e2d2dbf13473cd925db30c0b50a3293d1e79e331679f20547"'
if source.count(identity_old) != 1 or source.count(receipt_old) != 1:
    raise ValueError("EX80 technical-successor patch locations differ")
source = source.replace(identity_old, 'experiment_id="20260924_S008_EX81"')
source = source.replace(receipt_old, receipt_new)
exec(compile(source, str(failed_root / "experiment.py"), "exec"), globals())
