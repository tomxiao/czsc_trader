"""Apply the predeclared resource-allocation rule, without optimizing parameters."""
from statistics import mean
from common import WORK, NAMES, read, save, digest


def main():
    census = read(WORK/'others/census.json')
    sequence = census['temporal']['sequential']
    scores, selected = {}, []
    for name in NAMES:
        item = census['horizons']['6'][name]['nonoverlap']
        events = [r for r in sequence['pooled']['events'] if r['mechanism'] == name and r['net_return'] is not None]
        folds = [f for f in sequence['folds'] if f['choice'] == name]
        supported = sum(f['test_summary']['matched']['supported_target_count'] for f in folds)
        delta = sum(f['test_summary']['matched']['supported_target_count']*
            f['test_summary']['matched']['increment']['mean'] for f in folds
            if f['test_summary']['matched']['supported_target_count'])/supported if supported else None
        net = mean([r['net_return'] for r in events]) if events else None
        full_net, full_delta = item['summary']['net_mean'], item['ordinary']['net_increment']
        eligible = (full_net is not None and full_delta is not None and full_net > 0 and full_delta > 0
                    and net is not None and delta is not None and net > 0 and delta > 0
                    and supported == len(events) and supported > 0)
        scores[name] = {'full_pool_nonoverlap_net_mean': full_net, 'full_pool_nonoverlap_increment': full_delta,
            'sequential_selected_mature_events': len(events), 'sequential_matched_supported_events': supported,
            'sequential_net_mean': net, 'sequential_matched_increment': delta, 'eligible': eligible,
            'recent252': census['temporal']['last252_vs_earlier']['last252']['mechanisms'][name]['nonoverlap']}
        if eligible:
            selected.append(name)
    selected.sort(key=lambda n: (-scores[n]['sequential_matched_increment'], -scores[n]['full_pool_nonoverlap_increment'], n))
    save(WORK/'others/selection.json', {'schema': 's017-short-entry-selection/v1',
        'census_sha256': digest(WORK/'others/census.json'), 'protocol_sha256': digest(WORK/'protocols/design.md'),
        'source_sha256': digest(WORK/'src/choose_prototypes.py'), 'scores': scores, 'selected_mechanisms': selected[:2],
        'new_accounts_planned': 2*len(selected[:2]), 'scope': 'Predeclared research resource allocation; not new acceptance criteria or independent validation.'})
    print('SELECTED_MECHANISMS', selected[:2], flush=True)


if __name__ == '__main__':
    main()
