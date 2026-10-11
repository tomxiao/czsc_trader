"""Reproduce frozen EX053 analysis using one authenticated enum-only repair.

No native prepare/evaluate calls are introduced. Run only after method evidence
has been retained; inputs and all frozen sources are authenticated before reads.
"""
from hashlib import sha256
from pathlib import Path
import importlib.util
import json
import sys
from czsc_trader.research_tools.evidence import EvidenceRef

HERE = Path(__file__).resolve().parent


def file_hash(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    root = Path.cwd().resolve()
    src = root / 'research/S013/experiments/EX053_20261011/src'
    reference_path = (Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else
                      src.parent / 'protocols/analysis_repair_method_reference.json')
    reference = EvidenceRef.from_dict(json.loads(reference_path.read_text(encoding='utf-8')))
    assert reference.experiment.strategy_id == 'S013' and reference.experiment.experiment_id == 'EX053_20261011'
    method_path = reference.resolve(root)
    assert file_hash(method_path) == reference.sha256, 'Published repair method drift'
    method = json.loads(method_path.read_text(encoding='utf-8'))
    assert method['status'] == 'PURE_READY_TECHNICAL_ANALYSIS_REPAIR'
    for relative, digest in method['immutable_frozen_inputs'].items():
        assert file_hash(root / relative) == digest, relative
    for name, digest in method['repair_source_files'].items():
        assert file_hash(HERE / name) == digest, name
    plan = json.loads((src.parent / 'protocols/plan.json').read_text(encoding='utf-8-sig'))
    assert plan['method_reference'] == method['original_method_reference']
    original_method = EvidenceRef.from_dict(plan['method_reference'])
    assert original_method.experiment == reference.experiment
    assert file_hash(original_method.resolve(root)) == original_method.sha256
    assert len(plan['source_files']) == 22
    for name, digest in plan['source_files'].items():
        assert file_hash(src / name) == digest, name
    for name, digest in plan['external_source_files'].items():
        assert file_hash(root / name) == digest, name
    assert method['ast_added_literal_only'] is True
    sys.path.insert(0, str(src))
    # Import frozen common and helpers in the original formal source directory.
    # Only the analyze module's summarize function is replaced.
    common = load_module('common', src / 'common.py')
    sys.modules['common'] = common
    analyze = load_module('s013_ex053_frozen_analyze', src / 'analyze.py')
    corrected = load_module('s013_ex053_enum_only_repair', HERE / 'analysis_reference_corrected.py')
    assert analyze.summarize.__module__ == 'analysis_reference'
    assert not common.SOURCE_CALLS
    analyze.summarize = corrected.summarize
    assert analyze.source_check() == plan
    analyze.main()


if __name__ == '__main__':
    main()
