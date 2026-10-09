"""Actual FULL zero-margin equivalence control after prospective publication."""
from hashlib import sha256

from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence

from common import CACHE, EXPERIMENT, PROTOCOLS, RUNS, SOURCE, SOURCE_CALLS, cache_read, cache_write, context, read, request, write
from economic_equivalence import compare_evidence


def main():
    output = RUNS / 'price_margin_precheck.json'
    assert not output.exists(), 'Price-margin control already has an immutable record'
    plan = read(PROTOCOLS / 'price_margin_plan.json')
    refs = read(PROTOCOLS / 'price_margin_references.json')
    assert refs['plan'], 'Prospective public plan reference required before evaluation'
    for filename, expected in plan['source_files'].items():
        assert sha256((SOURCE / filename).read_bytes()).hexdigest() == expected
    control = plan['configurations'][0]
    assert control['candidate_id'] == 'C3200' and control['price_margin'] == 0.
    assert control['parameters']['bull']['momentum_min'] == .005
    original, original_result = cache_read(CACHE / 'C3107.pkl.gz')
    assert original_result.result_hash == plan['origin_result_hash']
    research = context(1)
    record = {'status': 'STARTED', 'origin_configuration': 'C3107', 'control': 'C3200',
              'origin_result_hash': original_result.result_hash,
              'plan_reference': refs['plan'], 'external_provider_access': False}
    try:
        bound = research.evaluation.prepare(request('C3200', control['parameters'], original.execution_data))
        computed = research.evaluation.evaluate(bound)
        cache_write(CACHE / 'C3200.pkl.gz', (bound, computed))
        record['control_result_hash'] = computed.result_hash
        record['comparison'] = compare_evidence(serialize_evaluation_evidence(original, original_result),
                                                serialize_evaluation_evidence(bound, computed))
        assert not SOURCE_CALLS
        record['status'] = 'PASS'
        write(output, record)
    except Exception as error:
        record.update(status='FAIL', error_type=type(error).__name__, error=str(error),
                      external_provider_access=bool(SOURCE_CALLS))
        write(output, record)
        publish_evidence(research, MaterialEvidenceWrite(EXPERIMENT,
            'cost-confirmation-price-margin-control-failure', output.read_bytes(), 'application/json', 'json'))
        raise
    print({'status': 'PASS', 'control': 'C3200', 'origin_configuration': 'C3107',
           'comparison': 'all signals, five ledgers, semantics and benchmark EXACT_EQUAL'}, flush=True)


if __name__ == '__main__':
    main()
