"""Qualified frozen V4 strategies in the normal durable PTE account lifecycle.

Inputs are explicit pinned DFLS publications. An existing decision interval never
silently fetches replacement inputs. Host execution context and known calendars
may extend beyond completed historical prices; no future OHLCV row is fabricated.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
import json
import math
from pathlib import Path
import re
from threading import Lock, RLock
from zoneinfo import ZoneInfo

from dataflows import BarFrequency, Dataflows, DataRequest, EquityDataRequest, TimeInterval, EquityProduct, PreparePolicy, PrepareResult
from dataflows.equity_data import sessions_from_metadata
from strategy_manager import Qualification, StrategyRegistry
from strategy_runtime import StrategyRelease, canonical_sha256
from strategy_runtime.deployment import load_strategy_deployment
from strategy_runtime.equity_definition import EquityInputBinding, EquityStrategyCandidate, EquityStrategyDefinition, InputBindingScope
from strategy_runtime.equity_definition import EquityAuxiliaryBinding

from .account_binding import AccountStrategyBinding
from .execution_reference import ExecutionReferenceBinding
from .equity_advice import EquityAdviceClient, PreparedEquityDecision, prepare_equity_decision
from .srt_advice_client import _strategy_identity
from .scheduling_contracts import ScheduledDecision


@dataclass(frozen=True, slots=True)
class FormalV4Inputs:
    release_hash: str
    binding: EquityInputBinding
    fee_rate: float
    execution_reference: ExecutionReferenceBinding

    def __post_init__(self):
        if type(self.release_hash) is not str or re.fullmatch('[0-9a-f]{64}', self.release_hash) is None:
            raise ValueError('V4 inputs require the exact release hash')
        if type(self.binding) is not EquityInputBinding or not self.binding.request_bindings:
            raise ValueError('formal V4 inputs require explicit request roles')
        if (type(self.execution_reference) is not ExecutionReferenceBinding
                or self.execution_reference.parameters.instrument != self.binding.instrument):
            raise ValueError('formal V4 inputs require a separate RAW execution binding for the traded instrument')
        if type(self.fee_rate) not in (float, int) or not math.isfinite(self.fee_rate) or not 0 <= self.fee_rate < 1:
            raise ValueError('formal V4 inputs require a finite model fee')

    @property
    def strategy_requests(self) -> tuple[DataRequest, ...]:
        unique = dict.fromkeys(parameters for _, parameters in self.binding.request_bindings)
        return (tuple(EquityDataRequest(p.instrument, p.source, p.query) for p in unique)
                + tuple(item.request for item in self.binding.observation_bindings if item.request is not None))

    @property
    def requests(self) -> tuple[DataRequest, ...]:
        return self.strategy_requests + (self.execution_reference.request,)

    def to_dict(self):
        return dict(schema_version=3, release_hash=self.release_hash,
                    binding=self.binding.to_dict(), fee_rate=self.fee_rate,
                    execution_reference=self.execution_reference.to_dict())

    def validate_candidate(self, release_hash: str, candidate: EquityStrategyCandidate) -> None:
        """Check a saved input declaration against the exact frozen definition."""
        binding, definition = self.binding, candidate.definition
        if self.execution_reference.parameters.query.frequency is not definition.execution_spec.decision_clock:
            raise ValueError('execution reference frequency differs from the frozen decision clock')
        execution = None if binding.execution_input is None else binding.execution_input.input
        if (self.release_hash != release_hash or binding.instrument != candidate.instrument
                or binding.specification_hash != candidate.execution_spec_hash
                or binding.warmup_bars != candidate.warmup_bars
                or tuple(item.input for item in binding.observation_bindings) != definition.observation_inputs
                or tuple(item.input for item in binding.auxiliary_inputs) != definition.auxiliary_inputs
                or (binding.scope is InputBindingScope.EXECUTION and execution != definition.execution_input)):
            raise ValueError('formal V4 input identity differs from account release')
        binding.bind_requests(self.strategy_requests)

    @classmethod
    def from_dict(cls, value):
        if (type(value) is not dict or set(value) != {'schema_version', 'release_hash', 'binding', 'fee_rate', 'execution_reference'}
                or type(value['schema_version']) is not int or value['schema_version'] != 3):
            raise ValueError('unsupported formal V4 input contract; migrate the account data recipe')
        return cls(value['release_hash'], EquityInputBinding.from_dict(value['binding']), value['fee_rate'],
                   ExecutionReferenceBinding.from_dict(value['execution_reference']))


class _CalendarPreparationError(ValueError):
    def __init__(self, result: PrepareResult):
        super().__init__('forward V4 calendar preparation is incomplete')
        self.result = result


class FormalV4AdviceClient:
    def __init__(self, *, repo_root: Path | str, store, dataflows: Dataflows | None, data_dir: Path | str,
                 inspection_permit=None):
        self.repo_root = Path(repo_root).resolve()
        self.store, self.dataflows = store, dataflows
        self.data_dir = Path(data_dir).resolve()
        if inspection_permit is not None:
            from strategy_runtime.inspection import InspectionRuntimePermit
            if type(inspection_permit) is not InspectionRuntimePermit:
                raise TypeError('V4 inspection requires a typed isolated permit')
            if self.repo_root != inspection_permit.isolated_repository:
                raise ValueError('V4 inspection repository differs from permit')
            inspection_permit.validate_path(self.data_dir)
            inspection_permit.validate_path(store.path)
            from .ec_boundary import execution_permit
            if getattr(store, '_inspection_permit', None) != execution_permit(inspection_permit):
                raise ValueError('V4 inspection store differs from permit')
        self.inspection_permit = inspection_permit
        self._lock = RLock()
        self._calendars = {}
        self._decision_cycles = {}

    def decision_cycle_lock(self, account_id: str):
        with self._lock:
            return self._decision_cycles.setdefault(account_id, Lock())

    def _path(self, account_id):
        if type(account_id) is not str or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', account_id) is None:
            raise ValueError('invalid formal V4 account id')
        return self.data_dir / 'v4-inputs' / (account_id + '.json')

    def load_release(self, strategy_id, strategy_version):
        release_id = f'{strategy_id}-{strategy_version}'
        if self.inspection_permit is None:
            deployment = load_strategy_deployment(self.repo_root / 'strategies', release_id)
        else:
            from strategy_runtime.deployment import load_inspection_deployment
            deployment = load_inspection_deployment(self.repo_root / 'strategies', release_id, self.inspection_permit)
        raw = json.loads((self.repo_root / 'strategies' / strategy_id / 'versions' / f'{strategy_version}.json').read_text(encoding='utf-8'))
        release = StrategyRelease.from_mapping(raw)
        if release.release_hash != deployment.release_hash or release.payload['runtime']['kind'] != 'ACCOUNT_REPLAY':
            raise ValueError('formal V4 deployment differs from native release')
        identity = _strategy_identity(self.repo_root, release, self.inspection_permit)
        definition = EquityStrategyDefinition.from_dict(dict(release.payload['equity_definition']))
        candidate = EquityStrategyCandidate(strategy_id, deployment.runtime_candidate_id, definition, deployment.source_root)
        if definition.contract_version != 4:
            raise ValueError('formal V4 requires the account contract')
        return release, candidate, identity

    def validate_account_binding(self, *, strategy_id: str, strategy_version: str,
                                 symbol: str, asset: str, fee_rate: float) -> AccountStrategyBinding:
        release, candidate, identity = self.load_release(strategy_id, strategy_version)
        if (symbol != candidate.instrument.symbol or asset != candidate.instrument.asset_class.value.lower()):
            raise ValueError('V4 account instrument differs from frozen strategy')
        version = StrategyRegistry(self.repo_root / 'strategies').get_version(strategy_id, strategy_version)
        return AccountStrategyBinding(strategy_id, strategy_version, release.release_hash, identity['name'],
            Qualification(identity['qualification']), date.fromisoformat(version.selection_data_cutoff), symbol,
            fee_rate, instrument=candidate.instrument)

    def _account_release(self, account_id):
        account = self.store.virtual_account(account_id)
        if account['run_state'] in {'RETIRING', 'RETIRED'}:
            raise ValueError('inactive account cannot load a strategy for execution')
        release, candidate, _ = self.load_release(account['strategy_id'], account['strategy_version'])
        rules = self.store.equity_account_rules(account_id)
        from .ec_boundary import execution_rules
        if (account['release_hash'] != release.release_hash or rules is None
                or rules.to_dict() != execution_rules(candidate.instrument, candidate.definition.execution_spec).to_dict()):
            raise ValueError('formal V4 account differs from qualified release and execution rules')
        return account, release, candidate

    def register_inputs(self, account_id: str, binding: EquityInputBinding, *,
                        expected_release_hash: str, fee_rate: float, execution_reference: ExecutionReferenceBinding) -> str:
        return self._register(account_id, FormalV4Inputs(expected_release_hash, binding, fee_rate, execution_reference), forward=False)

    def _register(self, account_id: str, inputs: FormalV4Inputs, *, forward: bool) -> str:
        _, release, candidate = self._account_release(account_id)
        inputs.validate_candidate(release.release_hash, candidate)
        inputs = replace(inputs, binding=inputs.binding.for_observations())
        if forward and candidate.definition.execution_spec.decision_clock is not BarFrequency.DAILY:
            raise ValueError('automatic live M30 requires a DFLS partial-session product; only DAILY is supported')
        path = self._path(account_id)
        value = inputs.to_dict()
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        identity = canonical_sha256(value)
        if self.store.v4_runtime_binding(account_id) is not None:
            self.store.replace_v4_runtime_inputs(account_id, value, forward=forward)
            return identity
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            archive = path.parent / 'records' / (identity + '.json')
            archive.parent.mkdir(exist_ok=True)
            if archive.exists():
                if archive.read_text(encoding='utf-8') != payload:
                    raise ValueError('immutable V4 input record differs from its identity')
            else:
                with archive.open('x', encoding='utf-8') as handle:
                    handle.write(payload)
            temporary = path.with_suffix('.pending')
            temporary.write_text(payload, encoding='utf-8')
            temporary.replace(path)
            if forward:
                recipe_path = path.with_suffix('.recipe.json')
                temporary.write_text(json.dumps({'schema_version': 2, 'kind': 'DAILY_FORWARD_V2',
                                                 'inputs': value}, sort_keys=True), encoding='utf-8')
                temporary.replace(recipe_path)
        return identity

    def inputs(self, account_id: str) -> FormalV4Inputs:
        stored = self.store.v4_runtime_binding(account_id)
        if stored is not None:
            return FormalV4Inputs.from_dict(stored['inputs'])
        return FormalV4Inputs.from_dict(json.loads(self._path(account_id).read_text(encoding='utf-8')))

    def register_recipe(self, account_id: str, inputs: FormalV4Inputs) -> str:
        """Declare automatic DAILY preparation using explicit source/role/range inputs."""
        if type(inputs) is not FormalV4Inputs:
            raise TypeError('forward preparation requires FormalV4Inputs')
        return self._register(account_id, inputs, forward=True)

    def recipe(self, account_id: str) -> FormalV4Inputs | None:
        stored = self.store.v4_runtime_binding(account_id)
        if stored is not None:
            return FormalV4Inputs.from_dict(stored['inputs']) if stored['forward'] else None
        path = self._path(account_id).with_suffix('.recipe.json')
        if not path.exists():
            return None
        value = json.loads(path.read_text(encoding='utf-8'))
        if (set(value) != {'schema_version', 'kind', 'inputs'} or type(value['schema_version']) is not int
                or value['schema_version'] != 2 or value['kind'] != 'DAILY_FORWARD_V2'):
            raise ValueError('unsupported V4 forward recipe')
        return FormalV4Inputs.from_dict(value['inputs'])

    def _interval_allowed(self, account_id: str, interval: TimeInterval) -> bool:
        stored = self.store.v4_runtime_binding(account_id)
        return stored is None or interval.start >= datetime.fromisoformat(stored['effective_interval']['start'])

    def _calendar_products(self, recipe, point):
        """Only independently available calendars; never current-day OHLCV."""
        items = tuple((role, replace(parameters, query=replace(parameters.query,
            end=point.astimezone(ZoneInfo(parameters.instrument.timezone)).date() + timedelta(days=14))))
            for role, parameters in recipe.binding.request_bindings
            if parameters.query.product is EquityProduct.SESSIONS)
        key = canonical_sha256({'recipe': recipe.to_dict(), 'days': [(role, p.query.end.isoformat()) for role, p in items]})
        if key not in self._calendars:
            requests = tuple(EquityDataRequest(p.instrument, p.source, p.query) for p in dict.fromkeys(p for _, p in items))
            result = self.dataflows.prepare(requests, policy=PreparePolicy.REUSE)
            if not result.ready:
                raise _CalendarPreparationError(result)
            by_parameters = {request.parameters: self.dataflows.fetch(request, prepared=result.reference) for request in requests}
            if any(not fetched.ready for fetched in by_parameters.values()):
                raise ValueError('forward V4 prepared calendar is unavailable')
            self._calendars[key] = {role: by_parameters[p] for role, p in items}
        return self._calendars[key]

    def _interval_path(self, account_id, release_hash, interval):
        identity = canonical_sha256({'account_id': account_id, 'release_hash': release_hash,
            'start': interval.start.isoformat(), 'end': interval.end.isoformat()})
        return self._path(account_id).parent / 'intervals' / (identity + '.json')

    def _existing_interval(self, account_id, path, interval):
        if path.exists():
            return FormalV4Inputs.from_dict(json.loads(path.read_text(encoding='utf-8')))
        account = self.store.virtual_account(account_id)
        adopted = json.loads(account['last_decision_payload']) if account['last_decision_payload'] else {}
        expected = {'start': interval.start.isoformat(), 'end': interval.end.isoformat()}
        if adopted.get('equity_execution_interval') == expected:
            raise ValueError('adopted interval input record is missing; automatic replacement is forbidden')
        return None

    @staticmethod
    def _save_interval(path, inputs):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.pending')
        temporary.write_text(json.dumps(inputs.to_dict(), sort_keys=True), encoding='utf-8')
        temporary.replace(path)

    def _pinned_inputs(self, account_id, interval):
        inputs = self.inputs(account_id)
        path = self._interval_path(account_id, inputs.release_hash, interval)
        with self._lock:
            existing = self._existing_interval(account_id, path, interval)
            if existing is not None:
                return existing
            self._save_interval(path, inputs)
            return inputs

    def _forward_requests(self, recipe, interval, candidate, *, cutoff):
        calendars = self._calendar_products(recipe, interval.start)
        from strategy_runtime.data_preparation import forward_requests
        requests, items, observations, ends = forward_requests(self.dataflows, recipe.binding, interval, candidate.definition,
                                candidate.source_root, calendars, cutoff=cutoff)
        primary = next(parameters for role, parameters in items if role == 'bars')
        raw = recipe.execution_reference.parameters
        raw = replace(raw, query=replace(raw.query, end=primary.query.end))
        raw_request = EquityDataRequest(raw.instrument, raw.source, raw.query)
        return requests + (raw_request,), items, observations, ends

    def _forward_inputs(self, account_id, recipe, interval, *, candidate=None):
        path = self._interval_path(account_id, recipe.release_hash, interval)
        with self._lock:
            existing = self._existing_interval(account_id, path, interval)
            if existing is not None:
                return existing
            if candidate is None:
                _, _, candidate = self._account_release(account_id)
            requests, items, observation_items, observation_ends = self._forward_requests(
                recipe, interval, candidate, cutoff=interval.start)
            from strategy_runtime.observation_preparation import request_selection
            from strategy_runtime.dataset_observations import DatasetObservationBinding
            result = self.dataflows.prepare(requests, policy=PreparePolicy.REUSE)
            if not result.ready:
                raise ValueError('forward V4 input preparation is incomplete: ' + '; '.join(str(x.error) for x in result.items if not x.ready))
            identities = {request_selection(item.request): item.identity.content_sha256 for item in result.items}
            hashes = {role: identities[request_selection(EquityDataRequest(p.instrument, p.source, p.query))] for role, p in items}
            binding = replace(recipe.binding, prepared=result.reference, request_bindings=tuple(items),
                content_identities=tuple((role, hashes[role]) for role, _ in recipe.binding.content_identities),
                auxiliary_inputs=tuple(EquityAuxiliaryBinding(item.input,
                    hashes[item.input.data_key(EquityProduct.BARS)], hashes[item.input.data_key(EquityProduct.SESSIONS)])
                    for item in recipe.binding.auxiliary_inputs),
                execution_input=None,
                observation_bindings=tuple(DatasetObservationBinding(bound.input, None, None, observation_ends[bound.input.name])
                    if query is None else DatasetObservationBinding(bound.input, query,
                    identities[request_selection(query)]) for bound, (_, query) in zip(
                        recipe.binding.observation_bindings, observation_items, strict=True)))
            raw_request = requests[-1]
            raw_binding = ExecutionReferenceBinding(raw_request.parameters, result.reference,
                identities[request_selection(raw_request)])
            value = FormalV4Inputs(recipe.release_hash, binding, recipe.fee_rate, raw_binding)
            self._save_interval(path, value)
            return value

    def prepare_data(self, account_id: str, interval: TimeInterval, *, as_of: datetime) -> PrepareResult:
        """Prepare DFLS inputs only, without pinning a live interval or evaluating a strategy."""
        if type(interval) is not TimeInterval or type(as_of) is not datetime or as_of.utcoffset() is None:
            raise TypeError('V4 data preparation requires an interval and aware as_of')
        _, release, candidate = self._account_release(account_id)
        recipe = self.recipe(account_id)
        if recipe is None or recipe.release_hash != release.release_hash:
            raise ValueError('V4 data preparation requires a forward recipe for the current release')
        recipe.validate_candidate(release.release_hash, candidate)
        with self._lock:
            try:
                requests, _, _, _ = self._forward_requests(recipe, interval, candidate,
                                                           cutoff=min(as_of, interval.start))
            except _CalendarPreparationError as exc:
                return exc.result
            return self.dataflows.prepare(requests, policy=PreparePolicy.REUSE)

    def prepare_interval(self, account_id: str, interval: TimeInterval, *,
                         observed_at: datetime) -> PreparedEquityDecision:
        if type(interval) is not TimeInterval or type(observed_at) is not datetime or observed_at.utcoffset() is None:
            raise TypeError('formal V4 preparation requires an interval and aware observation time')
        if not interval.start <= observed_at < interval.end:
            raise ValueError('formal V4 interval is not currently executable')
        if not self._interval_allowed(account_id, interval):
            raise ValueError('formal V4 interval precedes the account binding cutover')
        _, release, candidate = self._account_release(account_id)
        recipe = self.recipe(account_id)
        inputs = self._pinned_inputs(account_id, interval) if recipe is None else self._forward_inputs(account_id, recipe, interval, candidate=candidate)
        if inputs.release_hash != release.release_hash:
            raise ValueError('formal V4 prepared inputs belong to another release')
        from .execution_inputs import resolve_live_context
        session_request = next(request for role, request in inputs.binding.bind_requests(inputs.strategy_requests)
                               if role == 'sessions')
        calendar = self.dataflows.fetch(session_request, prepared=inputs.binding.prepared)
        if not calendar.ready:
            raise ValueError('live execution calendar is unavailable')
        context = resolve_live_context(candidate, interval, calendar.dataframe, calendar.identity.metadata)
        return prepare_equity_decision(self.dataflows, candidate, inputs.binding, inputs.strategy_requests,
                                       interval, fee_rate=inputs.fee_rate, live=True,
                                       execution_reference=inputs.execution_reference.fetch(self.dataflows, interval,
                                           latency_seconds=candidate.definition.execution_spec.data_latency_seconds),
                                       execution_context=context)

    def get_decision(self, *args, **kwargs):
        _, release, candidate = self._account_release(kwargs['account_id'])
        prepared = kwargs['prepared']
        if not self._interval_allowed(kwargs['account_id'], prepared.interval):
            raise ValueError('formal V4 interval precedes the account binding cutover')
        inputs = FormalV4Inputs.from_dict(json.loads(self._interval_path(
            kwargs['account_id'], release.release_hash, prepared.interval).read_text(encoding='utf-8')))
        if (not prepared.live_interval or prepared.candidate != candidate
                or inputs.release_hash != release.release_hash or inputs.binding != prepared.binding
                or inputs.fee_rate != prepared.fee_rate
                or inputs.execution_reference.content_sha256 != prepared.execution_reference.content_sha256):
            raise ValueError('formal V4 proposal differs from loaded deployment')
        return EquityAdviceClient(self.store).get_decision(*args, **kwargs)



class FormalV4ScheduleProvider:
    """Resolve the current interval from pinned calendar and constraint facts."""
    def __init__(self, client, accounts):
        self.client, self.accounts = client, accounts

    def due_decision(self, account: dict, observed_at: datetime) -> ScheduledDecision | None:
        if type(observed_at) is not datetime or observed_at.utcoffset() is None:
            raise TypeError('V4 schedule requires an aware observation time')
        recipe = self.client.recipe(account['account_id'])
        inputs = self.client.inputs(account['account_id']) if recipe is None else recipe
        rules = self.client.store.equity_account_rules(account['account_id'])
        if rules is None or inputs.release_hash != account['release_hash']:
            raise ValueError('V4 schedule input identity differs from account')
        if recipe is None:
            request = next(request for role, request in inputs.binding.bind_requests(inputs.strategy_requests) if role == 'sessions')
            fetched = self.client.dataflows.fetch(request, prepared=inputs.binding.prepared)
        else:
            fetched = self.client._calendar_products(recipe, observed_at)['sessions']
        if not fetched.ready or (recipe is None and fetched.identity.content_sha256 != inputs.binding.expected_identities['sessions']):
            raise ValueError('V4 schedule calendar is unavailable or changed')
        availability = {str(row.SessionDate): row.AvailableDate for row in fetched.dataframe.itertuples()}
        for session in sessions_from_metadata(fetched.identity.metadata):
            if availability[session.session_date.isoformat()] > observed_at:
                continue
            periods = ((TimeInterval(session.segments[0].start, session.segments[-1].end),)
                       if rules.execution.decision_clock.value == BarFrequency.DAILY.value
                       else session.bars(BarFrequency(rules.execution.decision_clock.value)))
            for interval in periods:
                if (interval.start <= observed_at < interval.end
                        and availability[session.session_date.isoformat()] <= interval.start
                        and self.client._interval_allowed(account['account_id'], interval)):
                    task_id = canonical_sha256({'account_id': account['account_id'], 'release_hash': account['release_hash'],
                                                'start': interval.start.isoformat(), 'end': interval.end.isoformat()})
                    return ScheduledDecision(task_id, interval, interval.start)
        return None

    def run_scheduled(self, account_id: str, task: ScheduledDecision, observed_at: datetime) -> None:
        with self.client.decision_cycle_lock(account_id):
            self._adopt(account_id, task, observed_at, source='formal_v4', actor='SCHEDULER')

    def drive_decision(self, account_id: str, observed_at: datetime) -> dict[str, object]:
        with self.client.decision_cycle_lock(account_id):
            account = self.client.store.virtual_account(account_id)
            if account['run_state'] != 'PAUSED':
                raise RuntimeError('manual V4 validation requires a paused strategy account')
            if account['health'] != 'OK':
                raise RuntimeError('manual V4 validation requires a healthy strategy account')
            task = self.due_decision(account, observed_at)
            if task is None:
                raise RuntimeError('no executable V4 interval for the current account binding')
            previous = json.loads(account['last_decision_payload'] or '{}')
            interval = {'start': task.interval.start.isoformat(), 'end': task.interval.end.isoformat()}
            reused = (previous.get('equity_execution_interval') == interval
                      and previous.get('strategy', {}).get('release_hash') == account['release_hash'])
            decision = previous if reused else self._adopt(
                account_id, task, observed_at, source='web.control', actor='OPERATOR',
            )
            result = {
                'status': 'DECISION_REUSED' if reused else 'DECISION_COMPLETED',
                'account_id': account_id,
                'channel_account_id': account['channel_account_id'],
                'release_hash': account['release_hash'],
                'execution_interval': interval,
                'prepared_data_identity': decision['prepared_data_identity'],
                'reused_decision': reused,
                **{key: decision[key] for key in (
                    'decision_id', 'signal_date', 'valid_session', 'action',
                    'target_quantity', 'execution_reference_price',
                )},
            }
            self.accounts.audit.record(
                'ACCOUNT_DECISION_DRIVEN', source='web.control', actor_type='OPERATOR',
                account_id=account_id, strategy_id=account['strategy_id'],
                strategy_version=account['strategy_version'], release_hash=account['release_hash'],
                symbol=account['symbol'], decision_id=result['decision_id'], details=result,
            )
            return result

    def _adopt(self, account_id, task, observed_at, *, source, actor):
        prepared = self.client.prepare_interval(account_id, task.interval, observed_at=observed_at)
        self.client.store.settle_equity_receivables(account_id, at=prepared.interval.start)
        from execution_channels.futu.audit import AuditRecorder
        AuditRecorder(self.client.store).record('MARKET_DATA_PREPARED', source=source,
            actor_type=actor, account_id=account_id, correlation_id=task.task_id,
            details={'prepared_data_reference': prepared.data_reference,
                     'data_identity': prepared.data_identity,
                     'interval': {'start': task.interval.start.isoformat(), 'end': task.interval.end.isoformat()}})
        if actor == 'OPERATOR':
            self.accounts.refresh_account(account_id, prepared=prepared, require_paused=True)
        else:
            self.accounts.refresh_account(account_id, prepared=prepared)
        account = self.client.store.virtual_account(account_id)
        adopted = json.loads(account['last_decision_payload']) if account['last_decision_payload'] else {}
        expected = {'start': task.interval.start.isoformat(), 'end': task.interval.end.isoformat()}
        if (adopted.get('equity_execution_interval') != expected
                or adopted.get('strategy', {}).get('release_hash') != account['release_hash']
                or adopted.get('prepared_data_identity') != prepared.data_identity):
            raise RuntimeError('scheduled V4 decision was not adopted; retry after active order reconciliation')
        return adopted
