"""Finalize EX063 with exact reviewed postprocessor and explicit technical evidence."""
from dataclasses import replace
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import patch
from contextlib import ExitStack

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.tmp/s013-management-execution'
FORMAL = ROOT / 'research/S013/experiments/EX063_20261011'
SOURCE = ROOT / '.tmp/s013-management-closeout/postprocess.py'
assert sha256(SOURCE.read_bytes()).hexdigest() == '8c87914f15c45c11bd5b455c496194358012b7b76cb3b5993b8e91170595b05f'
spec = importlib.util.spec_from_file_location('management_postprocessor', SOURCE)
post = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = post
spec.loader.exec_module(post)
from czsc_trader.research_tools.evaluation_access import EvaluationAccess
from dataflows import Dataflows


def forbidden(*args, **kwargs):
    raise AssertionError('EX063 finalization cannot prepare or evaluate accounts')


def json_shape_validate(original):
    def compare(bundle, state, plans, gates, selection):
        # Frozen selection returns a tuple; the original published JSON stores a list.
        # Convert this one representation only, retaining every label and other field.
        labels = selection['fivecheck_labels']
        if type(labels) is not tuple or labels != tuple(bundle['analysis']['selection']['fivecheck_labels']):
            raise ValueError('Expected exact declared labels before JSON representation normalization')
        return original(bundle, state, plans, gates, {**selection, 'fivecheck_labels': list(labels)})
    return compare


if __name__ == '__main__':
    before = post.read(WORK / 'journal.json')
    assert before['attempts'] == 4
    resume = post.read(WORK / 'selfcheck_resume_receipt.json')
    assert resume['status'] == 'COMPLETE_EXACT_COMPARISON_SELFCHECK_RESUME'
    assert resume['new_account_evaluations'] == resume['preparations'] == 0
    technical = post.read(FORMAL / 'protocols/equality_resume_correction.json')
    refs = tuple(post.checked_ref(technical[k]) for k in
                 ('source_reference', 'pure_proof_reference', 'failure_reference'))
    with ExitStack() as stack:
        stack.enter_context(patch.object(post, 'validate_shape', json_shape_validate(post.validate_shape)))
        for target, names in ((EvaluationAccess, ('prepare', 'evaluate', 'evaluate_many')),
                              (Dataflows, ('prepare',))):
            for name in names:
                stack.enter_context(patch.object(target, name, forbidden))
        collected = post.collect(WORK / 'method_reference.json', WORK)
        collected = replace(collected, evidence=tuple(dict.fromkeys((*collected.evidence, *refs))),
                            material_paths=(*collected.material_paths, Path(__file__)))
        mandate = post.d.DeliveryReference.from_dict(post.read(ROOT / 'research/S013/deliveries/MANDATE/6/receipt.json')['reference'])
        previous = post.d.DeliveryReference.from_dict(post.read(ROOT / 'research/S013/experiments/EX062_20261011/protocols/delivery_reference.json'))
        result = post.finalize(collected, mandate, previous, 56)
    assert post.read(WORK / 'journal.json') == before
    print(json.dumps({'status': 'PASS', 'reference': result.to_dict(), 'new_accounts': 0,
                      'technical_source_proof_failure_included': True}, ensure_ascii=False))
