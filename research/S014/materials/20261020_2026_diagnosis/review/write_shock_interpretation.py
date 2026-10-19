"""Freeze the complete two-arm interpretation from saved actual results only."""

import csv
import hashlib
import json
from pathlib import Path

BASE = Path("research/S014/materials/20261020_2026_diagnosis")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    paths = [
        "review/actual_result_evidence.json", "review/extract_shock_result_evidence.py",
        "accounting/independent_shock_audit_summary.json", "accounting/shock_account_000_independent_review.json",
        "accounting/shock_account_001_independent_review.json", "accounting/shock_policy_yearly_summary.csv",
        "accounting/shock_policy_summary.csv", "accounting/shock_actual_suppressed_rows.csv",
        "accounting/shock_2026_actual_exit_decisions.csv", "accounting/shock_2026_phase.csv",
        "accounting/shock_2026_flat_reason_summary.csv", "accounting/shock_2026_calendar_cycle_contributions.csv",
        "accounting/shock_2026_opening_ending.csv", "design_decision.json", "authorization.json",
    ]
    hashes = {(BASE / p).as_posix(): sha(BASE / p) for p in paths}
    hashes[Path(__file__).as_posix()] = sha(Path(__file__))
    evidence = json.loads((BASE / paths[0]).read_bytes())
    annual = list(csv.DictReader((BASE / "accounting/shock_policy_yearly_summary.csv").open(encoding="utf-8-sig")))
    summary = list(csv.DictReader((BASE / "accounting/shock_policy_summary.csv").open(encoding="utf-8-sig")))
    assert len(annual) == 14 and len(summary) == 2
    for p in evidence["policies"]:
        for y in p["annual_counts_and_metrics"]:
            row = next(r for r in annual if r["shock_profile"] == p["policy"] and int(r["year"]) == y["year"])
            assert all(float(row[k]) == y["annual"][k] for k in ["opening_equity", "closing_equity", "return", "max_drawdown", "required_return"])
    on, off = evidence["policies"]
    assert on["policy"] == "SHOCK_ON" and off["policy"] == "SHOCK_OFF"
    off26 = off["annual_counts_and_metrics"][-1]["annual"]
    on26 = on["annual_counts_and_metrics"][-1]["annual"]
    result = {
        "status": "COMPLETE_FIXED_TWO_ARM_ADVERSARIAL_INTERPRETATION",
        "blocking_findings": [],
        "reviewed_hashes": hashes,
        "source_actual_checks": evidence["check_count"],
        "additional_annual_csv_checks": 70,
        "plain_conclusion": "只关SHOCK确实提高2026收益，但仍未过原目标，并破坏2025已通过的收益门；不能替换固定C9461，也不能按年份开关。结果支持退出职责存在取舍，未支持全面撤掉该保护或发现独立新信号。",
        "full_pair_results": {
            "SHOCK_ON": {"original_return_pass": "6/7", "original_DD_pass": "7/7", "frequency": 3.361753958587089, "frequency_pass": True, "complete2020_25_return_pass": "6/6", "terminal_original_cutoff_equity": 944894.5750000005},
            "SHOCK_OFF": {"original_return_pass": "5/7", "original_DD_pass": "7/7", "frequency": 3.215590742996346, "frequency_pass": True, "complete2020_25_return_pass": "5/6", "terminal_original_cutoff_equity": 899477.4699999996},
            "both_all_original_goals_pass": False,
            "annual_returns_percent_ON_OFF": {str(y): [100 * float(next(r for r in annual if r["shock_profile"] == p and int(r["year"]) == y)["return"]) for p in ["SHOCK_ON", "SHOCK_OFF"]] for y in range(2020, 2027)},
            "original2026_required_return_percent": 196.4644018810632,
            "OFF2026_gap_to_required_pp": 100 * (off26["required_return"] - off26["return"]),
            "OFF2026_delta_vs_ON_pp": 100 * (off26["return"] - on26["return"]),
            "OFF2026_gap_to_BH_pp": 100 * (off26["buyhold_return"] - off26["return"])
        },
        "capital_and_risk": [
            "OFF2026按自己的402899.810年初资金收益+123.2509%，ON按527290.572收益+79.1981%；OFF截止权益899477.470反而低于ON944894.575。年度百分比改善不能偷换为全历史财富更高。",
            "OFF2020-24末权益422792.210高于ON358623.049，2025后却变为402899.810低于527290.572；说明早期历史优势被后来代价逆转，不能只报2026或去2025视图。",
            "OFF2026回撤25.6095%较ON23.1778%更大，仍低原BH59.7736%；OFF2025回撤28.4141%仍小于原BH28.8759%，但年度收益为-4.7050%，收益门失败。不得额外加入no-harm或回撤安全边际门。"
        ],
        "actual_path_evidence": [
            "OFF首个旧状态/target差在2020-07-06D、首个资金差2020-07-07E，原前缀精确；因此不是在2026年初重置账户后做的局部对照。",
            "两臂2025May30均实际买5.12并Jun16卖6.34，ENTRY_GRACE保留。Jun19又均实际买7.03；ON Jun20卖7.81，OFF Jun26才卖6.30并净亏。该真实跨年反例直接说明原SHOCK在部分上涨中有兑现价值。股数不同，不能将两个周期现金差当单动作因果份额。",
            "2026OFF的Jan9仓在Jan19按support卖6.29，实际净周期-1.60764%；ON同Jan9仓Jan12已卖6.80获利。OFF由此在Jan23消费自身一次loss槽，直到Feb10才实际再买，ON则有Jan26买入。新反馈人口来自自己实际闭合，不能复制旧ON未来盈亏。",
            "OFF2026Feb10→Mar4期限退出与Mar5→Mar19期限退出保留较长上涨，但并非所有OFF仓都自动持满H10；多笔仍被support卖出。",
            "旧ON九月退出后整空仓BH净-15.9318pp不等于取消SHOCK必亏：OFF Aug27实际仓Sep10按期限卖20.58，净周期+51.2436%，ON Sep2卖18.57。旧整空仓分区排除实际SELL/BUY日，且实际卖价与收盘不同；这正是不得把旧flat收益当持仓反事实的例子。"
        ],
        "trigger_population": {
            "OFF_suppressed_D_by2020_26": [8, 18, 0, 5, 7, 7, 12],
            "OFF_suppressed_distinct_cycles_by2020_26": [2, 5, 0, 3, 3, 3, 5],
            "interpretation": "57个被抑制D属于21个实际持仓周期，重复触发不是57份独立样本；2022无该年新抑制D，年度收益仍不同，来自先前路径/跨年状态与资金的延续，不能当作2022新风险识别证据。"
        },
        "remaining2026_competition": [
            "两臂只足以检验当前SHOCK动作的必要性及单独修复是否充分；OFF仍差原目标73.2135pp，不能据此声称完整解释了所有缺口。它较BH少7.7254pp，目标另要求超过BH65.4881pp。原高目标不被下调。",
            "OFF2026首日净贡献-14.5412pp，继续持仓+111.9117pp，卖出净+25.8804pp；整空仓0，合计+123.2509%。这是实际会计分区，不能从中挑一个收益最高的环节假想替换。",
            "OFF整空仓118日内，消费/处于loss暂停的61日BH净-19.2859pp，包含上涨与避跌；不能将暂停一律写成漏涨。原实际BUY预约45日BH净-25.1555pp，也不是完全有害。",
            "OFF2026唯一selected_cost_exit在Sep15，和support同D重合；当前实际路径没有cost独占的2026直接退出。因此再撤cost对当前2026直接职责的证据较弱，但全历史撤cost仍可能改变先前路径，不能断言任意新账户完全等价。"
        ],
        "followup_judgment": {
            "status": "ONE_FOCUSED_LOSS_PAUSE_INTERACTION_CAN_BE_INFORMATIVE_IF_ROOT_AUTHORIZES",
            "possible_control": "Fresh source exact current SHOCK_OFF plus fixed cost/GRACE/S5/H10/own-loss pause",
            "possible_single_active": "Keep SHOCK_OFF and all cost/entry/holding/execution rules; disable only completed-loss one-slot action across all2020-26, retaining truthful own completed signs as observations",
            "why": "Changed actual exit Jan19 turns an ON winning cycle into OFF loss, arming a newly early pause. This observed mechanism differs from old no-pause-with-SHOCK and old EX043-without-cost; it warrants an interaction falsification, not an expected cure.",
            "strongest_counterevidence": "All OFF pause-flat days together correspond to netnegativeBH contribution; old LOSS policy improved the six complete years. Jan23's favorable missed period is selected after seeing the path and cannot determine a date/year exception or forecast the whole successor.",
            "not_authorization": "No new account/implementation or extra axis selected by this interpretation. Root decides a separate fixed minimal design; no automatic step because the target remains missed.",
            "criteria": "All7original annual return/DD and original frequency. No every-year no-harm, CI, count or concentration veto. Any proposed pair must rerun original whole path with own actual feedback and exactsource control."
        },
        "limits": [
            "All2020-26 are already seen development history; original cutoff10/15 partial year not annualized. New test is adaptive to published old/current diagnoses, not unseen verification.",
            "Raw selected_profit_exit retains the legacy condition under OFF. Actual chosen exit is selected_shock_exit/selected_risk_exit; legacy condition counts must not be labeled real SHOCK sells.",
            "Different entry/exit/pause/fees/funding paths prevent additive causal attribution and old trade deletion arithmetic.",
            "No original candidate qualification, stage progression or production decision follows from this diagnostic pair. Keep C9461 as fixed diagnostic comparator unless the user chooses otherwise."
        ],
        "resources": {"actual_account_dispatches": 2, "SUCCEEDED": 2, "FAILED": 0, "UNKNOWN": 0, "retries": 0, "new_fits": 0, "new_market_calls": 0, "review_prepared_fetches": 0, "review_new_accounts": 0},
        "next_step": "Report both actual paths and the 2025 counterexample; separately decide whether the single lossPause interaction deserves a locked successor. No threshold/date/year search."
    }
    destination = BASE / "review/interpretation_results.json"
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"status": result["status"], "sha256": sha(destination)}))


if __name__ == "__main__":
    main()
