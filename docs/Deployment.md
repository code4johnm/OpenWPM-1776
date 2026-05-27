# Deployment Guide

**Document Version:** 1.0  
**OpenWPM Version:** 0.34.0  
**Last Updated:** 2026-05-27T02:47:30Z  
**Workspace:** OpenWPM-1776

---

## 1. Introduction

This guide covers production and large-scale deployment patterns for OpenWPM, including Docker, headless server environments, cloud orchestration considerations, and operational hardening.

**Security Requirement:** All deployment environments must follow the controls described in [Security-and-Privacy.md](Security-and-Privacy.md). In particular, measurement infrastructure must be isolated from personal or sensitive workloads.

---

## 2. Deployment Models

| Model                  | Typical Scale     | Isolation     | Recommended For                  | Key Trade-offs |
|------------------------|-------------------|---------------|----------------------------------|----------------|
| Local native           | 1–4 browsers      | Low           | Development & debugging          | Easy but risky for sensitive data |
| Local headless / xvfb  | 1–8 browsers      | Medium        | Small studies, testing           | Good balance |
| Docker (single host)   | 1–20 browsers     | High          | Reproducible research, CI        | Excellent reproducibility |
| Cloud VM / container   | 10–100+ browsers  | High          | Large-scale studies              | Requires orchestration |
| Multi-node / K8s       | 100s–1000s        | Very High     | Massive campaigns                | Significant engineering effort |

---

## 3. Docker Deployment (Recommended for Most Users)

The root `Dockerfile` produces a complete, reproducible image based on Ubuntu 22.04 with all dependencies pinned.

### Building the Image

```bash
docker build -f Dockerfile -t openwpm:0.34.0 .
```

### Running a Measurement

```bash
mkdir -p docker-volume

# Linux with X forwarding (GUI or xvfb inside container)
xhost +local:docker

docker run --rm \
  -v "$PWD/docker-volume:/opt/OpenWPM/datadir" \
  -e DISPLAY=$DISPLAY \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  --shm-size=2g \
  --init \
  -it \
  openwpm:0.34.0 \
  python demo.py --headless
```

**Critical flags explained:**

- `--shm-size=2g` — Firefox will crash on a significant fraction of sites without sufficient shared memory. 2 GB is a common minimum; increase for heavy workloads.
- `-v ...:/opt/OpenWPM/datadir` — Persists output on the host.
- `--init` — Ensures proper signal handling and zombie reaping.

### Running as Non-Root (Hardening)

The default image runs as root for simplicity. For hardened deployments:

1. Create a dedicated `openwpm` user inside the image or use `--user`.
2. Bind-mount only the directories you need.
3. Drop capabilities where possible.

See the Dockerfile and `scripts/run-on-osx-via-docker.sh` for macOS patterns.

### Image Security Recommendations

- Pin to a specific image digest in production pipelines, not just tags.
- Scan images with `grype` or Trivy before use in sensitive environments.
- Consider building your own image from source in air-gapped or high-security settings.

---

## 4. Headless and xvfb Environments

### Pure Headless (`display_mode: "headless"`)

Supported since Firefox 56. Fastest and lowest resource overhead. Some WebGL / graphics features are unavailable or behave differently.

### xvfb (`display_mode: "xvfb"`)

Provides a virtual framebuffer so the full (non-headless) Firefox runs. Required for certain fingerprinting or rendering studies.

On Ubuntu:

```bash
sudo apt-get install -y xvfb
```

Then set `browser_params[i].display_mode = "xvfb"`.

**Note:** `xvfb` and Firefox headless are **not** equivalent. Choose based on your measurement goals (see [#448](https://github.com/openwpm/OpenWPM/issues/448)).

---

## 5. Cloud and Large-Scale Considerations

### Resource Planning

- **Memory:** 1.5–3 GB per browser instance (instrumentation increases usage). Use the memory watchdog.
- **Disk:** Profiles + artifacts can grow to tens of GB quickly. Use `maximum_profile_size` and clean up between runs.
- **Network:** Full instrumentation on popular sites can generate hundreds of requests per page. Coordinate with cloud providers on egress quotas and abuse policies.
- **CPU:** JavaScript instrumentation is CPU-intensive on complex pages.

### Storage Strategy

For long-running or large campaigns, prefer remote structured + unstructured providers (S3 or GCS Parquet + object storage) over writing everything to local disk inside the VM.

### Failure and Cost Management

- Set realistic `failure_limit` values.
- Use spot/preemptible instances with checkpointing (dump important state via custom commands).
- Implement external monitoring of the `crawl_history` table to detect runaway costs.

---

## 6. Operational Hardening Checklist

- [ ] Dedicated VM / project / account with minimal IAM permissions
- [ ] Firewall rules allowing only necessary outbound traffic (or use egress proxies)
- [ ] Encrypted volumes for `data_directory` and logs
- [ ] `memory_watchdog` and `process_watchdog` enabled
- [ ] `maximum_profile_size` set to control disk bloat
- [ ] Docker images scanned and pinned by digest
- [ ] No personal credentials or SSH keys in measurement profiles or environment variables
- [ ] Log rotation and retention policy applied
- [ ] Output artifacts encrypted at rest (especially if using S3 without default encryption)
- [ ] Access to raw data limited to the minimum number of researchers

---

## 7. Continuous Integration / Testing

OpenWPM's own CI (`.github/workflows/run-tests.yaml`) runs the test matrix in GitHub Actions using xvfb and the `scripts/ci.sh` helper.

For projects that embed OpenWPM:

- Use the Docker image in your pipeline for end-to-end tests.
- For unit tests of custom commands or analysis code, the `pyonly` marker can be used to avoid browser startup.

---

## 8. Releasing and Versioning Your Studies

When publishing results:

1. Record the exact OpenWPM release / commit.
2. Record the exact Firefox version used (visible in `firefox-bin/` or via platform utilities).
3. Archive the `environment.yaml` (or the output of `conda list`) alongside your dataset.
4. Publish or cite the schema version used (`schema.sql`).

This level of reproducibility is a core strength of OpenWPM and is expected by the research community.

---

## 9. Related Documents

- [Installation-Guide.md](Installation-Guide.md)
- [Security-and-Privacy.md](Security-and-Privacy.md) — Mandatory reading for any production deployment
- [Architecture.md](Architecture.md)
- Root `Dockerfile` and `scripts/` for implementation details

---

*End of Deployment Guide*