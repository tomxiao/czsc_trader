"""Explicitly requeue UNKNOWN configurations without rewriting prior trials."""
import json
import argparse
from common import RUNS, save, context, PROTOCOLS
from search import configuration_hash
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--name', default='hfq_replay_completion')
    parser.add_argument('--filename', default='replay_completion_plan.json')
    parser.add_argument('--workers', type=int, choices=(4, 8), default=8)
    parser.add_argument('--expected', type=int, default=38)
    parser.add_argument('--expected-retries', type=int, default=8)
    args = parser.parse_args()
    original = json.loads((PROTOCOLS / 'replay_plan.json').read_text(encoding='utf-8'))
    rows = json.loads((RUNS / 'search_results.json').read_text(encoding='utf-8'))['rows']
    successes = {r['config_hash'] for r in rows if r['status'] == 'SUCCEEDED'}
    unsuccessful = {r['config_hash']: r for r in rows if r['status'] != 'SUCCEEDED'}
    remaining = []
    for config in original['configurations']:
        digest = configuration_hash(config['parameters'])
        if digest in successes:
            continue
        item = dict(config)
        if digest in unsuccessful:
            item['explicit_retry_of'] = unsuccessful[digest]['candidate_id']
        remaining.append(item)
    assert len(remaining) == args.expected
    retries = sum('explicit_retry_of' in r for r in remaining)
    assert retries == args.expected_retries
    plan = {'name': args.name,
            'reason': f'Windows spawn管道WinError6导致UNKNOWN；原状态与Optuna失败trial保留，新队列显式重试并补齐原计划未执行项。每个父进程只发起一批{args.workers}个工作进程，保持完整评价，不静默重试。',
            'resource_decision': '8并发在两个新父进程中均遇到句柄错误，明确改为4并发' if args.workers == 4 else '继续8并发，每个新父进程一批',
            'max_workers': args.workers,
            'configuration_count': len(remaining), 'explicit_retries': retries,
            'unattempted': len(remaining) - retries,
            'configurations': remaining}
    save(args.filename, plan, directory=PROTOCOLS)
    ref = publish_evidence(context(), MaterialEvidenceWrite(ExperimentRef('S013', 'EX004_20261007'),
        args.name + '-explicit-plan', (PROTOCOLS / args.filename).read_bytes(),
        'application/json', 'json'))
    save(args.filename.replace('.json', '_reference.json'), ref.to_dict(), directory=PROTOCOLS)
    print(json.dumps({'completion': ref.to_dict(), 'retry_ids': [r['explicit_retry_of'] for r in remaining if 'explicit_retry_of' in r]}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
