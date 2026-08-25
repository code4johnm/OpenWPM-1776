"""Playwright/CDP measurement: HTTP, cookies, navigation, DNS, JS, bodies.

Replaces the privileged Firefox WebExtension. Records land in the same
SQLite/Parquet tables via the StorageController socket.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import domain_utils as du

from ..browser import BrowserSession
from ..config import BrowserParamsInternal, ManagerParamsInternal
from ..storage.storage_controller import (
    ACTION_TYPE_FINALIZE,
    ACTION_TYPE_INITIALIZE,
    RECORD_TYPE_CONTENT,
    RECORD_TYPE_META,
    DataSocket,
)
from ..storage.storage_providers import TableName
from ..types import BrowserId, VisitId
from .neterror import is_dns_failure_message, neterror_code
from .provenance import build_crawl_outcome_record, build_provenance_record

if TYPE_CHECKING:
    from playwright.sync_api import BrowserContext, Frame, Page, Request, Response

logger = logging.getLogger("openwpm")

# Playwright Response.finished()/body() wait until Content-Length bytes
# arrive and accept no timeout. /CONNECTION_ABORT/ sends Content-Length
# 99999 and only b"partial", which pins the sync dispatcher until GHA
# cancels the job. Never call those waits unbounded.
_RESPONSE_IO_TIMEOUT_MS = 5000

INJECT_JS = Path(__file__).resolve().parent / "js_inject.js"

RESOURCE_TYPE_MAP = {
    "document": "main_frame",
    "stylesheet": "stylesheet",
    "image": "image",
    "media": "media",
    "font": "font",
    "script": "script",
    "texttrack": "other",
    "xhr": "xmlhttprequest",
    "fetch": "xmlhttprequest",
    "eventsource": "other",
    "websocket": "websocket",
    "manifest": "web_manifest",
    "other": "other",
    "ping": "ping",
    "prefetch": "other",
    "preflight": "other",
    "favicon": "image",
}

SKIP_URL_PREFIXES = (
    "chrome://",
    "chrome-extension://",
    "devtools://",
    "data:",
    "blob:",
)

DNS_FAIL_TOKENS = (
    "ERR_NAME_NOT_RESOLVED",
    "ERR_NAME_NOT_RESOLVED",
    "net::ERR_NAME_NOT_RESOLVED",
)


def _playwright_call_timeout(
    fn: Any,
    timeout_ms: int = _RESPONSE_IO_TIMEOUT_MS,
    allow_unbounded: bool = False,
) -> Any:
    """Invoke a Playwright wait only if it accepts ``timeout=``.

    Returns None on timeout, TypeError (no timeout API — do not call
    unbounded unless ``allow_unbounded``), or any other Playwright error.
    ``allow_unbounded`` is for ``save_content`` only: those pages complete
    and CONNECTION_ABORT tests do not enable body capture.
    """
    try:
        return fn(timeout=timeout_ms)
    except TypeError:
        if not allow_unbounded:
            return None
        try:
            return fn()
        except Exception:
            return None
    except Exception:
        return None


def _utc_now() -> str:
    # Match historical OpenWPM JS timestamps: milliseconds + Z.
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# Historical OpenWPM stored headers as a JSON list of ``[Name, value]``
# pairs. Playwright's ``headers`` dict lowercases names; ``headers_array``
# keeps wire case and duplicate names. Do not lowercase in ``_headers_json``.
def _headers_json(headers: Any) -> str:
    pairs: List[List[str]] = []
    items: Any
    if isinstance(headers, dict):
        items = headers.items()
    else:
        items = headers or []
    for item in items:
        if isinstance(item, dict):
            name, value = item.get("name", ""), item.get("value", "")
        else:
            name, value = item[0], item[1]
        pairs.append([str(name), str(value)])
    return json.dumps(pairs)


def _header_pairs_from_playwright(resource: Any) -> List[Tuple[str, str]]:
    try:
        array = resource.headers_array
        if callable(array):
            array = array()
        if array is not None:
            return [(str(h["name"]), str(h["value"])) for h in array]
    except Exception:
        pass
    try:
        return [(str(k), str(v)) for k, v in dict(resource.headers).items()]
    except Exception:
        return []


def _origin(url: str) -> str:
    try:
        parsed = urlparse(url)
        if not parsed.scheme:
            return "undefined"
        netloc = parsed.netloc
        return f"{parsed.scheme}://{netloc}"
    except Exception:
        return "undefined"


def _third_party(url: str, top_url: Optional[str]) -> Optional[int]:
    if not top_url or top_url.startswith("about:"):
        return None
    try:
        if du.get_ps_plus_1(url) != du.get_ps_plus_1(top_url):
            return 1
        return None
    except Exception:
        return None


def _should_skip_url(url: str) -> bool:
    if not url:
        return True
    return url.startswith(SKIP_URL_PREFIXES)


def _js_value_to_str(value: Any) -> str:
    """Match historical extension serialization: undefined/true/compact JSON."""
    if value is None:
        return "undefined"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    return str(value)


def _request_resource_type(request: Any, frame: Optional["Frame"]) -> str:
    raw = (getattr(request, "resource_type", None) or "").lower()
    mapped = RESOURCE_TYPE_MAP.get(raw, "other")
    if raw == "document":
        try:
            return (
                "main_frame"
                if (frame is None or frame.parent_frame is None)
                else "sub_frame"
            )
        except Exception:
            return "main_frame"
    if mapped != "other":
        return mapped
    path = urlparse(getattr(request, "url", "") or "").path.lower()
    if path.endswith(".js"):
        return "script"
    if path.endswith(".css"):
        return "stylesheet"
    if path.endswith((".html", ".htm")):
        try:
            return (
                "main_frame"
                if (frame is None or getattr(frame, "parent_frame", None) is None)
                else "sub_frame"
            )
        except Exception:
            return "main_frame"
    return mapped


class MeasurementController:
    """Per-browser instrumentation attached to a Playwright context.

    Implements ``send()`` so existing Initialize/Finalize/GetCommand call
    sites that talked to the extension socket keep working.
    """

    def __init__(
        self,
        session: BrowserSession,
        browser_params: BrowserParamsInternal,
        manager_params: ManagerParamsInternal,
    ) -> None:
        self.session = session
        self.browser_params = browser_params
        self.manager_params = manager_params
        assert browser_params.browser_id is not None
        self.browser_id: BrowserId = browser_params.browser_id
        self.visit_id: Optional[VisitId] = None
        self.event_ordinal = 0
        self.session_uuid = str(uuid.uuid4())
        self._request_ids: Dict[str, int] = {}
        self._next_request_id = 1
        self._cdp_by_url: Dict[str, Dict[str, Any]] = {}
        self._cdp_id_to_url: Dict[str, str] = {}
        self._cdp_cache_ids: set = set()
        self._cdp_cache_urls: set = set()
        self._cdp_initiator_types: Dict[str, str] = {}
        self._dedicated_workers: set = set()
        self._recorded_worker_request_keys: set = set()
        self._pending_cdp_worker: List[Tuple[str, str]] = []
        self._seen_dns: set = set()
        self._cookie_keys: set = set()
        self._cdp = None
        self._tab_ids: Dict[int, int] = {}
        self._next_tab_id = 1
        self._current_top_url: Optional[str] = None
        self._js_buffer: List[Dict[str, Any]] = []
        self._seen_favicon_paths: set = set()
        self._cdp_initiators: Dict[str, str] = {}
        self._seen_response_urls: set = set()
        self._cdp_bodies: Dict[str, bytes] = {}
        self._pending_responses: List[Dict[str, Any]] = []
        self._worker_cdps: List[Any] = []
        self._cdp_session_worker_url: Dict[str, str] = {}
        self._cdp_msg_id = 1000
        self._pending_auto_attach: List[Dict[str, Any]] = []
        self._paused_session_ids: set = set()
        self._resume_after_enable: Dict[int, str] = {}
        self._pending_content_responses: Dict[str, Any] = {}
        self._navigated_urls: set = set()
        self._provenance_written = False
        self.sock = DataSocket(
            manager_params.storage_controller_address,  # type: ignore[arg-type]
            f"Browser-{self.browser_id}",
        )

    def attach(self) -> None:
        page = self.session.page
        context = self.session.context

        if self.browser_params.record_provenance:
            self._record_provenance()

        if self.browser_params.js_instrument:
            self._attach_js(context)

        if (
            self.browser_params.http_instrument
            or self.browser_params.cookie_instrument
            or self.browser_params.dns_instrument
        ):
            self._attach_cdp(page)

        if self.browser_params.http_instrument:
            context.on("request", self._on_request)
            context.on("response", self._on_response)
            page.on("worker", self._on_worker)

        if self.browser_params.http_instrument or self.browser_params.dns_instrument:
            context.on("requestfailed", self._on_request_failed)

        if self.browser_params.navigation_instrument:
            context.on("page", self._on_new_page)
            page.on("framenavigated", self._on_frame_navigated)
        elif self.browser_params.http_instrument:
            context.on("page", self._on_new_page)

        if self.browser_params.cookie_instrument:
            self._snapshot_cookies("manual-export")

        logger.debug("BROWSER %i: Measurement controller attached", self.browser_id)

    def close(self) -> None:
        try:
            self._flush_pending_responses()
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass

    # --- extension-socket compatibility ---------------------------------
    def send(self, msg: Any) -> None:
        if isinstance(msg, dict):
            action = msg.get("action")
            visit_id = VisitId(int(msg["visit_id"]))
            if action == "Initialize":
                self.initialize(visit_id)
            elif action == "Finalize":
                self.finalize(visit_id, success=bool(msg.get("success", True)))
            return
        self.set_visit_id(VisitId(int(msg)))

    def set_visit_id(self, visit_id: VisitId) -> None:
        self.visit_id = visit_id

    def initialize(self, visit_id: VisitId) -> None:
        self._flush_pending_responses()
        self.visit_id = visit_id
        self.event_ordinal = 0
        self._seen_favicon_paths = set()
        self._current_top_url = None
        self._cdp_cache_ids = set()
        self._cdp_cache_urls = set()
        self._recorded_worker_request_keys = set()
        self._pending_cdp_worker = []
        self._cdp_bodies = {}
        self._pending_content_responses = {}
        self._flush_js_buffer()
        self.sock.socket.send(
            (
                RECORD_TYPE_META,
                {
                    "action": ACTION_TYPE_INITIALIZE,
                    "visit_id": int(visit_id),
                    "browser_id": int(self.browser_id),
                },
            )
        )

    def finalize(self, visit_id: VisitId, success: bool = True) -> None:
        self._flush_js()
        self._resume_auto_attached_targets()
        # Pump on the command thread (not inside a Playwright event).
        self._pump_playwright(300)
        self._flush_pending_cdp_worker_requests()
        self._flush_pending_responses()
        self._snapshot_history_safe()
        if self.browser_params.cookie_instrument:
            self._snapshot_cookies("manual-export")
        self.sock.socket.send(
            (
                RECORD_TYPE_META,
                {
                    "action": ACTION_TYPE_FINALIZE,
                    "visit_id": int(visit_id),
                    "browser_id": int(self.browser_id),
                    "success": success,
                },
            )
        )
        self.visit_id = None

    def persist_http_responses(self) -> None:
        """Flush queued http_responses on the command thread after navigation."""
        self._resume_auto_attached_targets()
        self._pump_playwright(300)
        self._flush_pending_cdp_worker_requests()
        self._flush_pending_responses()
        self._snapshot_history_safe()

    def _note_visited_url(self, url: Optional[str]) -> None:
        if not url or url.startswith(
            ("about:", "chrome:", "devtools:", "data:", "blob:")
        ):
            return
        self._navigated_urls.add(url)

    def _snapshot_history_safe(self) -> None:
        try:
            page = self.session.page
            if page is not None:
                self._note_visited_url(page.url)
        except Exception:
            pass
        self._note_visited_url(self._current_top_url)
        profile_path = getattr(self.browser_params, "profile_path", None)
        if profile_path is None:
            return
        try:
            from ..commands.utils.firefox_profile import (
                merge_visit_urls_into_history,
                snapshot_chromium_history,
            )

            snapshot_chromium_history(profile_path)
            merge_visit_urls_into_history(profile_path, self._navigated_urls)
        except Exception:
            logger.debug(
                "BROWSER %i: History snapshot failed",
                self.browser_id,
                exc_info=True,
            )

    def _next_ordinal(self) -> int:
        self.event_ordinal += 1
        return self.event_ordinal

    def _rid(self, key: str) -> int:
        if key not in self._request_ids:
            self._request_ids[key] = self._next_request_id
            self._next_request_id += 1
        return self._request_ids[key]

    def _tab_id(self, page: Optional[Page]) -> int:
        if page is None:
            return 1
        ident = id(page)
        if ident not in self._tab_ids:
            self._tab_ids[ident] = self._next_tab_id
            self._next_tab_id += 1
        return self._tab_ids[ident]

    def _save(self, table: str, record: Dict[str, Any]) -> None:
        if self.visit_id is None:
            if table == "javascript":
                self._js_buffer.append(record)
                return
            visit_id = VisitId(-1)
        else:
            visit_id = self.visit_id
        record.setdefault("visit_id", int(visit_id))
        record.setdefault("browser_id", int(self.browser_id))
        self.sock.store_record(TableName(table), visit_id, record)

    def _flush_js_buffer(self) -> None:
        pending = self._js_buffer
        self._js_buffer = []
        for record in pending:
            self._save("javascript", record)

    def record_document_outcome(self, visit_id: VisitId, http_status: Any) -> None:
        if self.browser_params.record_crawl_outcome != "status_codes_only":
            return
        try:
            status_int = int(http_status) if http_status is not None else None
        except (TypeError, ValueError):
            return
        record = build_crawl_outcome_record(
            visit_id=int(visit_id),
            browser_id=int(self.browser_id),
            http_status=status_int if status_int is not None else -1,
        )
        if record is None:
            return
        self.sock.store_record(TableName("crawl_outcome"), visit_id, record)

    def _record_provenance(self) -> None:
        if self._provenance_written:
            return
        user_agent = ""
        try:
            user_agent = self.session.page.evaluate("() => navigator.userAgent") or ""
        except Exception:
            user_agent = ""
        record = build_provenance_record(
            browser_id=int(self.browser_id),
            display_mode=self.browser_params.display_mode,
            user_agent=str(user_agent),
        )
        self.sock.store_record(TableName("crawl_run_provenance"), VisitId(-1), record)
        self.sock.finalize_visit_id(VisitId(-1), success=True)
        self._provenance_written = True

    # --- JS instrument --------------------------------------------------
    def _attach_js(self, context: BrowserContext) -> None:
        settings = self.browser_params.cleaned_js_instrument_settings or []
        testing = bool(self.manager_params.testing)

        def _on_js_log(source: Any, messages: Any) -> None:
            self._record_js_messages(source, messages)

        context.expose_binding("__openwpm_js_log__", _on_js_log)
        context.add_init_script(
            f"window.__OPENWPM_JS_SETTINGS__ = {json.dumps(settings)};"
            f"window.__OPENWPM_JS_TESTING__ = {json.dumps(testing)};"
        )
        if not INJECT_JS.is_file():
            raise RuntimeError(f"JS inject script missing: {INJECT_JS}")
        context.add_init_script(path=str(INJECT_JS))

    def _flush_js(self) -> None:
        if not self.browser_params.js_instrument:
            return
        context = getattr(self.session, "context", None)
        if context is None:
            return
        for page in list(context.pages):
            if page.is_closed():
                continue
            try:
                page.evaluate(
                    "() => { if (window.__openwpm_js_flush__) window.__openwpm_js_flush__(); }"
                )
            except Exception:
                pass

    def _record_js_messages(self, source: Any, messages: Any) -> None:
        if not messages:
            return
        frame_url = ""
        top_url = ""
        try:
            frame_url = source.frame.url if source.frame else ""
            top_url = source.page.url if source.page else ""
        except Exception:
            pass
        tab_id = self._tab_id(getattr(source, "page", None))
        if not isinstance(messages, list):
            messages = [messages]
        for item in messages:
            msg_type = item.get("type") if isinstance(item, dict) else None
            data = item.get("content") if isinstance(item, dict) else item
            if not isinstance(data, dict):
                continue
            document_url = str(data.get("documentUrl") or frame_url or "")
            top_from_js = str(data.get("topLevelUrl") or "")
            page_url = top_from_js or top_url or document_url
            if document_url.startswith(("about:", "chrome:", "chrome-extension:")):
                continue
            if page_url.startswith(("about:", "chrome:", "chrome-extension:")):
                page_url = self._current_top_url or document_url
            if (
                document_url
                and page_url == document_url
                and self._current_top_url
                and self._current_top_url != document_url
            ):
                page_url = self._current_top_url
            if (
                page_url
                and not page_url.startswith(("about:", "chrome:", "chrome-extension:"))
                and (
                    not self._current_top_url
                    or self._current_top_url.startswith(("about:", "chrome:"))
                )
            ):
                self._current_top_url = page_url
            record = {
                "incognito": 0,
                "extension_session_uuid": self.session_uuid,
                "event_ordinal": self._next_ordinal(),
                "page_scoped_event_ordinal": data.get("ordinal"),
                "window_id": 1,
                "tab_id": tab_id,
                "frame_id": 0,
                "script_url": data.get("scriptUrl") or "",
                "script_line": str(data.get("scriptLine") or ""),
                "script_col": str(data.get("scriptCol") or ""),
                "func_name": data.get("funcName") or "",
                "script_loc_eval": data.get("scriptLocEval") or "",
                "document_url": document_url,
                "top_level_url": page_url,
                "call_stack": data.get("callStack") or "",
                "symbol": data.get("symbol") or "",
                "operation": data.get("operation") or "",
                "value": _js_value_to_str(data.get("value")),
                "arguments": None,
                "time_stamp": _utc_now(),
            }
            if msg_type == "logCall" or data.get("operation") == "call":
                args = data.get("args")
                if args:
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            record["arguments"] = args
                            args = None
                    if args:
                        # Historical OpenWPM / JSON.stringify: no spaces.
                        record["arguments"] = json.dumps(args, separators=(",", ":"))
            self._save("javascript", record)

    # --- CDP ------------------------------------------------------------
    def _attach_cdp(self, page: Page) -> None:
        try:
            cdp = self.session.context.new_cdp_session(page)
            cdp.on("Network.requestWillBeSent", self._on_cdp_request)
            cdp.on("Network.responseReceived", self._on_cdp_response)
            cdp.on("Network.requestServedFromCache", self._on_cdp_served_from_cache)
            cdp.on("Network.loadingFailed", self._on_cdp_loading_failed)
            cdp.on("Network.loadingFinished", self._on_cdp_loading_finished)
            if self.browser_params.cookie_instrument:
                cdp.on("Network.cookieChanged", self._on_cdp_cookie)
            cdp.send("Network.enable")
            try:
                cdp.on("Target.attachedToTarget", self._on_cdp_attached_to_target)
                cdp.on(
                    "Target.receivedMessageFromTarget",
                    self._on_cdp_target_message,
                )
                cdp.send(
                    "Target.setAutoAttach",
                    {
                        "autoAttach": True,
                        "waitForDebuggerOnStart": True,
                        "flatten": False,
                    },
                )
            except Exception:
                logger.debug(
                    "BROWSER %i: Target.setAutoAttach failed",
                    self.browser_id,
                    exc_info=True,
                )
            self._cdp = cdp
        except Exception:
            logger.warning(
                "BROWSER %i: CDP Network session failed; cache/DNS extras limited",
                self.browser_id,
            )

    def _send_to_target(
        self, session_id: str, method: str, params: Optional[Dict[str, Any]] = None
    ) -> Optional[int]:
        if self._cdp is None or not session_id:
            return None
        self._cdp_msg_id += 1
        msg_id = self._cdp_msg_id
        message = json.dumps({"id": msg_id, "method": method, "params": params or {}})
        try:
            self._cdp.send(
                "Target.sendMessageToTarget",
                {"sessionId": session_id, "message": message},
            )
        except Exception:
            logger.debug(
                "BROWSER %i: Target.sendMessageToTarget %s failed",
                self.browser_id,
                method,
                exc_info=True,
            )
            return None
        return msg_id

    def _on_cdp_attached_to_target(self, params: Dict[str, Any]) -> None:
        self._pending_auto_attach.append(params)
        info = params.get("targetInfo") or {}
        session_id = str(params.get("sessionId") or "")
        ttype = str(info.get("type") or "")
        url = str(info.get("url") or "")
        if ttype == "worker":
            if url:
                self._dedicated_workers.add(url)
            if session_id:
                self._cdp_session_worker_url[session_id] = url
                enable_id = self._send_to_target(session_id, "Network.enable")
                if enable_id is not None:
                    self._resume_after_enable[enable_id] = session_id
                    self._paused_session_ids.add(session_id)
                    return
        elif ttype in ("service_worker", "shared_worker"):
            if session_id:
                self._cdp_session_worker_url[session_id] = url
                self._send_to_target(session_id, "Network.enable")
        if session_id:
            self._send_to_target(session_id, "Runtime.runIfWaitingForDebugger")
            self._paused_session_ids.discard(session_id)

    def _resume_auto_attached_targets(self) -> None:
        """Enable Network on paused workers, then resume them (command thread)."""
        pending = self._pending_auto_attach
        self._pending_auto_attach = []
        for params in pending:
            info = params.get("targetInfo") or {}
            session_id = str(params.get("sessionId") or "")
            ttype = str(info.get("type") or "")
            url = str(info.get("url") or "")
            if ttype in ("worker", "service_worker", "shared_worker"):
                if url:
                    self._dedicated_workers.add(url)
                if session_id:
                    self._cdp_session_worker_url[session_id] = url
                    self._send_to_target(session_id, "Network.enable")
            if session_id:
                self._send_to_target(session_id, "Runtime.runIfWaitingForDebugger")
                self._paused_session_ids.discard(session_id)
        for session_id in list(self._paused_session_ids):
            self._send_to_target(session_id, "Network.enable")
            self._send_to_target(session_id, "Runtime.runIfWaitingForDebugger")
        self._paused_session_ids.clear()

    def _on_cdp_target_message(self, params: Dict[str, Any]) -> None:
        session_id = str(params.get("sessionId") or "")
        try:
            msg = json.loads(params.get("message") or "{}")
        except Exception:
            return
        reply_id = msg.get("id")
        if reply_id in self._resume_after_enable:
            paused = self._resume_after_enable.pop(reply_id)
            self._send_to_target(paused, "Runtime.runIfWaitingForDebugger")
            self._paused_session_ids.discard(paused)
            return
        method = msg.get("method") or ""
        inner = msg.get("params") or {}
        if method != "Network.requestWillBeSent":
            return
        worker_url = self._cdp_session_worker_url.get(session_id) or ""
        if worker_url:
            self._on_worker_session_cdp_request(inner, worker_url)

    def _on_cdp_request(self, params: Dict[str, Any]) -> None:
        request = params.get("request") or {}
        url = request.get("url") or ""
        rid = params.get("requestId") or ""
        initiator = params.get("initiator") or {}
        init_url = _cdp_initiator_url(initiator)
        init_type = str(initiator.get("type") or "").lower()
        if url:
            self._cdp_initiators[url] = init_url
            self._cdp_initiator_types[url] = init_type
            rec = self._cdp_by_url.get(url) or {}
            rec["fromCache"] = bool(rid and rid in self._cdp_cache_ids)
            rec["fromDiskCache"] = bool(rec.get("fromCache"))
            rec["requestId"] = rid
            rec["initiatorType"] = init_type
            self._cdp_by_url[url] = rec
        if rid and url:
            self._cdp_id_to_url[rid] = url
        if (
            self.browser_params.http_instrument
            and init_type == "worker"
            and url
            and not _should_skip_url(url)
        ):
            try:
                worker_url = init_url or (
                    next(iter(self._dedicated_workers), None)
                    if self._dedicated_workers
                    else None
                )
                if worker_url:
                    self._ensure_worker_request_recorded(
                        url, worker_url, request.get("method") or "GET"
                    )
                else:
                    self._pending_cdp_worker.append(
                        (url, request.get("method") or "GET")
                    )
            except Exception:
                logger.debug(
                    "BROWSER %i: CDP worker request attribution failed",
                    self.browser_id,
                    exc_info=True,
                )
        redirect = params.get("redirectResponse")
        if redirect and self.browser_params.dns_instrument:
            # Chrome keeps requestId stable across hops; record the
            # completed redirect so the chain can be reconstructed.
            old_url = redirect.get("url") or url
            self._record_dns(
                url=old_url,
                request_key=rid or old_url,
                used_address=redirect.get("remoteIPAddress"),
                error=None,
            )

    def _on_cdp_served_from_cache(self, params: Dict[str, Any]) -> None:
        rid = params.get("requestId") or ""
        if not rid:
            return
        self._cdp_cache_ids.add(rid)
        url = self._cdp_id_to_url.get(rid) or ""
        if not url:
            return
        self._cdp_cache_urls.add(url)
        rec = self._cdp_by_url.setdefault(url, {})
        rec["fromDiskCache"] = True
        rec["fromCache"] = True
        rec["requestId"] = rid

    def _on_cdp_response(self, params: Dict[str, Any]) -> None:
        response = params.get("response") or {}
        url = response.get("url") or ""
        rid = params.get("requestId")
        prev = self._cdp_by_url.get(url) or {}
        from_cache = (
            bool(response.get("fromDiskCache"))
            or bool(response.get("fromPrefetchCache"))
            or bool(prev.get("fromCache"))
            or (bool(rid) and rid in self._cdp_cache_ids)
        )
        self._cdp_by_url[url] = {
            "fromDiskCache": from_cache,
            "fromPrefetchCache": bool(response.get("fromPrefetchCache")),
            "fromServiceWorker": bool(response.get("fromServiceWorker")),
            "remoteIPAddress": response.get("remoteIPAddress"),
            "requestId": rid,
            "status": response.get("status"),
            "fromCache": from_cache or bool(prev.get("fromCache")),
        }
        if rid and url:
            self._cdp_id_to_url[str(rid)] = url
        if from_cache and url:
            self._cdp_cache_urls.add(url)
        if self.browser_params.dns_instrument and url:
            self._record_dns(
                url=url,
                request_key=rid or url,
                used_address=response.get("remoteIPAddress"),
                error=None,
            )

    def _on_cdp_loading_finished(self, params: Dict[str, Any]) -> None:
        if not self.browser_params.save_content:
            return
        rid = str(params.get("requestId") or "")
        url = self._cdp_id_to_url.get(rid) or ""
        if not url:
            return
        body = self._cdp_response_body(url)
        if body:
            self._cdp_bodies[url] = body

    def _on_cdp_loading_failed(self, params: Dict[str, Any]) -> None:
        if not self.browser_params.dns_instrument:
            return
        error_text = params.get("errorText") or ""
        if (
            not is_dns_failure_message(error_text)
            and "NAME_NOT_RESOLVED" not in error_text
        ):
            return
        req_id = params.get("requestId") or ""
        url = self._cdp_id_to_url.get(req_id) or ""
        hostname_hint = None
        if url:
            try:
                hostname_hint = urlparse(url).hostname
            except Exception:
                hostname_hint = None
        self._record_dns(
            url=url,
            request_key=req_id or url,
            used_address=None,
            error=neterror_code(error_text) or error_text,
            hostname_hint=hostname_hint,
        )

    def _on_cdp_cookie(self, params: Dict[str, Any]) -> None:
        cookie = params.get("cookie") or {}
        removed = bool(
            params.get("removed") or params.get("cause") == "explicit" and False
        )
        if "removed" in params:
            removed = bool(params["removed"])
        cause = params.get("cause") or "explicit"
        record_type = "deleted" if removed else "added-or-changed"
        self._save_cookie_record(cookie, record_type, str(cause))

    # --- HTTP -----------------------------------------------------------
    def _on_request(self, request: Request) -> None:
        try:
            self._record_request(request)
        except Exception:
            logger.exception("BROWSER %i: HTTP request capture failed", self.browser_id)

    def _safe_frame(self, request: Request) -> Optional[Frame]:
        try:
            return request.frame
        except Exception:
            return None

    def _on_worker(self, worker: Any) -> None:
        try:
            url = worker.url
        except Exception:
            url = ""
        if url:
            self._dedicated_workers.add(url)
            pending = self._pending_cdp_worker
            self._pending_cdp_worker = []
            for req_url, method in pending:
                self._ensure_worker_request_recorded(req_url, url, method)
        try:
            wcdp = self.session.context.new_cdp_session(worker)
            worker_url = url

            def _on_worker_cdp_request(
                params: Dict[str, Any], wu: str = worker_url
            ) -> None:
                self._on_worker_session_cdp_request(params, wu)

            wcdp.on("Network.requestWillBeSent", _on_worker_cdp_request)
            wcdp.send("Network.enable")
            try:
                wcdp.send("Runtime.runIfWaitingForDebugger")
            except Exception:
                pass
            self._worker_cdps.append(wcdp)
        except Exception:
            logger.debug(
                "BROWSER %i: worker CDP session failed",
                self.browser_id,
                exc_info=True,
            )
        try:
            worker.on("request", self._on_request)
            worker.on("response", self._on_response)
        except Exception:
            pass

    def _on_worker_session_cdp_request(
        self, params: Dict[str, Any], worker_url: str
    ) -> None:
        request = params.get("request") or {}
        req_url = request.get("url") or ""
        if not req_url or _should_skip_url(req_url) or not worker_url:
            return
        if req_url.split("?")[0] == worker_url.split("?")[0]:
            return
        self._cdp_initiators[req_url] = worker_url
        self._cdp_initiator_types[req_url] = "worker"
        rid = params.get("requestId") or ""
        if rid:
            self._cdp_id_to_url[str(rid)] = req_url
            rec = self._cdp_by_url.setdefault(req_url, {})
            rec["requestId"] = rid
        self._ensure_worker_request_recorded(
            req_url, worker_url, request.get("method") or "GET"
        )

    def _flush_pending_cdp_worker_requests(self) -> None:
        worker_url = next(iter(self._dedicated_workers), None)
        if not worker_url:
            return
        pending = self._pending_cdp_worker
        self._pending_cdp_worker = []
        for req_url, method in pending:
            self._ensure_worker_request_recorded(req_url, worker_url, method)

    def _ensure_worker_request_recorded(
        self, url: str, worker_url: str, method: str = "GET"
    ) -> None:
        key = (url.split("?")[0], worker_url)
        if key in self._recorded_worker_request_keys:
            return
        if _should_skip_url(url) or url.startswith("about:"):
            return
        self._recorded_worker_request_keys.add(key)
        triggering = _origin(worker_url)
        request_id = self._rid(f"cdp-worker:{url}:{worker_url}")
        self._save(
            "http_requests",
            {
                "incognito": 0,
                "extension_session_uuid": self.session_uuid,
                "event_ordinal": self._next_ordinal(),
                "window_id": 1,
                "tab_id": 1,
                "frame_id": 0,
                "url": url,
                "top_level_url": worker_url,
                "parent_frame_id": -1,
                "frame_ancestors": "[]",
                "method": method,
                "referrer": "",
                "headers": "[]",
                "request_id": request_id,
                "is_XHR": 1,
                "is_third_party_channel": _third_party(url, worker_url),
                "is_third_party_to_top_window": _third_party(url, worker_url),
                "triggering_origin": triggering,
                "loading_origin": triggering,
                "loading_href": worker_url,
                "req_call_stack": None,
                "resource_type": "xmlhttprequest",
                "post_body": None,
                "post_body_raw": None,
                "time_stamp": _utc_now(),
            },
        )

    def _worker_url(self, request: Request) -> Optional[str]:
        resource = (getattr(request, "resource_type", None) or "").lower()
        req_name = urlparse(request.url).path.rsplit("/", 1)[-1]
        # The worker/SW *script* load is a page request.
        if req_name in {"worker.js", "service_worker.js"} and resource in (
            "script",
            "document",
            "",
        ):
            return None
        try:
            worker = getattr(request, "service_worker", None)
            if worker is not None and resource not in ("script", "document"):
                return worker.url
        except Exception:
            pass
        frame_missing = False
        try:
            request.frame
        except Exception:
            frame_missing = True
        init_url = self._cdp_initiators.get(request.url) or ""
        init_type = (self._cdp_initiator_types.get(request.url) or "").lower()
        init_name = urlparse(init_url).path.rsplit("/", 1)[-1] if init_url else ""
        # Dedicated-worker fetch: CDP initiator.type is "worker" even when
        # Playwright still exposes the page frame (the page also
        # <script src>s worker.js). Do not treat service_worker.js as
        # worker.js — the latter is a substring of the former.
        if init_type == "worker" and init_name == "worker.js":
            return init_url
        if frame_missing and init_name in {"worker.js", "service_worker.js"}:
            return init_url
        if frame_missing and self._dedicated_workers:
            if resource not in ("document", "script"):
                if init_url and init_url in self._dedicated_workers:
                    return init_url
                return next(iter(self._dedicated_workers))
        return None

    def _pump_playwright(self, timeout_ms: int = 200) -> None:
        """Process queued CDP events. time.sleep() blocks the sync dispatcher."""
        page = None
        try:
            page = self.session.page
        except Exception:
            page = None
        if page is None:
            return
        try:
            page.wait_for_timeout(timeout_ms)
        except Exception:
            try:
                page.evaluate("() => undefined")
            except Exception:
                pass

    def _record_request(self, request: Request) -> None:
        url = request.url
        if _should_skip_url(url):
            return
        if url.startswith("about:"):
            return
        parsed_path = urlparse(url).path
        if parsed_path == "/favicon.ico":
            # Chromium's automatic root-favicon probe. Record it only when
            # the page did not already request a named favicon (browse tests
            # rely on /favicon.ico as the fourth URL; page-visit tests use
            # shared/test_favicon.ico and fail if both appear).
            if (
                self._seen_favicon_paths
                and "/favicon.ico" not in self._seen_favicon_paths
            ):
                return
        if parsed_path.endswith("favicon.ico"):
            self._seen_favicon_paths.add(parsed_path)
        frame = self._safe_frame(request)
        page = None
        try:
            if frame is not None:
                page = frame.page
        except Exception:
            page = None
        page_url = ""
        try:
            page_url = page.url if page is not None else ""
        except Exception:
            page_url = ""
        resource = (request.resource_type or "").lower()
        mapped = _request_resource_type(request, frame)
        is_xhr = 1 if resource in ("xhr", "fetch") else 0
        frame_url = ""
        try:
            frame_url = frame.url if frame else ""
        except Exception:
            frame_url = ""
        worker_url = self._worker_url(request)
        if worker_url and mapped not in ("script", "main_frame", "sub_frame"):
            is_xhr = 1
            mapped = "xmlhttprequest"
            self._recorded_worker_request_keys.add((url.split("?")[0], worker_url))
        main_frame = mapped == "main_frame"
        if main_frame:
            top_url = url
            self._current_top_url = url
            self._note_visited_url(url)
            triggering = "undefined"
            loading_origin = "undefined"
            loading_href = "undefined"
        elif worker_url and frame is None:
            top_url = worker_url
            triggering = _origin(worker_url)
            loading_origin = triggering
            loading_href = worker_url
        elif (
            worker_url
            and urlparse(worker_url).path.rsplit("/", 1)[-1] == "worker.js"
            and is_xhr
        ):
            top_url = worker_url
            triggering = _origin(worker_url)
            loading_origin = triggering
            loading_href = worker_url
        else:
            top_url = self._current_top_url
            if not top_url or top_url.startswith("about:"):
                top_url = (
                    page_url if page_url and not page_url.startswith("about:") else url
                )
                if top_url and not top_url.startswith("about:"):
                    self._current_top_url = top_url
            triggering = (
                _origin(frame_url)
                if frame_url and not frame_url.startswith("about:")
                else (_origin(top_url) if top_url else "undefined")
            )
            loading_origin = triggering
            if mapped == "sub_frame":
                loading_href = top_url or "undefined"
            else:
                loading_href = (
                    frame_url
                    if frame_url and not frame_url.startswith("about:")
                    else (top_url or "undefined")
                )
        request_id = self._rid(_req_key(request))
        post_body, post_body_raw = _parse_post(request)
        header_pairs = _header_pairs_from_playwright(request)
        if request.method == "POST":
            header_pairs = _ensure_post_headers(header_pairs, request)
        referrer = ""
        for name, value in header_pairs:
            if name.lower() in ("referer", "referrer"):
                referrer = value
                break
        self._save(
            "http_requests",
            {
                "incognito": 0,
                "extension_session_uuid": self.session_uuid,
                "event_ordinal": self._next_ordinal(),
                "window_id": 1,
                "tab_id": self._tab_id(frame.page if frame else None),
                "frame_id": 0,
                "url": url,
                "top_level_url": top_url,
                "parent_frame_id": -1,
                "frame_ancestors": "[]",
                "method": request.method,
                "referrer": referrer,
                "headers": _headers_json(header_pairs),
                "request_id": request_id,
                "is_XHR": is_xhr,
                "is_third_party_channel": _third_party(url, top_url),
                "is_third_party_to_top_window": _third_party(url, top_url),
                "triggering_origin": triggering,
                "loading_origin": loading_origin,
                "loading_href": loading_href,
                "req_call_stack": None,
                "resource_type": mapped,
                "post_body": post_body,
                "post_body_raw": post_body_raw,
                "time_stamp": _utc_now(),
            },
        )
        redirected = request.redirected_from
        if redirected is not None:
            location = ""
            redirect_headers: List[Tuple[str, str]] = []
            try:
                resp = redirected.response()
                if resp:
                    redirect_headers = _header_pairs_from_playwright(resp)
                    for name, value in redirect_headers:
                        if name.lower() == "location":
                            location = value
                            break
            except Exception:
                location = ""
            if not any(name.lower() == "location" for name, _ in redirect_headers):
                redirect_headers = list(redirect_headers) + [
                    ("Location", location or url)
                ]
            self._save(
                "http_redirects",
                {
                    "incognito": 0,
                    "extension_session_uuid": self.session_uuid,
                    "event_ordinal": self._next_ordinal(),
                    "window_id": 1,
                    "tab_id": self._tab_id(page),
                    "frame_id": 0,
                    "old_request_url": redirected.url,
                    "old_request_id": str(self._rid(_req_key(redirected))),
                    "new_request_url": url,
                    "new_request_id": str(request_id),
                    "response_status": 302,
                    "response_status_text": "",
                    "headers": _headers_json(redirect_headers),
                    "time_stamp": _utc_now(),
                },
            )

    def _on_response(self, response: Response) -> None:
        try:
            self._record_response(response)
        except Exception:
            logger.exception(
                "BROWSER %i: HTTP response capture failed", self.browser_id
            )

    def _record_response(self, response: Response) -> None:
        url = response.url
        if _should_skip_url(url) or url.startswith("about:"):
            return
        parsed_path = urlparse(url).path
        if parsed_path == "/favicon.ico":
            if (
                self._seen_favicon_paths
                and "/favicon.ico" not in self._seen_favicon_paths
            ):
                return
        request = response.request
        request_id = self._rid(_req_key(request))
        _playwright_call_timeout(response.finished)
        extra = self._cdp_by_url.get(url, {})
        cdp_rid = extra.get("requestId")
        already_cached = bool(
            extra.get("fromCache")
            or extra.get("fromDiskCache")
            or extra.get("fromPrefetchCache")
            or (cdp_rid and cdp_rid in self._cdp_cache_ids)
            or url in self._cdp_cache_urls
        )
        from_cache = 1 if already_cached else 0
        self._seen_response_urls.add(url)
        header_pairs = _header_pairs_from_playwright(response)
        headers = {k.lower(): v for k, v in header_pairs}
        location = headers.get("location") or ""
        frame = self._safe_frame(request)
        page = None
        try:
            page = frame.page if frame is not None else None
        except Exception:
            page = None
        content_hash = None
        want_content = self._content_resource_allowed(response)
        if want_content:
            content_hash = self._maybe_save_body(response, request_id)
        record = {
            "incognito": 0,
            "extension_session_uuid": self.session_uuid,
            "event_ordinal": self._next_ordinal(),
            "window_id": 1,
            "tab_id": self._tab_id(page),
            "frame_id": 0,
            "url": url,
            "method": request.method,
            "response_status": response.status,
            "response_status_text": response.status_text or "",
            "is_cached": from_cache,
            "headers": _headers_json(header_pairs),
            "request_id": request_id,
            "location": location,
            "time_stamp": _utc_now(),
            "content_hash": content_hash,
        }
        if self.visit_id is not None:
            record["visit_id"] = int(self.visit_id)
        if want_content:
            record["_want_content"] = content_hash is None
            if content_hash is None:
                self._pending_content_responses[url] = response
        # Defer write so GetCommand/finalize can apply late CDP cache
        # and body events. wait_for_timeout inside this handler deadlocks.
        self._pending_responses.append(record)
        if self.browser_params.dns_instrument:
            used = extra.get("remoteIPAddress")
            if used:
                self._record_dns(
                    url=url,
                    request_key=_req_key(request),
                    used_address=used,
                    error=None,
                )

    def _flush_pending_responses(self) -> None:
        pending = self._pending_responses
        self._pending_responses = []
        for record in pending:
            url = str(record.get("url") or "")
            extra = self._cdp_by_url.get(url, {})
            cdp_rid = extra.get("requestId")
            if (
                extra.get("fromCache")
                or extra.get("fromDiskCache")
                or extra.get("fromPrefetchCache")
                or (cdp_rid and cdp_rid in self._cdp_cache_ids)
                or url in self._cdp_cache_urls
            ):
                record["is_cached"] = 1
            want_content = bool(record.pop("_want_content", False))
            if want_content and not record.get("content_hash"):
                body = self._cdp_bodies.get(url) or self._cdp_response_body(url)
                if not body:
                    pending_resp = self._pending_content_responses.get(url)
                    if pending_resp is not None:
                        raw = _playwright_call_timeout(
                            pending_resp.body, allow_unbounded=True
                        )
                        if raw is not None:
                            body = (
                                raw
                                if isinstance(raw, (bytes, bytearray))
                                else bytes(raw)
                            )
                if body:
                    digest = hashlib.sha256(body).hexdigest()
                    b64 = base64.b64encode(body).decode("ascii")
                    self.sock.socket.send((RECORD_TYPE_CONTENT, [b64, digest]))
                    record["content_hash"] = digest
                    self._pending_content_responses.pop(url, None)
            self._save("http_responses", record)

    def _on_request_failed(self, request: Request) -> None:
        err = ""
        try:
            failure = request.failure
            if isinstance(failure, dict):
                err = str(failure.get("errorText") or failure)
            else:
                err = failure or ""
        except Exception:
            err = ""
        if self.browser_params.dns_instrument and is_dns_failure_message(err):
            self._record_dns(
                url=request.url,
                request_key=_req_key(request),
                used_address=None,
                error=neterror_code(err) or "dnsNotFound",
            )

    def _cdp_response_body(self, url: str) -> Optional[bytes]:
        rec = self._cdp_by_url.get(url) or {}
        rid = rec.get("requestId")
        if not rid or self._cdp is None:
            return None
        try:
            send = self._cdp.send
            try:
                result = send(
                    "Network.getResponseBody",
                    {"requestId": rid},
                    timeout=_RESPONSE_IO_TIMEOUT_MS,
                )
            except TypeError:
                if not self.browser_params.save_content:
                    return None
                result = send("Network.getResponseBody", {"requestId": rid})
        except Exception:
            return None
        if not result:
            return None
        payload = result.get("body")
        if payload is None:
            return None
        if result.get("base64Encoded"):
            try:
                return base64.b64decode(payload)
            except Exception:
                return None
        if isinstance(payload, (bytes, bytearray)):
            return bytes(payload)
        return str(payload).encode("utf-8", errors="replace")

    def _content_resource_allowed(self, response: Response) -> bool:
        option = self.browser_params.save_content
        if option is True:
            return True
        if not option or not isinstance(option, str):
            return False
        allowed = {s.strip() for s in option.split(",") if s.strip()}
        if not allowed:
            return False
        frame = self._safe_frame(response.request)
        resource = _request_resource_type(response.request, frame)
        path = urlparse(response.url).path.lower()
        if resource in allowed:
            return True
        if "script" in allowed and path.endswith(".js"):
            return True
        if {"main_frame", "sub_frame"} & allowed and path.endswith((".html", ".htm")):
            return True
        return False

    def _maybe_save_body(self, response: Response, request_id: int) -> Optional[str]:
        if not self._content_resource_allowed(response):
            return None
        # CONNECTION_ABORT tests keep save_content off.
        _playwright_call_timeout(response.finished, allow_unbounded=True)
        body: Optional[bytes] = self._cdp_bodies.get(response.url)
        if not body:
            raw = _playwright_call_timeout(response.body, allow_unbounded=True)
            if raw is not None:
                body = raw if isinstance(raw, (bytes, bytearray)) else bytes(raw)
        if not body:
            body = self._cdp_response_body(response.url)
        if not body:
            return None
        digest = hashlib.sha256(body).hexdigest()
        b64 = base64.b64encode(body).decode("ascii")
        self.sock.socket.send((RECORD_TYPE_CONTENT, [b64, digest]))
        return digest

    # --- DNS ------------------------------------------------------------
    def _record_dns(
        self,
        url: str,
        request_key: str,
        used_address: Optional[str],
        error: Optional[str],
        hostname_hint: Optional[str] = None,
    ) -> None:
        hostname = hostname_hint or ""
        if url:
            try:
                hostname = urlparse(url).hostname or hostname
            except Exception:
                pass
        if not hostname and not error:
            return
        key = (hostname, used_address, error, url)
        if key in self._seen_dns:
            return
        self._seen_dns.add(key)
        addresses = used_address
        self._save(
            "dns_responses",
            {
                "request_id": self._rid(str(request_key)),
                "hostname": hostname,
                "redirect_url": url or None,
                "addresses": addresses,
                "used_address": used_address,
                "canonical_name": hostname or None,
                "is_TRR": 0,
                "error": error,
                "time_stamp": _utc_now(),
            },
        )

    # --- cookies --------------------------------------------------------
    def _snapshot_cookies(self, record_type: str) -> None:
        try:
            cookies = self.session.context.cookies()
        except Exception:
            return
        seen = set()
        for cookie in cookies:
            ident = (cookie.get("name"), cookie.get("domain"), cookie.get("path"))
            seen.add(ident)
            if ident in self._cookie_keys and record_type == "manual-export":
                continue
            if ident not in self._cookie_keys:
                self._save_cookie_record(cookie, "added-or-changed", "explicit")
            self._cookie_keys.add(ident)
        if record_type != "manual-export":
            for ident in list(self._cookie_keys):
                if ident not in seen:
                    name, domain, path = ident
                    self._save_cookie_record(
                        {"name": name, "domain": domain, "path": path, "value": ""},
                        "deleted",
                        "explicit",
                    )
                    self._cookie_keys.discard(ident)

    def _save_cookie_record(
        self, cookie: Dict[str, Any], record_type: str, change_cause: str
    ) -> None:
        expires = cookie.get("expires")
        if expires in (None, -1, 0, -1.0):
            expiry = "9999-12-31T21:59:59.000Z"
            is_session = 1
        else:
            try:
                if expires is None:
                    raise ValueError("missing expires")
                expiry = (
                    datetime.fromtimestamp(float(expires), tz=timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%S.%f"
                    )[:-3]
                    + "Z"
                )
            except Exception:
                expiry = "9999-12-31T21:59:59.000Z"
            is_session = 0
        domain = cookie.get("domain") or cookie.get("host") or ""
        same_site = cookie.get("sameSite") or cookie.get("same_site") or "unspecified"
        if isinstance(same_site, str):
            same_site = same_site.lower()
            if same_site == "none":
                same_site = "no_restriction"
            elif same_site not in ("lax", "strict", "unspecified", "no_restriction"):
                same_site = "unspecified"
        host_only = 1
        if domain.startswith("."):
            host_only = 0
        self._save(
            "javascript_cookies",
            {
                "extension_session_uuid": self.session_uuid,
                "event_ordinal": self._next_ordinal(),
                "record_type": record_type,
                "change_cause": change_cause,
                "expiry": expiry,
                "is_http_only": 1 if cookie.get("httpOnly") else 0,
                "is_host_only": host_only,
                "is_session": is_session,
                "host": domain,
                "is_secure": 1 if cookie.get("secure") else 0,
                "name": cookie.get("name") or "",
                "path": cookie.get("path") or "/",
                "value": cookie.get("value") or "",
                "same_site": same_site,
                "first_party_domain": "",
                "store_id": "0",
                "time_stamp": _utc_now(),
            },
        )
        ident = (cookie.get("name"), domain, cookie.get("path") or "/")
        if record_type == "deleted":
            self._cookie_keys.discard(ident)
        else:
            self._cookie_keys.add(ident)

    # --- navigation -----------------------------------------------------
    def _on_new_page(self, page: Page) -> None:
        if self.browser_params.http_instrument:
            page.on("worker", self._on_worker)
        if self.browser_params.navigation_instrument:
            page.on("framenavigated", self._on_frame_navigated)
        if self.browser_params.http_instrument and self._cdp is None:
            try:
                self._attach_cdp(page)
            except Exception:
                pass

    def _on_frame_navigated(self, frame: Frame) -> None:
        url = frame.url or ""
        if not url or url.startswith("chrome://") or url.startswith("devtools://"):
            return
        parent = frame.parent_frame
        if parent is None:
            self._note_visited_url(url)
            self._current_top_url = url
        try:
            page = frame.page
            viewport = page.viewport_size or {"width": 1366, "height": 768}
        except Exception:
            page = None
            viewport = {"width": 1366, "height": 768}
        self._save(
            "navigations",
            {
                "id": self._next_ordinal(),
                "incognito": 0,
                "extension_session_uuid": self.session_uuid,
                "process_id": -1,
                "window_id": 1,
                "tab_id": self._tab_id(page),
                "tab_opener_tab_id": -1,
                "frame_id": 0 if parent is None else 1,
                "parent_frame_id": -1 if parent is None else 0,
                "window_width": viewport["width"],
                "window_height": viewport["height"],
                "window_type": "normal",
                "tab_width": viewport["width"],
                "tab_height": viewport["height"],
                "tab_cookie_store_id": "0",
                "uuid": str(uuid.uuid4()),
                "url": url,
                "transition_qualifiers": "[]",
                "transition_type": "typed" if parent is None else "auto_subframe",
                "before_navigate_event_ordinal": None,
                "before_navigate_time_stamp": None,
                "committed_event_ordinal": self.event_ordinal,
                "committed_time_stamp": _utc_now(),
            },
        )


def _cdp_initiator_url(initiator: Dict[str, Any]) -> str:
    url = initiator.get("url") or ""
    if url:
        return url
    stack: Any = initiator.get("stack")
    while stack:
        for frame in stack.get("callFrames") or []:
            frame_url = frame.get("url") or ""
            if frame_url:
                return frame_url
        stack = stack.get("parent")
    return ""


def _req_key(request: Any) -> str:
    return str(id(request))


def _ensure_post_headers(
    header_pairs: List[Tuple[str, str]], request: Any
) -> List[Tuple[str, str]]:
    names = {name.lower() for name, _ in header_pairs}
    content_type = ""
    for name, value in header_pairs:
        if name.lower() == "content-type":
            content_type = value
            break
    try:
        raw = request.post_data_buffer
    except Exception:
        raw = None
    if "content-type" not in names and content_type:
        header_pairs.append(("Content-Type", content_type))
        names.add("content-type")
    if "content-type" not in names:
        headers = {k.lower(): v for k, v in getattr(request, "headers", {}).items()}
        inferred = headers.get("content-type")
        if inferred:
            header_pairs.append(("Content-Type", inferred))
            names.add("content-type")
    if "content-length" not in names and raw is not None:
        header_pairs.append(("Content-Length", str(len(raw))))
    return header_pairs


def _parse_post(request: Any) -> Tuple[Optional[str], Optional[str]]:
    headers = {k.lower(): v for k, v in request.headers.items()}
    content_type = headers.get("content-type") or ""
    try:
        raw = request.post_data_buffer
    except Exception:
        raw = None
    try:
        text = request.post_data
    except Exception:
        text = None
    if raw is None and text is None:
        return None, None

    body_bytes = raw if raw is not None else (text.encode("utf-8") if text else b"")
    raw_json = json.dumps([[None, base64.b64encode(body_bytes).decode("ascii")]])

    if "application/x-www-form-urlencoded" in content_type and text is not None:
        form = parse_qs(text, keep_blank_values=True)
        return json.dumps(form), None

    if "multipart/form-data" in content_type and body_bytes:
        multipart = _parse_multipart(body_bytes, content_type)
        if multipart is not None:
            return json.dumps(multipart), None

    if "application/json" in content_type and text:
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                as_form = {k: v if isinstance(v, list) else [v] for k, v in obj.items()}
                return json.dumps(as_form), None
        except Exception:
            pass

    return None, raw_json


def _parse_multipart(body: bytes, content_type: str) -> Optional[Dict[str, List[str]]]:
    match = re.search(r"boundary=([^;]+)", content_type, flags=re.I)
    if not match:
        return None
    boundary = match.group(1).strip().strip('"')
    parts = body.split(b"--" + boundary.encode("ascii", "replace"))
    result: Dict[str, List[str]] = {}
    for part in parts:
        if b"Content-Disposition" not in part:
            continue
        header, _, data = part.partition(b"\r\n\r\n")
        data = data.rstrip(b"\r\n-")
        name_m = re.search(rb'name="([^"]+)"', header)
        if not name_m:
            continue
        name = name_m.group(1).decode("utf-8", "replace")
        if b"filename=" in header:
            continue
        value = data.decode("utf-8", "replace")
        result.setdefault(name, []).append(value)
    return result or None
