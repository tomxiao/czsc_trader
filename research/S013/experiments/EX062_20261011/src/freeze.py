"""Prospective root freeze only: no preparation or new financial evaluation."""
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').exists())
WORK = ROOT / '.tmp/s013-robust-center'


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main():
    assert read(WORK / 'focused.json')['status'] == 'PURE_PASS'
    assert read(WORK / 'selfcheck_checks.json')['status'] == 'PASS'
    assert read(WORK / 'driver_checks.json')['status'] == 'PURE_PASS'
    assert read(WORK / 'authenticate_readonly.json')['status'] == 'PASS'
    review = read(WORK / 'review_driver.json')
    assert review['status'] == 'READY_FOR_ROOT_FREEZE', review
    for proof_name in ('focused.json', 'driver_checks.json', 'authenticate_readonly.json', 'review_driver.json'):
        proof = read(WORK / proof_name)
        for name, digest in proof.get('source_hashes', {}).items():
            path = WORK / name
            assert sha256(path.read_bytes()).hexdigest() == digest, (proof_name, name)
    assert not (WORK / 'method_reference.json').exists()
    sys.path.insert(0, str(ROOT / 'research/S013/experiments/EX058_20261011/src'))
    import common
    from czsc_trader.application import create_experiment, ExperimentRequest, publish_evidence
    from czsc_trader.research_tools import MaterialEvidenceWrite
    from czsc_trader.research_tools.evidence import ExperimentRef
    ctx = common.context(1)
    existing = ROOT / 'research/S013/experiments/EX062_20261011/experiment.json'
    exp = ExperimentRef.from_dict(read(existing)) if existing.exists() else create_experiment(ctx, ExperimentRequest(
        '固定九中心的扰动绝对表现筛选',
        '固定C8880源码与13完整域，直接比较原32扰动四门联合达标率、净年化Q10及全期回撤Q90，检验是否存在稳健中心。',
        date(2026, 10, 11)))
    assert exp.experiment_id == 'EX062_20261011', exp.to_dict()
    folder = exp.resolve(ROOT)
    src, protocols = folder / 'src', folder / 'protocols'
    src.mkdir(exist_ok=True)
    protocols.mkdir(exist_ok=True)
    names = ('driver.py', 'robust_center_draft.py', 'selfcheck.py', 'focused_checks.py',
             'selfcheck_checks.py', 'driver_checks.py', 'authenticate_readonly.py', 'freeze.py')
    for name in names:
        shutil.copyfile(WORK / name, src / name)
    for name in ('root_decision.json', 'source_inventory.json', 'selfcheck_method.json'):
        shutil.copyfile(WORK / name, src / name)
    sys.path.insert(0, str(src))
    import driver
    assert Path(driver.__file__).resolve() == src / 'driver.py'
    method = driver.method_draft()
    assert len(method['queue']) == 9 and len(method['coordinates']) == 13
    method.update(status='FROZEN_FOR_EXECUTION', role='RSCH', stage=3,
                  authorization='用户要求自主设目标并开始研究；允许重设计验证，不逐轮评审；原四门和标准扰动保持不变。',
                  root_decision=read(WORK / 'root_decision.json'),
                  source_review=read(WORK / 'review.json'),
                  driver_review=review,
                  five_item_method=read(WORK / 'selfcheck_method.json'),
                  code_base_commit='f42a047a')
    method['sources'].update({(src / n).relative_to(ROOT).as_posix(): sha256((src / n).read_bytes()).hexdigest() for n in names})
    refs = {}
    material_names = ('root_decision.json', 'review.json', 'review_driver.json', 'focused.json',
                      'selfcheck_checks.json', 'driver_checks.json', 'selfcheck_method.json', 'authenticate_readonly.json',
                      'duplicate_probe.json', 'source_inventory.json')
    for name in material_names:
        path = WORK / name
        ref = publish_evidence(ctx, MaterialEvidenceWrite(exp, 'prospective-' + path.stem.replace('_', '-'), path.read_bytes(), 'application/json', 'json'))
        refs[name] = ref.to_dict()
    for name in names:
        path = src / name
        ref = publish_evidence(ctx, MaterialEvidenceWrite(exp, 'source-' + path.stem.replace('_', '-'), path.read_bytes(), 'text/x-python', 'py'))
        refs[name] = ref.to_dict()
    method['prospective_material_references'] = refs
    common.write(protocols / 'method.json', method)
    ref = publish_evidence(ctx, MaterialEvidenceWrite(exp, 'fixed-nine-center-method', (protocols / 'method.json').read_bytes(), 'application/json', 'json'))
    common.write(protocols / 'method_reference.json', ref.to_dict())
    common.write(WORK / 'method_reference.json', ref.to_dict())
    common.write(protocols / 'prospective_references.json', refs)
    common.write(WORK / 'experiment.json', exp.to_dict())
    print({'experiment': exp.experiment_id, 'method': 'FROZEN', 'new_accounts': 0}, flush=True)


if __name__ == '__main__':
    main()
