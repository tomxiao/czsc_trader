"""Real-account equivalence after introducing explicit context, not posthoc edits."""
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence
from common import CACHE, PROTOCOLS, RUNS, context, read, write, request, cache_read, cache_write
from economic_equivalence import compare_evidence
from economic_equivalence import _table_projection
from copy import deepcopy


def main():
    config = read(PROTOCOLS / 'context_plan.json')['configurations'][0]
    old, previous = cache_read(CACHE / 'C2018.pkl.gz')
    cached = CACHE / 'C2100.pkl.gz'
    if cached.exists():
        bound, result = cache_read(cached)
        assert dict(bound.strategy.payload['parameters']) == config['parameters']
    else:
        research = context(1)
        bound = research.evaluation.prepare(request('C2100', config['parameters'], old.execution_data))
        result = research.evaluation.evaluate(bound)
        cache_write(cached, (bound, result))
    before, after = serialize_evaluation_evidence(old, previous), serialize_evaluation_evidence(bound, result)
    # Investigated mismatch: the new expression adds one diagnostic decision
    # column. Preserve full evidence and the original failed strict comparison;
    # compare every shared field exactly, excluding only this named addition.
    shared = deepcopy(after)
    diagnostic = 'confirmation_exit_context'
    for run in shared['runs']:
        table = run['ledgers']['decisions']
        assert all(diagnostic in row for row in table['data'])
        table['schema']['fields'] = [field for field in table['schema']['fields']
                                      if field['name'] != diagnostic]
        del table['dtypes'][diagnostic]
        for row in table['data']:
            del row[diagnostic]
    try:
        proof = compare_evidence(before, shared)
    except AssertionError as exc:
        left, right = _table_projection(before['runs'][0]), _table_projection(after['runs'][0])
        differences = []
        for key in left:
            if left[key] != right[key]:
                if key in ('decisions', 'orders', 'fills', 'account_daily', 'trades', 'signals'):
                    lhs, rhs = left[key]['data'], right[key]['data']
                    first = next(((a,b) for a,b in zip(lhs,rhs,strict=True) if a != b), None)
                    differences.append({'table': key, 'rows': [len(lhs),len(rhs)], 'first_difference': first})
                else:
                    differences.append({'table': key})
        write(RUNS / 'context_precheck_failure.json', {'status': 'FAILED_COMPARISON', 'message': str(exc), 'differences': differences})
        raise
    write(RUNS / 'context_precheck.json', {'status': 'PASS', 'old_source_candidate': 'C2018',
        'new_source_candidate': 'C2100', 'comparison': proof, 'external_provider_access': False,
        'excluded_new_diagnostic_column': diagnostic,
        'original_strict_comparison': 'context_precheck_failure.json',
        'investigation': 'Only the added exit-context diagnostic differs; all shared signal, decision, order, fill, daily account, trade and benchmark fields remain exact.'})
    print({'context_account': 'EXACT_EQUAL'}, flush=True)


if __name__ == '__main__':
    main()
