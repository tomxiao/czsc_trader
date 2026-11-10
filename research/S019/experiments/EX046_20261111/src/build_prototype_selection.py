"""Turn reviewed exact account selections into typed stage-two delivery entries."""
import argparse
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader import research_tools as d
from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence
from dataflows import ProviderConfig
from strategy_manager import CandidateKey

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'research/RSCH_AGENT.md').is_file())
BATCH = ROOT/'research/S019'


def read(path):
    return json.loads(path.read_bytes())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--recipe', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists()
    recipe = read(args.recipe)
    repo = RepositoryContext.discover(ROOT)
    batch = d.ResearchBatchRef('S019')
    context = create_research_context(repo, batch, providers=ProviderConfig(bindings={}, equity_bindings={}))
    exp = d.ExperimentRef('S019', recipe['owner_experiment'])
    prior = d.DeliveryReference.from_dict(read(BATCH/'deliveries/PROTOTYPES/2/receipt.json')['reference'])
    materials = {}

    def material(name):
        path = (ROOT/name).resolve()
        assert path.is_relative_to(BATCH) and path.is_file()
        if name not in materials:
            ext = path.suffix[1:]
            materials[name] = publish_evidence(context, d.MaterialEvidenceWrite(exp,
                f"mechanism-close-{len(materials):02}", path.read_bytes(),
                {'py': 'text/x-python', 'json': 'application/json', 'md': 'text/markdown'}[ext], ext))
        return materials[name]

    entries, components, evidence, account_files = [], [], {}, {}
    for item in recipe['prototypes']:
        ref = d.EvidenceRef.from_dict(read(ROOT/item['account']))
        raw = ref.resolve(ROOT).read_bytes()
        assert sha256(raw).hexdigest() == ref.sha256
        head = json.loads(raw)
        definition = read(ROOT/item['definition'])
        assert head['request']['candidate_definition'] == definition
        cid = head['request']['candidate_id']
        assert cid == item['candidate_id']
        rule = d.ExperimentDefinitionRef(material(item['definition']), definition['entrypoint'])
        protocol, result, source = (material(item[k]) for k in ('protocol', 'result', 'source'))
        component_id = 'F_'+cid
        components.append(d.ComponentEntry(component_id, rule, item['role'], item['hypothesis'],
            '30分钟决定、5日持有上限', item['comparison_basis'],
            '只使用完成行情及确认持仓状态', 'HFQ整数单位、当前权益目标仓位与日末MDD',
            'MU已见2022-01-03至2026-10-30', item['judgment'],
            (d.ComponentTestResult('mechanism_'+cid, ref.experiment.experiment_id, protocol,
                d.ComponentTestStatus(item['test_status']), item['judgment'], (result,)),)))
        entries.append(d.PrototypeEntry(cid,
            d.CandidateIdentityRef(CandidateKey('S019', cid), head['request']['content_sha256']), rule,
            item['hypothesis'], (d.PrototypeComponentUse(component_id, item['role'], item['interaction']),),
            (d.EvaluationEvidenceRef(ref, (head['evaluation_id'],)),),
            d.PrototypeDisposition(item['disposition']), item['judgment'], tuple(item['limitations']),
            item['next_action'], (source, result, protocol),
            sources=(d.PrototypeReference(prior, 'C0080'),)))
        evidence[cid] = (protocol, result)
        account_files[ref.sha256] = item['account']
    comparisons = [d.PrototypeComparison(item['subject']+'_vs_'+item['control'], item['subject'],
        item['control'], item['question'], evidence[item['subject']][0],
        tuple({r.sha256: r for r in (evidence[item['subject']][1], evidence[item['control']][1])}.values()), item['conclusion'])
        for item in recipe['comparisons']]
    output = {key: recipe[key] for key in ('owner_experiment', 'completed_experiments',
        'completed_mechanism_experiments', 'stage_report', 'conclusion')}
    output.update(stage='STAGE_TWO', prototypes=[x.to_dict() for x in entries],
        components=[x.to_dict() for x in components], comparisons=[x.to_dict() for x in comparisons],
        account_reference_files=account_files)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('SELECTION_BUILT', len(entries), len(comparisons))


if __name__ == '__main__':
    main()
