"""Real candidate/package replay for tests whose responsibility is Goal A only."""

from strategy_manager import StrategyRegistry
from strategy_manager import freeze_contracts as f

from czsc_trader.application._inspection_candidate import _load_inspection_candidate
from czsc_trader.application.inspection_inputs import authenticate_execution
from czsc_trader.application.inspection_replay import compute
from czsc_trader.application.inspection_service import _copy_plan, _EvidenceStore, _package
from czsc_trader.application.research_evidence import read_decision
from czsc_trader.research_tools._evaluation_workers import pack


class _ReplayResult:
    """Receive the worker result in-process; leave all replay logic unchanged."""

    def __init__(self):
        self.result = None
        self.closed = False

    def send(self, result):
        assert self.result is None
        self.result = result

    def close(self):
        self.closed = True


def candidate_release_replay(context, request):
    """Build and verify the real package, then compare one actual replay pair.

    The canonical inspection roundtrip owns process scheduling, Goal B, report
    publication and freezing. These replay facts do not constitute an
    admission result or a passing inspection report.
    """
    assert len(request.replays) == 1
    registration = StrategyRegistry(context.research_registry_root).get_candidate_registration(request.candidate)
    store = _EvidenceStore(context, f.ResearchEvidenceOwner(
        request.candidate.strategy_id, request.experiment.experiment_id))
    origin = f.CandidateOrigin(registration.key, registration.content_sha256,
                               store.put_json(registration.to_dict()))
    plan = _copy_plan(context, request, registration, store, origin)
    workspace = context.root / ".tmp" / "goal-a-replay"
    _, verified = _package(context, plan, store, workspace / "repository",
                           read_decision(context.root, request.selection).subject)
    candidate = _load_inspection_candidate(context, request.candidate)
    replay = request.replays[0]
    authenticate_execution(request.research.data, replay, request.target.selection_data_cutoff)
    binding = request.research.data.binding
    result = _ReplayResult()
    compute(result, pack((binding.base_dir, binding.space, candidate, verified, replay,
                          workspace / "replay", request.protocol.float_tolerance)))
    assert result.closed and result.result is not None
    ok, facts = result.result
    assert ok, facts
    return facts
