"""Declare a research-only observation definition change, preserving trading code."""
from common import ROOT, SOURCE, FROZEN_SOURCE, PROTOCOLS, RUNS, DEPENDENCIES
from common import read, write, fingerprint, context, candidate, material


def main():
    assert not (PROTOCOLS/'adapted_plan.json').exists()
    original = read(ROOT/'strategies/S007/versions/v1.json')['strategy_payload']
    copied = []
    for name in original['runtime']['source_files']:
        old, new = FROZEN_SOURCE/name, SOURCE/name
        new.parent.mkdir(parents=True, exist_ok=True)
        new.write_bytes(old.read_bytes())
        assert fingerprint(old)['sha256'] == fingerprint(new)['sha256']
        copied.append({'original': fingerprint(old), 'research_copy': fingerprint(new)})
    (SOURCE/'strategies/__init__.py').write_text('', encoding='utf-8')
    adapter = SOURCE/'strategies/s007_diagnostic.py'
    adapter.write_text('''"""Research observation metadata; inherited trading and inputs are unmodified."""
from dataclasses import replace
from strategy_runtime import ObservationDefinition
from .s007_v1 import S007V1


class S007Diagnostic(S007V1):
    def __init__(self, parameters):
        super().__init__(parameters)
        self._definition = replace(self._definition, observation=ObservationDefinition((), ()))
''', encoding='utf-8', newline='\n')
    research = context(4)
    identity = research.runtime.identify(candidate(), dependencies=DEPENDENCIES)
    plan = read(PROTOCOLS/'plan.json')
    plan['version'] = 'S007-four-diagnostics-v2-observation-metadata'
    plan['supersedes_plan'] = read(PROTOCOLS/'plan_reference.json')
    plan['center']['source_sha256'] = identity.source_sha256
    plan['center']['content_sha256'] = identity.content_sha256
    for case in plan['cases']:
        child = research.runtime.identify(candidate(case['candidate_id'], case['parameters']), dependencies=DEPENDENCIES)
        case['source_sha256'] = child.source_sha256
        case['content_sha256'] = child.content_sha256
    failure = read(RUNS/'center_technical_failure.json')
    plan['technical_correction'] = {
        'original_failure': failure,
        'diagnosis': 'SRT skips NaN fields in initial execution-plan evidence; original S007 observation definition requires base_score before normalization has sufficient observations.',
        'method': 'Explicit research subclass replaces only display-series metadata with an empty observation definition. All calculate_history, calendar/scope, decision, execution, inputs and parameters are inherited unchanged.',
        'identity': 'Different research implementation hash declared explicitly; no registration, frozen rewrite, deployment or platform change.',
        'equivalence_requirement': 'Original economic signals, decisions, limit plans, fills, cash, quantity, equity and cycles must be checked before using perturbations.',
        'points_and_scales': 'Original eight complete parameters/signs/scales unchanged; no successful S007 evaluation observed before this declaration.',
        'source_copies': copied, 'adapter': fingerprint(adapter)}
    write(PROTOCOLS/'adapted_plan.json', plan)
    ref = material('four-diagnostics-adapted-prospective-plan', PROTOCOLS/'adapted_plan.json')
    write(PROTOCOLS/'adapted_plan_reference.json', ref.to_dict())
    print({'adapted_plan': ref.to_dict(), 'source_sha256': identity.source_sha256}, flush=True)


if __name__ == '__main__':
    main()
