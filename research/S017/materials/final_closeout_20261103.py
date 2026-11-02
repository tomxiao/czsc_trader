"""Publish the authorized S017 stop decision and verify this bounded closeout."""
# ruff: noqa: E402
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[3]
WORK = ROOT / "research/S017"
SCRATCH = ROOT / ".tmp/s017-final-closeout"
SCRATCH.mkdir(parents=True, exist_ok=True)
os.environ["TMP"] = os.environ["TEMP"] = str(SCRATCH)
sys.pycache_prefix = str(SCRATCH / "pycache")

from hashlib import sha256
import json
import re
import xml.etree.ElementTree as ET
from czsc_trader import research_tools as d
from czsc_trader.application import (RepositoryContext, create_research_context, get_research_overview,
    load_candidate, publish_evidence, update_research_intent, ResearchIntentUpdate, validate_experiment)
from dataflows import ProviderConfig
from strategy_manager import CandidateKey, ResearchState
from strategy_runtime import ExecutionResources


def read(path):
    return json.loads(path.read_bytes())


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def main():
    repository = RepositoryContext.discover(ROOT)
    batch = d.ResearchBatchRef("S017")
    experiment = d.ExperimentRef("S017", "EX077_20261102")
    candidate = load_candidate(repository, CandidateKey("S017", "C0342"))
    research = create_research_context(repository, batch, providers=ProviderConfig(bindings={}, equity_bindings={}),
        execution_spec=candidate.definition.execution_spec, resources=ExecutionResources(1, 1, 17))
    retained = (WORK / "experiments/EX077_20261102/report.md", WORK / "experiments/EX077_20261102/report_ref.json",
        WORK / "experiments/EX077_20261102/others/results.json", WORK / "experiments/EX076_20261102/report.md")
    before = {str(path.relative_to(ROOT).as_posix()): sha256(path.read_bytes()).hexdigest() for path in retained}
    final_test = read(WORK / "experiments/EX077_20261102/others/results.json")
    require(not final_test["passed_all_declared_test_conditions"], "Closeout differs from final test results")
    require(all(x["combined_status"] == "FAILED" for x in final_test["results"].values()), "Missing five failures")
    tests = ET.parse(SCRATCH.parent / "stage4-interface-final-tests.xml").getroot().find("testsuite")
    require(tests is not None and tests.attrib["tests"] == "444" and tests.attrib["failures"] == "0"
        and tests.attrib["errors"] == "0", "Retained focused test evidence differs")
    record = {
        "schema": "s017-final-closeout/v1", "decision_date": "2026-11-03", "actor": "RSCH",
        "user_instruction": "同意。收口，然后合并master并推送",
        "research_state": "TERMINATED", "closeout_work_completed": True, "strategy_objective_achieved": False,
        "stage_five_recommendations": [], "further_LITE_optimization_authorized": False,
        "test_window_seen": True, "test_window": ["2026-01-02", "2026-09-30"],
        "test_candidates": final_test["candidate_order"], "test_passed": [],
        "test_report": read(WORK / "experiments/EX077_20261102/others/publication_final.json")["report"],
        "research_closeout": "research/S017/CLOSEOUT_20261103.md", "existing_evidence_sha256": before,
        "new_accounts": 0, "new_searches": 0, "independent_account_audits": 0,
        "future_research_requires_new_user_instruction": True,
        "merger": {"announcement_date": "2026-11-02", "agreement_date": "2026-11-01",
            "status": "DEFINITIVE_AGREEMENT_NOT_CLOSED", "MRVL_shares_per_LITE_share": 4.5,
            "expected_closing": "2028_H1_SUBJECT_TO_SHAREHOLDER_REGULATORY_AND_OTHER_CONDITIONS",
            "sources_verified_in_conversation": [
                "https://www.sec.gov/Archives/edgar/data/1835632/000119312526442714/d81187dex991.htm",
                "https://investor.marvell.com/sec-filings/all-sec-filings/content/0001193125-26-442717/0001193125-26-442717.pdf"],
            "not_an_explanation_of_pre_announcement_test_losses": True},
        "engineering_validation": {"scope": "RETAINED_FOCUSED_TESTS_NO_NEW_PLATFORM_CODE",
            "implementation_commit": "095a374e0", "tests": 444, "failures": 0, "errors": 0,
            "timestamp": tests.attrib["timestamp"], "junit_sha256": sha256((SCRATCH.parent / "stage4-interface-final-tests.xml").read_bytes()).hexdigest(),
            "full_repository_regression_performed": False},
        "git_scope": {"merge_master": "AUTHORIZED", "push_master": "AUTHORIZED", "tag_requested": False,
            "market_data_and_machine_assets": "LOCAL_BATCH_ASSETS_EXCLUDED_BY_EXISTING_GITIGNORE"}}
    record_path = WORK / "materials/FINAL_CLOSEOUT_20261103.json"
    write(record_path, record)
    doc = WORK / "CLOSEOUT_20261103.md"
    handoff = WORK / "HANDOFF.md"
    historical = handoff.read_text(encoding="utf-8")
    heading = "# S017 研究交接\n"
    require(historical.startswith(heading), "Unexpected handoff heading")
    current = """
## 当前：S017已收口终止，无最终测试达标候选（2026-11-03，RSCH）

用户已明确批准收口、合并master及推送。公共研究状态为`TERMINATED`；停止对LITE追加调优，无候选推荐进入阶段五，策略经济目标未达成。

[收口报告](CLOSEOUT_20261103.md)、[机器记录](materials/FINAL_CLOSEOUT_20261103.json)及[收口发布与核验](materials/FINAL_CLOSEOUT_PUBLICATION_20261103.json)为当前入口。阶段四257点有界设计中五配置通过；[EX077联合测试](experiments/EX077_20261102/report.md)五配置全部经济失败，双频率通过。2026-01-02至09-30已见，不能恢复封存资格；训练及阶段四原结论完整保留。

已签约的Marvell换股收购增加未来市场环境变化的考虑，但尚未交割，不能直接解释9月末以前的亏损。本轮仅基于已有账本完成有边界复盘，没有新增优化或研究账户。

下一步建议筛选新研究标的，等待用户新任务；未自动立项、搜索、进入阶段五、冻结或部署。以下各节保留历史时点描述，其中“当前”、待授权事项及“2026仍封存”均为当时状态，不覆盖本节收口决定。

"""
    handoff.write_text(heading + current + historical[len(heading):], encoding="utf-8", newline="\n")
    for path in (doc, handoff):
        for target in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            if target.startswith(("http:", "https:", "#")):
                continue
            # The publication receipt is produced immediately below.
            linked = path.parent / target.split("#", 1)[0]
            if linked.name != "FINAL_CLOSEOUT_PUBLICATION_20261103.json":
                require(linked.exists(), f"Missing closeout navigation target: {target}")
    references = tuple(publish_evidence(research, d.MaterialEvidenceWrite(experiment,
        "s017-closeout-" + path.stem, path.read_bytes(), "text/markdown" if path.suffix == ".md" else
        "application/json" if path.suffix == ".json" else "text/x-python", path.suffix[1:]))
        for path in (doc, record_path, Path(__file__)))
    family_path = ROOT / "research/registrations/S017/family.json"
    intent = read(family_path)["research_intent"]
    intent["final_closeout_20261103"] = {"status": "TERMINATED_NO_TEST_QUALIFIED_CANDIDATE",
        "user_instruction": record["user_instruction"], "report": references[0].to_dict(),
        "record": references[1].to_dict(), "future_research_requires_new_user_instruction": True,
        "further_LITE_optimization_authorized": False, "test_window_seen": True}
    intent["next_action"] = "S017已收口终止，无最终测试达标候选；完成获批Git合并推送后等待用户新任务，不自动开展新研究。"
    update_research_intent(repository, batch, ResearchIntentUpdate(intent, ResearchState.TERMINATED),
        actor="RSCH", reason="用户批准停止LITE调优并收口S017：五配置最终测试全部失败，保留历史原件及已见测试边界")
    overview = get_research_overview(repository, batch)
    require(overview.registered_state is ResearchState.TERMINATED, "Research state was not terminated")
    validation = validate_experiment(repository, d.ExperimentValidationRequest(experiment, d.ExperimentValidationScope.REPORT_PUBLICATION))
    require(validation.status is d.ValidationStatus.PASS, "Retained EX077 report publication is invalid")
    require(all(sha256((ROOT / path).read_bytes()).hexdigest() == digest for path, digest in before.items()), "Historical reports changed")
    require(read(family_path)["research_intent"]["active_final_test_20261102"]["report"] == record["test_report"], "Test report reference changed")
    receipt = {"status": "CLOSEOUT_COMPLETED", "registered_state": overview.registered_state.value,
        "evidence": [ref.to_dict() for ref in references], "test_report_validation": validation.to_dict(),
        "historical_report_hashes_unchanged": True, "local_closeout_links_exist": True,
        "new_accounts": 0, "new_searches": 0, "snapshot": {"scope": overview.snapshot.scope.value,
            "content_sha256": overview.snapshot.content_sha256, "observed_at": overview.snapshot.observed_at}}
    write(WORK / "materials/FINAL_CLOSEOUT_PUBLICATION_20261103.json", receipt)
    print(json.dumps({"status": receipt["status"], "research_state": receipt["registered_state"],
        "test_report_validation": validation.status.value, "new_accounts": 0, "new_searches": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
