"""Local-only HTTP server for the resource-scoped PTE console."""

from __future__ import annotations

from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json
import mimetypes
import re
import secrets
from threading import Thread
from urllib.parse import parse_qs, unquote, urlparse
from typing import Protocol
from uuid import uuid4


from .web_api import PteWebApi, ResourceNotFound
from .account_retirement import AccountRetirementRequest


class Operations(Protocol):
    def status(self) -> dict[str, object]: ...


def create_server(
    operations: Operations, *, host: str = "127.0.0.1", port: int = 8080,
    control_token: str | None = None, restart_callback=None, instance_id: str | None = None,
):
    api = operations if hasattr(operations, "system_status") else PteWebApi(operations)
    static_root = files("paper_trading_engine").joinpath("static")
    runtime_instance_id = instance_id or uuid4().hex

    class Handler(BaseHTTPRequestHandler):
        def _send(
            self, status: int, body: bytes, content_type: str, *,
            cache_control: str = "no-store", etag: str | None = None,
        ) -> None:
            try:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", cache_control)
                if etag is not None:
                    self.send_header("ETag", etag)
                self.end_headers()
                if body:
                    self.wfile.write(body)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                # Browser polling and chart navigation legitimately cancel stale requests.
                return

        def _json(self, status: int, payload: object) -> None:
            self._send(status, json.dumps(payload, ensure_ascii=False, default=str).encode(),
                       "application/json; charset=utf-8")

        def _resource(self, name: str) -> None:
            # Static assets are flat, package-owned files. Reject path syntax on
            # both Windows and POSIX before joining any user-controlled value.
            if not name or name in {".", ".."} or any(c in name for c in "/\\:%\0"):
                self._json(404, {"error": "not found"})
                return
            resource = static_root.joinpath(name)
            if not resource.is_file():
                self._json(404, {"error": "not found"})
                return
            content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
            self._send(200, resource.read_bytes(), f"{content_type}; charset=utf-8")

        def _body(self) -> dict[str, object]:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 1_000_000:
                raise ValueError("request body too large")
            value = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(value, dict):
                raise ValueError("request body must be an object")
            return value

        def _chart(self, account_id: str, query: dict[str, list[str]]) -> None:
            requested = query.get("v", [""])[-1]
            if re.fullmatch(r"[0-9a-f]{64}", requested) is None:
                raise ResourceNotFound(account_id)
            path = api.virtual_account_chart_path(account_id, requested)
            if not path.is_file():
                raise ResourceNotFound(account_id)
            etag = f'"{requested}"'
            cache_control = "private, max-age=31536000, immutable"
            if self.headers.get("If-None-Match") == etag:
                self._send(
                    304, b"", "text/html; charset=utf-8",
                    cache_control=cache_control, etag=etag,
                )
                return
            self._send(
                200, path.read_bytes(), "text/html; charset=utf-8",
                cache_control=cache_control, etag=etag,
            )

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            try:
                if path == "/api/status":
                    self._json(200, operations.status())
                elif path == "/api/health":
                    health = (
                        api.health()
                        if hasattr(api, "health")
                        else {
                            key: value
                            for key, value in api.system_status().items()
                            if key in {
                                "runtime", "watchdog_healthy", "scheduler_heartbeat_at",
                            }
                        }
                    )
                    self._json(200, {**health, "instance_id": runtime_instance_id})
                elif path == "/api/system/status":
                    self._json(200, {**api.system_status(), "instance_id": runtime_instance_id})
                elif path == "/api/virtual-accounts":
                    self._json(200, api.virtual_accounts())
                elif path.startswith("/api/virtual-accounts/") and path.endswith("/snapshot"):
                    account_id = unquote(path[len("/api/virtual-accounts/"):-len("/snapshot")].strip("/"))
                    self._json(200, api.virtual_account_snapshot(account_id))
                elif path.startswith("/api/virtual-accounts/") and path.endswith("/chart"):
                    account_id = unquote(path[len("/api/virtual-accounts/"):-len("/chart")].strip("/"))
                    self._json(200, api.virtual_account_chart(account_id))
                elif path.startswith("/charts/") and path.endswith("/observation.html"):
                    account_id = unquote(path[len("/charts/"):-len("/observation.html")].strip("/"))
                    self._chart(account_id, parse_qs(parsed.query, keep_blank_values=True))
                elif path == "/api/channels/futu-simulate-cn/snapshot":
                    self._json(200, api.channel_snapshot("futu_simulate_cn"))
                elif path == "/api/comparison":
                    self._json(200, api.comparison(parse_qs(parsed.query).get("account_id", [])))
                elif path == "/api/audit-events":
                    query = parse_qs(parsed.query, keep_blank_values=True)
                    filters = {key: values[-1] for key, values in query.items()}
                    self._json(200, api.audit_events(filters))
                elif path.startswith("/static/"):
                    self._resource(path.removeprefix("/static/"))
                elif path in {"/", "/comparison", "/audit-events", "/channels/futu-simulate-cn"} or path.startswith("/accounts/"):
                    self._resource("index.html")
                else:
                    self._json(404, {"error": "not found"})
            except ResourceNotFound as exc:
                self._json(404, {"error": f"unknown resource: {exc.args[0]}"})
            except ValueError as exc:
                self._json(400, {"error": str(exc)})

        def do_POST(self) -> None:
            if self.headers.get_content_type() != "application/json":
                self._json(415, {"error": "application/json is required"})
                return
            try:
                body = self._body()
                path = urlparse(self.path).path
                parts = path.strip("/").split("/")
                response_status = 200
                if path == "/api/system/restart":
                    supplied = self.headers.get("X-PTE-Control-Token", "")
                    if control_token is None or not secrets.compare_digest(supplied, control_token):
                        self._json(403, {"error": "invalid PTE control token"})
                        return
                    if restart_callback is None:
                        self._json(409, {"error": "restart control is unavailable"})
                        return
                    self._json(202, {"status": "RESTART_ACCEPTED", "instance_id": runtime_instance_id})
                    Thread(target=restart_callback, name="pte-graceful-restart", daemon=True).start()
                    return
                if path == "/api/channels/futu-simulate-cn/reconciliation-account":
                    supplied = self.headers.get("X-PTE-Control-Token", "")
                    if control_token is None or not secrets.compare_digest(supplied, control_token):
                        self._json(403, {"error": "invalid PTE control token"})
                        return
                    result = operations.store.create_channel_reconciliation_account()
                elif path in {"/api/pause", "/api/channels/futu-simulate-cn/pause"}:
                    result = operations.pause()
                    if path.startswith("/api/channels/"):
                        result = api.channel_snapshot("futu_simulate_cn")
                elif path in {"/api/resume", "/api/channels/futu-simulate-cn/resume"}:
                    result = operations.resume()
                    if path.startswith("/api/channels/"):
                        result = api.channel_snapshot("futu_simulate_cn")
                elif path in {"/api/cancel-token", "/api/channels/futu-simulate-cn/cancel-token"}:
                    result = {"token": operations.issue_cancel_token(
                        str(body["account_id"]), str(body["channel_order_id"])
                    )}
                elif path in {"/api/cancel", "/api/channels/futu-simulate-cn/cancel"}:
                    result = operations.confirm_cancel(
                        str(body["account_id"]), str(body["channel_order_id"]), str(body["token"])
                    )
                elif (
                    parts[:2] == ["api", "virtual-accounts"]
                    and len(parts) == 5
                    and parts[3:] == ["chart", "refresh"]
                ):
                    if body:
                        raise ValueError("chart refresh request body must be empty")
                    account_id = unquote(parts[2])
                    result = api.refresh_virtual_account_chart(account_id)
                    response_status = 202
                elif parts[:2] == ["api", "virtual-accounts"] and len(parts) == 4:
                    account_id = unquote(parts[2])
                    if parts[3] == "decision":
                        if body:
                            raise ValueError("decision request body must be empty")
                        result = operations.drive_virtual_account_decision(account_id)
                    elif parts[3] == "pause":
                        result = operations.pause_virtual(account_id)
                    elif parts[3] == "resume":
                        result = operations.resume_virtual(account_id)
                    elif parts[3] == "retire":
                        supplied = self.headers.get("X-PTE-Control-Token", "")
                        if control_token is None or not secrets.compare_digest(supplied, control_token):
                            self._json(403, {"error": "invalid PTE control token"})
                            return
                        if set(body) != {"expected_release_hash", "actor", "reason"}:
                            raise ValueError("retirement requires expected_release_hash, actor and reason")
                        result = asdict(operations.retire_account(AccountRetirementRequest(
                            account_id, body["expected_release_hash"], body["actor"], body["reason"],
                        )))
                    else:
                        self._json(404, {"error": "not found"})
                        return
                    if parts[3] in {"pause", "resume"}:
                        result = api.virtual_account_snapshot(account_id)
                elif (
                    parts[:2] == ["api", "virtual-accounts"]
                    and len(parts) == 6
                    and parts[3] == "intents"
                    and parts[5] == "repair-ledger"
                ):
                    supplied = self.headers.get("X-PTE-Control-Token", "")
                    if control_token is None or not secrets.compare_digest(supplied, control_token):
                        self._json(403, {"error": "invalid PTE control token"})
                        return
                    account_id = unquote(parts[2])
                    intent_id = unquote(parts[4])
                    result = operations.repair_account_ledger(account_id, intent_id)
                elif (
                    parts[:2] == ["api", "virtual-accounts"]
                    and len(parts) == 6
                    and parts[3] == "intents"
                    and parts[5] == "acknowledge"
                ):
                    account_id = unquote(parts[2])
                    intent_id = unquote(parts[4])
                    operations.acknowledge_execution_gap(
                        account_id, intent_id, str(body.get("resolution_note") or ""),
                    )
                    result = api.virtual_account_snapshot(account_id)
                else:
                    self._json(404, {"error": "not found"})
                    return
                self._json(response_status, result)
            except ResourceNotFound as exc:
                self._json(404, {"error": f"unknown resource: {exc.args[0]}"})
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except KeyError as exc:
                self._json(404, {"error": f"unknown resource: {exc.args[0]}"})
            except Exception as exc:
                self._json(409, {"error": str(exc)})

        def log_message(self, format: str, *args: object) -> None:
            return

    return ThreadingHTTPServer((host, int(port)), Handler)
