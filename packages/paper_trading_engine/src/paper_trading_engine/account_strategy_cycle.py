"""Shared account strategy cycle for scheduled and operator-driven execution."""

from __future__ import annotations

from datetime import date, datetime
from threading import Lock, RLock

from .audit import AuditRecorder


class AccountStrategyCycle:
    """Prepare one account's SRT data before calculating its decision."""

    def __init__(self, accounts, prepared_data, store, *, audit: AuditRecorder | None = None) -> None:
        self.accounts = accounts
        self.prepared_data = prepared_data
        self.store = store
        self.audit = audit or (
            AuditRecorder(store) if hasattr(store, "append_audit_event") else None
        )
        self._locks_guard = RLock()
        self._account_locks: dict[str, Lock] = {}

    def _account_lock(self, account_id: str) -> Lock:
        with self._locks_guard:
            return self._account_locks.setdefault(account_id, Lock())

    def latest_completed_signal_date(self, at: datetime) -> date:
        return self.prepared_data.latest_completed_signal_date(at)

    def run_latest(self, account_id: str, *, observed_at: datetime):
        signal_date = self.latest_completed_signal_date(observed_at)
        return self.run(
            account_id,
            signal_date=signal_date,
            observed_at=observed_at,
            operator_drive=True,
        )

    def run(
        self,
        account_id: str,
        *,
        signal_date: date,
        observed_at: datetime,
        operator_drive: bool = False,
    ):
        with self._account_lock(account_id):
            return self._run_locked(
                account_id,
                signal_date=signal_date,
                observed_at=observed_at,
                operator_drive=operator_drive,
            )

    def _run_locked(
        self,
        account_id: str,
        *,
        signal_date: date,
        observed_at: datetime,
        operator_drive: bool,
    ):
        account = self.store.virtual_account(account_id)
        if account["status"] != "RUNNING":
            raise ValueError("inactive account cannot prepare strategy data")
        cutoff = signal_date.isoformat()
        error_key = f"data_preparation_error:{account_id}"
        try:
            prepared = self.prepared_data.prepare(account, signal_date=signal_date)
        except Exception as exc:
            self.store.set_setting(error_key, str(exc))
            raise
        if prepared is None:
            self.store.set_setting(
                f"last_account_schedule_skip_date:{account_id}", cutoff
            )
            self.store.set_setting(error_key, "")
            return None
        cutoff = prepared.available_through.isoformat()
        self.store.set_setting(f"last_data_prepare_date:{account_id}", cutoff)
        self.store.set_setting(
            f"last_prepared_data_id:{account_id}", prepared.data_identity
        )
        self.store.set_setting(
            f"last_data_preparation:{account_id}", observed_at.isoformat()
        )
        self.store.set_setting(error_key, "")
        if self.audit is not None:
            self.audit.record(
                "MARKET_DATA_PREPARED",
                source="web.control" if operator_drive else "scheduler",
                actor_type="OPERATOR" if operator_drive else "SCHEDULER",
                account_id=account_id,
                strategy_id=str(account["strategy_id"]),
                strategy_version=str(account["strategy_version"]),
                release_hash=str(account["release_hash"]),
                symbol=str(account["symbol"]),
                correlation_id=f"prepared-data:{account_id}:{cutoff}",
                details={
                    "prepared_through": cutoff,
                    "data_identity": prepared.data_identity,
                },
            )
        decision = (
            self.accounts.drive_account_decision(account_id, prepared=prepared)
            if operator_drive
            else self.accounts.refresh_account(account_id, prepared=prepared)
        )
        self.store.set_setting(f"last_account_decision_date:{account_id}", cutoff)
        return decision
