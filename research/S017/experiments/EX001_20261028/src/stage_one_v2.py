"""S017 stage one revision 2: typed mandate, public data preparation and evidence publication.

Run from the repository root with `prepare` or `publish`. Neither command evaluates
a strategy, computes returns, or reads the reserved validation window.
"""
from dataclasses import asdict
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import os
import sys

import pandas as pd
from dataflows import (AssetClass, BarFrequency, EquityDataRequest, EquityProduct,
                       EquityQuery, InstrumentId, MarketId, PreparePolicy,
                       ProviderConfig, SourceRef, TimeInterval, UsEquityBarPolicy,
                       futu_equity_bindings)
from strategy_runtime import (AccountPolicy, CashAvailabilityPolicy, ExecutionResources,
                              ResearchExecutionSpec, UsEquitySpec)
from strategy_evaluator import research_models as m
from czsc_trader.application import (RepositoryContext, assemble_delivery,
    create_research_context, publish_evidence, validate_experiment)
from czsc_trader.research_tools import (ResearchBatchRef, ExperimentRef,
    MaterialEvidenceWrite, ExperimentReportWrite, ExperimentOutcome,
    ExperimentValidationRequest, ExperimentValidationScope,
    EvaluationBenchmark, EquityBuyHold, EvidenceRef)
from czsc_trader.research_tools import delivery as d

ROOT = Path(__file__).resolve().parents[5]
EXPERIMENT = ExperimentRef('S017', 'EX001_20261028')
WORK = EXPERIMENT.resolve(ROOT)
REPOSITORY = RepositoryContext.discover(ROOT)
BATCH = ResearchBatchRef('S017')
SOURCE = SourceRef('futu', 's017-development-gap-known-interruptions-v1-20261028')
SPEC = ResearchExecutionSpec(UsEquitySpec(), BarFrequency.M30,
    AccountPolicy('USD', CashAvailabilityPolicy.IMMEDIATE_RESEARCH), 1, .01, .01, 0.)
RESOURCES = ExecutionResources(max_workers=4, native_threads_per_worker=1, random_seed=17)
BENCHMARK = EvaluationBenchmark(EquityBuyHold(SPEC))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def targets():
    r, dd = m.ResearchMetric.NET_ANNUAL_RETURN, m.ResearchMetric.DRAWDOWN_MAGNITUDE
    gt, le = m.ComparisonOperator.GT, m.ComparisonOperator.LE
    positive = m.BenchmarkCondition(r, gt, 0.)
    nonpositive = m.BenchmarkCondition(r, le, 0.)
    def economic(prefix, multiple, dd_multiple):
        return (m.ResearchTarget(prefix+'-return-positive', r, lower=m.BenchmarkBound(multiple, True), when=positive),
                m.ResearchTarget(prefix+'-return-nonpositive', r, lower=m.ConstantBound(0., False), when=nonpositive),
                m.ResearchTarget(prefix+'-relative-dd', dd, upper=m.BenchmarkBound(dd_multiple, True)))
    stress = {'scope': m.TargetScope.STRESS, 'one_way_cost': .002}
    return (*economic('center', 1.5, .8),
        m.ResearchTarget('center-absolute-dd', dd, upper=m.ConstantBound(.25, True)),
        m.ResearchTarget('frequency-median', m.ResearchMetric.FREQUENCY_MEDIAN, lower=m.ConstantBound(6., True)),
        m.FrequencyCoverageTarget('frequency-coverage', 60, 3, 9, 10),
        m.ParameterNeighborhoodTarget('parameters', 13, 16, economic('point', 1.25, .9),
            (m.ResearchTarget('point-absolute-dd', dd, upper=m.ConstantBound(.25, True)),)),
        m.ResearchTarget('stress-positive-return', r, lower=m.ConstantBound(0., False), **stress),
        m.ResearchTarget('stress-relative-return', r, lower=m.BenchmarkBound(1., False), **stress),
        m.ResearchTarget('stress-relative-dd', dd, upper=m.BenchmarkBound(1., False),
            when=m.BenchmarkCondition(dd, gt, 0.), **stress),
        m.ResearchTarget('stress-zero-dd', dd, upper=m.ConstantBound(0., True),
            when=m.BenchmarkCondition(dd, le, 0.), **stress),
        m.ResearchTarget('stress-absolute-dd', dd, upper=m.ConstantBound(.25, True), **stress))


def policy():
    prior = json.loads((ROOT/'research/S017/materials/pre_registration_readiness.json').read_text(encoding='utf-8'))
    intervals = tuple(TimeInterval(pd.Timestamp(e['start_et'], tz='America/New_York').to_pydatetime(),
                                  pd.Timestamp(e['resume_et'], tz='America/New_York').to_pydatetime())
                      for e in prior['known_events'])
    return UsEquityBarPolicy(1, .01, intervals)


def context(providers):
    return create_research_context(REPOSITORY, BATCH, providers=providers,
        execution_spec=SPEC, resources=RESOURCES)


def prepare():
    scratch = ROOT/'.tmp/s017-stage1-v2'
    scratch.mkdir(parents=True, exist_ok=True)
    os.environ['APPDATA'] = str(scratch/'sdk-logs')
    os.environ['TEMP'] = os.environ['TMP'] = str(scratch)
    import futu
    contract = {'version': 's017-mandate-v2', 'authorization': 'STAGE_ONE_ONLY',
        'development': ['2019-01-02', '2025-12-31'], 'warmup': ['2018-11-01', '2018-12-31'],
        'reserved': ['2026-01-02', '2026-10-27'], 'reserved_access': 'NOT_AUTHORIZED',
        'execution_spec': asdict(SPEC), 'execution_spec_hash': SPEC.fingerprint,
        'initial_cash': 100000., 'one_way_cost': .001, 'stress_cost': .002,
        'drawdown_basis': 'BAR_CLOSE', 'concentration_basis': 'MAX_SINGLE',
        'benchmark': BENCHMARK.to_dict(), 'targets': m.ResearchTargets(targets(), 60).to_dict(),
        'resource_budget': asdict(RESOURCES), 'assumption_confirmation': 'PARTIALLY_CONFIRMED',
        'confirmed_terms': ['sample_windows', 'one_way_cost', 'fixed_buy_premium'],
        'other_proposals_confirmation': 'PROPOSED', 'buy_premium_searchable': False,
        'data_source': asdict(SOURCE), 'bar_policy': asdict(policy())}
    save(WORK/'protocols/contract_v2.json', contract)
    quotes = futu.OpenQuoteContext(host='127.0.0.1', port=11111, is_async_connect=True)
    quotes.set_sync_query_connect_timeout(8)
    try:
        research = context(ProviderConfig(bindings={}, equity_bindings=futu_equity_bindings(
            source=SOURCE, quote_context=quotes, research_policy=policy())))
        requests = tuple(EquityDataRequest(InstrumentId(MarketId.US, AssetClass.STOCK, 'LITE'), SOURCE,
            EquityQuery(product, date(2018,11,1), date(2025,12,31))) for product in EquityProduct)
        prepared = research.data.prepare(requests, policy=PreparePolicy.REUSE)
        if not prepared.ready:
            raise RuntimeError([(i.request.dataset.value, str(i.error)) for i in prepared.items])
        output = {'observed_at': datetime.now(timezone.utc).isoformat(), 'status': prepared.status.value,
            'scope': 'S017 development and warmup only; no strategy/return calculation',
            'binding': {'space': research.data.binding.space.path.as_posix(),
                        'space_id': research.data.binding.space_id},
            'reference': asdict(prepared.reference), 'requests': [asdict(r) for r in requests], 'items': []}
        for item in prepared.items:
            data = research.data.fetch(item.request, prepared=prepared.reference)
            if not data.ready:
                raise RuntimeError(data.error)
            frame = data.dataframe
            row = {'product': item.request.dataset.value, 'rows': len(frame),
                   'sha256': item.identity.content_sha256,
                   'metadata': {k: v for k, v in item.identity.metadata.items() if k != 'sessions'},
                   'calendar_sessions': len(item.identity.metadata.get('sessions', ())) }
            if 'BarStatus' in frame:
                local = frame.Date.dt.tz_convert('America/New_York')
                assert local.max().date() <= date(2025,12,31)
                output['windows'] = []
                for label, mask in [('warmup', local.dt.year<2019), ('development', local.dt.year>=2019)]:
                    sub = frame.loc[mask]
                    output['windows'].append({'label': label, 'bars': len(sub),
                        'sessions': sub.Date.dt.tz_convert('America/New_York').dt.date.nunique(),
                        'statuses': sub.BarStatus.value_counts().to_dict(),
                        'known_blocked_bars': int(sub.ExecutionBlocked.sum())})
                output['blocked_intervals'] = [{'start': r.BarStart.isoformat(), 'end': r.Date.isoformat()}
                    for _, r in frame.loc[frame.ExecutionBlocked].iterrows()]
            if 'Kind' in frame:
                row['action_kinds'] = frame.Kind.value_counts().to_dict()
            output['items'].append(row)
        save(WORK/'others/data_preparation_v2.json', output)
        print(json.dumps({'status': output['status'], 'windows': output['windows'],
                          'reference': output['reference']}, ensure_ascii=False, default=str))
    finally:
        quotes.close()


def publish():
    research = context(ProviderConfig(bindings={}))
    references = []
    for name, path in [('authorization', WORK/'protocols/authorization_v2.md'),
                       ('mandate-protocol', WORK/'protocols/mandate_v2.md'),
                       ('contract', WORK/'protocols/contract_v2.json'),
                       ('data-preparation', WORK/'others/data_preparation_v2.json'),
                       ('stage-one-source', Path(__file__)),
                       ('research-policy', ROOT/'research/RSCH_AGENT.md'),
                       ('market-guidance', ROOT/'research/guides/US_RESEARCH.md'),
                       ('prior-data-audit', ROOT/'research/S017/materials/pre_registration_readiness.json')]:
        media = 'application/json' if path.suffix == '.json' else 'text/plain'
        references.append(publish_evidence(research, MaterialEvidenceWrite(EXPERIMENT, name,
            path.read_bytes(), media, path.suffix[1:])))
    auth = d.ConfirmationRecord(d.ConfirmationStatus.CONFIRMED, references[0])
    proposed = d.ConfirmationRecord(d.ConfirmationStatus.PROPOSED)
    mandate = d.ResearchMandate((
        d.MandateItem('instrument', d.MandateItemKind.TRADABLE_SYMBOL, 'US.LITE，单标的只做多、不加杠杆', auth),
        d.MandateItem('clock', d.MandateItemKind.EXECUTION, '常规时段30分钟决策', auth),
        d.MandateItem('gap-policy', d.MandateItemKind.EXECUTION, '已确认缺口不可成交及陈旧估值研究假设；不宣称停牌事实完整', auth),
        d.MandateItem('sample', d.MandateItemKind.HORIZON, '用户确认2019-2025开发池，2018-11/12预热；2026-01-02至2026-10-27保留，详见v2协议', auth),
        d.MandateItem('targets', d.MandateItemKind.OBJECTIVE, '完整采用共同政策：收益、回撤、双频率、邻域及费用压力，不以高收益抵消风险失败', proposed,
                      d.PerformanceRequirement(targets())),
        d.MandateItem('benchmark', d.MandateItemKind.BENCHMARK, '同条件可执行买入持有；固定1%买入溢价', proposed,
                      d.BenchmarkRequirement(BENCHMARK)),
        d.MandateItem('fee', d.MandateItemKind.EXECUTION, '每侧成交额0.1%简化费用，不代表实际富途账单', auth,
                      d.NumericRequirement('one_way_cost', 'ratio', .001, .001)),
        d.MandateItem('buy-premium', d.MandateItemKind.EXECUTION, '买入限价溢价固定1%，不搜索；候选与基准一致', auth,
                      d.NumericRequirement('buy_premium', 'ratio', .01, .01)),
        d.MandateItem('execution', d.MandateItemKind.EXECUTION, '100000USD，每侧0.1%，压力0.2%，1股/0.01美元，即时可用研究现金，BAR_CLOSE验收；详见合同', proposed),
        d.MandateItem('frequency_days', d.MandateItemKind.EXECUTION, '完整滚动60交易日窗口', proposed,
                      d.NumericRequirement('frequency_window_days', 'sessions', 60., 60.)),
        d.MandateItem('data', d.MandateItemKind.DATA_PERMISSION, '当前仅阶段一开发数据准备；保留样本及机制研究须另获批准', auth),
        d.MandateItem('resources', d.MandateItemKind.RESOURCE, '后续获准CPU独立评价使用4进程、每进程1线程、种子17，禁止嵌套并发', proposed),
    ))
    previous = json.loads((WORK/'others/publication.json').read_text(encoding='utf-8'))
    report = (WORK/'report.md').read_text(encoding='utf-8')
    report_ref = publish_evidence(research, ExperimentReportWrite(EXPERIMENT,
        sha256(report.encode()).hexdigest(), ExperimentOutcome.COMPLETED, tuple(references),
        previous=EvidenceRef.from_dict(previous['report'])))
    assembled = assemble_delivery(REPOSITORY, d.DeliveryDefinition(BATCH, d.DeliveryStage.MANDATE, 2,
        (d.DeliveryReference.from_dict(previous['delivery']['reference']),)),
        d.DeliveryContent(mandate, d.DeliveryStatus.COMPLETE, (), (), report=report,
                         evidence=tuple(references)+(report_ref,)), resources=RESOURCES)
    validation = validate_experiment(REPOSITORY, ExperimentValidationRequest(EXPERIMENT,
        ExperimentValidationScope.REPORT_PUBLICATION))
    save(WORK/'others/publication_v2.json', {'delivery': assembled.receipt.to_dict(),
        'validation': assembled.validation.to_dict(), 'experiment_validation': validation.to_dict(),
        'evidence': [r.to_dict() for r in references], 'report': report_ref.to_dict()})
    print(json.dumps({'delivery': assembled.receipt.reference.to_dict(),
                     'validation': assembled.validation.status.value,
                     'experiment_validation': validation.status.value}, ensure_ascii=False))


if __name__ == '__main__':
    {'prepare': prepare, 'publish': publish}[sys.argv[1]]()
