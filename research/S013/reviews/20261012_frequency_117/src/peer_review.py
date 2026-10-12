"""Read recorded S013 decisions, never calculate a strategy or potential return."""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT/'.tmp/s013-frequency-117'
IDS = ('C0507','C0509','C2008','C2009','C9029','C9030','C9070','C8880')
POSITIVE = {2020,2021,2024,2025,2026}


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def strip_ids(data):
    return [{key: value for key, value in row.items()
             if not key.endswith('_id')} for row in data]


def observable_gate_counts(run, parameters):
    """Condition on actual recorded prior holding; no policy transition simulation.

    Rebuild only causal range/ACF features with the stored execution prefix.
    Exclude missing old warmup rather than supplementing or shortening windows.
    """
    prices = run['replay_evidence']['execution_daily']
    index = {row['date'][:10]: i for i, row in enumerate(prices)}
    signals = run['signals']['data']
    counts = Counter()
    bands = Counter()
    previous_target = 0
    for row in signals:
        date = row['signal_date'][:10]
        signal_i = index[date]
        if int(row['valid_session'][:4]) not in POSITIVE:
            previous_target = row['target_position']
            continue
        route = row['regime']
        rp = parameters[route]
        if previous_target:
            counts['held_before_signal_exit_today' if row['target_position']==0
                   else 'held_before_signal_continue'] += 1
        else:
            window = rp['range_window']
            if signal_i+1 < window or signal_i < 20:
                counts['flat_insufficient_stored_warmup'] += 1
            else:
                bars = prices[signal_i-window+1:signal_i+1]
                low = min(x['low'] for x in bars)
                high = max(x['high'] for x in bars)
                position = (prices[signal_i]['close']-low)/(high-low)
                changes = [prices[j]['close']/prices[j-1]['close']-1
                           for j in range(signal_i-19,signal_i+1)]
                mean = math.fsum(changes)/20
                centered = [value-mean for value in changes]
                variance = math.fsum(value*value for value in centered)/20
                acf = (math.fsum(centered[j]*centered[j-1] for j in range(1,20))/19/variance
                       if variance > 1e-8 else None)
                acf_pass = rp['acf_min'] is None or (acf is not None and acf>=rp['acf_min'])
                if position > rp['entry']:
                    counts['flat_range_rejected'] += 1
                elif not acf_pass:
                    counts['flat_raw_acf_failed_but_actual_signal_entry' if row['target_position']
                           else 'flat_range_pass_raw_acf_failed_no_entry'] += 1
                elif row['target_position']:
                    counts['flat_basic_gates_pass_actual_signal_entry'] += 1
                else:
                    counts['flat_basic_gates_pass_no_entry_other_rules'] += 1
                if route=='bear' and .95 < position <= .985:
                    bands['flat_acf_pass' if acf_pass else 'flat_acf_reject'] += 1
        # Separately inspect the changed bear entry band even while occupied.
        if previous_target and route=='bear' and signal_i>=119:
            bars = prices[signal_i-119:signal_i+1]
            low,high = min(x['low'] for x in bars),max(x['high'] for x in bars)
            position = (prices[signal_i]['close']-low)/(high-low)
            if .95 < position <= .985:
                bands['held_before_signal'] += 1
        previous_target = row['target_position']
    return {'classification':dict(counts), 'changed_bear_entry_band':dict(bands),
            'limit':'Recorded execution prefix excludes 2019 warmup. No full-year gate rejection count claimed; other_rules is not isolated confirmation rejection. No potential trade or profit counterfactual.'}


def main():
    reviewed = read(ROOT/'.tmp/s013-new-four-203/results.json')
    rows = {row['candidate_id']:row for row in reviewed['rows']}
    loaded, proof = {}, {}
    for cid in IDS:
        item = rows[cid]
        path = ROOT/item['source']
        assert sha(path)==item['source_sha256']
        native = read(path)
        registration = read(ROOT/f'research/registrations/S013/candidates/{cid}.json')['record']
        assert registration['content_sha256']==item['content_sha256']
        payload_path = ROOT/'research/S013'/registration['payload']['path']
        assert sha(payload_path)==registration['payload']['sha256']
        payload = read(payload_path)
        sources = []
        for source in registration['source_files']:
            source_path = ROOT/'research/S013'/source['path']
            assert sha(source_path)==source['sha256']
            sources.append(source)
        run = native['runs'][0]
        loaded[cid] = run
        axis = [row['session'] for row in native['assessment_evidence'][0]['account']]
        locations = {date:i for i,date in enumerate(axis)}
        trades = run['ledgers']['trades']['data']
        closed = [row for row in trades if row['status']=='CLOSED']
        durations = [locations[row['exit_date'][:10]]-locations[row['entry_date'][:10]]
                     for row in closed]
        positive_closed = [row for row in closed if int(row['exit_date'][:4]) in POSITIVE]
        account = native['assessment_evidence'][0]['account']
        occupied = sum(row['quantity']>0 for row in account if int(row['session'][:4]) in POSITIVE)
        order_counts = Counter(row['status'] for row in run['ledgers']['orders']['data'])
        proof[cid] = {'source':item['source'], 'source_sha256':sha(path),
            'payload':registration['payload'], 'source_files':sources,
            'parameters':payload['parameters'], 'runtime_qualname':payload['runtime']['qualname'],
            'cagr':item['economics']['net_cagr'], 'drawdown':item['economics']['full_drawdown'],
            'positive_closed_cycles':len(positive_closed), 'required':77,
            'shortage':77-len(positive_closed), 'all_closed_cycles':len(closed),
            'positive_year_actual_held_sessions':occupied, 'positive_year_sessions':1152,
            'actual_closed_holding_sessions_median':median(durations),
            'actual_closed_holding_sessions_max':max(durations), 'order_status_counts':dict(order_counts),
            'observed_signal_conditions':observable_gate_counts(run,payload['parameters'])}
    reference = loaded['C0507']
    equivalence = {}
    for cid in IDS[:6]:
        run = loaded[cid]
        equivalence[cid] = {
            'signals_without_identity_exact':strip_ids(run['signals']['data'])==strip_ids(reference['signals']['data']),
            'account_exact':run['ledgers']['account_daily']['data']==reference['ledgers']['account_daily']['data'],
            'fills_without_identity_exact':strip_ids(run['ledgers']['fills']['data'])==strip_ids(reference['ledgers']['fills']['data']),
            'trades_without_identity_exact':strip_ids(run['ledgers']['trades']['data'])==strip_ids(reference['ledgers']['trades']['data']),
        }
    entry_dates = {}
    for cid in ('C9070','C8880'):
        entry_dates[cid] = {row['session'] for row in
                           read(ROOT/rows[cid]['source'])['assessment_evidence'][0]['fills']
                           if row['side']=='BUY'}
    comparison = {'common_buy_dates':len(entry_dates['C9070']&entry_dates['C8880']),
                  'short_alternative_only_buy_dates':sorted(entry_dates['C9070']-entry_dates['C8880']),
                  'original_only_buy_dates':sorted(entry_dates['C8880']-entry_dates['C9070'])}
    result = {'status':'PASS','kind':'READ_ONLY_RECORDED_RULES_AND_PARTICIPATION_REVIEW',
        'candidate_count':8, 'rows':proof, 'six_nearest_path_equivalence':equivalence,
        'C9070_C8880_buy_date_comparison':comparison,
        'recorded_actual_alternative_attribution':{
            'source':'research/S013/experiments/EX070_20261011/others/report.md:68',
            'source_sha256':sha(ROOT/'research/S013/experiments/EX070_20261011/others/report.md'),
            'alternative_only_signal_opportunities':11,'actual_source_closed_trades':10,
            'winning_source_trades':5,'losing_source_trades':5,'net_pnl_approx':-91400,
            'not_isolated_incremental_causal_profit':True},
        'limits':['No calculate_history, new strategy run, evaluation, parameter changes or profit proxy.',
                  'Same equity does not prove every unaccepted eligibility flag identical.',
                  'Occupied sessions do not prove profitable opportunities were lost.',
                  'BH positive-year labels used only for retrospective participation accounting.']}
    WORK.mkdir(parents=True,exist_ok=True)
    with (WORK/'peer_review_v2.json').open('x',encoding='utf-8') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2,allow_nan=False)
        stream.write('\n')
    print(json.dumps({'status':'PASS','equivalence':equivalence,
                      'counts':{cid:{k:v for k,v in row.items() if k in
                          ('positive_closed_cycles','positive_year_actual_held_sessions','all_closed_cycles',
                           'actual_closed_holding_sessions_median','order_status_counts','observed_signal_conditions')}
                                for cid,row in proof.items()}},ensure_ascii=False))


if __name__=='__main__':
    main()
