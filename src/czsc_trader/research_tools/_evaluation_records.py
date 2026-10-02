"""Per-call evidence persistence, without search lifecycle or scheduling."""

from dataclasses import dataclass
import json
from uuid import uuid4
from math import isfinite

from research_experiment import EvaluationRecord, ExperimentArtifact, ExperimentWorkspace


def _signal_table(value):
    table = json.loads(
        value.to_json(orient="table", date_format="iso", date_unit="ns", index=False)
    )
    # pandas JSON limits doubles to 15 digits. Keep Python float values so the
    # enclosing JSON writer preserves the full binary64 round-trip precision.
    for encoded, original in zip(table["data"], value.to_dict(orient="records")):
        for name, cell in original.items():
            if isinstance(cell, float) and isfinite(cell):
                encoded[name] = cell
    return table


class EvaluationExecutionError(RuntimeError):
    def __init__(self, message: str, *, attempt_id: str, error_code: str):
        super().__init__(message)
        self.attempt_id = attempt_id
        self.error_code = error_code


@dataclass
class _CallEvidence:
    workspace: ExperimentWorkspace
    attempt_id: str

    def write(self, name: str, payload: dict, kind: str) -> ExperimentArtifact:
        relative = f"evaluations/{self.attempt_id}/{name}.json"
        target = self.workspace.path(relative)
        if target.exists():
            raise FileExistsError("evaluation evidence already exists")
        temporary = self.workspace.path(f".tmp/evaluation-records/{uuid4().hex}.json")
        temporary.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
            ),
            encoding="utf-8", newline="\n",
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary.replace(target)
        return self.workspace.register_artifact(relative, kind)

    def record(self, record: EvaluationRecord) -> ExperimentArtifact:
        name = "started" if record.status.value == "STARTED" else "record"
        return self.write(name, record.to_dict(), "evaluation_record")

    def result(self, result, request) -> ExperimentArtifact:
        from dataclasses import replace
        from .assessment import build_assessment_evidence
        from .evaluation import _request_identity_payload
        from ..backtesting.audit_adapter import build_replay_evidence
        from ..backtesting.metrics import calculate_metrics

        assessment = build_assessment_evidence(request, replace(result, attempt_id=self.attempt_id))

        def frame(value):
            return json.loads(
                value.to_json(
                    orient="table",
                    date_format="iso",
                    date_unit="ns",
                    double_precision=15,
                    index=False,
                )
            )

        runs = []
        for run in result.runs:
            item = {
                "identity": run.identity.to_dict(),
                "replay_evidence": build_replay_evidence(
                    run.signals,
                    request.execution_data,
                    run.execution,
                    request.initial_cash,
                    calculate_metrics(run.execution, request.initial_cash),
                ).to_dict(),
                "window_id": run.window_id,
                "scenario_id": run.scenario_id,
                "candidate_id": run.candidate_id,
                "signals": _signal_table(run.signals.decisions),
                "signal_dtypes": {
                    name: str(dtype) for name, dtype in run.signals.decisions.dtypes.items()
                },
                "signal_data_identity": run.signals.data_identity,
                "signal_support": run.signals.support_data,
                "signal_window": {
                    "calculation_start": run.signals.calculation_start.isoformat(),
                    "evaluation_start": run.signals.evaluation_start.isoformat(),
                    "evaluation_end": run.signals.evaluation_end.isoformat(),
                },
                "observation": run.observation.to_dict(),
                "ledgers": {
                    name: frame(getattr(run.execution, name))
                    for name in ("decisions", "orders", "fills", "account_daily", "trades")
                },
                "buyhold": None
                if run.buyhold is None
                else {
                    "account_daily": frame(run.buyhold.account_daily),
                    "orders": frame(run.buyhold.orders),
                    "metrics": run.buyhold.metrics,
                    "benchmark": run.buyhold.benchmark.to_dict(),
                    "execution": None if run.buyhold.execution is None else {
                        name: frame(getattr(run.buyhold.execution, name))
                        for name in ("decisions", "orders", "fills", "account_daily", "trades")
                    },
                },
            }
            runs.append(item)
        return self.write(
            "result",
            {
                "schema_version": 4,
                "request_identity": _request_identity_payload(
                    request, result.runs[0].identity.content_sha256, result.runtime_binding_hash
                ),
                "request_hash": result.request_hash,
                "result_hash": result.result_hash,
                "runs": runs,
                "assessment_evidence": [item.to_dict() for item in assessment],
            },
            "evaluation_result",
        )
