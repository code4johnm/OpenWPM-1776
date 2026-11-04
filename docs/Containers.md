# Containers and orchestration

**OpenWPM-1776 0.35.0** — Playwright 1.62.0 + Chromium 151.0.7922.34

This document covers OCI packaging (Docker, Podman, Buildah), Compose for local runs, optional Kubernetes Jobs for node-level retry, and how that stack **complements** in-platform recovery.

Dedicated measurement hosts only. Image outputs (HAR, SQLite, screenshots, profiles, cookies, JS values) are confidential research data.

---

## 1. Current packaging vs this stack

| Piece | Before | Now |
|-------|--------|-----|
| Image | Root Ubuntu 22.04, `CMD python demo.py` | Non-root uid 10001, `tini` + entrypoint, default **smoke** |
| Browsers | `/opt/ms-playwright` (unchanged idea) | Same path, **never bind-mount over it** |
| Compose | None | `compose.yaml` with `init`, `shm_size: 2gb`, persistent `docker-volume` |
| Orchestration | Operator `docker run` | Compose `on-failure:3` for demo/crawl; optional K8s Job |
| CI | Build+push to Docker Hub (secrets) | Plus `container-smoke.yaml`: build + in-container smoke |

In-platform (do not duplicate): `BrowserManager` spawn/restart, `failure_limit`, `incomplete_visits`, `memory_watchdog` / `process_watchdog`, StorageController in a separate process. Orchestration restarts the **container/job**, not an individual Chromium tab.

---

## 2. Failed-state and capture model

| Layer | What “failed” means | Response | Must not |
|-------|---------------------|----------|----------|
| Application | Browser crash, hung command, neterror | Watchdog restart browser; DNS neterror excluded from `failure_limit`; `incomplete_visits` | Compose should not SIGKILL the container on the first browser crash |
| Container | Non-zero process exit (smoke, demo, crawl) | Visible exit code; Compose `on-failure:3` for demo/crawl; smoke `restart: "no"` | Infinite restart loops; deleting `datadir` |
| Resources | OOM, `/dev/shm` exhaustion | Chromium dies; raise `shm_size`, lower `num_browsers`, add RAM | Fake HTTP probes |
| Storage | SQLite/object-store write error | StorageController logs; crawl should fail closed | Writing only to ephemeral rootfs |
| Node (K8s/Nomad only) | Host gone | Job `backoffLimit`; PVC still holds `datadir` | `privileged: true` |

**Capture integrity:** always mount a host path or PVC at `/opt/OpenWPM/datadir`. The image `VOLUME` is a reminder, not a backup. Partial runs must remain on that volume for `incomplete_visits` and logs.

**Handoff:** one container restart = new TaskManager + new browsers, **same datadir**. That is intentional after a whole-process death. Do not run a sidecar that `pkill chrome` and expects Compose to “heal” the same crawl without reading OpenWPM logs.

---

## 3. Build

Docker:

```bash
docker build -f Dockerfile -t openwpm-1776:local .
```

Podman / Buildah (same Dockerfile):

```bash
podman build -f Dockerfile -t openwpm-1776:local .
# or: buildah bud -f Dockerfile -t openwpm-1776:local .
```

The build runs `./install.sh` (conda env + `python -m playwright install chromium` into `/opt/ms-playwright`). Expect several GB and tens of minutes on a cold cache.

---

## 4. Run (Compose — default path)

```bash
mkdir -p docker-volume
# uid 10001 must write the volume
sudo chown -R 10001:10001 docker-volume   # Linux; skip if you override user

# Smoke (default service). Exit code is the smoke result.
docker compose run --rm openwpm
# artifacts: docker-volume/smoke.png, docker-volume/smoke.har

# Headless demo (capped retries)
docker compose --profile demo run --rm demo

# Redis/GCS worker (needs REDIS_HOST / GCS env; CALLSTACK forced off in compose)
docker compose --profile crawl run --rm crawl
```

Podman Compose: `podman compose` with the same file (`shm_size` and `init` are supported on recent Podman).

Equivalent `docker run`:

```bash
docker run --rm --init --shm-size=2g \
  -v "$PWD/docker-volume:/opt/OpenWPM/datadir" \
  -e OPENWPM_NO_SANDBOX=1 \
  -e OPENWPM_DISABLE_DEV_SHM=1 \
  openwpm-1776:local \
  python -m openwpm.smoke --outdir /opt/OpenWPM/datadir
```

Override the command for a crawl script:

```bash
docker run --rm --init --shm-size=2g \
  -v "$PWD/docker-volume:/opt/OpenWPM/datadir" \
  openwpm-1776:local \
  python demo.py --headless
```

### Commands

| Intent | Command inside the image |
|--------|--------------------------|
| Smoke (default `CMD`) | `python -m openwpm.smoke --outdir /opt/OpenWPM/datadir` |
| Demo | `python demo.py --headless` |
| Queue worker | `python crawler.py` with `CALLSTACK_INSTRUMENT=0` |
| Shell | `bash` |

`scripts/docker-entrypoint.sh` creates `OPENWPM_DATADIR` (default `/opt/OpenWPM/datadir`), refuses an unwritable mount (exit 2), then `exec`s the command so the orchestrator sees the real exit code.

---

## 5. Resources

| Resource | Guidance |
|----------|----------|
| `/dev/shm` | **2 GiB minimum** (`shm_size: 2gb` / `--shm-size=2g`). Chromium crashes on many sites below this. |
| RAM | About **2–4 GiB per browser** plus Playwright and StorageController. `demo.py` default is 2 browsers. |
| CPU | 1 vCPU per browser is a starting point. |
| Disk | `datadir` grows with screenshots, HAR, SQLite, profiles. Use `maximum_profile_size` for long crawls. |

`OPENWPM_DISABLE_DEV_SHM=1` is set because container `/dev/shm` is small **unless** you pass `shm_size`. Keep both: large shm **and** the env var Chromium already expects in this project.

---

## 6. Failure matrix

| Symptom | Likely cause | Mitigation |
|---------|--------------|------------|
| Chromium `crashpad` / tab died, `/dev/shm` | Shared memory too small | `--shm-size=2g` or larger; do not drop `init` |
| `TargetClosedError` / spawn timeout | Sandbox, missing libs, fork+Playwright | Use this image (libs + `OPENWPM_NO_SANDBOX=1`); do not import Playwright in the parent before fork (already handled in `BrowserManager.run_impl`) |
| Smoke missing `smoke.png` | Command never ran or volume not mounted | Check compose volume; entrypoint exit 2 = unwritable datadir |
| `ConfigError` callstack | `crawler.py` default `CALLSTACK_INSTRUMENT=1` | Set `CALLSTACK_INSTRUMENT=0` (compose `crawl` service does this) |
| OOM killer | `mem_limit` too low or too many browsers | Lower `num_browsers`; raise memory; inspect `dmesg` |
| `CommandExecutionError` / `failure_limit` | Too many non-DNS command failures | In-platform; inspect `crawl_history`; do not auto-`compose up` in a tight loop |
| Job restarted, empty data | Volume was ephemeral | PVC or `docker-volume`; never only container rootfs |
| Zombies (`<defunct>` chrome) | No init/tini | `init: true` or image `tini` entrypoint |

### Failure-injection checklist

1. **Bad command:** `docker compose run --rm openwpm python -c 'raise SystemExit(1)'` — expect non-zero; `docker-volume` still has prior files.
2. **Unwritable datadir:** `chmod 000 docker-volume` then run — expect entrypoint exit 2.
3. **Kill Chromium during a demo:** `docker compose --profile demo run demo` in one terminal; `docker exec` + `pkill -f chrome` — OpenWPM should restart the browser or fail the command; Compose must **not** immediately bounce the container unless the Python process exits.
4. **Tiny shm:** run with `--shm-size=64m` — expect Chromium crashes; restore 2g.

---

## 7. When to use Kubernetes

See `deploy/kubernetes/`. Use a Job when the **node** can die or you want `backoffLimit` independent of Compose. Do not use it for a single laptop demo.

Scale-out: one crawl worker per Redis job (`crawler.py`), shared object storage (GCS/S3 providers already in-tree), PVC or bucket for unstructured blobs. Not: many replicas of `demo.py` sharing one SQLite file.

---

## 8. Security

- Measurement-only hosts. Do not mount `~/.config/google-chrome` or personal profiles.
- Image user is **10001**. Chromium **sandbox is off** in containers (`needs_no_sandbox()` is true whenever `/.dockerenv` exists). Unsetting `OPENWPM_NO_SANDBOX` does **not** enable the renderer sandbox.
- No `privileged`. Capabilities dropped in the sample Job.
- Treat `docker-volume` as High data (cookies, bodies, screenshots). Encrypt at rest on the host; restrict who can `docker cp`.
- Do not bake credentials. Cloud keys via env / secret manager only (`crawler.py` already uses env).
- Do not bind-mount the whole git worktree over `/opt/OpenWPM` in production (unsigned code + easy to hide `datadir`). Dev bind-mount of source is acceptable; keep `PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright` **outside** that mount.

---

## 9. CI

`.github/workflows/container-smoke.yaml` builds the image and runs smoke with `--shm-size=2g`, then asserts `smoke.png` / `smoke.har` on the volume and that a failing command is non-zero without deleting artifacts.

Hub publish remains `.github/workflows/build-container.yaml` (unsigned `latest`). Signed GHCR is a follow-up (see `openwpm-1776-secure-baseline/`).

---

## 10. Follow-ups (not blocking)

- Image signing / SPDX 3 SBOM (baseline package)
- Multi-arch (`linux/arm64`) Playwright browsers
- Queue-based crawler docs (`crawler.py` + Redis) beyond a single Compose service
- Tighten `needs_no_sandbox()` when user namespaces work as non-root (increment 2)
- `CALLSTACK_INSTRUMENT` default `"0"` in `crawler.py` itself
