"""Final supplement interpretation, derived only from audited actual policies."""

import csv
import hashlib
import json
from pathlib import Path

ROOT = Path.cwd()
BASE = Path("research/S014/materials/20261020_2026_diagnosis")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    paths = [
        "review/interaction_actual_result_evidence.json", "review/interaction_extract_result_evidence.py",
        "accounting/independent_interaction_audit_summary.json", "accounting/interaction_account_000_independent_review.json",
        "accounting/interaction_account_001_independent_review.json", "accounting/interaction_policy_yearly_summary.csv",
        "accounting/interaction_policy_summary.csv", "accounting/interaction_four_cell_review.json",
        "accounting/interaction_four_cell_summary.csv", "accounting/interaction_four_cell_yearly.csv",
        "accounting/interaction_descriptive_yearly_contrast.csv", "accounting/interaction_pause_actual_review.json",
        "accounting/interaction_2026_actual_pause_slots.csv", "accounting/interaction_2026_pause_candidate_trace.csv",
        "accounting/interaction_2026_phase.csv", "accounting/interaction_2026_flat_reason_summary.csv",
        "accounting/interaction_2026_calendar_cycle_contributions.csv", "accounting/interaction_2026_opening_ending.csv",
        "accounting/interaction_2026_actual_exit_decisions.csv", "accounting/interaction_2026_phase_summary.csv",
        "review/interpretation_results_v2.json", "interaction_design_decision.json",
    ]
    hashes = {(BASE / p).as_posix(): sha(BASE / p) for p in paths}
    hashes[Path(__file__).relative_to(ROOT).as_posix()] = sha(Path(__file__))
    evidence = json.loads((BASE / paths[0]).read_bytes())
    yearly = list(csv.DictReader((BASE / "accounting/interaction_policy_yearly_summary.csv").open(encoding="utf-8-sig")))
    summary = list(csv.DictReader((BASE / "accounting/interaction_policy_summary.csv").open(encoding="utf-8-sig")))
    four = list(csv.DictReader((BASE / "accounting/interaction_four_cell_summary.csv").open(encoding="utf-8-sig")))
    contrast = list(csv.DictReader((BASE / "accounting/interaction_descriptive_yearly_contrast.csv").open(encoding="utf-8-sig")))
    assert len(yearly) == 14 and len(summary) == 2 and len(four) == 4 and len(contrast) == 7
    checks = 4
    for p in evidence["policies"]:
        for y in p["annual_counts_and_metrics"]:
            row = next(r for r in yearly if r["pause_profile"] == p["policy"] and int(r["year"]) == y["year"])
            for k in ["opening_equity", "closing_equity", "return", "max_drawdown", "required_return"]:
                assert float(row[k]) == y["annual"][k]
                checks += 1
    for r in contrast:
        assert abs(float(r["BASE_minus_LOSS_at_fixed_SHOCK_OFF_pp"]) - float(r["BASE_minus_LOSS_at_fixed_SHOCK_ON_pp"]) - float(r["descriptive_difference_of_annual_policy_return_differences_pp"])) < 1e-10
        checks += 1
    offbase26 = next(r for r in yearly if r["pause_profile"] == "BASE" and r["year"] == "2026")
    margin = 100 * (float(offbase26["return"]) - float(offbase26["required_return"]))
    output = {
        "status": "COMPLETE_ALL_FIXED_INTERACTION_ARMS_ADVERSARIAL_INTERPRETATION",
        "blocking_findings": [],
        "reviewed_hashes": hashes,
        "independent_actual_chronology_checks": evidence["check_count"],
        "additional_csv_identity_checks": checks,
        "plain_conclusion": "关SHOCK再关亏后暂停能够修到2026原收益门，但会重新损害2024/2025，且2025回撤也失败。四个固定组合均未同时通过全部原目标；本轮没有全年度可接受的新替代策略。保留C9461为诊断基线，不因单年或期末财富选胜。",
        "four_fixed_cells": four,
        "new_supplement": {
            "fresh_LOSS_control": "EX048000 exactEX047001 C9471; existing OFF+LOSS path, not a new independent economic finding",
            "BASE": {
                "diagID": "S014-C9481", "original_return_pass": "5/7", "original_drawdown_pass": "6/7", "frequency_full_contract": 5.0426309378806335,
                "2026_return_percent": 196.73646085016064, "2026_required_percent": 196.4644018810632,
                "2026_margin_pp": margin, "2026_original_return_pass": True, "2026_drawdown_percent": 26.87286460531906,
                "2024_return_percent": -19.051265400363326, "2025_return_percent": -1.3080546429662054,
                "2025_drawdown_percent": 31.452586365731617, "2025_BH_drawdown_percent": 28.875875711755516,
                "all_original_goals_pass": False,
                "2026_opening_equity": 324604.3179999997, "original_cutoff_equity": 963219.365
            },
            "margin_interpretation": "0.272059pp余量是已实现历史结果。按原>=门正式记为该年PASS，不添加buffer、CI、样本量或稳健性否决条件；该单年PASS也不能覆盖其他年失败。"
        },
        "wealth_and_risk": [
            "C9481截止963219.365确实高于C9461的944894.575。这个事实必须保留；它仍不是原逐年验收目标的替代品。",
            "C9481年初只有324604.318，而C9461为527290.572，双方全历史资金和跨年仓不同。各年收益使用自己的年初分母，无年度重置；不能把196.74%与79.20%的差全部叫同一仓位的直接收益。",
            "不暂停增加实际参与与费用，也增加风险；C9481原全窗口138闭合、频率5.04263通过，但2025DD31.4526%>BH28.8759%是实际原门失败。",
            "SHOCK_OFF仍保留亏后暂停的C9471/C9480，2024+15.9846%和2025DD28.4141%仍通过相应门；关闭暂停后2024变负且2025DD超限，不能以2026单年进步否定此前pause保护。"
        ],
        "actual_January_chain": {
            "with_loss_pause": "实际Jan9买6.38→Jan19按support卖6.29，闭合净亏；Jan23消费一次槽，Feb10才实际再买。",
            "without_pause": "实际Jan9买6.38→Jan19仍卖6.29，BASE如实观察净亏但不arm；Jan26实际买7.14，Feb9按原H10卖9.01，47300研究单位、净现金87687.105。不是事后拼接一个假想订单。",
            "boundary": "Jan26-Feb9原11个空仓日BH+40.7519pp不是该新增周期可赚数，也不是整个政策年度收益差。真实新增BUY、费用、股数、退出和此后所有交易共同形成新政策。"
        },
        "descriptive_interaction": {
            "annual_table": contrast,
            "2026": "关闭亏后暂停在SHOCK_OFF时年度变化+73.48556pp，在SHOCK_ON时+9.90110pp，两差相差+63.58445pp。",
            "2024": "同样关闭暂停在SHOCK_OFF时-35.03588pp、在SHOCK_ON时-32.62383pp；反馈保护并非无用。",
            "interpretation": "这些是四条全历史政策各自年初归一后的描述差分，说明单独作用随组合而变；不是随机差分实验或可线性相加的因果贡献。补格在见到EX047和Jan链后选择，适应性历史披露保留。"
        },
        "answered": [
            "固定C9461的2026缺口主要是上涨兑现/参与不足，且原目标比BH再多0.5倍；不是该年亏钱或单纯费用。",
            "仅撤SHOCK不足修2026，且会破坏2025；继续撤lossPause可修2026，却重坏2024/2025收益及2025DD。静态撤保护路线存在明确跨年反证。",
            "新OFF亏损反馈确实产生Jan23早期暂停；禁pause后真实Jan26重新参与，机制链由实际订单/资金支持。",
            "旧九月flatBH为负不证明SHOCK动作获益，新OFF实际Sep10卖20.58>ON18.57。原初design成功避跌表述由实际后继证据限定，旧锁不修改。"
        ],
        "not_answered": [
            "有没有不编码日期/年份、且D当晚可知的状态能区分急涨后的延续和回吐。四个固定动作对照不提供这个新信号。",
            "本轮不能证明任何新条件的未来收益，也不能把四格之间的年度差额当条件模型的预算。",
            "未优化Z、ATR、持有期或暂停长度，故不声称找到最优阈值/期限。"
        ],
        "recommendation": {
            "diagnostic_baseline": "Retain frozen S014-C9461 diagnostic comparator only; no formal registration, qualification or automatic stage advance.",
            "current_round": "Stop adding accounts. All four actual dispatches from two new sources and all original goals reported, including two source-specific controls.",
            "next_question_for_root_user": "如继续，先审急涨后延续/回吐在D是否有可辨的既有状态及跨年反例，再决定是否有值得锁的新职责规则；不是以2026年名开关，也不是先扫邻近阈值。",
            "no_added_gate": "All original2020-26 annualreturn/DD and originalfrequency unchanged; negative deltas alone do not veto a still-passing year, and no new margin or concentration gate."
        },
        "resource_accounting": {"new_actual_dispatches_total_EX047_EX048": 4, "SUCCEEDED": 4, "FAILED": 0, "UNKNOWN": 0, "retries": 0, "fresh_source_controls": 2, "review_new_accounts": 0, "review_prepared_fetches": 0, "new_market_calls": 0, "fits": 0},
        "limits": ["All2020-26 shared-seen development, not a fresh holdout;2026 newly authorized for economic diagnosis, originalOct15 cutoff not annualized.", "Four cells include reused prior actual accounts; fresh controls are source-equivalence checks, not independent confirmation samples.", "Repeated suppressed D states and many cycles remain correlated; no independent-event or additive-local-PnL claim.", "No date/year switch, outside data, platform change or altered contract introduced."
        ],
        "next_step": "Freeze this interpretation and precise delivery for EX048. Root final report/judgment then receive exact hash review; local publication and old-byte/intent preservation remain delivery checks."
    }
    destination = BASE / "review/interaction_interpretation_results.json"
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"status": output["status"], "sha256": sha(destination), "checks": checks}))


if __name__ == "__main__":
    main()
