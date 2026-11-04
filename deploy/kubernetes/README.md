# Kubernetes (optional)

**Do not require Kubernetes for a demo or smoke run.** Use Compose on a single measurement host first.

Graduate to this Job when:

- The host can disappear (preemptible VM, cluster node drain).
- You need capped retries (`backoffLimit`) after a container-level failure.
- You already operate a cluster and want PVC-backed `datadir`.

Do **not** use Kubernetes to restart individual Chromium processes. OpenWPM `BrowserManager` watchdogs, `failure_limit`, and `incomplete_visits` already do that. A Job restart is a **new container** with the same volume: StorageController isolation plus a persistent `datadir` keep partial capture.

Do **not** add HTTP liveness probes. This platform is a batch job.

Scale-out (many sites) is `crawler.py` + Redis URL queue (upstream worker pattern), not extra replicas of `demo.py`. Set `CALLSTACK_INSTRUMENT=0` until that default is fixed.

Privileged is not required. Chromium in this image is already `--no-sandbox`; `privileged: true` would only widen residual risk.

## Dashboard

`dashboard.yaml` is the launcher. It publishes Service `openwpm-1776` on port 8770 and Deployment `openwpm-dashboard` (git keeps `replicas: 0`). The page edits `datadir/crawl-links.json`, then creates Job `openwpm-crawl` from image `openwpm-1776:local`. That Job runs `dashboard/crawl_list.py`. It does not use `crawler.py`, Redis, or GCS. Callstack instrumentation stays off.

```bash
kubectl apply -f deploy/kubernetes/dashboard.yaml
kubectl -n default scale deployment/openwpm-dashboard --replicas=1
```

Open `http://192.168.0.47:8770/` on this LAN. The k38 console card OpenWPM-1776 launches the same Deployment.
