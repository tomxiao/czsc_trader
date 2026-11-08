"""Real retained observations through an isolated PTE core and recorded broker.

Not a production deployment, frozen-package inspection, or real broker trade.
"""
from dataclasses import asdict
import argparse
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import traceback
from uuid import uuid4
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[5]
EXPERIMENT = Path(__file__).resolve().parents[1]
TEMP = ROOT/'.tmp/s018-target'
TEMP.mkdir(parents=True, exist_ok=True)
os.environ.update(TEMP=str(TEMP), TMP=str(TEMP), PYTHONDONTWRITEBYTECODE='1',
                  OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
sys.dont_write_bytecode = True

from czsc_trader.application import RepositoryContext
from czsc_trader.application.ec_boundary import execution_instrument
from czsc_trader.research_tools import (EquityEvaluationRequest, ExperimentRef,
    ResearchExecutionSession, EquityBuyHold, EvaluationBenchmark)
from dataflows import EquityProduct, TimeInterval
from strategy_runtime.inspection import InspectionRuntimePermit
from paper_trading_engine.account_engine import AccountEngine
from paper_trading_engine.ec_boundary import execution_rules, execution_permit
from paper_trading_engine.equity_advice import EquityAdviceClient, prepare_equity_decision
from execution_channels.futu.broker import BrokerOrder
from execution_channels.futu.store import PaperStore
from execution_channels.futu.equity_contracts import EquityOrderReport, equity_channel_id
from execution_channels.futu.equity_execution import EquityExecution
from execution_channels.execution_effects import ExecutionEffectStatus
from candidate import build_candidate
from data_inputs import (build_data_context, prepare_raw_reference, request as data_request,
                         FIRST, MU)


class RecordedBroker:
    def __init__(self, channel_id):
        self.channel_id = channel_id
        self.submissions = []

    def place_order(self, intent):
        self.submissions.append(asdict(intent))
        return BrokerOrder('recorded-'+intent.intent_id, intent.symbol, intent.side,
            intent.quantity, intent.limit_price, 'SUBMITTED', 0, 0., intent.intent_id,
            order_type=intent.order_type)


def write(value):
    path = EXPERIMENT/'others/pte_verification.json'
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str)+'\n', encoding='utf-8')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--start',default='2026-09-01')
    parser.add_argument('--end',default='2026-10-30')
    parser.add_argument('--append-prior',action='store_true')
    args=parser.parse_args()
    prior=None
    if args.append_prior:
        prior=json.loads((EXPERIMENT/'others/pte_verification.json').read_text(encoding='utf-8'))
    report = {'status':'RUNNING', 'scope':'ISOLATED_PTE_CORE_REAL_HFQ_SIGNAL_RAW_EXECUTION',
        'not_formal_stage_five':True, 'not_live_broker_trade':True,
        'candidate_id':'C9396', 'network_requests':0,
        'requested_sessions':{'start':args.start,'end':args.end},
        'model':{'price_for_strategy':'HFQ', 'price_for_orders_and_account':'RAW',
            'initial_cash':'100000', 'one_way_fee_rate':'0.001',
            'fills':'Recorded synthetic cumulative broker reports. BUY at RAW open if open <= limit; '
                    'otherwise at limit only if RAW low < limit; otherwise cancel unfilled. '
                    'MARKET SELL at RAW open. Reports are injected before session close; '
                    'timestamps are test event order, not known intraday execution times.',
            'corporate_actions':'No dividend or split inference; no nontrade cash injected.',
            'quantity':'Actual integer share units within the isolated simulation account'},
        'limitations':['Retained data availability and tradability assumptions remain unverified historically.',
            'Record-driven broker is an isolated test double, not a Futu connection.',
            'This checks candidate/PTE core behavior, not frozen deployment or official stage-five acceptance.',
            'This is not old/new strategy economic equivalence, nor HFQ/RAW account equality.'],
        'decisions':[], 'checks':{}, 'events':[]}
    store = None
    try:
        candidate = build_candidate()
        report.update(implementation_hash=candidate.implementation_hash,
                      definition_hash=candidate.definition.content_identity.content_sha256)
        repository = RepositoryContext.discover(ROOT)
        context,sources,provenance = build_data_context(repository,candidate.definition.execution_spec)
        report['data_provenance_sha256'] = sha256(json.dumps(provenance,sort_keys=True,default=str).encode()).hexdigest()
        experiment = ExperimentRef('S018',EXPERIMENT.name)
        zone = ZoneInfo('America/New_York')
        request = EquityEvaluationRequest(experiment,candidate,
            TimeInterval(datetime(2023,1,3,9,30,tzinfo=zone),datetime(2026,10,30,16,tzinfo=zone)),
            FIRST,sources,100000.,.001,benchmark=EvaluationBenchmark(EquityBuyHold(candidate.definition.execution_spec)),
            drawdown_basis='BAR_CLOSE',concentration_basis='MAX_SINGLE')
        with ResearchExecutionSession(context,experiment=experiment) as session:
            prepared_request = context.evaluation.prepare(request,execution=session).request
        binding = prepared_request.input_binding
        raw_binding = prepare_raw_reference(context)
        raw_result = context.data.fetch(data_request(MU,EquityProduct.BARS),prepared=raw_binding.prepared)
        if not raw_result.ready:
            raise RuntimeError(raw_result.error)
        raw = raw_result.dataframe
        local_dates = raw.BarStart.dt.tz_convert(zone).dt.date
        selected = raw.loc[(local_dates>=datetime.fromisoformat(args.start).date()) &
                           (local_dates<=datetime.fromisoformat(args.end).date())]
        report['raw_binding'] = raw_binding.to_dict()
        report['hfq_binding'] = binding.to_dict()
        run_id = 's018-target-pte-'+uuid4().hex[:12]
        workspace = ROOT/'.tmp/strategy-inspection'/run_id
        isolated = workspace/'repository'
        isolated.mkdir(parents=True)
        content_hash = candidate.definition.content_identity.content_sha256
        protocol_hash = sha256(json.dumps(report['model'],sort_keys=True).encode()).hexdigest()
        permit = InspectionRuntimePermit(run_id,'S018-v1',content_hash,candidate.implementation_hash,
                                         protocol_hash,isolated,workspace)
        store = PaperStore(workspace/'paper.db',inspection_permit=execution_permit(permit))
        report['isolated_database'] = store.path.relative_to(ROOT).as_posix()
        channel_id = equity_channel_id(execution_instrument(candidate.instrument))
        account_id = 'S018-C9396-isolated'
        store.create_virtual_account(account_id,'S018 target-weight isolated core','v1',content_hash,100000.,
            symbol='MU',asset_type='stock',strategy_id='S018',strategy_name_snapshot='C9396 technical isolation',
            strategy_version='v1',release_hash=content_hash,qualification_snapshot='INSPECTION',
            selection_data_cutoff='2026-10-30',channel_id=channel_id,
            equity_rules=execution_rules(candidate.instrument,context.execution_spec))
        store.set_virtual_paused(account_id,False)
        broker = RecordedBroker(channel_id)
        independent_cash,independent_quantity = Decimal('100000'),0
        partial_checked = restart_checked = duplicate_checked = submission_checked = False
        idempotent_decisions = 0
        for row in selected.itertuples():
            interval = TimeInterval(row.BarStart.to_pydatetime(),row.Date.to_pydatetime())
            reference = raw_binding.fetch(context.data,interval,
                latency_seconds=context.execution_spec.data_latency_seconds)
            prepared = prepare_equity_decision(context.data,candidate,binding,
                prepared_request.requests(context.execution_spec),interval,fee_rate=.001,
                execution_reference=reference)
            at = interval.start
            engine = AccountEngine(store,EquityAdviceClient(store),now=lambda:at)
            engine.refresh_account(account_id,prepared=prepared)
            account = store.virtual_account(account_id)
            decision_id = account['last_decision_id']
            frozen_state = account['account_v4_json']
            count_before = len(store.account_decisions(account_id))
            engine.refresh_account(account_id,prepared=prepared)
            assert store.virtual_account(account_id)['account_v4_json']==frozen_state
            assert len(store.account_decisions(account_id))==count_before
            idempotent_decisions += 1
            execution = EquityExecution(store,broker,now=lambda:at)
            execution.reconcile(cash=independent_cash,quantity=independent_quantity,account_id=account_id)
            before = store.decision_execution_effect(account_id,decision_id,
                valuation_price=reference.price,at=at)
            order_ids = execution.submit_pending(account_id)
            submitted = store.decision_execution_effect(account_id,decision_id,
                valuation_price=reference.price,at=at)
            assert submitted.actual_quantity==before.actual_quantity
            assert submitted.cash==before.cash
            if order_ids:
                assert submitted.status is ExecutionEffectStatus.WAITING
                submission_checked=True
            order_results=[]
            for order_id in order_ids:
                order=store.account_order(order_id)
                quantity=order['quantity']
                limit=Decimal(str(order['limit_price']))
                raw_open,raw_low=Decimal(str(row.Open)),Decimal(str(row.Low))
                fill_price = (raw_open if order['side']=='SELL' or raw_open<=limit
                              else limit if raw_low<limit else None)
                if fill_price is None:
                    final_report=EquityOrderReport(order_id,0,Decimal(0),interval.end-timedelta(seconds=1),'CANCELLED_ALL')
                    execution.apply_report(final_report)
                    order_results.append({'order_id':order_id,'side':order['side'],'quantity':quantity,
                        'fill_quantity':0,'status':'CANCELLED_ALL','reason':'RAW_BAR_DID_NOT_TOUCH_LIMIT'})
                    continue
                if not partial_checked and quantity>1:
                    when=interval.end-timedelta(minutes=2)
                    partial=EquityOrderReport(order_id,1,fill_price,when,'FILLED_PART')
                    execution.apply_report(partial)
                    effect=store.decision_execution_effect(account_id,decision_id,valuation_price=fill_price,at=when)
                    assert effect.status is ExecutionEffectStatus.PARTIAL and not effect.terminal
                    state_before=store.virtual_account(account_id)['account_v4_json']
                    execution.apply_report(partial)
                    assert store.decision_execution_effect(account_id,decision_id,valuation_price=fill_price,at=when)==effect
                    assert store.virtual_account(account_id)['account_v4_json']==state_before
                    report['events'].append({'kind':'PARTIAL_DUPLICATE_RESTART','effect':asdict(effect)})
                    path=store.path
                    store.close()
                    store=PaperStore(path,inspection_permit=execution_permit(permit))
                    assert store.virtual_account(account_id)['account_v4_json']==state_before
                    assert store.decision_execution_effect(account_id,decision_id,valuation_price=fill_price,at=when)==effect
                    execution=EquityExecution(store,broker,now=lambda:at)
                    partial_checked=restart_checked=duplicate_checked=True
                when=interval.end-timedelta(minutes=1)
                final_report=EquityOrderReport(order_id,quantity,fill_price,when,'FILLED_ALL')
                execution.apply_report(final_report)
                done=store.decision_execution_effect(account_id,decision_id,valuation_price=fill_price,at=when)
                assert done.status is ExecutionEffectStatus.COMPLETED and done.terminal
                execution.apply_report(final_report)
                assert store.decision_execution_effect(account_id,decision_id,valuation_price=fill_price,at=when)==done
                gross=fill_price*quantity
                fee=(gross*Decimal('.001')).quantize(Decimal('.0001'))
                independent_cash += (-gross-fee if order['side']=='BUY' else gross-fee)
                independent_quantity += quantity if order['side']=='BUY' else -quantity
                order_results.append({'order_id':order_id,'side':order['side'],'quantity':quantity,
                    'fill_quantity':quantity,'price':str(fill_price),'fee':str(fee),'status':'FILLED_ALL'})
            execution.reconcile(cash=independent_cash,quantity=independent_quantity,account_id=account_id)
            effect=store.decision_execution_effect(account_id,decision_id,valuation_price=Decimal(str(row.Close)),at=interval.end)
            assert effect.actual_quantity==independent_quantity and effect.cash==independent_cash
            assert effect.equity==independent_cash+effect.receivable+independent_quantity*Decimal(str(row.Close))
            assert not store.account_invariant_violations()
            document=json.loads(store.virtual_account(account_id)['account_v4_json'])
            report['decisions'].append({'session':row.BarStart.tz_convert(zone).date().isoformat(),
                'signal_hfq_close':float(prepared.history.Close.iloc[-1]),
                'execution_raw_reference':str(reference.price),
                'observed_through':reference.observed_through.isoformat(),
                'before':asdict(before),'after_submission':asdict(submitted),'after':asdict(effect),
                'orders':order_results,'state':document['state']})
            print('PTE',report['decisions'][-1]['session'],'target',effect.target_weight,
                  'actual',effect.actual_weight,'orders',len(order_ids),flush=True)
        report['checks']={'submission_does_not_change_holdings_or_cash':submission_checked,
            'partial_fill':partial_checked,'duplicate_report_idempotent':duplicate_checked,
            'restart_mid_order':restart_checked,'duplicate_decisions':idempotent_decisions,
            'independent_cash_and_quantity_reconciled_each_session':True,'account_invariant_violations':0}
        report['fills']=store.account_fills(account_id)
        report['final_account']=store.virtual_account(account_id)
        report['broker_submissions']=broker.submissions
        report['session_count']=len(report['decisions'])
        targets=[r['after']['target_weight'] for r in report['decisions']]
        states=[r['state']['cycle'] for r in report['decisions']]
        report['coverage']={'entry':any(x>0 for x in targets),
            'promoted_target':any(s is not None and dict(s['values']['values']).get('promoted') for s in states),
            'exit_after_holding':any(targets[i]==0 and targets[i-1]>0 for i in range(1,len(targets))),
            'distinct_targets':sorted(set(targets)),
            'raw_hfq_price_difference_observed':any(float(r['execution_raw_reference'])!=r['signal_hfq_close'] for r in report['decisions'])}
        assert all(report['coverage'][key] for key in ('entry','promoted_target','exit_after_holding'))
        assert all((partial_checked,restart_checked,duplicate_checked,submission_checked))
        report['status']='PASS'
        if prior is not None:
            report['previous_scenarios']=[prior]
            report['prior_scope_note']='Prior 43-session run completed its core accounting, partial/duplicate/restart checks; '
            report['prior_scope_note']+='its final coverage assertion failed because the chosen dates did not include a promoted target. '
            report['prior_scope_note']+='That original diagnostic is retained; this independent added window covers promotion without rerunning it.'
            report['total_sessions']=report['session_count']+prior['session_count']
            report['total_fills']=len(report['fills'])+len(prior['fills'])
            report['combined_coverage']={key:any((report['coverage'][key],prior['coverage'][key]))
                for key in ('entry','promoted_target','exit_after_holding','raw_hfq_price_difference_observed')}
        write(report)
        print(json.dumps({'status':'PASS','sessions':report['session_count'],'fills':len(report['fills']),
                          'coverage':report['coverage']},ensure_ascii=False),flush=True)
        return 0
    except Exception as exc:
        report.update(status='FAILED',error_type=type(exc).__name__,error=str(exc),traceback=traceback.format_exc())
        write(report)
        print(traceback.format_exc(),flush=True)
        return 1
    finally:
        if store is not None:
            store.close()


if __name__=='__main__':
    raise SystemExit(main())
