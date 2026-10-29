"""Fixed, synthetic-only four-corner comparison; no account or data access."""
from datetime import date
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

import pandas as pd


WORK = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[5]
PATHS = {
    'draft': WORK/'src/strategy.py',
    'c36_c37': ROOT/'research/S017/experiments/EX011_20261029/src/strategy.py',
    'c44': ROOT/'research/S017/experiments/EX015_20261029/src/strategy.py',
    'fixture': ROOT/'research/S017/experiments/EX015_20261029/src/check_mechanism.py',
}
HASHES = {name: sha256(path.read_bytes()).hexdigest() for name, path in PATHS.items()}


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


draft = load('_volume_overnight_draft_exact', PATHS['draft'])
legacy = load('_volume_overnight_c36_c37_exact', PATHS['c36_c37'])
c44 = load('_volume_overnight_c44_exact', PATHS['c44'])
# The historical fixture has one absolute `from strategy` import. Bind it to
# its exact historical file only during import; do not use search-path fallback.
previous_strategy = sys.modules.get('strategy')
sys.modules['strategy'] = c44
try:
    fixture = load('_volume_overnight_c44_fixture_exact', PATHS['fixture'])
finally:
    if previous_strategy is None:
        sys.modules.pop('strategy', None)
    else:
        sys.modules['strategy'] = previous_strategy


def context(original, volume=False, overnight=True):
    copied = SimpleNamespace(**vars(original))
    copied.parameters = {'volume_gate': volume, 'allow_overnight': overnight}
    return copied


def original_context(original, **parameters):
    copied = SimpleNamespace(**vars(original))
    copied.parameters = parameters
    return copied


# Reuse the existing synthetic contracts against the draft with volume disabled.
# Only this isolated in-memory module is rebound; historical files stay untouched.
fixture.decide = lambda ctx: draft.decide(context(ctx, False, ctx.parameters['allow_overnight']))
fixture.entry_opening_anchor = draft.entry_opening_anchor
fixture.cycle_stop = draft.cycle_stop
COUNTS = {'c36': 0, 'c37': 0, 'c44': 0, 'combined_held': 0, 'combined_flat': 0,
          'blocked_by_volume': 0, 'prefix_comparisons': 0}


class FourCornerChecks(fixture.MechanismChecks):
    def test_four_corner_matrix_and_original_facts(self):
        for day, half in ((fixture.DAY, True), (fixture.MONDAY, False), (date(2025,11,3), False)):
            base = fixture.history(day, half=half)
            today = base.BarStart.dt.tz_convert(str(fixture.ZONE)).dt.date == day
            opening_index = base.index[today][0]
            for volume in (50., 100., 200.):
                for stopped in (False, True):
                    frame = base.copy(deep=True)
                    frame.loc[opening_index, 'Volume'] = volume
                    if stopped:
                        frame.loc[base.index[today][2], 'Close'] = 9.
                    states = [fixture.portfolio(), fixture.portfolio(day),
                              fixture.portfolio(closed=fixture.feedback(day, day))]
                    for hour, minute in ((10,0), (10,30), (11,30), (12 if half else 15,30)):
                        when = fixture.moment(day,hour,minute)
                        for state in states:
                            if state.quantity and state.cycle_entry >= when:
                                continue
                            if state.closed_cycle_feedback.latest and state.closed_cycle_feedback.latest.exit_interval.end > when:
                                continue
                            ctx = fixture.context(frame,day,hour,minute,half=half,held=state)
                            before = ctx.history.copy(deep=True)
                            for volume_gate in (False,True):
                                old = legacy.decide(original_context(ctx,volume_gate=volume_gate))
                                new = draft.decide(context(ctx,volume_gate,False))
                                self.assertEqual((old.target,old.reason),(new.target,new.reason))
                                new_facts = fixture.facts(new)
                                self.assertEqual(new_facts.pop('allow_overnight'),'False')
                                self.assertEqual(fixture.facts(old),new_facts)
                                COUNTS['c37' if volume_gate else 'c36'] += 1
                            original = c44.decide(original_context(ctx,allow_overnight=True))
                            unchanged = draft.decide(context(ctx,False,True))
                            self.assertEqual(original,unchanged)
                            COUNTS['c44'] += 1
                            combined = draft.decide(context(ctx,True,True))
                            if state.quantity:
                                self.assertEqual((combined.target,combined.reason),(original.target,original.reason))
                                original_facts,new_facts = fixture.facts(original),fixture.facts(combined)
                                original_facts.pop('volume_gate')
                                new_facts.pop('volume_gate')
                                self.assertEqual(original_facts,new_facts)
                                COUNTS['combined_held'] += 1
                            else:
                                self.assertLessEqual(combined.target,original.target)
                                reference_entry = legacy.decide(original_context(ctx,volume_gate=True))
                                self.assertEqual(combined.target,reference_entry.target)
                                COUNTS['combined_flat'] += 1
                                COUNTS['blocked_by_volume'] += int(combined.target < original.target)
                            self.assertEqual(combined,draft.decide(context(ctx,True,True)))
                            pd.testing.assert_frame_equal(before,ctx.history)

    def test_strict_volume_mean_and_insufficient_history(self):
        frame = fixture.history()
        today = frame.BarStart.dt.tz_convert(str(fixture.ZONE)).dt.date == fixture.DAY
        first = frame.index[today][0]
        for volume,expected in ((50.,0),(100.,0),(100.0001,1),(200.,1)):
            values = frame.copy(deep=True)
            values.loc[first,'Volume'] = volume
            ctx = fixture.context(values,fixture.DAY,10,30,half=True)
            decision = draft.decide(context(ctx,True,True))
            self.assertEqual(decision.target,expected)
            self.assertEqual(fixture.facts(decision)['prior_opening_mean_volume'],'100.0')
        ctx = fixture.context(frame,fixture.DAY,10,30,half=True)
        short = SimpleNamespace(**vars(ctx))
        short.history = ctx.history.iloc[-13*13:]
        with self.assertRaisesRegex(ValueError,'14 prior'):
            draft.decide(context(short,True,True))
        # A continuing actual position does not reacquire an entry-volume gate.
        held = fixture.context(frame,fixture.DAY,11,30,half=True,held=fixture.portfolio(fixture.DAY))
        held.history = held.history.loc[held.history.BarStart >= fixture.moment(fixture.DAY,9,30)]
        self.assertEqual(draft.decide(context(held,True,True)).target,1)

    def test_combined_cross_session_anchor_stop_and_entry_day_limit(self):
        frame = fixture.history()
        monday = fixture.session_frame(fixture.MONDAY,opening_high=100.,opening_low=1.)
        monday.loc[0,'Volume'] = 200.
        joined = pd.concat([frame,monday],ignore_index=True)
        for stopped in (False,True):
            values = joined.copy(deep=True)
            if stopped:
                values.loc[len(frame)-2,'Close'] = 9.
                values.loc[len(frame)-1,'Close'] = 15.
            for hour,minute in ((9,30),(10,0),(15,30)):
                ctx = fixture.context(values,fixture.MONDAY,hour,minute,held=fixture.portfolio(fixture.DAY))
                original = c44.decide(original_context(ctx,allow_overnight=True))
                actual = draft.decide(context(ctx,True,True))
                self.assertEqual(actual.target,original.target)
                self.assertEqual(fixture.facts(actual)['opening_anchor_session'],str(fixture.DAY))
                self.assertEqual(fixture.facts(actual)['opening_range'],'2.0')
                if stopped:
                    self.assertEqual(actual.target,0)
        ordinary = fixture.history(fixture.MONDAY,half=False)
        today = ordinary.BarStart.dt.tz_convert(str(fixture.ZONE)).dt.date == fixture.MONDAY
        ordinary.loc[ordinary.index[today][0],'Volume'] = 200.
        prior_exit = fixture.feedback(fixture.DAY,fixture.MONDAY,exit_hour=10)
        current_exit = fixture.feedback(fixture.MONDAY,fixture.MONDAY,exit_hour=11)
        for closed,expected in ((prior_exit,1),(current_exit,0)):
            ctx = fixture.context(ordinary,fixture.MONDAY,11,30,held=fixture.portfolio(closed=closed))
            self.assertEqual(draft.decide(context(ctx,True,True)).target,expected)

    def test_prefix_future_and_parameter_types(self):
        frame = fixture.history()
        today = frame.BarStart.dt.tz_convert(str(fixture.ZONE)).dt.date == fixture.DAY
        frame.loc[frame.index[today][0],'Volume'] = 200.
        for hour,minute in ((10,0),(10,30),(11,30),(12,30)):
            ctx = fixture.context(frame,fixture.DAY,hour,minute,half=True)
            actual = draft.decide(context(ctx,True,True))
            changed = frame.copy(deep=True)
            changed.loc[changed.Date > ctx.point.decision_at,['Close','High','Volume']] *= 100
            prefix = fixture.context(changed,fixture.DAY,hour,minute,half=True)
            self.assertEqual(actual,draft.decide(context(prefix,True,True)))
            COUNTS['prefix_comparisons'] += 1
        ctx = fixture.context(frame,fixture.DAY,10,30,half=True)
        for parameters in ({'volume_gate':True},{'allow_overnight':True},
                {'volume_gate':1,'allow_overnight':True},{'volume_gate':True,'allow_overnight':1},
                {'volume_gate':'true','allow_overnight':True},
                {'volume_gate':True,'allow_overnight':True,'extra':False}):
            with self.assertRaisesRegex(ValueError,'two boolean'):
                draft.decide(original_context(ctx,**parameters))
        future = context(ctx,True,True)
        future.history = frame
        with self.assertRaisesRegex(ValueError,'future or unavailable'):
            draft.decide(future)

    def test_actual_entry_anchor_survives_dst_offset_change(self):
        monday, friday = date(2025,11,3), date(2025,10,31)
        frame = fixture.history(monday,half=False)
        openings = frame.loc[frame.BarStart.dt.hour.eq(9) & frame.BarStart.dt.minute.eq(30)]
        friday_open = openings.loc[openings.BarStart.dt.date == friday,'BarStart'].iloc[0]
        monday_open = openings.loc[openings.BarStart.dt.date == monday,'BarStart'].iloc[0]
        self.assertEqual(friday_open.tz_convert('UTC').hour,13)
        self.assertEqual(monday_open.tz_convert('UTC').hour,14)
        ctx = fixture.context(frame,monday,9,30,held=fixture.portfolio(friday))
        actual = draft.decide(context(ctx,True,True))
        original = c44.decide(original_context(ctx,allow_overnight=True))
        self.assertEqual(actual.target,original.target)
        self.assertEqual(fixture.facts(actual)['opening_anchor_session'],str(friday))


def main():
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(FourCornerChecks))
    after = {name:sha256(path.read_bytes()).hexdigest() for name,path in PATHS.items()}
    report = {'status':'PASS' if result.wasSuccessful() and after==HASHES else 'FAIL',
        'scope':'SYNTHETIC_ONLY_NO_REAL_ACCOUNT','tests_run':result.testsRun,
        'failures':len(result.failures),'errors':len(result.errors),'cases':COUNTS,
        'inherited_volume_disabled_c36_cases':fixture.EQUIVALENCE_CASES,
        'source_sha256_before':HASHES,'source_sha256_after':after,
        'strategy_source_sha256':HASHES['draft'],
        'check_source_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),
        'experiments_assigned_by_this_check':0,'formal_account_replays':0,
        'new_data_or_checkpoint_reads':0,'limitations':['NO_PERFORMANCE_EVIDENCE','NOT_ALL_POSSIBLE_STATES',
        'NO_NEW_REGISTRATION','NO_2026_DATA','VOLUME_AND_OVERNIGHT_INTERACTION_NOT_PROVEN']}
    (WORK/'others/precheck_mechanism.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)
    if report['status']!='PASS':
        raise SystemExit(1)


if __name__=='__main__':
    main()
