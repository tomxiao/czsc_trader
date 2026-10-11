"""EX062 orchestration spies and fixture transport only; no native financial I/O."""
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
from types import MappingProxyType, SimpleNamespace
from unittest.mock import patch

import driver


def run():
    checks = []
    def check(label, condition):
        if not condition:
            raise AssertionError(label)
        checks.append(label)
    root = Path(__file__).resolve().parent
    work = root / "pure-transport" / ("run-" + uuid4().hex[:12])
    work.mkdir(parents=True, exist_ok=True)
    method = driver.method_draft()
    check("draft never execution-frozen", method["status"] == "DRAFT_NOT_FROZEN")
    check("nine centers", len(method["queue"]) == 9)
    check("262 collision-checked reserved four-digit IDs", len(method["candidate_reservation"]) == 262 and all(len(identifier) == 5 for identifier in method["candidate_reservation"]))
    probe = driver.read(root / "duplicate_probe.json")
    check("297 roles and294 unique", probe["unique"] == 294 and len(probe["duplicates"]) == 3)
    check("known binding overlap exact", ["P00:P21", "P20:P00"] in probe["duplicates"])
    check("C0632 is reserved but declared unused", "C0632" in method["candidate_reservation"] and "C0632 unused" in method["reuse_mapping"]["binding_duplicate"])
    fixture = work / "mapping.pkl.gz"
    driver.cache_write(fixture, {"data": MappingProxyType({"finite": 13})})
    check("local stable pickle", dict(driver.cache_read(fixture)["data"]) == {"finite": 13})
    code = "import sys;from pathlib import Path;sys.path.insert(0," + repr(str(root)) + ");import driver;v=driver.cache_read(Path(" + repr(str(fixture)) + "));assert dict(v['data'])=={'finite':13};print('STABLE_MODULE_PASS')"
    child = subprocess.run([sys.executable, "-B", "-c", code], check=True, capture_output=True, text=True)
    check("pickle readable in independent interpreter", "STABLE_MODULE_PASS" in child.stdout)
    class EvaluationSpy:
        def __init__(self, failure=False):
            self.calls = []
            self.failure = failure
        def evaluate(self, request):
            raise AssertionError("Serial evaluate forbidden in parameter chunk")
        def evaluate_many(self, requests):
            self.calls.append(requests)
            return tuple(SimpleNamespace(status=SimpleNamespace(value="FAILED" if self.failure and i == 3 else "SUCCEEDED"),
                  result={"fixture_result": i}, error=SimpleNamespace(code="FIXTURE", message="preserved")) for i, _ in enumerate(requests))
    def fake_retain(ctx, request, label, state):
        return (request, {"fixture": label}), {"fixture_ref": label}
    children = tuple({"fixture_request": index} for index in range(32))
    state = {"status": "DECLARED", "evaluation_attempts": 0, "new_successful_business": 0, "failure": None}
    with patch.object(driver, "WORK", work / "batch"), patch.object(driver, "evaluate_and_retain", fake_retain):
        spy = EvaluationSpy()
        points, refs = driver.evaluate_point_chunk(SimpleNamespace(evaluation=spy), children, 0, 0, state)
        check("one actual scheduling call per8 pending", len(spy.calls) == 1 and len(spy.calls[0]) == 8 and len(points) == len(refs) == 8)
        check("eight successes counted", state["new_successful_business"] == 8)
        driver.evaluate_point_chunk(SimpleNamespace(evaluation=spy), children, 0, 0, state)
        check("resume cached chunk never evaluated", len(spy.calls) == 1)
    state = {"status": "DECLARED", "evaluation_attempts": 0, "new_successful_business": 0, "failure": None}
    with patch.object(driver, "WORK", work / "failed-batch"), patch.object(driver, "evaluate_and_retain", fake_retain):
        spy = EvaluationSpy(failure=True)
        try:
            driver.evaluate_point_chunk(SimpleNamespace(evaluation=spy), children, 0, 0, state)
        except RuntimeError:
            pass
        else:
            raise AssertionError("Failed chunk cannot become PASS")
        failed = driver.read(driver.WORK / "checkpoint.json")
        check("failure fully persisted", failed["failure"]["failures"][0]["label"] == "center-00-point-03" and failed["new_successful_business"] == 7)
    guarded = work / "guarded"
    guarded.mkdir(parents=True, exist_ok=True)
    driver.write(guarded / "checkpoint.json", {"failure": "retained"})
    with patch.object(driver, "WORK", guarded), patch.object(driver.draft, "require_frozen_method", lambda ref: {}), patch.object(driver.draft, "existing_only_context", side_effect=AssertionError("Context must not start")):
        try:
            driver.declare(None)
        except RuntimeError:
            check("declaration cannot overwrite success/state", True)
        else:
            raise AssertionError("Existing declaration overwritten")
        try:
            driver.preflight(None)
        except RuntimeError:
            check("preflight rejects prior failure before context", True)
        else:
            raise AssertionError("Failed preflight rerun")
    output = {"status": "PURE_PASS", "checks": len(checks), "check_names": checks,
              "new_account_evaluations": 0, "real_preparations": 0, "publications": 0,
              "native_account_reads": 0, "market_reads": 0, "provider_calls": 0,
              "fixture_evaluate_many_calls": 2, "source_hashes": {
                  path.name: sha256(path.read_bytes()).hexdigest() for path in
                  (Path(driver.__file__), Path(driver.draft.__file__), Path(__file__))}}
    driver.write(root / "driver_checks.json", output)
    print(json.dumps({"status": "PURE_PASS", "checks": len(checks)}))


if __name__ == "__main__":
    run()
