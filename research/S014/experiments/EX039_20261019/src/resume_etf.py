"""One explicitly authorized ETF metadata-guard repair; preserve attempt one."""

from hashlib import sha256
import json
from pathlib import Path

import capture_sources as c
import prepare_etf


ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
OUT = EX / "others"
ATTEMPT = OUT / "etf_attempt2"
COPY_NAMES = (
    "etf_features.csv", "etf_features.json", "etf_combined_source.csv",
    "etf_share_source.csv", "etf_price_source.csv",
    "etf_share_fetch.json", "etf_price_fetch.json",
)
PRESERVE_NAMES = (
    "etf_preparation_request.json", "etf_preparation.json", "etf_source_receipt.json",
)


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def relative(path):
    return path.relative_to(ROOT).as_posix()


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def check_repair_lock():
    from czsc_trader.research_tools import EvidenceRef

    lock = read(EX / "protocols/published_etf_repair.json")
    if not isinstance(lock, dict) or not lock:
        raise ValueError("Nonempty published ETF repair lock required")
    if relative(Path(__file__).resolve()) not in lock:
        raise ValueError("ETF repair implementation must be in its published lock")
    for name, value in lock.items():
        local = ROOT / name
        if local.is_absolute() and not local.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError("Repair lock outside repository")
        ref = EvidenceRef.from_dict(value)
        if digest(local) != ref.sha256 or digest(ref.resolve(ROOT)) != ref.sha256:
            raise ValueError("Published repair reference/hash mismatch")
    return lock


def copy_new(source, target):
    content = source.read_bytes()
    with target.open("xb") as stream:
        stream.write(content)
    if source.read_bytes() != target.read_bytes():
        raise ValueError("Byte-copy verification failed")
    return {"source": relative(source), "target": relative(target),
            "bytes": len(content), "sha256": digest(target)}


def main():
    repair_lock = check_repair_lock()
    c.locks()
    if ATTEMPT.exists() or (OUT / "etf_successful_preparation.json").exists():
        raise FileExistsError("Explicit repair already exists; automatic retry prohibited")
    if (OUT / "etfrepair_source_receipt.json").exists():
        raise FileExistsError("Repair source receipt already exists")
    if any((OUT / name).exists() for name in COPY_NAMES):
        raise FileExistsError("Canonical ETF success outputs already exist")
    old_receipt = read(OUT / "etf_source_receipt.json")
    if old_receipt["http_reservations"] != 2 or old_receipt["cap"] != 24:
        raise ValueError("Expected original ETF budget 24 less two consumed HTTP calls")
    if len(old_receipt["results"]) != 2 or any(row["status"] != "SUCCESS" for row in old_receipt["results"]):
        raise ValueError("Original numerical source receipts must remain successful")
    originals = {name: digest(OUT / name) for name in PRESERVE_NAMES}
    ATTEMPT.mkdir()
    event_copy = copy_new(OUT / "etf_events.json", ATTEMPT / "etf_events.json")
    original_out, original_allowed = prepare_etf.OUT, c.ALLOWED
    prepare_etf.OUT = ATTEMPT
    c.ALLOWED = original_allowed | {"fund_basic"}
    try:
        with c.Capture("etfrepair", 22):
            result = prepare_etf.prepare()
    finally:
        prepare_etf.OUT = original_out
        c.ALLOWED = original_allowed
        if any(digest(OUT / name) != value for name, value in originals.items()):
            raise ValueError("Original failed-attempt evidence changed")
    prepared = read(ATTEMPT / "etf_preparation.json")
    if prepared["status"] != "READY" or not prepared["reference"]:
        raise ValueError("Repair did not produce a READY formal preparation")
    feature_receipt = read(ATTEMPT / "etf_features.json")
    if feature_receipt["prepared"] != prepared["reference"]:
        raise ValueError("Feature/preparation reference mismatch")
    copies = [copy_new(ATTEMPT / name, OUT / name) for name in COPY_NAMES]
    pointer = {
        "status": "READY_CONDITIONAL_RAW_PROXY", "attempt": relative(ATTEMPT),
        "reference": prepared["reference"], "prepared": prepared["reference"],
        "requests": feature_receipt["requests"],
        "preparation": {"path": relative(ATTEMPT / "etf_preparation.json"),
                        "sha256": digest(ATTEMPT / "etf_preparation.json")},
        "source_receipt": {"path": relative(OUT / "etfrepair_source_receipt.json"),
                           "sha256": digest(OUT / "etfrepair_source_receipt.json")},
        "implementation": {"path": relative(Path(__file__).resolve()), "sha256": digest(Path(__file__))},
        "repair_lock": {"path": relative(EX / "protocols/published_etf_repair.json"),
                        "sha256": digest(EX / "protocols/published_etf_repair.json"),
                        "references": repair_lock},
        "original_attempt_preserved": originals, "event_copy": event_copy,
        "verified_canonical_copies": copies,
        "budget": {"original_http_used": 2, "repair_cap": 22, "total_etf_cap": 24},
        "repair": "Only add same-provider fund_basic listing metadata to transport guard; fixed numerical sources, method and original source/prepare code unchanged",
        "automatic_retry": False, "fits": 0, "accounts": 0,
    }
    c.write(OUT / "etf_successful_preparation.json", pointer)
    print(json.dumps({"status": "READY_CONDITIONAL_RAW_PROXY", "attempt": relative(ATTEMPT),
                      "result": prepare_etf.plain(result)}, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status": "FAILED", "error_type": type(error).__name__,
                          "detail": "Exception text suppressed; preserve repair attempt and sanitized source receipts"}), flush=True)
        raise SystemExit(1) from None
