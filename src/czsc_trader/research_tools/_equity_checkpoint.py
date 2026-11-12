"""Account checkpoint references; artifact bytes are stored once by content hash."""
from .equity_evaluation import EQUITY_EVIDENCE_SCHEMAS, EquityArtifact, EquityEvaluationResult
from .equity_replay import equity_artifact_fields


def encode_result(result):
    if type(result) is EquityEvaluationResult:
        header = result.payload
        if len(result.artifacts) != len(equity_artifact_fields(header)):
            raise ValueError("account checkpoints require the complete immutable artifact closure")
        return {"schema_version": 3, "kind": header["schema"], "request_hash": result.request_hash,
            "result_hash": result.result_hash,
            "artifact_refs": [{"kind": item.kind, "sha256": item.sha256} for item in result.artifacts]}
    raise TypeError("equity checkpoints require an equity result")


def decode_result(payload, request_hash, load_artifact=None, load_content=None):
    if type(payload) is dict and payload.get("kind") in EQUITY_EVIDENCE_SCHEMAS:
        if (set(payload) != {"schema_version", "kind", "request_hash", "result_hash", "artifact_refs"}
                or type(payload["schema_version"]) is not int or payload["schema_version"] != 3
                or payload["request_hash"] != request_hash):
            raise ValueError("equity checkpoint fields or request identity differ")
        expected_count = 3 if payload["kind"] == "equity-research/v4" else 2
        if type(payload["artifact_refs"]) is not list or len(payload["artifact_refs"]) != expected_count:
            raise ValueError("equity checkpoint requires the complete artifact closure")
        if not callable(load_artifact) or not callable(load_content):
            raise TypeError("equity checkpoint requires explicit artifact and header resolvers")
        artifacts = []
        for row in payload["artifact_refs"]:
            if type(row) is not dict or set(row) != {"kind", "sha256"}:
                raise ValueError("equity checkpoint artifact reference fields differ")
            item = load_artifact(row["kind"], row["sha256"])
            if type(item) is not EquityArtifact or item.kind != row["kind"] or item.sha256 != row["sha256"]:
                raise ValueError("equity checkpoint artifact identity differs")
            artifacts.append(item)
        result = EquityEvaluationResult(request_hash, load_content(payload["result_hash"]), tuple(artifacts))
        header = result.payload
        if header.get("schema") != payload["kind"] or header.get('request_hash') != request_hash:
            raise ValueError("checkpoint kind differs from account schema")
        if result.result_hash != payload["result_hash"]:
            raise ValueError("equity checkpoint result bytes or artifact closure differ")
        if tuple(header[name] for name, _ in equity_artifact_fields(header)) != tuple(
                item.reference() for item in artifacts):
            raise ValueError('equity checkpoint artifact references differ from the result')
        return result
    raise ValueError("equity checkpoints require a supported artifact closure")
