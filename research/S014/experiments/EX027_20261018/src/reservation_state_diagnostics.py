"""Describe actual C/R shared-entry cooldown windows; no new account or policy."""
from hashlib import sha256
import importlib.util
import json
import math
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
SOURCE = EX.parent / 'EX023_20261018'


def main():
    out = EX / 'others/reservation_state_diagnostics.json'
    if out.exists():
        raise RuntimeError('Preserve existing diagnostic evidence')
    core_path = EX.parent / 'EX018_20261017/src/account_diagnostics.py'
    spec = importlib.util.spec_from_file_location('reservation_cycle_core', core_path)
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    records = json.loads((SOURCE / 'others/comparison_accounts.json').read_text(encoding='utf-8'))['records']
    names = ('support_exit_H10', 'support_exit_reserve_H10')
    records = [r for r in records if r['variant'] in names]
    tables = {r['variant']: core.load(r) for r in records}
    c_daily = tables[names[0]]['account_daily']
    r_daily = tables[names[1]]['account_daily']
    calendar = c_daily.index
    assert calendar.equals(r_daily.index)
    cycles = pd.read_csv(SOURCE / 'others/path_cycles.csv')
    c_cycles = cycles[(cycles.window == 'ALL') & (cycles.variant == names[0])].set_index('entry_date')
    loss = json.loads((SOURCE / 'others/loss_state_diagnostics.json').read_text(encoding='utf-8'))
    episodes = [r for r in loss['episodes'] if r['window'] == 'ALL' and r['early_break']]
    windows, unmatched = [], []
    for episode in episodes:
        entry = episode['entry_date']
        if entry not in c_cycles.index:
            unmatched.append(episode)
            continue
        cycle = c_cycles.loc[entry]
        assert cycle.status == 'CLOSED' and episode['status'] == 'CLOSED'
        assert cycle.exit_or_mark_date == episode['exit_or_mark_date']
        exit_day = pd.Timestamp(episode['exit_or_mark_date'])
        end_index = calendar.get_loc(pd.Timestamp(entry)) + 10
        complete = end_index < len(calendar)
        end = calendar[min(end_index, len(calendar) - 1)]
        assert exit_day <= end
        assert c_daily.loc[exit_day, 'quantity'] == 0
        assert (r_daily.loc[exit_day:end, 'quantity'] == 0).all()
        start_equity = float(c_daily.loc[exit_day, 'equity'])
        end_equity = float(c_daily.loc[end, 'equity'])
        ret = end_equity / start_equity - 1
        new_entries = c_cycles[(pd.to_datetime(c_cycles.index) > exit_day) & (pd.to_datetime(c_cycles.index) <= end)]
        windows.append(dict(entry_date=entry, decision_date=episode['decision_date'],
            exit_date=str(exit_day.date()), reservation_close_date=str(end.date()),
            reservation_index=end_index, complete_reservation_window=complete,
            end_semantics='reservation_close' if complete else 'evaluation_end_before_reservation',
            first_break_float_pnl=episode['close_net_of_buy_fee_return'],
            positive_mark=episode['positive_mark'], C_start_equity=start_equity,
            C_end_equity=end_equity, C_window_return=ret, C_window_log=math.log1p(ret),
            C_reentry_count=len(new_entries), C_open_at_reservation_close=bool(c_daily.loc[end, 'quantity']),
            C_reentry_dates=list(new_entries.index)))
    frame = pd.DataFrame(windows)
    summaries = []
    for window in ('ALL_OBSERVED_INCLUDING_CENSORED', 'COMPLETE_WINDOWS', 'RESERVATION_CLOSE_BEFORE2026'):
        f = frame if window == 'ALL_OBSERVED_INCLUDING_CENSORED' else frame[frame.complete_reservation_window]
        if window == 'RESERVATION_CLOSE_BEFORE2026':
            f = f[f.reservation_close_date < '2026-01-01']
        for state in (False, True):
            g = f[f.positive_mark == state]
            values = g.C_window_return.sort_values()
            summaries.append(dict(window=window, positive_mark=state, n=len(g),
                reentered_windows=int((g.C_reentry_count > 0).sum()),
                reentry_count=int(g.C_reentry_count.sum()),
                open_at_reservation_close=int(g.C_open_at_reservation_close.sum()),
                mean_return=float(values.mean()), median_return=float(values.median()),
                positive_return_n=int((values > 1e-12).sum()), negative_return_n=int((values < -1e-12).sum()),
                zero_return_n=int((values.abs() <= 1e-12).sum()),
                window_log_sum=float(g.C_window_log.sum()),
                mean_remove_top3=None if len(g) <= 3 else float(values.iloc[:-3].mean())))
    sources = [Path(__file__), core_path, SOURCE / 'others/comparison_accounts.json',
        SOURCE / 'others/path_cycles.csv', SOURCE / 'others/loss_state_diagnostics.json']
    result = dict(status='PASS', new_accounts=0, new_trials=0, upstream_calls=0,
        sources={p.relative_to(ROOT).as_posix(): sha256(p.read_bytes()).hexdigest() for p in sources},
        source_records=records,
        coverage=dict(R_early_exits=len(episodes), matched_same_entry_and_exit=len(windows),
            unmatched_R_early_exits=len(unmatched), R_positive_early_exits=sum(r['positive_mark'] for r in episodes),
            matched_positive_early_exits=int(frame.positive_mark.sum()),
            complete_reservation_windows=int(frame.complete_reservation_window.sum()),
            right_censored_windows=int((~frame.complete_reservation_window).sum()),
            windows_with_C_position_at_reservation_close=int(frame.C_open_at_reservation_close.sum())),
        methodology=dict(condition='Already recorded first early-break decision close P=Close/(actual BUY price*1.001)-1>0; no threshold search.',
            anchor='Only actual C35/R56 entries with the same actual entry date and actual sale date. Start at common sale close; end at original entry+10 close, inclusive. R stays cash throughout. One end beyond the evaluation cutoff is explicitly right-censored and excluded from the primary COMPLETE_WINDOWS summary.',
            label='Actual C account NAV at reservation close / its NAV at common sale close - 1. Includes subsequent execution fees and marks open positions, without synthetic terminal sale.',
            cutoff='Reservation-close-before2026 subset, not entry-year grouping; no post-cutoff mark is used.',
            comparison='A diagnostic of actual C continuation relative to R cash inside common anchored windows. Different prior capital levels, selective common-entry coverage, and future policy path changes prevent interpreting it as a new conditional account.'),
        summaries=summaries, windows=windows,
        unmatched_episodes=[dict(entry_date=r['entry_date'],decision_date=r['decision_date'],positive_mark=r['positive_mark']) for r in unmatched],
        conclusion='Insufficient priority evidence for conditional reservation: positive-state matched coverage is only six; nonpositive-state average continuation benefit reverses after removing the best three windows. Do not attribute unmatched C/R path differences to one exit state.',
        falsifiable_candidate='If later justified, keep all support-triggered early SELLs; freeze P at the first early-break decision, retain E+10 reservation iff P>0, otherwise release only after actual SELL. Never revoke pending SELL or re-evaluate P. Compare complete actual accounts with unchanged C35/R56 and original annual goals.',
        limits=['This is a post-result route diagnostic, not a registered account or additional trial.',
            '35 matched windows contain open C positions at the end; labels are NAV window changes, not closed-trade returns. One 2026-10-12 entry sells on the last session with its reservation beyond the cutoff; its zero observed continuation is not complete-window evidence.',
            'No year switching, new threshold, parameter search, or rule change is implemented.'])
    assert result['coverage']['R_early_exits'] == 103
    assert result['coverage']['matched_same_entry_and_exit'] == 47
    assert result['coverage']['unmatched_R_early_exits'] == 56
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({'status': 'PASS', 'coverage': result['coverage']}))


if __name__ == '__main__':
    main()
