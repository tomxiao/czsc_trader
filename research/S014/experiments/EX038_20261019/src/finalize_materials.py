"""Save the bounded interface census; this does not evaluate a trading signal."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_bytes())


def write(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def main():
    inventory = read(EX / "others/census_inventory.json")
    calls = sorted((EX / "others/calls").glob("*.json"))
    assert [read(p)["id"] for p in calls] == list(range(1, 42))
    assert inventory["mcp_budget"]["recorded_call_files"] == 41
    assert inventory["interfaces_tested"] == inventory["interfaces_total"] == 21
    source = read(ROOT / ".tmp/20261019_option_etf_census_docs.json")
    assert source["interfaces_reviewed"] == 21
    for item in source["interfaces"]:
        origin = ROOT / item["document_snapshot_path"]
        payload = origin.read_bytes()
        assert sha256(payload).hexdigest() == item["document_sha256"]
        dest = EX / "others/official_docs" / f"{item['doc_id']}.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("xb") as stream:
            stream.write(payload)
        item["document_snapshot_path"] = dest.relative_to(ROOT).as_posix()
    source["original_review_sha256"] = sha256((ROOT / ".tmp/20261019_option_etf_census_docs.json").read_bytes()).hexdigest()
    # Final semantic review corrects the preliminary currency caveat using the
    # saved official field tables; official document bytes remain unchanged.
    for item in source["interfaces"]:
        if item["api"] == "etf_sh_cons":
            item["fields"]["sca"] = "替代金额，人民币元（官方471输出字段）"
        if item["api"] == "etf_sz_cons":
            item["fields"]["sub_cc"] = "申购替代金额，人民币元（官方472输出字段）"
            item["fields"]["red_cc"] = "赎回替代金额，人民币元（官方472输出字段）"
    for key, value in source.items():
        if isinstance(value, list):
            source[key] = [x.replace("PCF替代额可能多币种", "PCF替代额按471/472文档为人民币元")
                           if isinstance(x, str) else x for x in value]
    source["final_semantic_correction"] = "PCF现金替代金额据已保存471/472字段表确认为人民币元；原文快照不改。"
    write(EX / "others/official_document_review.json", source)
    method = (ROOT / ".tmp/20261019_option_etf_census_method_review.json").read_bytes()
    with (EX / "protocols/method_review.json").open("xb") as stream:
        stream.write(method)

    available, denied, unresolved = [], [], []
    for item in inventory["interfaces"]:
        counts = item["call_status_counts"]
        if counts.get("SUCCESS_NONEMPTY", 0):
            available.append(item["endpoint"])
        elif counts.get("PROVIDER_PERMISSION_DENIED", 0):
            denied.append(item["endpoint"])
        else:
            unresolved.append(item["endpoint"])
    assert (len(available), len(denied), len(unresolved)) == (11, 5, 5)
    snapshot = {p.relative_to(ROOT).as_posix(): sha256(p.read_bytes()).hexdigest() for p in calls}
    write(EX / "others/frozen_calls.json", {
        "status": "FROZEN_COLLECTION_STOPPED", "calls": 41, "max_calls": 48,
        "source_identity": "current_tushare_mcp_session_credential_identity_not_exposed",
        "no_sdk_execution": True, "wire_http_requests": None, "source_hashes": snapshot,
    })
    judgment = {
        "status": "COMPLETE_BOUNDED_CENSUS_WITH_UNRESOLVED_ACCESS_AND_HISTORY",
        "conclusion": "普查已完成：21类接口均已尝试，11类有非空返回、5类明确无权限、5类因自动审批失败尚未核实。ETF份额变化优先、可比期权持仓结构其次，值得形成下一轮验证；当前没有新增获支持的买卖信号。",
        "recommendation": "PRIORITIZE_ETF_SHARE_STATE_THEN_COMPARABLE_OPTION_OI",
        "next_step": "建议下一轮先核清历史份额折算、发布时间及完整覆盖，再固定一个ETF净赎回状态，检验它在既有价格信息之外能否区分600722.SH的H3损失风险；期权待历史合约与调整口径核清后再检验。不优先购买新权限或重复价格指标。",
        "interfaces_total": 21, "interfaces_available": 11, "interfaces_denied": 5,
        "interfaces_unresolved": 5, "available": available, "denied": denied,
        "unresolved": unresolved, "mcp_calls": 41, "mcp_cap": 48,
        "actual_budget": {"mcp_invocations": 41, "cap": 48, "unused": 7,
                          "call_status_counts": dict(Counter(inventory["call_status_counts"])),
                          "wire_http_requests": None, "new_model_fits": 0,
                          "new_return_labels": 0, "new_continuous_accounts": 0,
                          "new_candidates": 0, "new_supported_components": 0},
        "historical_window": ["2020-01-01", "2026-10-15"],
        "full_history_or_first_publication_certified": False,
        "current_metadata_not_historical_universe": True,
        "historical_component_definitions": 28, "historical_continuous_accounts": 66,
        "historical_all_targets_pass_count": 0, "historical_eligibility_changed": False,
        "phase_three_recommended": False, "future_execution_authorized": False,
        "incomplete_items": [
            "fund_nav、etf_limit、fund_adj、fund_factor_pro、rt_etf_min因自动审批失败尚未核实；不是供应商明确无权限。",
            "历史锚点与短段不认证全窗覆盖、逐时可得、历史修订、ETF份额折算或期权历史调整链。",
            "本轮仅数据可行性与研究问题排序，未做新标签、预测或账户检验，信号是否有效仍未知。",
        ],
    }
    write(EX / "others/judgment.json", judgment)
    print(json.dumps({"status": "PASS", "calls": 41, "available": available,
                      "denied": denied, "unresolved": unresolved}, ensure_ascii=False))


if __name__ == "__main__":
    main()
