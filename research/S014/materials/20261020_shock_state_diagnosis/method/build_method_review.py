"""Source-only inventory; never fetch market data, replay cycles, or calculate labels."""
from hashlib import sha256
import json
from pathlib import Path

ROOT = Path.cwd()
OUT = ROOT / "research/S014/materials/20261020_shock_state_diagnosis/method"
SOURCES = {
    "proposal": "research/S014/materials/20261020_shock_state_diagnosis/method_proposal.json",
    "population": "research/S014/materials/20261020_shock_state_diagnosis/accounting/original_shock_population_review.json",
    "local_method_A": "research/S014/materials/20261020_shock_state_diagnosis/accounting/local_cycle_method_review.json",
    "c9461_source": "research/S014/experiments/EX046_20261020/src/strategy_runtime/strategies/completed_pause_review.py",
    "c9461_receipt": "research/S014/experiments/EX046_20261020/others/accounts/run-001.json",
    "c9461_binding": "research/S014/experiments/EX046_20261020/others/bindings/001.json",
    "early_profit_report": "research/S014/experiments/EX006_20261016/others/report.md",
    "holding_report": "research/S014/experiments/EX007_20261017/others/report.md",
    "holding_features": "research/S014/experiments/EX007_20261017/src/components.py",
    "concentration_report": "research/S014/experiments/EX013_20261017/others/report.md",
    "concentration_features": "research/S014/experiments/EX013_20261017/src/features.py",
    "concentration_direct": "research/S014/experiments/EX013_20261017/src/direct.py",
    "trend_source": "research/S014/experiments/EX043_20261019/src/strategy_runtime/strategies/exante_hold_exit.py",
    "trend_findings": "research/S014/materials/20261019_exante_hold_exit/accounting/research_findings.json",
    "role_design": "research/S014/materials/20261019_2024_diagnosis/design_decision.json",
    "old_action_report": "research/S014/experiments/EX035_20261018/others/report.md",
    "current_shock_summary": "research/S014/materials/20261020_2026_diagnosis/accounting/shock_policy_summary.csv",
    "current_interaction_summary": "research/S014/materials/20261020_2026_diagnosis/accounting/interaction_policy_summary.csv",
    "prepared_reader_reference": "research/S014/materials/20261019_exante_hold_exit/accounting/audit_policy_accounts.py",
    "exact_fill_oracle": "research/S014/materials/20261019_2024_diagnosis/accounting/clock_execution_oracle.py",
}


def anchor(name, snippet):
    lines = (ROOT / SOURCES[name]).read_bytes().decode("utf-8").split("\n")
    found = [i + 1 for i, line in enumerate(lines) if snippet in line]
    assert found, (name, snippet)
    return {"source": name, "path": SOURCES[name], "lines": found, "match": snippet}


sources = {key: {"path": path, "sha256": sha256((ROOT / path).read_bytes()).hexdigest()} for key, path in SOURCES.items()}
anchors = [
    anchor("holding_features", 'BASE = ["ret1", "ret5", "ret20"'),
    anchor("holding_features", '"ma_slope": ma20 / ma20.shift(5) - 1'),
    anchor("holding_features", '"trend_preserved":'),
    anchor("holding_report", "标签是原固定退出净收益减下一TXE可执行退出净收益"),
    anchor("holding_report", "价格结构增量在三个期限的合并均值均为负"),
    anchor("concentration_features", "out['positive_concentration']="),
    anchor("concentration_features", "out['return_center']="),
    anchor("concentration_direct", "'concentration':(x.ret20.gt(0)&x.ret1.gt(0)"),
    anchor("concentration_report", "强基线模型增量未稳固"),
    anchor("trend_source", "close >= feature.ma20_prior"),
    anchor("trend_source", "feature.ma20_prior > feature.ma20_prior_lag5"),
    anchor("trend_findings", "TREND_CYCLE protection activates only"),
    anchor("c9461_source", 'out["ma20_prior"] ='),
    anchor("c9461_source", 'out["ret5_log"] ='),
    anchor("c9461_source", 'out["sigma20_pre5"] ='),
    anchor("c9461_source", "pending_at_start = bool("),
    anchor("c9461_source", "deadline = i + 9"),
    anchor("prepared_reader_reference", "def fetch_execution(binding,pricing):"),
    anchor("prepared_reader_reference", "ctx=get_context()"),
    anchor("exact_fill_oracle", "def exact_execution_prices(account,frames):"),
]
review = {
    "status": "METHOD_FEASIBLE_WITH_FIXED_ROLE_AND_UNIT_TIMING_BOUNDARIES_NO_NEW_LABELS",
    "baseline_commit": "f06371a5",
    "execution_authorized_by_this_review": False,
    "sources": sources,
    "anchors": anchors,
    "states": [
        {
            "name": "PRIOR_TREND_ESTABLISHED",
            "recommendation": "RETAIN_AS_FIXED_COMPONENT_STRATIFICATION_NOT_NEW_INFORMATION",
            "formula": "finite(ma20_prior,ma20_prior_lag5,Close[D-1]) AND ma20_prior>ma20_prior_lag5 AND Close[D-1]>=ma20_prior",
            "known_at": "Entirely before D impulse: MA ends D-1, lag5 MA ends D-6; previous means previous original trading session, not civil date",
            "prior_information": "EX007 structure group and plain trend already use MA levels/slope and ret1/5/20. EX013 strong baseline also includes distance_ma20/ma_alignment/ma_slope. EX043 TREND_CYCLE uses same slope plus D close, actual entry-day support break and <=1 priorATR.",
            "unanswered_increment": "Freeze this state at the original first positive-profit SHOCK D and ask the same actual cycle's exit responsibility. This is a different decision domain from EX043 entry-day support protection and fixed-midpoint EX007 probes; proposal uses D-1 close rather than EX043 D close.",
            "counterevidence": "EX007 price structure group pooled gains negative across H5/10/20; ordinary structure2026 benefit had opposite2023-25 behavior. EX043 trend protection activates only2020/2023 cycles, so it did not establish the proposed all-held SHOCK-role efficacy. Existing models could already represent related information.",
            "not_claimed": "New feature, independent alpha, established causal trend regime, or proof that all trend-true cycles should hold",
        },
        {
            "name": "FINAL_DAY_DOMINATES_RET5",
            "recommendation": "RETAIN_AS_FIXED_TEMPORAL_SHAPE_STRATIFICATION_WITH_OLD_CONCENTRATION_NEGATIVES",
            "formula": "r1=log(C_D/C_Dminus1); r4=log(C_Dminus1/C_Dminus5); state=r1>r4; exact tie false; all values finite; original SHOCK domain has r1+r4>0",
            "known_at": "D close only, before D-to-next-E trading decision; not known before the D move starts",
            "prior_information": "EX007 simple baseline already has ret1/5; EX013 tested20-day positive/negative concentration, largest absolute share, signed return_center and jump_trend, plus annual-training-median direct concentration contrasts. These are adjacent old temporal-shape hypotheses, with weak strong-baseline incremental evidence.",
            "unanswered_increment": "Specific fixed5-day final-day-versus-prior4 signed log-return equality at a positive-profit SHOCK exit was not found as an explicit tested rule in the inspected routes. It is deterministic transformation/role reuse of existing returns, not independent new data.",
            "counterevidence": "EX013 concentration had some positive direct contrasts but no robust strong-baseline incremental support. r4 can be negative: state true then means a late rebound dominates net5-day change, not that most of five sessions rose. State false may include a negative D after earlier gains. The boundary is economically interpretable but still adaptively proposed after seeing history.",
            "not_claimed": "A discovered jump threshold, an untested new input, or that state true necessarily favors selling/holding",
        },
    ],
    "role_overlap_inventory": [
        {"route": "EX006/EX007 fixed-horizon or midpoint continue-vs-next-TXE-exit labels", "difference": "Old component action comparison and related return/MA information already exist; new question is C9461 actual first-SHOCK domain with its exact cost/support/H10 exit, no model or fixed midpoint."},
        {"route": "EX043 TREND_CYCLE and SHOCK_PROFIT", "difference": "Old trend gate protects actual entry-day support break for the cycle; risk SHOCK outranks protection. It did not condition SHOCK selection on prior established trend."},
        {"route": "EX044 Z entry guard / ANY_P exit / cost", "difference": "Same shock information assigned before BUY or to nonpositive-P held positions, not two-state discrimination of original selectedpositiveP_SHOCK."},
        {"route": "EX047/EX048 full-window SHOCK and own-loss pause ablations", "difference": "They prove interactions/path changes and negative full-goal tradeoffs. Their alternative entries, cash and quantities cannot be imported as local labels for fixed original C9461 cycles."},
        {"route": "EX034/EX035 C0011 local action/participation decomposition", "difference": "Warns local carry value and total policy value can disagree. Old H3/E6/E9 terminal labels, sign epsilon and C0011 account identity do not apply to C9461 H10 component labels."},
    ],
    "component_label_contract": {
        "population": "Only A-authenticated original C9461 first selected_shock_exit D, actual held positive funded Q; one equal-weight row per original cycle. All21 original cycles retained including zero/censored; no alternative-path cohort selection.",
        "intervention_semantics": "Freeze each state at first originalSHOCK D. For each independent alternative suppress SHOCK for the rest of that one actual cycle, not daily state reclassification or one-day deferral. Before firstSHOCK paths must coincide. No new BUY after the original supplied entry, no later original entry seeded into this branch.",
        "ON_control": "Replay each original actual entry through its original actual exit. Exact source-D target/mandatory/risk/support/GRACE flags, all actual SELL attempts, filldate/trigger/price/Q/fee must match, not only final liquidation price. Authenticate actual originalBUY cost and IDs first.",
        "OFF_other_rules": "Keep cost1ATR, S5 support, original actual-entryD-only GRACE, entry-index H10 deadline and blockedSELL pending continuation. Inheritedpending/expiry outrank risk; OFF cannot cancel pending. Reservations retained as provenance, pause feedback cannot create a later entry in a one-cycle label.",
        "unit": "delta_return=(Q*alt_exit_price-alt_exit_fee - (Q*ON_exit_price-ON_exit_fee))/(Q*actual_entry_price+actual_buy_fee). With exact proportional.001 costs, equivalent .999*(alt_price-ON_price)/(entry_price*1.001). All numerator/denominator prices same original anchoredHFQ ledger basis and quantities RESEARCH_UNIT. Runtime fullHFQ features/entry prices kept separately; original anchor5.892 mapping authenticated.",
        "sign": "Strict negative/zero/positive, no new epsilon for outcome signs; exact equality zero. Tolerance if needed only predeclared arithmetic identity rounding, not public fill predicates or label classification.",
        "common_terminal_cash": "ON sale cash frozen without interest or reentry while alternative remains held; compare both liquidation proceeds at their common post-liquidation point under original cutoff. This is local liquidation opportunity cost, not an account return, annual alpha, cash participation benefit or additive budget.",
        "cutoff": "Only original valid D-to-E schedule through final sourceD2026-10-14 and executionE2026-10-15. Original pending SELL may execute finalE; no invented closeD10/15 signal or postcutoff fill. Either arm unresolved at cutoff: censored with null delta/sign, retain age/known state/attempt history; no terminal mark substituted into liquidation label.",
        "descriptive_controls": "Per-year counts/labels including empty2022; state known/true/false/unknown; actual entry-day age0 vs age>=1 and each exact remaining deadline count, plus actual extra liquidation duration. Report state-label cells and adverse examples, no tuned bins/new minimum counts/CI/noharm economic gate.",
        "downstream_limit": "A future full policy must decide on the first actualSHOCK of its own cycle and latch any hold choice until actual sale. It must separately reevaluate own later entries, loss feedback, quantity and capital under original full7-year goals. This component cannot answer that total value.",
    },
    "interfaces_and_sources": {
        "reader_reference": "audit_policy_accounts.py:fetch_execution shows exact DataRequest/PreparedDataRef/identity and ExecutionPricing.apply projection. Do not call its old get_context() wrapper: it reaches EX017 pinned default context. Reuse the body with an explicit create_research_context(...providers=ProviderConfig(bindings={})) plus socket/requests denial, prepared-only fetch and identity checks. No prepare, catalog enumeration or market export.",
        "strategy_prepared": "C9461 binding.input_bindings.full.prepared and .plan.requests market/raw/limits/status/calendar preserve original sourceD data through10/14. Reuse C9461 causal_features unchanged and source ready/inwindow mask, not source bars beyond the declared clock.",
        "execution_prepared": "C9461 binding.execution_prepared and execution_requests/identities supply original execution_daily, adjusted_daily, price_limits, trading_status through10/15. They are distinct prepared identities from strategy input; never infer finalE execution availability from sourceD-only bars.",
        "fill_reference": "clock_execution_oracle.py:exact_execution_prices uses anchored projected quote, original raw-bound ratio and public resolve_fill. Require exact returned fillprice/availability; no direct float fill<=limit shortcut, no new epsilon, no custom raw/HFQ fill logic.",
        "suggested_private_research_api": "Typed immutable CycleSeed(actual original IDs,entrydate,Q,ledger entry cost,runtime entry state,original deadline/reservation), enum ON/OFF, authenticated PreparedInputs and fixedcutoff -> CycleTrace plus CLOSED/CENSORED/TECHNICAL_ERROR. No new platform API or candidate registration; source/plan/prechecks local-public freeze and independent control gate before alternative labels.",
    },
    "decision": "Both fixed states worth the bounded component test; reject new-information or predictive-success wording. No added thresholds, models, external inputs or policy accounts now. Root final method lock must precede new labels/source execution.",
    "new_market_fetches": 0, "new_state_values": 0, "new_future_labels": 0, "new_model_fits": 0, "new_accounts": 0,
}
target = OUT / "method_review.json"
with target.open("x", encoding="utf-8", newline="\n") as f:
    json.dump(review, f, ensure_ascii=False, indent=2, allow_nan=False)
    f.write("\n")
print("METHOD_REVIEW_SOURCE_ONLY", sha256(target.read_bytes()).hexdigest(), "sources", len(sources), "anchors", len(anchors))
