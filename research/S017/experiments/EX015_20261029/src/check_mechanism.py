"""EX015 pure synthetic checks; never load market assets or published accounts.

The False-policy matrix compares target, reason, and all original explanation
facts against frozen EX011/C0036 for identical histories and portfolio feedback.
Identical targets under the same public execution contract imply identical order
inputs at those tested states; this is not a formal account-path replay or proof
over every possible state. Only True is assigned a formal configuration; False
is a verification branch and does not replay the existing real-data C0036 account.
"""
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from zoneinfo import ZoneInfo

import pandas as pd
from dataflows import TimeInterval, TradingSession
from strategy_runtime import (DecisionPoint, EquityPortfolio, EquityClosedCycle,
                              EquityClosedCycleFeedback)

from strategy import decide, entry_opening_anchor, cycle_stop


WORK = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[5]
LEGACY = ROOT/'research/S017/experiments/EX011_20261029/src/strategy.py'
spec = importlib.util.spec_from_file_location('frozen_c0036_reference', LEGACY)
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)
ZONE = ZoneInfo('America/New_York')
DAY = date(2025, 11, 28)
MONDAY = date(2025, 12, 1)
EQUIVALENCE_CASES = 0


def moment(day, hour, minute=0):
    return datetime.combine(day, time(hour, minute), tzinfo=ZONE)


def session_frame(day, *, half=False, closes=None, opening_high=11., opening_low=9.):
    count = 7 if half else 13
    closes = closes or [10.5, 11.5]+[12.]*(count-2)
    rows = []
    for index, close in enumerate(closes):
        start = moment(day, 9, 30)+timedelta(minutes=30*index)
        opening = 10. if index == 0 else closes[index-1]
        rows.append(dict(BarStart=start, Date=start+timedelta(minutes=30),
            AvailableDate=start+timedelta(minutes=30), Open=opening,
            High=opening_high if index == 0 else max(opening, close)+.5,
            Low=opening_low if index == 0 else min(opening, close)-.5,
            Close=close, Volume=100.))
    return pd.DataFrame(rows)


def history(day=DAY, *, half=True):
    days, cursor = [], day-timedelta(days=1)
    while len(days) < 22:
        if cursor.weekday() < 5 and cursor != date(2025, 11, 27):
            days.append(cursor)
        cursor -= timedelta(days=1)
    prior = [session_frame(value) for value in reversed(days)]
    return pd.concat([*prior, session_frame(day, half=half)], ignore_index=True)


def feedback(entry_day, exit_day, *, entry_hour=10, entry_minute=30, exit_hour=11):
    return EquityClosedCycleFeedback(EquityClosedCycle('closed-synthetic',
        TimeInterval(moment(entry_day, entry_hour, entry_minute),
                     moment(entry_day, entry_hour, entry_minute)+timedelta(minutes=30)),
        TimeInterval(moment(exit_day, exit_hour), moment(exit_day, exit_hour, 30)),
        100, 1100., moment(exit_day, exit_hour)))


def portfolio(day=None, *, closed=None, cost=1100.):
    return EquityPortfolio(10000. if day is None else 0., 0 if day is None else 100, 0., 1,
        None if day is None else moment(day, 10, 30), 0. if day is None else cost,
        closed_cycle_feedback=closed or EquityClosedCycleFeedback())


def context(frame, day, hour, minute=0, *, half=False, held=None, overnight=True):
    point_at = moment(day, hour, minute)
    visible = frame.loc[(frame.Date <= point_at) & (frame.AvailableDate <= point_at)].copy()
    session = TradingSession(day, str(ZONE), (TimeInterval(moment(day, 9, 30), moment(day, 13 if half else 16)),))
    return SimpleNamespace(history=visible, portfolio=held or portfolio(), session=session,
        parameters={'allow_overnight': overnight},
        point=DecisionPoint(visible.Date.iloc[-1].to_pydatetime(), point_at,
                            TimeInterval(point_at, point_at+timedelta(minutes=30))))


def facts(decision):
    return {item.key: item.text for item in decision.explanation.basis}


class MechanismChecks(unittest.TestCase):
    def test_false_matches_frozen_c0036_decision_matrix(self):
        global EQUIVALENCE_CASES
        for day, half in ((DAY, True), (MONDAY, False)):
            frame = history(day, half=half)
            for scenario in ('normal', 'equality', 'bearish_open', 'stop_then_rebound'):
                modified = frame.copy(deep=True)
                today = modified.BarStart.dt.tz_convert(str(ZONE)).dt.date == day
                indices = modified.index[today].tolist()
                if scenario == 'equality':
                    modified.loc[indices[1:], 'Close'] = 11.
                elif scenario == 'bearish_open':
                    modified.loc[indices[0], 'Close'] = 9.5
                elif scenario == 'stop_then_rebound':
                    modified.loc[indices[2], 'Close'] = 10.
                states = [portfolio(), portfolio(day),
                          portfolio(closed=feedback(day, day)),
                          portfolio(closed=feedback(day-timedelta(days=1), day-timedelta(days=1))),
                          portfolio(day-timedelta(days=1))]
                for at_hour, at_minute in ((9, 30), (10, 0), (10, 30), (11, 30),
                                          (12 if half else 15, 30)):
                    for state in states:
                        # Only compare physically valid pre-entry/feedback timing.
                        decision_at = moment(day, at_hour, at_minute)
                        if state.quantity and state.cycle_entry >= decision_at:
                            continue
                        closed = state.closed_cycle_feedback.latest
                        if closed and closed.exit_interval.end > decision_at:
                            continue
                        ctx = context(modified, day, at_hour, at_minute, half=half,
                                      held=state, overnight=False)
                        old_ctx = SimpleNamespace(**vars(ctx))
                        old_ctx.parameters = {'volume_gate': False}
                        old, new = legacy.decide(old_ctx), decide(ctx)
                        self.assertEqual(old.target, new.target)
                        self.assertEqual(old.reason, new.reason)
                        original_facts, draft_facts = facts(old), facts(new)
                        self.assertEqual(draft_facts.pop('allow_overnight'), 'False')
                        self.assertEqual(original_facts, draft_facts)
                        EQUIVALENCE_CASES += 1

    def test_true_flat_entries_match_false_and_strict_close(self):
        frame = history()
        for minute in (0, 30):
            ctx = context(frame, DAY, 10, minute, half=True)
            before = ctx.history.copy(deep=True)
            other = SimpleNamespace(**vars(ctx))
            other.parameters = {'allow_overnight': False}
            self.assertEqual(decide(ctx).target, decide(other).target)
            pd.testing.assert_frame_equal(before, ctx.history)
        ctx = context(frame, DAY, 10, 30, half=True)
        ctx.history.loc[ctx.history.index[-1], ['Close', 'High']] = [11., 1000.]
        self.assertEqual(decide(ctx).target, 0)
        ctx.history.loc[ctx.history.index[-1], 'Close'] = 11.01
        self.assertEqual(decide(ctx).target, 1)
        self.assertEqual(decide(ctx), decide(ctx))

    def test_last_interval_blocks_new_entries_but_existing_position_may_survive(self):
        for day, half, hour in ((DAY, True, 12), (MONDAY, False, 15)):
            frame = history(day, half=half)
            self.assertEqual(decide(context(frame, day, hour, 30, half=half)).target, 0)
            held = portfolio(day)
            self.assertEqual(decide(context(frame, day, hour, 30, half=half, held=held)).target, 1)
            self.assertEqual(decide(context(frame, day, hour, 30, half=half, held=held, overnight=False)).target, 0)

    def test_halfday_to_weekend_first_point_does_not_wait_for_new_opening(self):
        frame = history()
        ctx = context(frame, MONDAY, 9, 30, held=portfolio(DAY))
        result = decide(ctx)
        self.assertEqual(result.target, 1)
        self.assertEqual(facts(result)['opening_anchor_session'], str(DAY))
        self.assertEqual(facts(result)['cycle_observations'], '5')

    def test_previous_final_close_stop_exits_at_next_session_first_point(self):
        frame = history()
        frame.loc[frame.index[-1], 'Close'] = 9.
        ctx = context(frame, MONDAY, 9, 30, held=portfolio(DAY))
        result = decide(ctx)
        self.assertEqual(result.target, 0)
        self.assertEqual(facts(result)['first_trigger_at'], moment(DAY, 13).isoformat())

    def test_trigger_latches_across_weekend_despite_rebound(self):
        frame = history()
        frame.loc[frame.index[-2], 'Close'] = 10.
        frame.loc[frame.index[-1], 'Close'] = 14.
        ctx = context(frame, MONDAY, 9, 30, held=portfolio(DAY))
        self.assertEqual(decide(ctx).target, 0)
        after = pd.concat((frame, session_frame(MONDAY)), ignore_index=True)
        after.loc[after.index[-13], 'Close'] = 15.
        self.assertEqual(decide(context(after, MONDAY, 10, held=portfolio(DAY))).target, 0)

    def test_today_range_and_intrabar_high_never_reset_entry_anchor(self):
        old = history()
        today = session_frame(MONDAY, opening_high=100., opening_low=1.)
        today.loc[0, 'Close'] = 12.
        frame = pd.concat((old, today), ignore_index=True)
        ctx = context(frame, MONDAY, 10, held=portfolio(DAY))
        result = decide(ctx)
        self.assertEqual(result.target, 1)
        self.assertEqual(facts(result)['opening_range'], '2.0')
        self.assertEqual(facts(result)['initial_stop'], '9.0')
        self.assertEqual(facts(result)['peak_close'], '12.0')
        self.assertEqual(facts(result)['stop'], '10.0')

    def test_full_history_retains_entry_anchor_and_peak_beyond_261_bars(self):
        entry_day = date(2025, 9, 2)
        frame = history(entry_day, half=False)
        entry_rows = frame.BarStart.dt.tz_convert(str(ZONE)).dt.date == entry_day
        indices = frame.index[entry_rows].tolist()
        frame.loc[indices[2:], 'Close'] = 15.
        days, cursor = [], entry_day+timedelta(days=1)
        while len(days) < 23:
            if cursor.weekday() < 5:
                days.append(cursor)
            cursor += timedelta(days=1)
        for day in days:
            frame = pd.concat((frame, session_frame(day, closes=[14.]*13,
                                                    opening_high=100., opening_low=1.)), ignore_index=True)
        held = portfolio(entry_day)
        ctx = context(frame, days[-1], 15, 30, held=held)
        self.assertGreater(len(ctx.history.loc[ctx.history.Date > held.cycle_entry]), 261)
        result = decide(ctx)
        self.assertEqual(result.target, 1)
        self.assertEqual(facts(result)['opening_anchor_session'], str(entry_day))
        self.assertEqual(facts(result)['peak_close'], '15.0')
        self.assertEqual(facts(result)['stop'], '13.0')
        truncated = SimpleNamespace(**vars(ctx))
        truncated.history = ctx.history.iloc[-261:]
        with self.assertRaisesRegex(ValueError, 'exactly one 09:30'):
            decide(truncated)

    def test_missing_duplicate_zero_range_anchors_fail_explicitly(self):
        frame = history()
        ctx = context(frame, MONDAY, 9, 30, held=portfolio(DAY))
        selected = ctx.history.BarStart == moment(DAY, 9, 30)
        for variant in ('missing', 'duplicate', 'zero', 'unavailable_at_entry'):
            altered = SimpleNamespace(**vars(ctx))
            altered.history = ctx.history.copy(deep=True)
            if variant == 'missing':
                altered.history = altered.history.loc[~selected]
            elif variant == 'duplicate':
                altered.history = pd.concat((altered.history, altered.history.loc[selected]), ignore_index=True)
            elif variant == 'zero':
                altered.history.loc[selected, 'High'] = 9.
            else:
                altered.history.loc[selected, 'AvailableDate'] = moment(DAY, 11)
            with self.assertRaises(ValueError):
                decide(altered)

    def test_future_execution_bar_or_unavailable_input_is_rejected(self):
        frame = history()
        ctx = context(frame, MONDAY, 9, 30, held=portfolio(DAY))
        initial = decide(ctx)
        for future_close in (1., 1000.):
            bad = SimpleNamespace(**vars(ctx))
            future = session_frame(MONDAY, closes=[future_close])
            bad.history = pd.concat((ctx.history, future), ignore_index=True)
            with self.assertRaisesRegex(ValueError, 'future or unavailable'):
                decide(bad)
        bad = SimpleNamespace(**vars(ctx))
        bad.history = ctx.history.copy(deep=True)
        bad.history.loc[bad.history.index[-1], 'AvailableDate'] = moment(MONDAY, 10)
        with self.assertRaisesRegex(ValueError, 'future or unavailable'):
            decide(bad)
        self.assertEqual(initial, decide(ctx))

    def test_first_completed_bar_uses_close_not_unknown_execution_open(self):
        frame = history()
        today = session_frame(MONDAY)
        today.loc[0, ['Open', 'High', 'Low', 'Close']] = [5., 12., 5., 12.]
        joined = pd.concat((frame, today), ignore_index=True)
        held = portfolio(DAY)
        before = decide(context(frame, MONDAY, 9, 30, held=held))
        first_close = decide(context(joined, MONDAY, 10, held=held))
        self.assertEqual(before.target, 1)
        self.assertEqual(first_close.target, 1)
        joined.loc[joined.index[-13], 'Close'] = 9.
        self.assertEqual(decide(context(joined, MONDAY, 10, held=held)).target, 0)

    def test_actual_entry_day_limit_does_not_add_exit_day_cooldown(self):
        frame = history(MONDAY, half=False)
        previous = feedback(DAY, MONDAY, exit_hour=10)
        same = feedback(MONDAY, MONDAY, exit_hour=11)
        self.assertEqual(decide(context(frame, MONDAY, 11, 30,
                                       held=portfolio(closed=previous))).target, 1)
        self.assertEqual(decide(context(frame, MONDAY, 11, 30,
                                       held=portfolio(closed=same))).target, 0)

    def test_entry_cost_floor_and_no_partial_or_split_coverage_claim(self):
        frame = history()
        ctx = context(frame, DAY, 11, half=True, held=portfolio(DAY, cost=1400.))
        state = cycle_stop(ctx.history, ctx.portfolio,
                           entry_opening_anchor(ctx.history, ctx.portfolio, str(ZONE)))
        self.assertEqual(state['peak_close'], 14.)
        self.assertEqual(state['stop'], 12.)
        self.assertTrue(state['stop_hit'])
        ctx.portfolio = replace(ctx.portfolio, reference_price_scale=2.)
        with self.assertRaisesRegex(ValueError, 'split rebasing'):
            decide(ctx)


def main():
    legacy_before = sha256(LEGACY.read_bytes()).hexdigest()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(MechanismChecks)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    legacy_after = sha256(LEGACY.read_bytes()).hexdigest()
    report = {'status': 'PASS' if result.wasSuccessful() and legacy_before == legacy_after else 'FAIL',
        'observed_at': datetime.now(timezone.utc).isoformat(), 'synthetic_only': True,
        'formal_experiments_created_by_check': 0, 'formal_candidates_assigned_by_check': 0,
        'formal_account_replays': 0,
        'tests_run': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
        'false_policy_equivalence_cases': EQUIVALENCE_CASES,
        'frozen_c0036_path': LEGACY.relative_to(ROOT).as_posix(),
        'frozen_c0036_source_sha256_before': legacy_before,
        'frozen_c0036_source_sha256_after': legacy_after,
        'strategy_source_sha256': sha256((WORK/'src/strategy.py').read_bytes()).hexdigest(),
        'check_source_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
        'equivalence_scope': 'TESTED_TARGET_REASON_AND_ALL_ORIGINAL_FACTS_NOT_FORMAL_ACCOUNT_REPLAY',
        'contracts_unchanged': {'fee_rate': .001, 'buy_limit_premium': .01,
            'execution': 'EXISTING_WHOLE_FILL_BAR_RANGE', 'new_entry_final_interval': 'PROHIBITED'},
        'limitations': ['SYNTHETIC_ONLY', 'NO_NEW_DATA_OR_PUBLISHED_ACCOUNT_READ',
            'NO_MOC_OR_INTRABAR_STOP', 'NO_2026_PRICE', 'NO_PARTIAL_FILL_OR_SPLIT_SUPPORT']}
    (WORK/'others/precheck_mechanism.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if report['status'] != 'PASS':
        raise SystemExit(1)
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
