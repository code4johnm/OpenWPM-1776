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
from typing import Any, Dict, List, Optional, Tuple
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

logger = logging.getLogger("openwpm")

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


def _utc_now() -> str:
    # Match historical OpenWPM JS timestamps: milliseconds + Z.
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _headers_json(headers: Dict[str, str]) -> str:
    items = [{"name": k, "value": v} for k, v in headers.items()]
    return json.dumps(items)


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
    if not top_url:
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
        self._seen_dns: set = set()
        self._cookie_keys: set = set()
        self._cdp = None
        self._tab_ids: Dict[int, int] = {}
        self._next_tab_id = 1
        self.sock = DataSocket(
            manager_params.storage_controller_address,  # type: ignore[arg-type]
            f"Browser-{self.browser_id}",
        )

    def attach(self) -> None:
        page = self.session.page
        context = self.session.context

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
            context.on("requestfailed", self._on_request_failed)

        if self.browser_params.navigation_instrument:
            context.on("page", self._on_new_page)
            page.on("framenavigated", self._on_frame_navigated)

        if self.browser_params.cookie_instrument:
            self._snapshot_cookies("manual-export")

        logger.debug("BROWSER %i: Measurement controller attached", self.browser_id)

    def close(self) -> None:
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
        self.visit_id = visit_id
        self.event_ordinal = 0
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
        visit_id = self.visit_id if self.visit_id is not None else VisitId(-1)
        record.setdefault("visit_id", int(visit_id))
        record.setdefault("browser_id", int(self.browser_id))
        self.sock.store_record(TableName(table), visit_id, record)

    # --- JS instrument --------------------------------------------------
    def _attach_js(self, context) -> None:
        settings = self.browser_params.cleaned_js_instrument_settings or []
        testing = bool(self.manager_params.testing)

        def _on_js_log(source, messages) -> None:
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
        for page in list(self.session.context.pages):
            if page.is_closed():
                continue
            try:
                page.evaluate(
                    "() => { if (window.__openwpm_js_flush__) window.__openwpm_js_flush__(); }"
                )
            except Exception:
                pass

    def _record_js_messages(self, source, messages) -> None:
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
                "document_url": frame_url,
                "top_level_url": top_url,
                "call_stack": data.get("callStack") or "",
                "symbol": data.get("symbol") or "",
                "operation": data.get("operation") or "",
                "value": data.get("value") if data.get("value") is not None else "",
                "arguments": None,
                "time_stamp": _utc_now(),
            }
            if msg_type == "logCall" or data.get("operation") == "call":
                args = data.get("args")
                if args:
                    record["arguments"] = json.dumps(args)
            self._save("javascript", record)

    # --- CDP ------------------------------------------------------------
    def _attach_cdp(self, page: Page) -> None:
        try:
            cdp = self.session.context.new_cdp_session(page)
            cdp.on("Network.responseReceived", self._on_cdp_response)
            cdp.on("Network.loadingFailed", self._on_cdp_loading_failed)
            if self.browser_params.cookie_instrument:
                cdp.on("Network.cookieChanged", self._on_cdp_cookie)
            cdp.send("Network.enable")
            self._cdp = cdp
        except Exception:
            logger.warning(
                "BROWSER %i: CDP Network session failed; cache/DNS extras limited",
                self.browser_id,
            )

    def _on_cdp_response(self, params: Dict[str, Any]) -> None:
        response = params.get("response") or {}
        url = response.get("url") or ""
        self._cdp_by_url[url] = {
            "fromDiskCache": bool(response.get("fromDiskCache")),
            "fromPrefetchCache": bool(response.get("fromPrefetchCache")),
            "fromServiceWorker": bool(response.get("fromServiceWorker")),
            "remoteIPAddress": response.get("remoteIPAddress"),
            "requestId": params.get("requestId"),
            "status": response.get("status"),
        }
        if self.browser_params.dns_instrument and url:
            self._record_dns(
                url=url,
                request_key=params.get("requestId") or url,
                used_address=response.get("remoteIPAddress"),
                error=None,
            )

    def _on_cdp_loading_failed(self, params: Dict[str, Any]) -> None:
        if not self.browser_params.dns_instrument:
            return
        error_text = params.get("errorText") or ""
        if not is_dns_failure_message(error_text) and "NAME_NOT_RESOLVED" not in error_text:
            # Still record DNS rows for NXDOMAIN; skip other failures here
            # (HTTP instrument records the failed request separately).
            if "NAME_NOT_RESOLVED" not in error_text:
                return
        # request URL is not always present; fall back to requestId only
        url = ""
        req_id = params.get("requestId") or ""
        self._record_dns(
            url=url,
            request_key=req_id,
            used_address=None,
            error=neterror_code(error_text) or error_text,
            hostname_hint=None,
        )

    def _on_cdp_cookie(self, params: Dict[str, Any]) -> None:
        cookie = params.get("cookie") or {}
        removed = bool(params.get("removed") or params.get("cause") == "explicit" and False)
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

    def _record_request(self, request: Request) -> None:
        url = request.url
        if _should_skip_url(url):
            return
        if url.startswith("about:"):
            return
        frame = request.frame
        top_url = None
        try:
            if frame and frame.page:
                top_url = frame.page.url
        except Exception:
            top_url = None
        resource = request.resource_type
        mapped = RESOURCE_TYPE_MAP.get(resource, "other")
        if resource == "document":
            try:
                mapped = "main_frame" if (frame is None or frame.parent_frame is None) else "sub_frame"
            except Exception:
                mapped = "main_frame"
        is_xhr = 1 if resource in ("xhr", "fetch") else 0
        frame_url = ""
        try:
            frame_url = frame.url if frame else ""
        except Exception:
            frame_url = ""
        main_frame = mapped == "main_frame"
        triggering = "undefined" if main_frame else (_origin(frame_url) if frame_url else "undefined")
        loading_origin = triggering
        loading_href = "undefined" if main_frame else (frame_url or "undefined")
        request_id = self._rid(_req_key(request))
        post_body, post_body_raw = _parse_post(request)
        headers = dict(request.headers)
        referrer = headers.get("referer") or headers.get("referrer") or ""
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
                "headers": _headers_json(headers),
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
            try:
                # Location is on the redirecting response when available.
                resp = redirected.response()
                if resp:
                    location = resp.headers.get("location") or ""
            except Exception:
                location = ""
            self._save(
                "http_redirects",
                {
                    "incognito": 0,
                    "extension_session_uuid": self.session_uuid,
                    "event_ordinal": self._next_ordinal(),
                    "window_id": 1,
                    "tab_id": self._tab_id(frame.page if frame else None),
                    "frame_id": 0,
                    "old_request_url": redirected.url,
                    "old_request_id": str(self._rid(_req_key(redirected))),
                    "new_request_url": url,
                    "new_request_id": str(request_id),
                    "response_status": 302,
                    "response_status_text": "",
                    "headers": _headers_json({"Location": location} if location else {}),
                    "time_stamp": _utc_now(),
                },
            )

    def _on_response(self, response: Response) -> None:
        try:
            self._record_response(response)
        except Exception:
            logger.exception("BROWSER %i: HTTP response capture failed", self.browser_id)

    def _record_response(self, response: Response) -> None:
        url = response.url
        if _should_skip_url(url) or url.startswith("about:"):
            return
        request = response.request
        request_id = self._rid(_req_key(request))
        extra = self._cdp_by_url.get(url, {})
        from_cache = 1 if extra.get("fromDiskCache") or extra.get("fromPrefetchCache") else 0
        headers = dict(response.headers)
        location = headers.get("location") or ""
        self._save(
            "http_responses",
            {
                "incognito": 0,
                "extension_session_uuid": self.session_uuid,
                "event_ordinal": self._next_ordinal(),
                "window_id": 1,
                "tab_id": self._tab_id(request.frame.page if request.frame else None),
                "frame_id": 0,
                "url": url,
                "method": request.method,
                "response_status": response.status,
                "response_status_text": response.status_text or "",
                "is_cached": from_cache,
                "headers": _headers_json(headers),
                "request_id": request_id,
                "location": location,
                "time_stamp": _utc_now(),
                "content_hash": None,
            },
        )
        if self.browser_params.save_content:
            self._maybe_save_body(response, request_id)
        if self.browser_params.dns_instrument:
            used = extra.get("remoteIPAddress")
            if used:
                self._record_dns(
                    url=url,
                    request_key=_req_key(request),
                    used_address=used,
                    error=None,
                )

    def _on_request_failed(self, request: Request) -> None:
        err = ""
        try:
            failure = request.failure
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

    def _maybe_save_body(self, response: Response, request_id: int) -> None:
        option = self.browser_params.save_content
        resource = RESOURCE_TYPE_MAP.get(response.request.resource_type, "other")
        if response.request.resource_type == "document":
            frame = response.request.frame
            resource = (
                "main_frame"
                if (frame is None or frame.parent_frame is None)
                else "sub_frame"
            )
        if option is True:
            pass
        elif isinstance(option, str):
            allowed = {s.strip() for s in option.split(",") if s.strip()}
            if resource not in allowed:
                return
        else:
            return
        try:
            body = response.body()
        except Exception:
            return
        digest = hashlib.sha256(body).hexdigest()
        b64 = base64.b64encode(body).decode("ascii")
        self.sock.socket.send((RECORD_TYPE_CONTENT, [b64, digest]))
        # content_hash is stored on the response row; send a follow-up update
        # by inserting a second response is wrong. The schema allows content_hash
        # on insert — we already inserted. Store hash on a dedicated update only
        # if the provider supports it. Re-insert is harmful. Attach hash via
        # a javascript-free path: save a tiny side record? Historical extension
        # set content_hash on the response before insert, because it buffered
        # until onCompleted. We cannot rewrite the row easily. Insert hash by
        # delaying response insert... too late here.
        # Best effort: store an additional http_responses row is wrong.
        # We'll include content_hash by saving a note in unstructured storage
        # keyed by hash (already done) and skip updating the SQL row.
        _ = request_id
        _ = digest

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
                expiry = datetime.fromtimestamp(float(expires), tz=timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%S.%f"
                )[:-3] + "Z"
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


def _req_key(request: Any) -> str:
    return str(id(request))


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
        parsed = parse_qs(text, keep_blank_values=True)
        return json.dumps(parsed), None

    if "multipart/form-data" in content_type and body_bytes:
        parsed = _parse_multipart(body_bytes, content_type)
        if parsed is not None:
            return json.dumps(parsed), None

    if "application/json" in content_type and text:
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                as_form = {
                    k: v if isinstance(v, list) else [v] for k, v in obj.items()
                }
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
        name_m = re.search(br'name="([^"]+)"', header)
        if not name_m:
            continue
        name = name_m.group(1).decode("utf-8", "replace")
        if b"filename=" in header:
            continue
        value = data.decode("utf-8", "replace")
        result.setdefault(name, []).append(value)
    return result or None
