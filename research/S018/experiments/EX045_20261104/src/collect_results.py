"""Read already published accounts; no recomputation or original-evidence edits."""
from pathlib import Path
from hashlib import sha256
import json
from run import read, save, metrics, materialized, ROOT, FAMILY
from czsc_trader import research_tools as d
from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence
from dataflows import ProviderConfig
from strategy_runtime import ExecutionResources
from strategy_runtime.equity_definition import execution_spec_from_dict
from czsc_trader.research_tools.equity_replay import materialize_equity


def economic(rows):
    return [{k:v for k,v in row.items() if not k.endswith('_id')} for row in rows]


def main():
    work = Path(__file__).resolve().parents[1]
    exp = d.ExperimentRef('S018', work.name)
    output = work/'others'
    baseline = read(FAMILY/'experiments/EX025_20261104/others/results.json')['accounts']['C6300']
    spec = execution_spec_from_dict(baseline['definition']['execution_spec'])
    context = create_research_context(RepositoryContext.discover(ROOT), d.ResearchBatchRef('S018'),
        providers=ProviderConfig(bindings={}, equity_bindings={}), execution_spec=spec, resources=ExecutionResources(4,1,17))
    refs = [d.EvidenceRef.from_dict(baseline['account_ref'])]
    old = materialized(refs[0])['runs']['candidate']
    directory = FAMILY/'assets/evidence'/exp.experiment_id
    accounts = {}
    for path in directory.glob('*.json'):
        raw = path.read_bytes()
        value = json.loads(raw)
        if value.get('schema') != 'equity-research/v4':
            continue
        assert sha256(raw).hexdigest() == path.stem
        key = value['request']['candidate_id']
        ref = d.EvidenceRef(exp, path.name, path.stem, 'application/json', key, 'equity_research', 4)
        assert ref.resolve(ROOT) == path.resolve()
        refs.append(ref)
        payload = materialize_equity(raw, lambda r: (directory/(r['sha256']+'.json')).read_bytes()).payload
        run = payload['runs']['candidate']
        x, y = metrics(run), metrics(payload['runs']['buy_hold'])
        assert all(row['observed_through'] < row['execution_start'] for row in run['decisions'])
        definition = value['request']['candidate_definition']
        parameters = json.loads(definition['parameters_json'])
        gates = dict(calmar=x['calmar'] is not None and x['calmar'] >= 1.5*y['calmar'],
            dd_absolute=x['dd'] <= .25, dd_relative=x['dd'] <= .8*y['dd'], median=x['median'] >= 6, coverage=x['coverage'] >= .9)
        accounts[key] = dict(config=parameters, candidate=x, gates=gates, definition=definition, account_ref=ref.to_dict())
        if parameters['entry'] == 'raw_control':
            check = {name:economic(run[name]) == economic(old[name]) for name in ('fills','account_daily','trades','actions')}
            assert all(check.values()), check
            assert run['metrics'] == old['metrics']
            save(output/'control_check.json', {'C6300_economic_comparison':check, 'metrics':'EXACT_MATCH',
                'excluded_fields':'Only lineage fields ending _id; different candidate/input identities necessarily have distinct decision IDs.',
                'postprocessing_note':'Initial run asserted full dictionary equality including decision_id after all 10 accounts were published. This collector compares all economic fields without recomputation.'})
    assert len(accounts) == 10
    accounts = dict(sorted(accounts.items()))
    save(output/'results.json', {'accounts':accounts, 'benchmark':y, 'workload':{'completed_new_accounts':len(accounts),'workers':4,
        'statistics':'Session statistics not saved because initial post-publication lineage comparison stopped; execution status and published roots certify completed accounts.'}})
    for name in ('protocol','results','data_preparation','data_checks','execution_status','control_check'):
        path = output/(name+'.json')
        refs.append(publish_evidence(context, d.MaterialEvidenceWrite(exp, name, path.read_bytes(), 'application/json', 'json')))
    save(output/'evidence_refs.json', [r.to_dict() for r in refs])
    for key, item in accounts.items():
        print(key, item['config'], {k:round(v,5) for k,v in item['candidate'].items() if isinstance(v,(int,float))}, item['gates'], flush=True)


if __name__ == '__main__':
    main()
