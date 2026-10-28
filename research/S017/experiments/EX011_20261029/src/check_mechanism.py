"""Synthetic mechanism checks only; no research data or account replay."""
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
import unittest
from zoneinfo import ZoneInfo

import pandas as pd
from dataflows import TimeInterval, TradingSession
from strategy_runtime import (DecisionPoint, EquityPortfolio, EquityClosedCycle,
                              EquityClosedCycleFeedback)
from strategy import decide, opening_facts, cycle_stop


ZONE = ZoneInfo('America/New_York')


def moment(day, hour, minute=0):
    return datetime.combine(day, time(hour, minute), tzinfo=ZONE)


def history(day, *, volume=200., close=11.5, count=14):
    days = []
    cursor = day-timedelta(days=1)
    while len(days) < count:
        if cursor.weekday() < 5 and cursor != date(2025, 11, 27):
            days.append(cursor)
        cursor -= timedelta(days=1)
    rows = []
    for prior in reversed(days):
        for n in range(13):
            start = moment(prior, 9, 30)+timedelta(minutes=30*n)
            rows.append(dict(BarStart=start, Date=start+timedelta(minutes=30),
                AvailableDate=start+timedelta(minutes=30), Open=10., High=11., Low=9.,
                Close=10.5, Volume=100.))
    for n, value in enumerate((10.5, close)):
        start = moment(day, 9, 30)+timedelta(minutes=30*n)
        rows.append(dict(BarStart=start, Date=start+timedelta(minutes=30),
            AvailableDate=start+timedelta(minutes=30), Open=10. if n == 0 else 10.5,
            High=11. if n == 0 else max(11.5, value), Low=9. if n == 0 else min(10., value),
            Close=value, Volume=volume if n == 0 else 100.))
    return pd.DataFrame(rows)


def add_close(frame, value):
    start = frame.Date.iloc[-1].to_pydatetime()
    row = dict(BarStart=start, Date=start+timedelta(minutes=30),
        AvailableDate=start+timedelta(minutes=30), Open=float(frame.Close.iloc[-1]),
        High=max(float(frame.Close.iloc[-1]), value), Low=min(float(frame.Close.iloc[-1]), value),
        Close=value, Volume=100.)
    return pd.concat((frame, pd.DataFrame([row])), ignore_index=True)


def context(frame, *, gate=False, day=None, hour=None, minute=0, half=False, portfolio=None):
    day = day or frame.Date.iloc[-1].date()
    at = (frame.Date.iloc[-1].to_pydatetime() if hour is None else moment(day, hour, minute))
    session = TradingSession(day, str(ZONE), (TimeInterval(moment(day, 9, 30), moment(day, 13 if half else 16)),))
    portfolio = portfolio or EquityPortfolio(10000., 0, 0., 0,
                                             closed_cycle_feedback=EquityClosedCycleFeedback())
    return SimpleNamespace(history=frame, portfolio=portfolio, session=session,
        parameters={'volume_gate': gate}, point=DecisionPoint(frame.Date.iloc[-1].to_pydatetime(), at,
        TimeInterval(at, at+timedelta(minutes=30))))


class MechanismChecks(unittest.TestCase):
    day = date(2025, 11, 26)

    def test_strict_completed_close_breakout(self):
        frame = history(self.day, close=11.)
        self.assertEqual(decide(context(frame)).target, 0)
        frame.loc[frame.index[-1], 'High'] = 100.
        self.assertEqual(decide(context(frame)).target, 0)
        frame.loc[frame.index[-1], 'Close'] = 11.01
        self.assertEqual(decide(context(frame)).target, 1)

    def test_opening_direction_and_first_bar_not_sufficient(self):
        frame = history(self.day)
        self.assertEqual(decide(context(frame.iloc[:-1])).target, 0)
        frame.loc[frame.index[-2], 'Close'] = 9.5
        self.assertEqual(decide(context(frame)).target, 0)

    def test_volume_control_only_changes_gate(self):
        frame = history(self.day, volume=100.)
        self.assertEqual(decide(context(frame, gate=False)).target, 1)
        self.assertEqual(decide(context(frame, gate=True)).target, 0)
        frame.loc[frame.index[-2], 'Volume'] = 100.1
        self.assertEqual(decide(context(frame, gate=True)).target, 1)

    def test_volume_denominator_excludes_today(self):
        frame = history(self.day, volume=10000.)
        facts, _ = opening_facts(frame, context(frame).session, True)
        self.assertEqual(facts['prior_opening_mean_volume'], 100.)
        self.assertEqual(facts['opening_relative_volume'], 100.)
        frame.loc[frame.index[-1], 'Volume'] = 99999999.
        again, _ = opening_facts(frame, context(frame).session, True)
        self.assertEqual(facts, again)

    def test_volume_gate_refuses_insufficient_prior_sessions(self):
        frame = history(self.day, count=13)
        with self.assertRaisesRegex(ValueError, '14 prior completed'):
            decide(context(frame, gate=True))
        self.assertEqual(decide(context(frame, gate=False)).target, 1)

    def test_unfilled_intent_can_retry_but_actual_cycle_prevents_reentry(self):
        frame = history(self.day)
        ctx = context(frame)
        self.assertEqual(decide(ctx), decide(ctx))
        self.assertEqual(decide(ctx).target, 1)
        frame = add_close(add_close(frame, 12.), 12.5)
        cycle = EquityClosedCycle('filled-cycle', TimeInterval(moment(self.day, 10, 30), moment(self.day, 11)),
            TimeInterval(moment(self.day, 11), moment(self.day, 11, 30)), 100, 1100., moment(self.day, 11))
        closed = replace(ctx.portfolio, revision=2, closed_cycle_feedback=EquityClosedCycleFeedback(cycle))
        self.assertEqual(decide(context(frame, portfolio=closed)).target, 0)

    def test_prior_day_closed_entry_does_not_consume_current_day(self):
        frame = history(self.day)
        prior = self.day-timedelta(days=1)
        closed = EquityClosedCycle('prior-cycle', TimeInterval(moment(prior, 10, 30), moment(prior, 11)),
            TimeInterval(moment(prior, 11), moment(prior, 11, 30)), 100, 1100., moment(prior, 11))
        portfolio = EquityPortfolio(10000., 0, 0., 1, closed_cycle_feedback=EquityClosedCycleFeedback(closed))
        self.assertEqual(decide(context(frame, portfolio=portfolio)).target, 1)

    def test_actual_entry_excludes_preentry_peak(self):
        frame = history(self.day, close=20.)
        frame = add_close(frame, 12.)
        prior = self.day-timedelta(days=1)
        closed = EquityClosedCycle('old-cycle', TimeInterval(moment(prior, 10, 30), moment(prior, 11)),
            TimeInterval(moment(prior, 11), moment(prior, 11, 30)), 100, 5000., moment(prior, 11))
        portfolio = EquityPortfolio(0., 100, 0., 1, moment(self.day, 10, 30), 1100.,
                                   closed_cycle_feedback=EquityClosedCycleFeedback(closed))
        facts, current = opening_facts(frame, context(frame).session, False)
        state = cycle_stop(current, portfolio, facts)
        self.assertEqual(state['peak_close'], 12.)
        self.assertEqual(state['stop'], 10.)
        self.assertFalse(state['stop_hit'])
        self.assertEqual(decide(context(frame, portfolio=portfolio)).target, 1)

    def test_initial_opening_low_and_actual_cost_lower_bound(self):
        frame = add_close(history(self.day), 10.2)
        portfolio = EquityPortfolio(0., 100, 0., 1, moment(self.day, 10, 30), 1050.,
                                   closed_cycle_feedback=EquityClosedCycleFeedback())
        facts, current = opening_facts(frame, context(frame).session, False)
        state = cycle_stop(current, portfolio, facts)
        self.assertEqual(state['peak_close'], 10.5)
        self.assertEqual(state['initial_stop'], 9.)
        self.assertEqual(state['stop'], 9.)
        self.assertEqual(decide(context(frame, portfolio=portfolio)).target, 1)
        frame = add_close(frame, 9.)
        self.assertEqual(decide(context(frame, portfolio=portfolio)).target, 0)

    def test_stop_ratchet_and_exit_latch_survive_rebound(self):
        frame = add_close(history(self.day), 12.)
        portfolio = EquityPortfolio(0., 100, 0., 1, moment(self.day, 10, 30), 1100.,
                                   closed_cycle_feedback=EquityClosedCycleFeedback())
        self.assertEqual(decide(context(frame, portfolio=portfolio)).target, 1)
        frame = add_close(frame, 10.)
        self.assertEqual(decide(context(frame, portfolio=portfolio)).target, 0)
        frame = add_close(frame, 14.)
        self.assertEqual(decide(context(frame, portfolio=portfolio)).target, 0)
        facts, current = opening_facts(frame, context(frame).session, False)
        state = cycle_stop(current, portfolio, facts)
        self.assertEqual(state['levels'], sorted(state['levels']))
        self.assertEqual(state['levels'], [10., 10., 12.])

    def test_regular_and_halfday_last_execution_interval_exits_and_blocks_entry(self):
        for day, half, hour in ((self.day, False, 15), (date(2025, 11, 28), True, 12)):
            frame = history(day)
            while frame.Date.iloc[-1] < moment(day, hour, 30):
                frame = add_close(frame, float(frame.Close.iloc[-1])+.2)
            flat = context(frame, half=half)
            held = replace(flat.portfolio, cash=0., quantity=100, cycle_entry=moment(day, 10, 30), cycle_cost=1100.)
            self.assertEqual(decide(flat).target, 0)
            self.assertEqual(decide(context(frame, half=half, portfolio=held)).target, 0)

    def test_overnight_residual_exits_before_new_opening_bar(self):
        frame = history(self.day)
        next_day = date(2025, 11, 28)
        portfolio = EquityPortfolio(0., 100, 0., 1, moment(self.day, 10, 30), 1100.,
                                   closed_cycle_feedback=EquityClosedCycleFeedback())
        self.assertEqual(decide(context(frame, day=next_day, hour=9, minute=30, half=True,
                                       portfolio=portfolio)).target, 0)

    def test_input_immutability_and_complete_explanation(self):
        frame = history(self.day)
        before = frame.copy(deep=True)
        ctx = context(frame, gate=True)
        first, second = decide(ctx), decide(ctx)
        self.assertEqual(first, second)
        pd.testing.assert_frame_equal(frame, before)
        self.assertTrue(first.explanation.basis)
        self.assertTrue(first.explanation.next_watch)
        self.assertEqual(ctx.parameters, {'volume_gate': True})


if __name__ == '__main__':
    unittest.main(verbosity=2)
