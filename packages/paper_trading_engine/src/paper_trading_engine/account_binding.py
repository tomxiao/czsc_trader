"""Validated account-facing identity of an installed paper-trading strategy."""

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
import math
import re
from typing import TYPE_CHECKING

from strategy_manager import Qualification
from dataflows import InstrumentId, MarketId, AssetClass, TimeInterval
from strategy_runtime.equity_replay import StateRecord
from strategy_runtime.inspection import InspectionRuntimePermit

from execution_channels.futu.equity_contracts import EquityAccountRules

if TYPE_CHECKING:
    from .formal_v4_advice import FormalV4Inputs


@dataclass(frozen=True, slots=True)
class AccountStrategyBinding:
    strategy_id: str
    version: str
    release_hash: str
    name: str
    qualification: Qualification | None
    selection_data_cutoff: date
    symbol: str
    fee_rate: float
    inspection_permit: InspectionRuntimePermit | None = field(default=None, kw_only=True, repr=False, compare=False)
    instrument: InstrumentId | None = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        for name, pattern in (
            ("strategy_id", r"S[0-9]{3}"),
            ("version", r"v[1-9][0-9]*"),
            ("release_hash", r"[0-9a-f]{64}"),
        ):
            value = getattr(self, name)
            if type(value) is not str or re.fullmatch(pattern, value) is None:
                raise ValueError(f"invalid account binding {name}")
        if self.instrument is None:
            if type(self.symbol) is not str or re.fullmatch(r"[0-9]{6}\.(SH|SZ)", self.symbol) is None:
                raise ValueError('invalid account binding symbol')
        elif (type(self.instrument) is not InstrumentId or self.instrument.symbol != self.symbol
              or self.instrument.market not in (MarketId.CN, MarketId.US)
              or self.instrument.asset_class not in (AssetClass.STOCK, AssetClass.ETF)):
            raise ValueError('account binding differs from typed equity instrument')
        if type(self.name) is not str or not self.name.strip():
            raise ValueError("account binding requires a name")
        if self.inspection_permit is not None:
            from strategy_runtime.inspection import InspectionRuntimePermit
            if type(self.inspection_permit) is not InspectionRuntimePermit:
                raise ValueError("invalid technical account permit")
            self.inspection_permit.validate_release(self.release_id, self.release_hash)
            if self.qualification is not None:
                raise ValueError("technical account cannot claim formal qualification")
        elif type(self.qualification) is not Qualification or self.qualification not in {
            Qualification.PAPER_READY,
            Qualification.LIVE_READY,
        }:
            raise ValueError("account binding requires paper trading qualification")
        if type(self.selection_data_cutoff) is not date:
            raise TypeError("account binding requires a selection cutoff date")
        if (
            type(self.fee_rate) not in (float, int)
            or not math.isfinite(self.fee_rate)
            or not 0 <= self.fee_rate < 1
        ):
            raise ValueError("account binding requires a finite fee rate in [0, 1)")

    @property
    def release_id(self) -> str:
        return f"{self.strategy_id}-{self.version}"


@dataclass(frozen=True, slots=True)
class AccountBindingUpdate:
    account_id: str
    expected_release_hash: str
    target_release_hash: str
    target_version: str

    def __post_init__(self) -> None:
        if type(self.account_id) is not str or not self.account_id.strip():
            raise ValueError("account binding update requires an account id")
        if type(self.target_version) is not str or re.fullmatch(r"v[1-9][0-9]*", self.target_version) is None:
            raise ValueError("invalid account binding update target_version")
        for name in ("expected_release_hash", "target_release_hash"):
            value = getattr(self, name)
            if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise ValueError(f"invalid account binding update {name}")
        if self.expected_release_hash == self.target_release_hash:
            raise ValueError("account binding update requires a different target hash")


@dataclass(frozen=True, slots=True)
class V4StateContinuation:
    """Attest to private-state compatibility between exact frozen versions."""

    source_runtime_release_id: str
    evidence: str

    def __post_init__(self) -> None:
        for value in (self.source_runtime_release_id, self.evidence):
            if type(value) is not str or not value.strip():
                raise ValueError("state continuation requires source runtime and review evidence")


@dataclass(frozen=True, slots=True)
class V4StateMigration:
    """Reviewed strategy fields. Platform-owned ledger facts are derived separately."""

    account_values: StateRecord
    evidence: str
    cycle_values: StateRecord | None = None
    pending_cycle_values: StateRecord | None = None
    source_runtime_release_id: str | None = None

    def __post_init__(self) -> None:
        if type(self.evidence) is not str or not self.evidence.strip():
            raise ValueError("state migration requires review evidence")
        if self.source_runtime_release_id is not None and (
            type(self.source_runtime_release_id) is not str or not self.source_runtime_release_id.strip()
        ):
            raise ValueError("invalid source runtime release id")
        if type(self.account_values) is not StateRecord or any(
            item is not None and type(item) is not StateRecord
            for item in (self.cycle_values, self.pending_cycle_values)
        ):
            raise TypeError("state migration requires typed private-state records")


@dataclass(frozen=True, slots=True)
class V4AccountBindingUpdate:
    binding: AccountBindingUpdate
    channel_account_id: str
    expected_facts_sha256: str
    effective_interval: TimeInterval
    rules: EquityAccountRules
    inputs: 'FormalV4Inputs'
    state: V4StateContinuation | V4StateMigration

    def __post_init__(self) -> None:
        from .formal_v4_advice import FormalV4Inputs

        if type(self.binding) is not AccountBindingUpdate or type(self.inputs) is not FormalV4Inputs:
            raise TypeError("V4 account update requires typed binding and input contracts")
        if self.inputs.release_hash != self.binding.target_release_hash:
            raise ValueError("V4 inputs must belong to the target release")
        if type(self.channel_account_id) is not str or not self.channel_account_id.strip():
            raise ValueError("V4 account update requires channel account identity")
        if type(self.expected_facts_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}", self.expected_facts_sha256):
            raise ValueError("V4 account update requires the account facts SHA-256")
        if type(self.rules) is not EquityAccountRules or type(self.effective_interval) is not TimeInterval:
            raise TypeError("V4 account update requires typed account rules and cutover interval")
        if type(self.state) not in (V4StateContinuation, V4StateMigration):
            raise TypeError("V4 account update requires an explicit state treatment")

    @property
    def account_id(self) -> str:
        return self.binding.account_id


class AccountBindingUpdateStatus(StrEnum):
    COMMITTED = "COMMITTED"
    ALREADY_APPLIED = "ALREADY_APPLIED"


@dataclass(frozen=True, slots=True)
class AccountBindingUpdateResult:
    status: AccountBindingUpdateStatus
    account_ids: tuple[str, ...]
