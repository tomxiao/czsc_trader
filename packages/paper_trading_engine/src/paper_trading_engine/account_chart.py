"""Account-scoped PTE forward charts refreshed outside request threads."""

from __future__ import annotations

from concurrent.futures import CancelledError, Executor, Future
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from queue import Empty, Queue
import re
from threading import Event, RLock, Thread
import time
from typing import Any, Callable
from uuid import uuid4

from strategy_runtime import StrategyObservation

from .audit import AuditRecorder
from .forward_chart import FORWARD_CHART_CONTRACT_VERSION, render_forward_chart_html


ACCOUNT_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
INPUT_LIMIT = 5 * 1024 * 1024
OUTPUT_LIMIT = 20 * 1024 * 1024
CACHE_RENDER_REVISION = "pte-forward-chart-v4"


def _path_comparison_key(path: Path) -> str:
    """Normalize equivalent Windows DOS and extended-length path spellings."""

    value = os.path.normcase(os.path.abspath(path))
    if value.startswith("\\\\?\\UNC\\"):
        return "\\\\" + value[8:]
    if value.startswith("\\\\?\\"):
        return value[4:]
    return value


def _same_directory(left: Path, right: Path) -> bool:
    try:
        return os.path.samefile(left, right)
    except (OSError, ValueError):
        return _path_comparison_key(left) == _path_comparison_key(right)


class _RefreshCancelled(Exception):
    pass


class _DaemonSingleWorker(Executor):
    """One daemon worker so a stuck optional chart task cannot hold PTE open."""

    _STOP = object()

    def __init__(self) -> None:
        self._queue: Queue[object] = Queue()
        self._closed = False
        self._guard = RLock()
        self._thread = Thread(
            target=self._run, name="pte-account-chart", daemon=True,
        )
        self._thread.start()

    def submit(self, fn, /, *args, **kwargs) -> Future:
        with self._guard:
            if self._closed:
                raise RuntimeError("account chart worker is closed")
            future: Future = Future()
            self._queue.put((future, fn, args, kwargs))
            return future

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is self._STOP:
                return
            future, fn, args, kwargs = item
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(fn(*args, **kwargs))
            except BaseException as exc:
                future.set_exception(exc)

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        with self._guard:
            if self._closed:
                return
            self._closed = True
            if cancel_futures:
                while True:
                    try:
                        item = self._queue.get_nowait()
                    except Empty:
                        break
                    if item is not self._STOP:
                        item[0].cancel()
            self._queue.put(self._STOP)
        if wait:
            self._thread.join()

    def join(self, timeout: float) -> None:
        self._thread.join(timeout)


class AccountChartService:
    """Serve cached charts while keeping DFLS and rendering off request threads."""

    def __init__(
        self,
        store,
        *,
        market_data,
        cache_dir: Path,
        context_sessions: int = 60,
        refresh_interval_seconds: float = 60,
        fetch_timeout_seconds: float = 35,
        shutdown_timeout_seconds: float = 2,
        audit: AuditRecorder | None = None,
        executor: Executor | None = None,
        renderer: Callable[[object], str] = render_forward_chart_html,
    ) -> None:
        if fetch_timeout_seconds <= 0 or shutdown_timeout_seconds < 0:
            raise ValueError("account chart timeouts are invalid")
        self.store = store
        self.market_data = market_data
        self.cache_dir = Path(cache_dir)
        self.context_sessions = context_sessions
        self.refresh_interval_seconds = refresh_interval_seconds
        self.fetch_timeout_seconds = fetch_timeout_seconds
        self.shutdown_timeout_seconds = shutdown_timeout_seconds
        self.audit = audit or AuditRecorder(store)
        self.renderer = renderer
        self._executor = executor or _DaemonSingleWorker()
        self._owns_executor = executor is None
        self._jobs: dict[str, Future[None]] = {}
        self._last_submit: dict[str, float] = {}
        self._guard = RLock()
        self._store_guard = RLock()
        self._fetch_guard = RLock()
        self._market_fetches: dict[
            str, tuple[dict[str, object], Future]
        ] = {}
        self._closing = Event()

    def _account_dir(self, account_id: str) -> Path:
        if ACCOUNT_ID_PATTERN.fullmatch(account_id) is None:
            raise ValueError("invalid account id")
        root = self.cache_dir.resolve()
        target = root / account_id
        resolved_target = target.resolve()
        if not _same_directory(resolved_target.parent, root):
            raise ValueError("account chart path escapes cache root")
        return target

    def chart_path(self, account_id: str, fingerprint: str | None = None) -> Path:
        account_dir = self._account_dir(account_id)
        selected = fingerprint
        if selected is None:
            selected = self._load_meta(self._meta_path(account_id)).get("fingerprint")
        if selected is None:
            return account_dir / "observation.html"
        if not isinstance(selected, str) or re.fullmatch(r"[0-9a-f]{64}", selected) is None:
            raise ValueError("invalid account chart fingerprint")
        return account_dir / f"{selected}.html"

    def _meta_path(self, account_id: str) -> Path:
        return self._account_dir(account_id) / "observation.meta.json"

    @staticmethod
    def _sha256(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def _bounded_market_history(self, fetch_key: str, **kwargs):
        request = dict(kwargs)
        with self._fetch_guard:
            current = self._market_fetches.get(fetch_key)
            if current is not None and current[0] != request:
                if not current[1].done():
                    raise RuntimeError("previous account chart DFLS fetch is still running")
                self._market_fetches.pop(fetch_key, None)
                current = None
            if current is None:
                result: Future = Future()
                self._market_fetches[fetch_key] = (request, result)
            else:
                result = current[1]

        def fetch() -> None:
            try:
                result.set_result(self.market_data.history(**kwargs))
            except BaseException as exc:
                result.set_exception(exc)

        if current is None:
            Thread(
                target=fetch,
                name=f'pte-chart-dfls-{kwargs["symbol"]}',
                daemon=True,
            ).start()
        try:
            return result.result(timeout=self.fetch_timeout_seconds)
        except TimeoutError as exc:
            raise TimeoutError(
                f"account chart DFLS fetch exceeded {self.fetch_timeout_seconds:g} seconds"
            ) from exc
        finally:
            if result.done():
                with self._fetch_guard:
                    active = self._market_fetches.get(fetch_key)
                    if active is not None and active[1] is result:
                        self._market_fetches.pop(fetch_key, None)

    def _market_data(self, account: dict[str, Any]) -> tuple[str, list[dict[str, object]]]:
        cutoff = date.fromisoformat(str(account["selection_data_cutoff"])).isoformat()
        price_identity, frame = self._bounded_market_history(
            str(account["account_id"]),
            symbol=str(account["symbol"]),
            asset=str(account["asset_type"]),
            selection_data_cutoff=cutoff,
            context_sessions=self.context_sessions,
        )
        frame = frame.rename(
            columns={
                "dt": "date", "Date": "date", "Open": "open", "High": "high",
                "Low": "low", "Close": "close",
            }
        )
        if not {"date", "open", "high", "low", "close"} <= set(frame.columns):
            raise ValueError("DFLS adjusted daily input has incomplete OHLC data")
        bars: dict[str, dict[str, object]] = {}
        for row in frame.to_dict("records"):
            session = date.fromisoformat(str(row["date"])[:10]).isoformat()
            if session in bars:
                raise ValueError(f"duplicate daily market-data session: {session}")
            bars[session] = {
                "date": session,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            }
        ordered = [bars[key] for key in sorted(bars)]
        history = [bar for bar in ordered if bar["date"] <= cutoff][-self.context_sessions :]
        selected = history + [bar for bar in ordered if bar["date"] > cutoff]
        if not selected:
            raise ValueError("no daily market data is available for the account chart")
        return str(price_identity), selected

    @staticmethod
    def _fact_date(row: dict[str, Any], fields: tuple[str, ...]) -> str | None:
        for field in fields:
            if row.get(field) not in (None, ""):
                return date.fromisoformat(str(row[field])[:10]).isoformat()
        return None

    @staticmethod
    def _decision(row: dict[str, Any]) -> dict[str, Any]:
        payload = dict(row.get("payload") or {})
        observation = payload.get("observation")
        if not isinstance(observation, dict) or observation.get("status") != "READY":
            message = observation.get("message") if isinstance(observation, dict) else None
            raise ValueError(message or f'decision {row["decision_id"]} has no chart observation')
        fact = StrategyObservation.from_dict(observation)
        if (fact.signal_identity != payload.get('signal_identity') or
            fact.plan_identity != payload.get('plan_identity') or
            fact.strategy.reference_id != payload.get('strategy', {}).get('release_id') or
            fact.strategy.release_hash != payload.get('strategy', {}).get('release_hash') or
            fact.strategy.symbol != payload.get('symbol') or
            fact.signal_date.isoformat() != row['signal_date'] or
            fact.valid_session.isoformat() != row['valid_session'] or
            fact.action != payload.get('action') or
            fact.strategy.runtime_sha256 != payload.get('runtime_sha256')):
            raise ValueError('stored observation differs from decision identity')
        return {
            "account_id": row["account_id"],
            "decision_id": row["decision_id"],
            "signal_date": row["signal_date"],
            "valid_session": row["valid_session"],
            "generated_at": row["generated_at"],
            "action": payload.get("action"),
            "target_quantity": payload.get("target_quantity"),
            "observation": observation,
        }

    @staticmethod
    def _has_ready_observation(row: dict[str, Any], release_hash: str) -> bool:
        payload = dict(row.get("payload") or {})
        observation = payload.get("observation")
        return (
            payload.get("strategy", {}).get("release_hash") == release_hash
            and isinstance(observation, dict)
            and observation.get("status") == "READY"
        )

    @staticmethod
    def _intent(row: dict[str, Any]) -> dict[str, Any]:
        payload = dict(row.get("payload") or {})
        return {
            "account_id": row.get("account_id"),
            "intent_id": row.get("intent_id"),
            "decision_id": row.get("decision_id"),
            "valid_session": row.get("valid_session") or payload.get("valid_session"),
            "side": row.get("side") or payload.get("side"),
            "quantity": row.get("quantity") or payload.get("quantity"),
            "limit_price": row.get("limit_price") or payload.get("limit_price"),
        }

    def _after_cutoff(
        self, rows: list[dict[str, Any]], cutoff: str, fields: tuple[str, ...],
    ) -> list[dict[str, Any]]:
        return [
            row for row in rows
            if (observed := self._fact_date(row, fields)) is not None and observed > cutoff
        ]

    def _request(self, account: dict[str, Any]) -> tuple[dict[str, object], bool]:
        account_id = str(account["account_id"])
        cutoff_value = account.get("selection_data_cutoff")
        if not cutoff_value:
            raise ValueError("strategy selection cutoff is unavailable")
        cutoff = date.fromisoformat(str(cutoff_value)).isoformat()
        with self._store_guard:
            if self._closing.is_set():
                raise _RefreshCancelled
            decision_rows = [
                row for row in self.store.account_decisions(account_id)
                if row.get("status") == "ACTIVE"
            ]
            intent_rows = self.store.account_intents(account_id)
            fill_rows = self.store.account_fills(account_id)
            snapshot_rows = self.store.account_snapshots(account_id)
        forward_decision_rows = self._after_cutoff(
            decision_rows, cutoff, ("signal_date",)
        )
        decisions = [
            self._decision(row)
            for row in forward_decision_rows
            if self._has_ready_observation(row, account["release_hash"])
        ]
        omitted_decision_count = len(forward_decision_rows) - len(decisions)
        observation_start = min(
            (str(row["signal_date"]) for row in decisions), default=None,
        )
        intents = [
            self._intent(row)
            for row in self._after_cutoff(
                intent_rows, cutoff, ("valid_session", "session"),
            )
        ]
        fills = [
            {
                "account_id": row.get("account_id"),
                "fill_id": row.get("fill_id"),
                "decision_id": row.get("decision_id"),
                "channel_order_id": row.get("order_id"),
                "occurred_at": row.get("occurred_at"),
                "side": row.get("side"),
                "quantity": row.get("quantity"),
                "price": row.get("price"),
                "fee": row.get("fee"),
            }
            for row in self._after_cutoff(
                fill_rows, cutoff, ("occurred_at", "session"),
            )
        ]
        snapshots = [
            {
                "account_id": row.get("account_id"),
                "session": row.get("session"),
                "quantity": row.get("quantity"),
            }
            for row in self._after_cutoff(
                snapshot_rows, cutoff, ("session",),
            )
        ]
        market_identity, bars = self._market_data(account)
        if self._closing.is_set():
            raise _RefreshCancelled
        release_id = f'{account["strategy_id"]}-{account["strategy_version"]}'
        request = {
            "contract_version": FORWARD_CHART_CONTRACT_VERSION,
            "strategy": {
                "account_id": account_id,
                "strategy_id": account["strategy_id"],
                "version": account["strategy_version"],
                "release_id": release_id,
                "release_hash": account["release_hash"],
                "name": account["strategy_name_snapshot"],
                "symbol": account["symbol"],
            },
            "window": {
                "selection_data_cutoff": cutoff,
                "context_sessions": self.context_sessions,
                "observation_start": observation_start,
                "omitted_decision_count": omitted_decision_count,
            },
            "market_data": {
                "identity": market_identity,
                "adjustment": "hfq",
                "as_of": bars[-1]["date"],
                "bars": bars,
            },
            "observations": decisions,
            "execution": {"intents": intents, "fills": fills, "snapshots": snapshots},
        }
        return request, any(bar["date"] > cutoff for bar in bars)

    @staticmethod
    def _load_meta(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def current_error(self, account_id: str) -> str | None:
        """Return the persisted chart error without triggering a refresh."""
        self._account_dir(account_id)
        value = self._load_meta(self._meta_path(account_id)).get("error")
        return str(value) if value else None

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(content, encoding="utf-8", newline="\n")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _record_failure(self, account: dict[str, Any], error: Exception) -> None:
        meta_path = self._meta_path(str(account["account_id"]))
        message = str(error)[:500]
        error_fingerprint = self._sha256(message.encode("utf-8"))
        old = self._load_meta(meta_path)
        should_audit = old.get("error_fingerprint") != error_fingerprint
        old.update({"error_fingerprint": error_fingerprint, "error": message})
        self._atomic_write(meta_path, json.dumps(old, ensure_ascii=False))
        if should_audit:
            with self._store_guard:
                if self._closing.is_set():
                    return
                try:
                    self.audit.record(
                        "ACCOUNT_CHART_GENERATION_FAILED", source="account_chart",
                        outcome="FAILURE", actor_type="ENGINE",
                        account_id=account["account_id"],
                        strategy_id=account.get("strategy_id"),
                        strategy_version=account.get("strategy_version"),
                        release_hash=account.get("release_hash"), symbol=account.get("symbol"),
                        details={"operation": "render", "error": message},
                    )
                except Exception:
                    return

    def _refresh(self, account: dict[str, Any]) -> None:
        account_id = str(account["account_id"])
        meta_path = self._meta_path(account_id)
        old_meta = self._load_meta(meta_path)
        try:
            request, has_forward = self._request(account)
            encoded = json.dumps(
                request, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                allow_nan=False, default=str,
            )
            if len(encoded.encode("utf-8")) > INPUT_LIMIT:
                raise ValueError("account observation input exceeds 5 MiB")
            fingerprint = self._sha256(f"{CACHE_RENDER_REVISION}\n{encoded}".encode("utf-8"))
            html_path = self.chart_path(account_id, fingerprint)
            if old_meta.get("fingerprint") != fingerprint or not html_path.is_file():
                html = self.renderer(request)
                if self._closing.is_set():
                    raise _RefreshCancelled
                if len(html.encode("utf-8")) > OUTPUT_LIMIT:
                    raise ValueError("account observation output exceeds 20 MiB")
                if not html.lstrip().lower().startswith(("<html", "<!doctype html")):
                    raise ValueError("chart renderer returned invalid HTML")
                self._atomic_write(html_path, html)
            self._atomic_write(
                meta_path,
                json.dumps(
                    {
                        "fingerprint": fingerprint, "has_forward": has_forward,
                        "has_observation": bool(request["observations"]),
                        "observation_start": request["window"]["observation_start"],
                        "omitted_decision_count": request["window"][
                            "omitted_decision_count"
                        ],
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                    },
                    ensure_ascii=False,
                ),
            )
            if old_meta.get("error_fingerprint"):
                with self._store_guard:
                    if not self._closing.is_set():
                        try:
                            self.audit.record(
                                "ACCOUNT_CHART_RECOVERED", source="account_chart",
                                actor_type="ENGINE", account_id=account_id,
                                strategy_id=account.get("strategy_id"),
                                strategy_version=account.get("strategy_version"),
                                release_hash=account.get("release_hash"),
                                symbol=account.get("symbol"),
                                details={"operation": "render"},
                            )
                        except Exception:
                            pass
        except _RefreshCancelled:
            return
        except Exception as exc:
            if not self._closing.is_set():
                self._record_failure(account, exc)

    @staticmethod
    def _scope(account: dict[str, Any]) -> dict[str, str]:
        return {
            "account_id": str(account["account_id"]),
            "release_id": f'{account["strategy_id"]}-{account["strategy_version"]}',
        }

    def _status_from_cache(
        self, account: dict[str, Any], *, refreshing: bool,
    ) -> dict[str, object]:
        account_id = str(account["account_id"])
        meta = self._load_meta(self._meta_path(account_id))
        fingerprint = str(meta.get("fingerprint") or "")
        chart_exists = self.chart_path(account_id).is_file()
        base = {
            "scope": self._scope(account),
            "selection_data_cutoff": account.get("selection_data_cutoff"),
            "context_sessions": self.context_sessions,
        }
        if meta.get("error") and refreshing:
            return {
                **base, "status": "BUILDING", "chart_url": None,
                "fingerprint": None, "message": "正在重新生成观察图",
            }
        if meta.get("error"):
            return {
                **base, "status": "UNAVAILABLE", "chart_url": None,
                "fingerprint": None, "message": str(meta["error"]),
            }
        if fingerprint and chart_exists:
            has_forward = bool(meta.get("has_forward"))
            has_observation = bool(meta.get("has_observation"))
            omitted_count = int(meta.get("omitted_decision_count") or 0)
            observation_start = meta.get("observation_start")
            observation_message = (
                f"观察事实自 {observation_start} 开始；其中 {omitted_count} 条决策"
                "缺少可用的观察事实，未绘制策略解释"
                if observation_start and omitted_count
                else (
                    f"等待第一条策略观察事实；其中 {omitted_count} 条决策"
                    "缺少可用的观察事实，未绘制策略解释"
                    if omitted_count
                    else None
                )
            )
            return {
                **base,
                "status": "REFRESHING" if refreshing else (
                    "READY" if has_forward and has_observation else "EMPTY"
                ),
                "chart_url": f"/charts/{account_id}/observation.html?v={fingerprint}",
                "fingerprint": fingerprint,
                "message": "正在刷新观察图" if refreshing else (
                    observation_message if has_observation else (
                        observation_message or "等待第一条策略观察事实"
                    )
                ) if has_forward else (
                    observation_message or "等待新的完整收盘数据"
                ),
            }
        return {
            **base, "status": "BUILDING", "chart_url": None,
            "fingerprint": None, "message": "正在生成观察图",
        }

    def _consume_job(self, account: dict[str, Any], job: Future[None]) -> None:
        try:
            job.result()
        except CancelledError:
            return
        except Exception as exc:
            self._record_failure(account, exc)

    def status(self, account_id: str, *, force: bool = False) -> dict[str, object]:
        """Return immediately; enqueue at most one refresh for this account."""
        self._account_dir(account_id)
        account = self.store.virtual_account(account_id)
        now = time.monotonic()
        with self._guard:
            if self._closing.is_set():
                return self._status_from_cache(account, refreshing=False)
            job = self._jobs.get(account_id)
            if job is not None and job.done():
                self._consume_job(account, job)
                self._jobs.pop(account_id, None)
                job = None
            last_submit = self._last_submit.get(account_id)
            if job is None and (
                force
                or last_submit is None
                or now - last_submit >= self.refresh_interval_seconds
            ):
                job = self._executor.submit(self._refresh, dict(account))
                self._jobs[account_id] = job
                self._last_submit[account_id] = now
                if job.done():
                    self._consume_job(account, job)
                    self._jobs.pop(account_id, None)
                    job = None
            return self._status_from_cache(account, refreshing=job is not None)

    def refresh(self, account_id: str) -> dict[str, object]:
        """Force one asynchronous rebuild without mutating trading state."""

        return self.status(account_id, force=True)

    def close(self) -> None:
        with self._guard:
            self._closing.set()
            with self._store_guard:
                pass
            if self._owns_executor:
                self._executor.shutdown(wait=False, cancel_futures=True)
                if isinstance(self._executor, _DaemonSingleWorker):
                    self._executor.join(self.shutdown_timeout_seconds)
        with self._fetch_guard:
            self._market_fetches.clear()
