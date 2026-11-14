"""Generate and retain strategy-authored explanations outside trading transactions."""

from contextlib import closing
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from strategy_runtime import EquityStrategyCandidate, EquityStrategyDefinition, StrategyRelease
from strategy_runtime.deployment import validate_release_package
from strategy_runtime.equity_source_runtime import BoundEquityInvocation
from strategy_runtime.execution_explanation import (
    ExecutionFillFact, ExecutionIntentFact, ExecutionPlanContext, ExecutionResultContext,
    PlannedOrderFact, PreviousPlanFact, explain_execution,
)

_SELECT = (
    "SELECT summary,detail FROM execution_explanations WHERE account_id=? AND decision_id=?"
    " AND stage=? AND release_hash=? AND fingerprint=?"
)


def _plan(row, event):
    execution = event['execution_plan']
    planning = execution['planning_result']
    facts = row['payload']['strategy_output']['execution_plan']
    previous = facts.get('previous_plan')
    if previous is not None:
        previous = PreviousPlanFact(**{**previous, 'intents': tuple(
            ExecutionIntentFact(**intent) for intent in previous['intents'])})
    return ExecutionPlanContext(
        event['decision_id'], event['signal_date'], event['valid_session'],
        event['generated_at'], event['explanation']['judgment'],
        event['target_position'], event['position_at_decision'],
        tuple(PlannedOrderFact(**order) for order in execution['orders']),
        execution['trigger'], planning['status'], tuple(planning['reasons']),
        planning['desired_quantity'], planning['planned_quantity'], previous,
    )


def _candidate(root, release_id, release_hash):
    if not re.fullmatch(r'S[0-9]{3}-v[1-9][0-9]*', release_id) or not re.fullmatch(r'[a-f0-9]{64}', release_hash):
        raise ValueError('invalid execution explanation release identity')
    family, version = release_id.split('-')
    relative = Path(family, 'versions', f'{version}.json')
    archived = root / 'revisions' / release_id / release_hash / 'strategies'
    for source in (archived, root):
        if not (source / relative).is_file():
            continue
        release = StrategyRelease.from_mapping(json.loads((source / relative).read_bytes()))
        if release.release_id != release_id or release.release_hash != release_hash:
            continue
        definition = release.payload.get('equity_definition')
        if not definition or not definition.get('execution_explainer'):
            return None
        package = validate_release_package(source, release_id)
        if package.release.release_hash != release_hash:
            raise ValueError('explanation release changed during loading')
        return EquityStrategyCandidate(
            family, package.runtime_candidate_id, EquityStrategyDefinition.from_dict(dict(definition)),
            package.source_root,
        )
    return None


class ExecutionExplanationStore:
    """PTE display snapshots, kept alongside the account database and independent of HTML caches."""

    def __init__(self, path: Path, strategy_root: Path):
        self.path = path
        self.strategy_root = strategy_root

    def _load_or_generate(self, connection, context, params, facts, candidates, key):
        saved = connection.execute(_SELECT, params).fetchone()
        if saved is not None:
            return saved
        if key not in candidates:
            candidates[key] = _candidate(self.strategy_root, *key)
        if candidates[key] is None:
            return None
        # Each stage runs in a fresh module scope, separate from trading.
        with BoundEquityInvocation(candidates[key], execution_only=True) as invocation:
            text = explain_execution(invocation, context)
        with connection:
            saved = connection.execute(
                "INSERT INTO execution_explanations VALUES(?,?,?,?,?,?,?,?)"
                " ON CONFLICT DO NOTHING RETURNING summary,detail",
                (*params, facts, text.summary, text.detail)).fetchone()
            return saved if saved is not None else connection.execute(_SELECT, params).fetchone()

    def project(self, account_id, rows, events, intents, fills, on_error):
        eligible = [(row, event, row['payload'].get('strategy')) for row, event in zip(rows, events, strict=True)
                    if event['explanation'] and event['execution_plan']['planning_result']]
        if not eligible:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS execution_explanations (
                    account_id TEXT NOT NULL, decision_id TEXT NOT NULL, stage TEXT NOT NULL,
                    release_hash TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    facts TEXT NOT NULL, summary TEXT NOT NULL, detail TEXT NOT NULL,
                    PRIMARY KEY (account_id, decision_id, stage, release_hash, fingerprint)
                )
            """)
            candidates = {}
            for row, event, identity in eligible:
                if not identity:
                    continue
                release_hash = identity.get('release_hash')
                try:
                    if release_hash is None:
                        continue
                    release_id = f"{identity['strategy_id']}-{identity['version']}"
                    key = (release_id, release_hash)
                    plan = _plan(row, event)
                    decision_id = plan.decision_id
                    saved_intents = tuple(ExecutionIntentFact(
                        intent['intent_id'], intent['status'], intent['channel_order_id'], intent['channel_status'],
                        intent['submitted_at'])
                        for intent in sorted(intents.get(decision_id, ()), key=lambda item: item['intent_id']))
                    saved_fills = tuple(ExecutionFillFact(fill['fill_id'], fill['side'], fill['quantity'], fill['occurred_at'])
                        for fill in sorted(fills.get(decision_id, ()), key=lambda item: (item['occurred_at'], item['fill_id'])))
                    result = ExecutionResultContext(plan, event['status'], event['state_reason'],
                        event['state_changed_at'], saved_intents, saved_fills)
                    for stage, context in (('plan', plan), ('result', result)):
                        facts = json.dumps(asdict(context), ensure_ascii=False, sort_keys=True,
                                           separators=(',', ':'), allow_nan=False)
                        fingerprint = hashlib.sha256(facts.encode('utf-8')).hexdigest()
                        params = (account_id, decision_id, stage, release_hash, fingerprint)
                        try:
                            saved = self._load_or_generate(connection, context, params, facts, candidates, key)
                            if saved is None:
                                break
                            event[f'{stage}_explanation'] = dict(zip(('summary', 'detail'), saved, strict=True))
                        except Exception as exc:
                            on_error(row, release_hash, exc)
                except Exception as exc:
                    on_error(row, release_hash, exc)
