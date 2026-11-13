"""Local-only HTTP server for the resource-scoped PTE console."""

from __future__ import annotations

from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from hashlib import sha256
import json
import mimetypes
import re
import secrets
from threading import Thread
from urllib.parse import parse_qs, unquote, urlparse
from typing import Protocol
from uuid import uuid4


from .web_api import PteWebApi, ResourceNotFound
from execution_channels.futu.account_retirement import AccountRetirementRequest
from execution_channels.futu.channel_accounts import DEFAULT_CHANNEL_ACCOUNT


class Operations(Protocol):
    def drive_virtual_account_decision(self, account_id: str) -> dict[str, object]: ...


def create_server(
    operations: Operations, *, host: str = "127.0.0.1", port: int = 8080,
    control_token: str | None = None, restart_callback=None, instance_id: str | None = None,
    multichannel_runtime=None,
):
    api = (operations if hasattr(operations, "system_status")
           else PteWebApi(operations, multichannel_runtime=multichannel_runtime))
    static_root = files("paper_trading_engine").joinpath("static")
    runtime_instance_id = instance_id or uuid4().hex
    # Bind the loaded document to its assets, independently of the release label.
    chart_root = files("strategy_chart").joinpath("static")
    digest = sha256()
    for root in (static_root, chart_root):
        for resource in sorted(root.iterdir(), key=lambda item: item.name):
            if resource.is_file():
                digest.update(resource.name.encode())
                digest.update(sha256(resource.read_bytes()).digest())
    ui_revision = digest.hexdigest()

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
                self.send_header("X-PTE-UI-Revision", ui_revision)
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
            resource = (files("strategy_chart").joinpath("static", name)
                        if name in {"strategy-chart.js", "strategy-chart.css"}
                        else static_root.joinpath(name))
            if not resource.is_file():
                self._json(404, {"error": "not found"})
                return
            content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
            body = resource.read_bytes()
            if name == "index.html":
                body = body.replace(b"__PTE_UI_REVISION__", ui_revision.encode())
            self._send(200, body, f"{content_type}; charset=utf-8")

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
                if path == "/api/health":
                    self._json(200, {**api.health(), "instance_id": runtime_instance_id})
                elif path == "/api/system/status":
                    market = parse_qs(parsed.query).get("market", [None])[-1]
                    status = api.system_status() if market is None else api.system_status(market)
                    self._json(200, {**status, "instance_id": runtime_instance_id})
                elif path == "/api/channel-accounts":
                    self._json(200, api.channel_accounts(parse_qs(parsed.query).get("market", [None])[-1]))
                elif path == "/api/virtual-accounts":
                    market = parse_qs(parsed.query).get("market", [None])[-1]
                    self._json(200, api.virtual_accounts() if market is None else api.virtual_accounts(market))
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
                elif path.startswith("/api/channel-accounts/") and path.endswith("/snapshot"):
                    channel_account_id = unquote(path[len("/api/channel-accounts/"):-len("/snapshot")])
                    self._json(200, api.channel_account_snapshot(channel_account_id))
                elif path == "/api/comparison":
                    query = parse_qs(parsed.query, keep_blank_values=True)
                    ids = [value for value in query["account_id"] if value] if "account_id" in query else None
                    market = query.get("market", [None])[-1] or None
                    self._json(200, api.comparison(ids) if market is None else api.comparison(ids, market))
                elif path == "/api/audit-events":
                    query = parse_qs(parsed.query, keep_blank_values=True)
                    filters = {key: values[-1] for key, values in query.items()}
                    self._json(200, api.audit_events(filters))
                elif path.startswith("/static/"):
                    self._resource(path.removeprefix("/static/"))
                elif path in {"/", "/comparison", "/audit-events", "/channels", "/channels/futu-simulate-cn"} or path.startswith("/accounts/"):
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
                driver = operations if multichannel_runtime is None else multichannel_runtime
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
                elif path == "/api/channels/futu-simulate-cn/pause":
                    operations.pause()
                    result = api.channel_snapshot("futu_simulate_cn")
                elif path == "/api/channels/futu-simulate-cn/resume":
                    operations.resume()
                    result = api.channel_snapshot("futu_simulate_cn")
                elif path == "/api/channels/futu-simulate-cn/cancel-token":
                    result = {"token": operations.issue_cancel_token(
                        str(body["account_id"]), str(body["channel_order_id"])
                    )}
                elif path == "/api/channels/futu-simulate-cn/cancel":
                    result = operations.confirm_cancel(
                        str(body["account_id"]), str(body["channel_order_id"]), str(body["token"])
                    )
                elif parts[:2] == ["api", "channel-accounts"] and len(parts) == 4:
                    channel_account_id, action = unquote(parts[2]), parts[3]
                    if multichannel_runtime is None and channel_account_id == DEFAULT_CHANNEL_ACCOUNT:
                        channel = operations
                    else:
                        channel = api._channel_services(channel_account_id).execution
                    if action in {"pause", "resume"} and not body:
                        (channel.pause if action == "pause" else channel.resume)()
                        result = api.channel_account_snapshot(channel_account_id)
                    elif action in {"cancel-token", "cancel"}:
                        fields = {"account_id", "channel_order_id"}
                        if action == "cancel":
                            fields.add("token")
                        if set(body) != fields or any(type(body[key]) is not str or not body[key] for key in fields):
                            raise ValueError("invalid channel cancellation request")
                        args = body["account_id"], body["channel_order_id"]
                        result = ({"token": channel.issue_cancel_token(*args)} if action == "cancel-token"
                                  else channel.confirm_cancel(*args, body["token"]))
                    elif action in {"pause", "resume"}:
                        raise ValueError("channel pause/resume request body must be empty")
                    else:
                        self._json(404, {"error": "not found"})
                        return
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
                        result = driver.drive_virtual_account_decision(account_id)
                    elif parts[3] == "pause":
                        result = driver.pause_virtual(account_id)
                    elif parts[3] == "resume":
                        result = driver.resume_virtual(account_id)
                    elif parts[3] == "retire":
                        supplied = self.headers.get("X-PTE-Control-Token", "")
                        if control_token is None or not secrets.compare_digest(supplied, control_token):
                            self._json(403, {"error": "invalid PTE control token"})
                            return
                        if set(body) != {"expected_release_hash", "actor", "reason"}:
                            raise ValueError("retirement requires expected_release_hash, actor and reason")
                        result = asdict(driver.retire_account(AccountRetirementRequest(
                            account_id, body["expected_release_hash"], body["actor"], body["reason"],
                        )))
                        response_status = 200 if result["status"] == "RETIRED" else 202
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
                    result = driver.repair_account_ledger(account_id, intent_id)
                elif (
                    parts[:2] == ["api", "virtual-accounts"]
                    and len(parts) == 6
                    and parts[3] == "intents"
                    and parts[5] == "acknowledge"
                ):
                    account_id = unquote(parts[2])
                    intent_id = unquote(parts[4])
                    driver.acknowledge_execution_gap(
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
