"""Immutable account checkpoint codec; no account computation."""
from .equity_evaluation import EquityArtifact, EquityEvaluationResult


def encode_result(result):
    if type(result) is EquityEvaluationResult and result.payload.get("schema") in {"equity-research/v3", "equity-research/v4"}:
        if len(result.artifacts) != 3:
            raise ValueError("account checkpoints require the complete immutable artifact closure")
        return {"kind": result.payload["schema"], "request_hash": result.request_hash,
            "result_hash": result.result_hash, "content": result.content.decode("utf-8"),
            "artifacts": [{"kind": item.kind, "sha256": item.sha256, "content": item.content.decode("utf-8")}
                          for item in result.artifacts]}
    raise TypeError("equity checkpoints require a V3 or V4 result")


def decode_result(payload, request_hash):
    if type(payload) is dict and payload.get("kind") in {"equity-research/v3", "equity-research/v4"}:
        if set(payload) != {"kind", "request_hash", "result_hash", "content", "artifacts"} or payload["request_hash"] != request_hash:
            raise ValueError("v3 checkpoint fields or request identity differ")
        artifacts = []
        for row in payload["artifacts"]:
            if type(row) is not dict or set(row) != {"kind", "sha256", "content"}:
                raise ValueError("v3 checkpoint artifact fields differ")
            item = EquityArtifact(row["kind"], row["content"].encode("utf-8"))
            if item.sha256 != row["sha256"]:
                raise ValueError("v3 checkpoint artifact bytes differ")
            artifacts.append(item)
        result = EquityEvaluationResult(request_hash, payload["content"].encode("utf-8"), tuple(artifacts))
        if result.payload.get("schema") != payload["kind"]:
            raise ValueError("checkpoint kind differs from account schema")
        if result.result_hash != payload["result_hash"] or len(artifacts) != 3:
            raise ValueError("v3 checkpoint result bytes or artifact closure differ")
        return result
    raise ValueError("equity checkpoints require V3 or V4 artifact closure")
