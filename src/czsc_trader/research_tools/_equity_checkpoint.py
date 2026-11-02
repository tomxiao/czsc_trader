"""Account checkpoint references; artifact bytes are stored once by content hash."""
from .equity_evaluation import EquityArtifact, EquityEvaluationResult


def encode_result(result):
    if type(result) is EquityEvaluationResult and result.payload.get("schema") == "equity-research/v4":
        if len(result.artifacts) != 3:
            raise ValueError("account checkpoints require the complete immutable artifact closure")
        return {"schema_version": 2, "kind": result.payload["schema"], "request_hash": result.request_hash,
            "result_hash": result.result_hash, "content": result.content.decode("utf-8"),
            "artifact_refs": [{"kind": item.kind, "sha256": item.sha256} for item in result.artifacts]}
    raise TypeError("equity checkpoints require a V4 result")


def decode_result(payload, request_hash, load_artifact=None):
    if type(payload) is dict and payload.get("kind") == "equity-research/v4":
        if (set(payload) != {"schema_version", "kind", "request_hash", "result_hash", "content", "artifact_refs"}
                or type(payload["schema_version"]) is not int or payload["schema_version"] != 2
                or payload["request_hash"] != request_hash):
            raise ValueError("equity checkpoint fields or request identity differ")
        if type(payload["artifact_refs"]) is not list or len(payload["artifact_refs"]) != 3:
            raise ValueError("equity checkpoint requires the complete artifact closure")
        if not callable(load_artifact):
            raise TypeError("equity checkpoint requires an explicit artifact resolver")
        artifacts = []
        for row in payload["artifact_refs"]:
            if type(row) is not dict or set(row) != {"kind", "sha256"}:
                raise ValueError("equity checkpoint artifact reference fields differ")
            item = load_artifact(row["kind"], row["sha256"])
            if type(item) is not EquityArtifact or item.kind != row["kind"] or item.sha256 != row["sha256"]:
                raise ValueError("equity checkpoint artifact identity differs")
            artifacts.append(item)
        result = EquityEvaluationResult(request_hash, payload["content"].encode("utf-8"), tuple(artifacts))
        if result.payload.get("schema") != payload["kind"]:
            raise ValueError("checkpoint kind differs from account schema")
        if result.result_hash != payload["result_hash"] or len(artifacts) != 3:
            raise ValueError("equity checkpoint result bytes or artifact closure differ")
        return result
    raise ValueError("equity checkpoints require V4 artifact closure")
