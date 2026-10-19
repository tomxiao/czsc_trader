"""Bind independent interpretation to saved evidence; no new policy evaluation."""

import csv
import hashlib
import json
from pathlib import Path

BASE = Path("research/S014/materials/20261020_preentry_diagnosis")
OUT = BASE / "review"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(name, content):
    with (OUT / name).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(content, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def main():
    evidence_path = OUT / "pause_path_interpretation_evidence_v2.json"
    evidence = json.loads(evidence_path.read_bytes())
    bridge_path = BASE / "accounting/pause_entryday_yearly_attribution.csv"
    bridge_review = BASE / "accounting/pause_entryday_attribution_review.json"
    rows = list(csv.DictReader(bridge_path.open(encoding="utf-8-sig")))
    annual = {(r["policy_id"], r["year"]): r for r in evidence["annual_table"]}
    checks = 0
    for r in rows:
        entry, later, net = (float(r[k]) for k in ["entryday_net", "postentry_residual_net", "year_net_pnl"])
        assert abs(entry + later - net) < 1e-7
        assert abs(net / float(r["opening_equity"]) - float(annual[r["pause_profile"], r["year"]]["return"])) < 1e-12
        assert abs(float(r["difference_vs_BASE_entryday_net_pp"]) + float(r["difference_vs_BASE_postentry_residual_net_pp"]) - float(r["difference_vs_BASE_year_net_pnl_pp"])) < 1e-10
        checks += 3
    hashes = {str(p).replace("\\", "/"): sha(p) for p in [evidence_path, bridge_path, bridge_review, Path(__file__), OUT / "interpret_pause_results.py", OUT / "pause_path_interpretation_evidence.json"]}
    scope = {
        "status": "DISCLOSED_SCOPE_EXPOSURE_NO_NEW_SELECTION",
        "incident": "An initial whole-lifecycle schema print of the saved A reviews included economic_window=false completed-cycle rows from2026 in tool output before truncation. No new2026 data were fetched.2026 is already seen S014 history and not a fresh holdout.",
        "effect": "No rule, parameter, account, interpretation selection or threshold changed from the fixed three-profile design. No2026 case or detailed economic values are used in the new interpretation. Original published full-contract pass counts remain the acceptance reference.",
        "subsequent_extraction": "Filter source ledger rows in memory to2020-01-01..2025-12-31 before extracting/outputting cases. Original evidence and source unchanged.",
        "no_claims": ["2026 unseen", "zero2026 exposure", "2020-25 six-year success means all original seven-year goals passed"],
        "new_accounts": 0,
    }
    save("scope_disclosure.json", scope)
    hashes[(OUT / "scope_disclosure.json").as_posix()] = sha(OUT / "scope_disclosure.json")
    result = {
        "status": "INDEPENDENT_INTERPRETATION_COMPLETE",
        "blocking_findings": [],
        "reviewed_hashes": hashes,
        "saved_account_evidence": evidence["actual_evidence"],
        "independent_arithmetic_checks": {"path_feedback_and_slots": evidence["check_count"], "annual_bridge": checks},
        "scope": "All fixed3 actual policies;2020-25 seen development economics. Original2020-partial2026 contract retained only through published pass/frequency counts, with no new2026 economic case selection.",
        "conclusion": "亏后一次暂停取得明确的完整六年历史改进，但原七年验收仍未全部达标；结果支持这个完整执行政策的历史价值，未证实简单的‘亏后下一笔更危险’预测说法。",
        "acceptance": {
            "LOSS_complete2020_25": {"annual_return_pass": "6/6", "annual_drawdown_pass": "6/6", "original_full_contract_frequency": 3.361753958587089, "frequency_pass": True},
            "LOSS_original_full_contract": {"annual_return_pass": "6/7", "annual_drawdown_pass": "7/7", "all_original_goals_pass": False, "qualified": False},
            "BASE_complete2020_25": "5/6 return,6/6 drawdown",
            "PROFIT_complete2020_25": "5/6 return,6/6 drawdown;2025return fails",
            "reference": "accounting/pause_original_mandate_clarification.json supersedes the total audit's narrow original_economic_goal prose; original frozen total audit is retained."
        },
        "whole_policy_comparisons": {
            "terminal2025_equity": {"BASE": 439233.7639999993, "LOSS": 527290.572, "PROFIT": 328095.1490000005},
            "end2024_equity_without2025": {"BASE": 312130.0339999996, "LOSS": 358623.04900000006, "PROFIT": 337723.0590000003},
            "annual_return_percent_BASE_LOSS_PROFIT": {str(year): [100 * float(annual[profile, str(year)]["return"]) for profile in ["BASE", "AFTER_NET_LOSS_SKIP1", "AFTER_NET_PROFIT_SKIP1"]] for year in range(2020, 2026)},
            "opportunity_costs": ["LOSS2020收益4.2511%较BASE35.5932%少31.3420pp，回撤17.0758%也较BASE15.4742%大，但仍过该年原目标，不另设负delta否决门。", "LOSS2023收益8.5327%较BASE17.2884%少8.7556pp，仍高于原3.36535%收益门。", "LOSS2021收益150.7390%高于本轮BASE116.6954%，但较最初原策略低28.1518pp；仍高于原71.9038%收益要求。"]
        },
        "entryday_vs_later_path": {
            "definition": "买入首日净额=actual Q*(Eclose-actualfill)-actualBUYfee；后续残差含年内继续持仓价格变化、实际卖出价格变化及SELLfee，按各自年初资金归一。包含跨年持仓，周期净现金不能直接替代年度收益。",
            "2024_rows": [r for r in rows if r["year"] == "2024"],
            "interpretation": "LOSS确有首日减损：首日贡献-17.5371pp→-4.00745pp，改善13.52962pp；更大的后参与/卖出净残差改善19.09422pp，合计32.62383pp。不是全部由事前剔除坏首日解释。PROFIT同年首日净贡献+2.47036pp更高，但2025全年失败，不能以该局部指标替代完整政策验收。",
            "fees": "2024实际总费用BASE15568.786、LOSS9807.756、PROFIT9258.167。费用降低是少交易与不同资金路径的共同结果；不能从年末差额机械扣出一个独立因果费用份额。"
        },
        "mechanisms": [
            {"claim": "亏后下一次入场必然更危险", "judgment": "NOT_SUPPORTED", "evidence": "旧BASE观察先前亏后68成交首日净负28；盈后53成交净负27，后续闭合均值亏后反较高。新政策不能反向改写旧观察，也不能将旧分组的好坏交易直接移入自己的实际历史。"},
            {"claim": "有限暂停连同H10机会槽和自己的反馈可改善完整路径", "judgment": "SUPPORTED_IN_SEEN_COMPLETEYEARS", "evidence": "LOSS六完整年度过原收益/DD门，2020-24终值也较BASE高；实际每条反馈来自自己的完成成交。仍有2020/2023机会成本和完整七年收益未全过。"},
            {"claim": "2024修复是亏后信息独享", "judgment": "REFUTED", "evidence": "PROFIT2024也+19.5669%，LOSS+20.2514%；二者都保留Apr25大盈利。暂停带来的不同市场参与时段是有力竞争解释。"},
            {"claim": "任意相近降频都同样好", "judgment": "NOT_RESOLVED_AND_SIMPLE_UNIVERSAL_VERSION_REFUTED", "evidence": "PROFIT2025-2.85083%对LOSS+47.03198%是实际反例。LOSS41槽、PROFIT35槽，日期与闭合历史不同，反向控制不是等剂量随机或同日对照，不能据差额量化loss标签的纯因果价值。"},
            {"claim": "改进只靠删除几个旧亏损周期即可复原", "judgment": "REFUTED_AS_ACCOUNTING_METHOD", "evidence": "初次暂停后下一次入场、费用、仓位、后续反馈都会改变；必须用已执行完整资金路径，不能将旧交易PnL相减或把局部变化线性相加。"}
        ],
        "actual_path_examples": [
            "LOSS2024DJan26在自己Jan16净亏后消耗槽，Feb20恢复资格，Feb21才实际买；避开BASEJan29周期。D和未来E分别记录，不能把未来成交/收盘当D可知。",
            "LOSS2024DMar26真实亏损之后，DApr9消耗一次槽，Apr24恢复、Apr25实际买，May7净周期+22.7517%。同年最大闭合盈利现金77736.834，高于该年净财富增长60395.244；这是集中度描述，不能据此另加门或构造删交易账户。",
            "LOSS2024DMay22仍买、May24净周期-6.33159%；没有普遍剔除不利入场。DOct8在自己Sep19亏损后消耗槽，Oct24恢复实际买，不能声称Oct例子单独解释全年改善。",
            "LOSS2025Apr25实际买、Apr29仍净亏-2.74373%；DMay14消费这个已闭合亏损的一次槽。到DMay29旧亏损符号仍在但已disarmed，不重复暂停，May30实际买并Jun16卖，净周期+23.5807%。Jun19实际买、Jun20卖的正P SHOCK退出也保留。",
            "PROFIT2025Jun12实际买、Jun16卖，净周期+21.6795%；原持仓预约使Jun19没有重买，并非在DJun18直接暂停Jun19。之后DJun26才消耗自己的盈后槽。这是排期竞争解释的明确例子。"
        ],
        "limitations": ["三条完整政策是三条相关路径，不能将41/35槽或全年周期当独立重复实验。", "全2020-25已见且反复开发；发现历史改善不等于独立未来预测验证。", "阈值、严格符号、i+11槽和三档方向已事先固定，旧人口反证已见且保存；不因实际结果再调暂停天数、亏损串或符号。", "保留原BASE执行SUCCEEDED与原内部auditFAIL；v2仅同账户D/E审计映射补核，无重派。一次publication拒绝/同操作重审与资金执行失败也须分别报告。", "不提出修改原目标、增加经济硬门或将2026删出原验收。"],
        "next_step": "将固定三档真实结果、旧人口反证、首日/后续桥和原全合同不足一起写入主报告；核报告精确字节后发布。不追加账户、阈值、年份门或新数据。",
        "resources": {"new_accounts": 0, "new_market_calls": 0, "prepared_fetches": 0, "new_policy_replays": 0, "fits": 0},
        "extraction_successor": "The first local interpretation extractor/evidence are retained. v2 normalizes timestamp order.signal_date to YYYY-MM-DD before same-D/no-order comparisons; no funded/source/strategy data changes. Only v2 evidence is the final path-check authority."
    }
    save("interpretation_results.json", result)
    print(json.dumps({"status": result["status"], "checks": 1042 + checks, "sha256": sha(OUT / "interpretation_results.json"), "scope_sha256": sha(OUT / "scope_disclosure.json")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
