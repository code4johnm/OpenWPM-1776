"""OpenWPM-1776 crawl dashboard.

Edits the link list and starts or stops the Kubernetes Job openwpm-crawl.
Stdlib only. Bind 0.0.0.0 so a phone on the LAN can open it.
"""

from __future__ import annotations

import json
import os
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(os.environ.get("OPENWPM_ROOT", "/opt/OpenWPM"))
if not (ROOT / "dashboard").is_dir():
    ROOT = Path(__file__).resolve().parents[1]
# hostPath inside the crawl Job must be the laptop path, not the mount path.
HOST_ROOT = os.environ.get("OPENWPM_HOST_ROOT", str(ROOT))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# isort: off
from openwpm.header_bidding import (  # noqa: E402
    PROFILES,
    compare_profiles,
    dataset_csv,
    dataset_document,
    profile_config,
)
# isort: on

DATA = Path(os.environ.get("OPENWPM_DATADIR", str(ROOT / "datadir")))
LINKS = DATA / "crawl-links.json"
SETTINGS = DATA / "crawl-settings.json"
STATUS = DATA / "crawl-status.json"
PAGE = Path(__file__).resolve().parent / "index.html"
HOST = os.environ.get("OPENWPM_DASH_HOST", "0.0.0.0")
PORT = int(os.environ.get("OPENWPM_DASH_PORT", "8770"))
NAMESPACE = os.environ.get("OPENWPM_NAMESPACE", "default")
JOB = "openwpm-crawl"
MAX_LINKS = 200

DEFAULT_LINKS = {
    "links": [
        {"url": "https://www.cooksdefensellc.com", "note": ""},
        {"url": "https://www.quantumresearchlaboratories.com", "note": ""},
    ]
}
DEFAULT_SETTINGS = {
    "dwell": 3,
    "timeout": 60,
    "headless": True,
    "http": True,
    "cookie": True,
    "navigation": True,
    "js": True,
    "dns": True,
    "profile": "baseline",
    "user_agent": "",
    "viewport": "",
    "geolocation": "",
    "cookie_state": "",
    "inject_script": "",
    "consent": "",
    "fingerprint_resistance": False,
}


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_data() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    os.chmod(DATA, 0o777)
    if not LINKS.is_file():
        save_json(LINKS, DEFAULT_LINKS)
    if not SETTINGS.is_file():
        save_json(SETTINGS, DEFAULT_SETTINGS)


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o666)
    tmp.replace(path)


def load_json(path: Path, fallback: dict) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return json.loads(json.dumps(fallback))
    return data if isinstance(data, dict) else json.loads(json.dumps(fallback))


def clean_url(value: object) -> str:
    if not isinstance(value, str):
        raise ApiError(400, "Each link needs a URL.")
    url = value.strip()
    if len(url) > 2000:
        raise ApiError(400, "A URL is too long.")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ApiError(400, "Links must be http or https URLs.")
    if parsed.username or parsed.password:
        raise ApiError(400, "Links must not include a username or password.")
    return url


def clean_links(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ApiError(400, "Link list must be an object.")
    raw = payload.get("links")
    if not isinstance(raw, list):
        raise ApiError(400, "links must be a list.")
    if len(raw) > MAX_LINKS:
        raise ApiError(400, f"At most {MAX_LINKS} links.")
    links = []
    seen: set[str] = set()
    for item in raw:
        if isinstance(item, str):
            url = clean_url(item)
            note = ""
        elif isinstance(item, dict):
            url = clean_url(item.get("url"))
            note = item.get("note") if isinstance(item.get("note"), str) else ""
            note = note.strip()[:240]
        else:
            raise ApiError(400, "A link is not an object.")
        if url in seen:
            continue
        seen.add(url)
        links.append({"url": url, "note": note})
    return {"links": links, "updated": now()}


def clean_settings(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ApiError(400, "Settings must be an object.")
    try:
        dwell = int(payload.get("dwell", 3))
        timeout = int(payload.get("timeout", 60))
    except (TypeError, ValueError) as exc:
        raise ApiError(400, "Dwell and timeout must be whole numbers.") from exc
    if not 0 <= dwell <= 120:
        raise ApiError(400, "Dwell must be from 0 to 120 seconds.")
    if not 5 <= timeout <= 180:
        raise ApiError(400, "Timeout must be from 5 to 180 seconds.")
    name = payload.get("profile") or "baseline"
    if name not in PROFILES:
        raise ApiError(400, "Profile must be training, testing, or baseline.")
    try:
        overrides = {
            "user_agent": payload.get("user_agent"),
            "viewport": payload.get("viewport"),
            "geolocation": payload.get("geolocation"),
            "cookie_state": payload.get("cookie_state"),
            "inject_script": payload.get("inject_script"),
            "consent": payload.get("consent"),
        }
        if "fingerprint_resistance" in payload:
            overrides["fingerprint_resistance"] = payload.get("fingerprint_resistance")
        chosen = profile_config(name, overrides)
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    out = {
        "dwell": dwell,
        "timeout": timeout,
        "headless": bool(payload.get("headless", True)),
        "http": bool(payload.get("http", True)),
        "cookie": bool(payload.get("cookie", True)),
        "navigation": bool(payload.get("navigation", True)),
        "js": bool(payload.get("js", True)),
        "dns": bool(payload.get("dns", True)),
        "profile": name,
        "user_agent": chosen["user_agent"],
        "viewport": chosen["viewport"],
        "geolocation": chosen["geolocation"],
        "cookie_state": chosen["cookie_state"],
        "inject_script": chosen["inject_script"] if isinstance(chosen["inject_script"], str) else "",
        "consent": chosen["consent"],
        "fingerprint_resistance": bool(chosen["fingerprint_resistance"]),
        "updated": now(),
    }
    if len(out["inject_script"]) > 2000:
        raise ApiError(400, "Injected script is too long.")
    return out


def sa_token() -> str | None:
    path = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8").strip()


def k8s_api(method: str, path: str, body: dict | None = None) -> tuple[int, dict | str]:
    token = sa_token()
    if token:
        host = os.environ.get("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
        port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"https://{host}:{port}" + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        # CoreDNS is not running. The API is reached by its service IP.
        # The cluster CA is still required. The IP is not the certificate name.
        context = ssl.create_default_context(
            cafile="/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
        )
        context.check_hostname = False
        try:
            with urllib.request.urlopen(req, context=context, timeout=20) as resp:
                raw = resp.read().decode("utf-8", "replace")
                code = resp.status
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            code = exc.code
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = raw
        return code, parsed
    args = ["kubectl", method.lower() if False else "get"]
    # Host fallback uses kubectl for the few calls the dashboard makes.
    return kubectl_raw(method, path, body)


def kubectl_raw(method: str, path: str, body: dict | None) -> tuple[int, dict | str]:
    if method == "GET" and path.endswith("/log"):
        name = path.split("/pods/")[1].split("/")[0]
        proc = subprocess.run(
            ["kubectl", "logs", "-n", NAMESPACE, name, "--tail=200"],
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        return (200 if proc.returncode == 0 else 502), (proc.stdout or proc.stderr)
    if method == "GET" and "/pods" in path:
        proc = subprocess.run(
            ["kubectl", "get", "pods", "-n", NAMESPACE, "-l", f"job-name={JOB}", "-o", "json"],
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
    elif method == "GET":
        proc = subprocess.run(
            ["kubectl", "get", "job", JOB, "-n", NAMESPACE, "-o", "json"],
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
    elif method == "DELETE":
        proc = subprocess.run(
            ["kubectl", "delete", "job", JOB, "-n", NAMESPACE, "--ignore-not-found"],
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        return proc.returncode and 502 or 200, {"status": proc.stdout or proc.stderr}
    elif method == "POST":
        proc = subprocess.run(
            ["kubectl", "apply", "-f", "-"],
            input=json.dumps(body),
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        # kubectl apply wants YAML. Use the API only in-cluster. On the host,
        # create from a JSON file via kubectl create --raw if apply cannot.
        if proc.returncode != 0:
            proc = subprocess.run(
                ["kubectl", "create", "-f", "-"],
                input=job_yaml(),
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
        return (200 if proc.returncode == 0 else 502), {"status": (proc.stdout or proc.stderr).strip()}
    else:
        return 400, {"message": "unsupported"}
    if proc.returncode != 0:
        if "NotFound" in (proc.stderr or ""):
            return 404, {}
        return 502, {"message": (proc.stderr or proc.stdout).strip()}
    try:
        return 200, json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return 200, {"status": proc.stdout}


def job_manifest() -> dict:
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": JOB, "namespace": NAMESPACE, "labels": {"app": "openwpm-1776"}},
        "spec": {
            "backoffLimit": 1,
            "ttlSecondsAfterFinished": 86400,
            "template": {
                "metadata": {"labels": {"app": "openwpm-1776", "job-name": JOB}},
                "spec": {
                    "restartPolicy": "Never",
                    "securityContext": {
                        "runAsNonRoot": True,
                        "runAsUser": 10001,
                        "runAsGroup": 10001,
                        "fsGroup": 10001,
                    },
                    "containers": [
                        {
                            "name": "openwpm",
                            "image": "openwpm-1776:local",
                            "imagePullPolicy": "Never",
                            "workingDir": "/opt/OpenWPM",
                            "command": ["python", "/opt/OpenWPM/dashboard/crawl_list.py"],
                            "env": [
                                {"name": "OPENWPM_NO_SANDBOX", "value": "1"},
                                {"name": "OPENWPM_DISABLE_DEV_SHM", "value": "1"},
                                {"name": "OPENWPM_DATADIR", "value": "/opt/OpenWPM/datadir"},
                                {"name": "OPENWPM_ROOT", "value": "/opt/OpenWPM"},
                                {"name": "CALLSTACK_INSTRUMENT", "value": "0"},
                            ],
                            "resources": {
                                "requests": {"cpu": "500m", "memory": "2Gi"},
                                "limits": {"cpu": "2", "memory": "8Gi"},
                            },
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "capabilities": {"drop": ["ALL"]},
                            },
                            "volumeMounts": [
                                {"name": "src", "mountPath": "/opt/OpenWPM"},
                                {"name": "dshm", "mountPath": "/dev/shm"},
                            ],
                        }
                    ],
                    "volumes": [
                        {
                            "name": "src",
                            "hostPath": {
                                "path": HOST_ROOT,
                                "type": "Directory",
                            },
                        },
                        {"name": "dshm", "emptyDir": {"medium": "Memory", "sizeLimit": "2Gi"}},
                    ],
                },
            },
        },
    }


def job_yaml() -> str:
    # Small YAML for the host kubectl fallback. The in-cluster path uses JSON.
    body = job_manifest()
    return (
        "apiVersion: batch/v1\n"
        "kind: Job\n"
        "metadata:\n"
        f"  name: {JOB}\n"
        f"  namespace: {NAMESPACE}\n"
        "  labels:\n"
        "    app: openwpm-1776\n"
        "spec:\n"
        "  backoffLimit: 1\n"
        "  ttlSecondsAfterFinished: 86400\n"
        "  template:\n"
        "    metadata:\n"
        "      labels:\n"
        "        app: openwpm-1776\n"
        f"        job-name: {JOB}\n"
        "    spec:\n"
        "      restartPolicy: Never\n"
        "      securityContext:\n"
        "        runAsNonRoot: true\n"
        "        runAsUser: 10001\n"
        "        runAsGroup: 10001\n"
        "        fsGroup: 10001\n"
        "      containers:\n"
        "        - name: openwpm\n"
        "          image: openwpm-1776:local\n"
        "          imagePullPolicy: Never\n"
        "          workingDir: /opt/OpenWPM\n"
        "          command: [\"python\", \"/opt/OpenWPM/dashboard/crawl_list.py\"]\n"
        "          env:\n"
        "            - name: OPENWPM_NO_SANDBOX\n"
        "              value: \"1\"\n"
        "            - name: OPENWPM_DISABLE_DEV_SHM\n"
        "              value: \"1\"\n"
        "            - name: OPENWPM_DATADIR\n"
        "              value: /opt/OpenWPM/datadir\n"
        "            - name: OPENWPM_ROOT\n"
        "              value: /opt/OpenWPM\n"
        "            - name: CALLSTACK_INSTRUMENT\n"
        "              value: \"0\"\n"
        "          volumeMounts:\n"
        "            - name: src\n"
        "              mountPath: /opt/OpenWPM\n"
        "            - name: dshm\n"
        "              mountPath: /dev/shm\n"
        "      volumes:\n"
        "        - name: src\n"
        "          hostPath:\n"
        f"            path: {HOST_ROOT}\n"
        "            type: Directory\n"
        "        - name: dshm\n"
        "          emptyDir:\n"
        "            medium: Memory\n"
        "            sizeLimit: 2Gi\n"
    )


def job_phase(doc: dict) -> str:
    if not doc:
        return "idle"
    status = doc.get("status") or {}
    if status.get("succeeded"):
        return "succeeded"
    if status.get("failed"):
        return "failed"
    if status.get("active"):
        return "running"
    return "pending"


def cluster_status() -> dict:
    code, doc = k8s_api("GET", f"/apis/batch/v1/namespaces/{NAMESPACE}/jobs/{JOB}")
    if code == 404 or not isinstance(doc, dict) or doc.get("kind") != "Job":
        phase = "idle"
        job = None
    else:
        phase = job_phase(doc)
        job = {
            "name": JOB,
            "phase": phase,
            "active": (doc.get("status") or {}).get("active") or 0,
            "succeeded": (doc.get("status") or {}).get("succeeded") or 0,
            "failed": (doc.get("status") or {}).get("failed") or 0,
        }
    crawl = load_json(STATUS, {"state": "idle", "sites": [], "error": ""})
    return {"job": job, "crawl": crawl, "phase": phase}


def launch_job() -> dict:
    links = load_json(LINKS, DEFAULT_LINKS).get("links") or []
    if not links:
        raise ApiError(400, "Add at least one link before launching.")
    code, existing = k8s_api("GET", f"/apis/batch/v1/namespaces/{NAMESPACE}/jobs/{JOB}")
    if code == 200 and isinstance(existing, dict) and existing.get("kind") == "Job":
        phase = job_phase(existing)
        if phase in {"running", "pending"}:
            raise ApiError(409, "A crawl is already running.")
        delete_job()
    if sa_token():
        code, created = k8s_api(
            "POST", f"/apis/batch/v1/namespaces/{NAMESPACE}/jobs", job_manifest()
        )
        if code >= 300:
            message = created.get("message") if isinstance(created, dict) else str(created)
            raise ApiError(502, message or "Kubernetes rejected the crawl Job.")
        return {"ok": True, "phase": "pending"}
    code, created = kubectl_raw("POST", "", None)
    if code >= 300:
        message = created.get("status") if isinstance(created, dict) else str(created)
        raise ApiError(502, message or "kubectl could not create the crawl Job.")
    return {"ok": True, "phase": "pending"}


def delete_job() -> dict:
    if sa_token():
        code, doc = k8s_api(
            "DELETE",
            f"/apis/batch/v1/namespaces/{NAMESPACE}/jobs/{JOB}?propagationPolicy=Background",
        )
        if code not in {200, 202, 404}:
            message = doc.get("message") if isinstance(doc, dict) else str(doc)
            raise ApiError(502, message or "Could not stop the crawl.")
        return {"ok": True}
    code, doc = kubectl_raw("DELETE", "", None)
    if code >= 300:
        message = doc.get("message") if isinstance(doc, dict) else str(doc)
        raise ApiError(502, message or "Could not stop the crawl.")
    return {"ok": True}


def pod_log() -> str:
    if sa_token():
        code, pods = k8s_api(
            "GET",
            f"/api/v1/namespaces/{NAMESPACE}/pods?labelSelector=job-name%3D{JOB}",
        )
        if code >= 300 or not isinstance(pods, dict):
            return ""
        items = pods.get("items") or []
        if not items:
            return ""
        name = (items[-1].get("metadata") or {}).get("name") or ""
        if not name:
            return ""
        log_code, text = k8s_api(
            "GET", f"/api/v1/namespaces/{NAMESPACE}/pods/{name}/log?tailLines=200"
        )
        return text if isinstance(text, str) else ""
    code, pods = kubectl_raw("GET", f"/pods?labelSelector=job-name={JOB}", None)
    if not isinstance(pods, dict):
        return ""
    items = pods.get("items") or []
    if not items:
        return ""
    name = (items[-1].get("metadata") or {}).get("name") or ""
    if not name:
        return ""
    log_code, text = kubectl_raw("GET", f"/pods/{name}/log", None)
    return text if isinstance(text, str) else ""


class Handler(BaseHTTPRequestHandler):
    server_version = "openwpm-dash"

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} {fmt % args}", flush=True)

    def send_json(self, code: int, payload: dict) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or "0")
        if length > 200_000:
            raise ApiError(413, "Body is too large.")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ApiError(400, "Body is not JSON.") from exc
        if not isinstance(data, dict):
            raise ApiError(400, "Body must be an object.")
        return data

    def do_GET(self) -> None:  # noqa: N802
        try:
            path = urlparse(self.path).path
            if path in {"/", "/index.html"}:
                body = PAGE.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/state":
                self.send_json(
                    200,
                    {
                        "links": load_json(LINKS, DEFAULT_LINKS),
                        "settings": load_json(SETTINGS, DEFAULT_SETTINGS),
                        "status": cluster_status(),
                    },
                )
                return
            if path == "/api/logs":
                self.send_json(200, {"log": pod_log()})
                return
            if path == "/api/profiles":
                self.send_json(200, {"profiles": PROFILES, "summary": compare_profiles()})
                return
            if path in {"/api/export.json", "/api/export.csv"}:
                document = dataset_document()
                if path.endswith(".csv"):
                    raw = dataset_csv(document).encode("utf-8")
                    mime = "text/csv; charset=utf-8"
                    filename = "hb-profiles.csv"
                else:
                    raw = (json.dumps(document, indent=2) + "\n").encode("utf-8")
                    mime = "application/json; charset=utf-8"
                    filename = "hb-profiles.json"
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return
            self.send_json(404, {"error": "not found"})
        except ApiError as exc:
            self.send_json(exc.status, {"error": exc.message})
        except Exception as exc:  # noqa: BLE001
            self.send_json(500, {"error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        try:
            path = urlparse(self.path).path
            if path == "/api/links":
                saved = clean_links(self.read_json())
                save_json(LINKS, saved)
                self.send_json(200, saved)
                return
            if path == "/api/settings":
                saved = clean_settings(self.read_json())
                save_json(SETTINGS, saved)
                self.send_json(200, saved)
                return
            if path == "/api/launch":
                self.send_json(200, launch_job())
                return
            if path == "/api/stop":
                self.send_json(200, delete_job())
                return
            self.send_json(404, {"error": "not found"})
        except ApiError as exc:
            self.send_json(exc.status, {"error": exc.message})
        except Exception as exc:  # noqa: BLE001
            self.send_json(500, {"error": str(exc)})


def main() -> None:
    ensure_data()
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"OpenWPM dashboard listening on http://192.168.0.47:{PORT}/", flush=True)
    httpd.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
