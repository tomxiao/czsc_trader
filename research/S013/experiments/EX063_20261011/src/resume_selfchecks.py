"""Source-only strict equality correction for one frozen EX063 reused-fee check."""
from __future__ import annotations

import argparse
from collections.abc import Mapping
from contextlib import ExitStack
from dataclasses import fields, is_dataclass, replace
from datetime import date, timedelta
from enum import Enum
from hashlib import sha256
import importlib.util
import json
import math
from pathlib import Path
import sys
from unittest.mock import patch
from uuid import UUID

import numpy as np
import pandas as pd
from czsc_trader.research_tools.evaluation import EvaluationRequest

ROOT = Path(__file__).resolve().parents[2]
FORMAL = ROOT / 'research/S013/experiments/EX063_20261011'
RUNNER_SHA = '8a9d86a30d1c5f98a4a621ef1dc4c26387ec7db0e1f365e8fc28952b364e82e8'
METHOD_SHA = 'e093462ebbb2c1cde58dea505fc7597f313fb4aedd8f70f489514c90510a4cd9'
FAILURE_SHA = '9c651d57a9cc107efda88be0d52265687449a435d967ef2cef74acfde0e90d30'


class ExactMismatch(ValueError):
    """Different full contract field; values deliberately omitted from message."""


def exact(left, right, path='request'):
    """All fields, frame types/index/order/dtypes/values/NaNs/attrs, no fingerprint shortcut."""
    if type(left) is not type(right):
        raise ExactMismatch(path + ':type')
    if left is None or left is pd.NA or left is pd.NaT:
        if left is not right:
            raise ExactMismatch(path + ':null')
        return
    if isinstance(left, pd.DataFrame):
        try:
            pd.testing.assert_frame_equal(left, right, check_dtype=True, check_index_type=True,
                check_column_type=True, check_names=True, check_exact=True, check_categorical=True,
                check_like=False, check_freq=True, check_flags=True)
        except AssertionError as error:
            raise ExactMismatch(path + ':frame') from error
        exact(left.attrs, right.attrs, path+'.attrs')
    elif isinstance(left, pd.Series):
        try:
            pd.testing.assert_series_equal(left, right, check_dtype=True, check_index_type=True,
                check_names=True, check_exact=True, check_categorical=True, check_freq=True, check_flags=True)
        except AssertionError as error:
            raise ExactMismatch(path + ':series') from error
        exact(left.attrs, right.attrs, path+'.attrs')
    elif isinstance(left, pd.Index):
        try:
            pd.testing.assert_index_equal(left, right, exact=True, check_names=True,
                                          check_categorical=True, check_order=True)
        except AssertionError as error:
            raise ExactMismatch(path + ':index') from error
        if isinstance(left, (pd.DatetimeIndex, pd.TimedeltaIndex)):
            exact(left.freqstr, right.freqstr, path+'.freqstr')
    elif isinstance(left, np.ndarray):
        if left.shape != right.shape or left.dtype != right.dtype:
            raise ExactMismatch(path + ':array_shape_dtype')
        if left.dtype.hasobject:
            for i, (a, b) in enumerate(zip(left.flat, right.flat, strict=True)):
                exact(a, b, path+f'[{i}]')
        else:
            try:
                np.testing.assert_array_equal(left, right, strict=True)
            except AssertionError as error:
                raise ExactMismatch(path + ':array_values') from error
    elif is_dataclass(left):
        for field in fields(left):
            exact(getattr(left, field.name), getattr(right, field.name), path+'.'+field.name)
    elif isinstance(left, Mapping):
        if set(left) != set(right):
            raise ExactMismatch(path + ':mapping_keys')
        for key in left:
            actual_key = next(value for value in right if value == key)
            exact(key, actual_key, path+'.key')
            exact(left[key], right[actual_key], path+'['+repr(key)+']')
    elif isinstance(left, (tuple, list)):
        if len(left) != len(right):
            raise ExactMismatch(path + ':sequence_length')
        for i, (a, b) in enumerate(zip(left, right, strict=True)):
            exact(a, b, path+f'[{i}]')
    elif isinstance(left, (str, bytes, int, float, bool, complex, date, timedelta, Enum, Path, UUID, np.generic)):
        if isinstance(left, (float, np.floating)) and math.isnan(left) and math.isnan(right):
            return
        if isinstance(left, np.generic) and bool(pd.isna(left)) and bool(pd.isna(right)):
            return
        if not bool(left == right):
            raise ExactMismatch(path + ':scalar')
    else:
        raise TypeError(path + ': unsupported public field type ' + type(left).__qualname__)


class Comparison:
    """Scalar boolean equality that visits the entire replaced request."""
    def __init__(self, request):
        if type(request) is not EvaluationRequest:
            raise TypeError('Comparison requires real public EvaluationRequest')
        self.request, self.compared, self.mismatch = request, 0, None

    def __eq__(self, other):
        self.compared += 1
        try:
            exact(self.request, other)
        except ExactMismatch as error:
            self.mismatch = str(error)
            return False
        return True

    def __ne__(self, other):
        return not self.__eq__(other)


def comparison(old, expected):
    if type(old) is not EvaluationRequest or type(expected) is not EvaluationRequest:
        raise TypeError('Only exact public EvaluationRequests may be rebound')
    return Comparison(replace(old, experiment_id=expected.experiment_id, lineage=expected.lineage))


def adapter(runner, events):
    original = runner.replace

    def corrected(old, *args, **changes):
        if type(old) is EvaluationRequest and set(changes) == {'experiment_id', 'lineage'}:
            caller = sys._getframe(1)
            if (args or caller.f_code is not runner.selfchecks.__code__ or caller.f_lineno != 560
                    or caller.f_locals.get('old') is not old):
                raise RuntimeError('Equality correction is confined to frozen selfchecks:560')
            expected = caller.f_locals['expected']
            exact(changes['experiment_id'], expected.experiment_id, 'declared.experiment_id')
            exact(changes['lineage'], expected.lineage, 'declared.lineage')
            result = comparison(old, expected)
            events.append(result)
            return result
        return original(old, *args, **changes)
    return corrected


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def execute(args):
    from czsc_trader.research_tools.evidence import EvidenceRef
    from czsc_trader.research_tools.evaluation_access import EvaluationAccess
    from dataflows import Dataflows
    import concurrent.futures

    if not args.execute or digest(__file__) != args.source_sha256:
        raise ValueError('Explicit root execution and exact correction source SHA required')
    technical_ref = EvidenceRef.from_dict(read(args.technical_reference))
    technical = read(technical_ref.resolve(ROOT))
    method_ref = EvidenceRef.from_dict(read(args.method_reference))
    if (technical_ref.experiment.experiment_id != 'EX063_20261011'
            or technical_ref.experiment.strategy_id != 'S013'
            or technical['status'] != 'AUTHORIZED_EXACT_REQUEST_EQUALITY_RESUME'
            or technical['scope'] != 'B0_PREVIOUSLY_AUTHENTICATED_FEE_ONLY'
            or technical['method_reference'] != method_ref.to_dict() or method_ref.sha256 != METHOD_SHA
            or technical['runner_source_sha256'] != RUNNER_SHA or technical['source_sha256'] != args.source_sha256):
        raise ValueError('Exact prospective public correction/frozen method binding required')
    source_ref, proof_ref, failure_ref = (EvidenceRef.from_dict(technical[k]) for k in
        ('source_reference', 'pure_proof_reference', 'failure_reference'))
    for ref in (source_ref, proof_ref, failure_ref):
        if ref.experiment != technical_ref.experiment:
            raise ValueError('Technical materials must belong to original EX063')
        ref.resolve(ROOT)
    proof, failure = read(proof_ref.resolve(ROOT)), read(failure_ref.resolve(ROOT))
    if (source_ref.sha256 != args.source_sha256 or proof['status'] != 'PURE_EXACT_REQUEST_EQUALITY_PASS'
            or proof['source_sha256'] != args.source_sha256 or failure_ref.sha256 != FAILURE_SHA
            or failure['status'] != 'FAILED_TECHNICAL_SELFCHECK_REUSE'
            or failure['runner_source_sha256'] != RUNNER_SHA or failure['method_sha256'] != METHOD_SHA):
        raise ValueError('Original failure and pure strict equality proof must remain exact')
    source = FORMAL / 'src/runner.py'
    if digest(source) != RUNNER_SHA:
        raise ValueError('Frozen runner changed')
    sys.path.insert(0, str(source.parent))
    if 'runner' in sys.modules:
        raise ValueError('Existing runner module is not an explicit recovery import')
    spec = importlib.util.spec_from_file_location('runner', source)
    runner = importlib.util.module_from_spec(spec)
    sys.modules['runner'] = runner
    spec.loader.exec_module(runner)
    contract = runner.require_method(args.method_reference, args.work)
    state_path = contract.work / 'journal.json'
    # Use the frozen journal path contract, not an invented alternate state file.
    state = runner.journal(contract)
    analysis = runner.read(contract.work / 'analysis.json')
    if (analysis['selection']['fivecheck_labels'] != ['B0']
            or contract.method.get('baseline_fee_reuse') is None
            or state['status'] != 'STANDARD_ACCOUNTS_COMPLETE' or state['attempts'] != 4
            or len(state['accounts']) != 4 or any(a['status'] != 'COMPLETE' for a in state['accounts'].values())
            or (contract.work / 'selfchecks.json').exists()):
        raise ValueError('Only original completed four-native state and reused B0 fee may resume')
    before = read(state_path)
    events, forbidden_calls = [], []

    def forbidden(*unused, **kwargs):
        forbidden_calls.append('prohibited finance/preparation/spawn')
        raise AssertionError('Equality recovery cannot prepare/evaluate/spawn new accounts')

    with ExitStack() as stack:
        stack.enter_context(patch.object(runner, 'replace', adapter(runner, events)))
        for target, names in ((runner, ('execute_one', 'execute_batch')),
                              (Dataflows, ('prepare',)),
                              (EvaluationAccess, ('prepare', 'evaluate', 'evaluate_many')),
                              (concurrent.futures, ('ProcessPoolExecutor', 'ThreadPoolExecutor'))):
            for name in names:
                stack.enter_context(patch.object(target, name, forbidden))
        output = runner.selfchecks(contract)
    if len(events) != 1 or events[0].compared != 1 or events[0].mismatch or forbidden_calls or set(output) != {'B0'}:
        raise ValueError('Exact single comparison-only recovery contract not satisfied')
    exact(before, read(state_path), 'unchanged.journal')
    receipt = {'status': 'COMPLETE_EXACT_COMPARISON_SELFCHECK_RESUME',
        'technical_reference': technical_ref.to_dict(), 'source_sha256': args.source_sha256,
        'runner_source_sha256': RUNNER_SHA, 'method_sha256': METHOD_SHA, 'original_failure_sha256': FAILURE_SHA,
        'exact_rebinding_comparisons': 1, 'original_journal_unchanged': True,
        'new_account_evaluations': 0, 'preparations': 0, 'new_parameter_point_accounts': 0, 'new_fee_accounts': 0}
    receipt_path = contract.work / 'selfcheck_resume_receipt.json'
    if receipt_path.exists():
        raise ValueError('Immutable recovery receipt exists')
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(receipt, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', required=True)
    parser.add_argument('--source-sha256', required=True)
    parser.add_argument('--technical-reference', type=Path, required=True)
    parser.add_argument('--method-reference', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    execute(parser.parse_args())


if __name__ == '__main__':
    main()
