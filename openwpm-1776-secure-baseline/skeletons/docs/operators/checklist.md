### E. Operator checklist (`docs/operators/checklist.md` skeleton)

Reinforces Security-and-Privacy.md; does not replace IRB legal advice.

```markdown
# OpenWPM-1776 operator checklist (0.35.0)

## Authority and ethics
- [ ] I am not using this platform under a claimed U.S. Government ATO unless my program independently authorized it.
- [ ] IRB/ethics review completed when the protocol requires it (human subjects even indirect).
- [ ] Purpose limitation / minimization: instruments match the approved research question (not “EO 12333 compliance”).
- [ ] Cookie/HTTP opt-in may incidentally record authentication-equivalent material from public sites; treat as High; this is not a collection charter.

## Host
- [ ] Dedicated measurement host or VM (no personal browsing profiles).
- [ ] Leftover `firefox-bin/` removed from disk if present (gitignored residual).
- [ ] Chromium from Playwright 1.62.0 only (`python -m playwright install chromium`).
- [ ] `python -m openwpm.smoke` succeeds.

## Profile
- [ ] `dev` / `audit` / `prod` selected from `conf/profiles.yml` and recorded in `custom_params.openwpm_profile`.
- [ ] `prod`/`audit`: `display_mode` is headless or xvfb (not native).
- [ ] `prod`/`audit` applied via `OPENWPM_PROFILE` / validator CLI / image entrypoint — YAML on disk is not enough.
- [ ] Cookie/HTTP/JS/`save_content` on a profiled worker: `OPENWPM_RESEARCH_PURPOSE` **and** the matching `*_INSTRUMENT=1` env vars (re-applied after overlay).
- [ ] `prod`/`audit`: High instruments (`cookie`/`js`/`http`/`save_content`) off unless purpose is a non-empty stripped string.
- [ ] Nav/DNS default-off; enabling them does not require purpose (Medium).
- [ ] Cookie/HTTP studies: explicit opt-in; dataset classified High (headers/bodies included).

## Docker (if used)
- [ ] `--shm-size=2g` or larger.
- [ ] Non-root user (prod image); `chown` of conda/Playwright paths.
- [ ] Accept that increment-1 Docker Chromium is **always** `--no-sandbox` (unsetting `OPENWPM_NO_SANDBOX` does not enable the renderer sandbox).
- [ ] Bind-mount `datadir` only; do not bind-mount over `/opt/OpenWPM` in prod.
- [ ] Do not publish localhost storage/logger ports.
- [ ] Pull **GHCR digest** with verified cosign attestation — not Docker Hub `latest`.

## Network and sites
- [ ] Respect robots.txt and terms of service (README one-liner).
- [ ] No stolen sessions; no authentication bypass.
- [ ] No attacking or exploiting measured sites.

## Secrets and cloud
- [ ] No credentials in git or crawl scripts.
- [ ] AWS/GCP via env or instance role; prefix-scoped.
- [ ] `SENTRY_DSN` optional; prod sets `LOG_LEVEL_SENTRY_BREADCRUMB=ERROR`.

## Data
- [ ] Treat cookies, JS values, POST bodies, HTTP Cookie/Authorization **headers in the dataset**, screenshots, profile tars as High/Very High.
- [ ] Operator logs reviewed for accidental values (PR 6 does not redact storage).
- [ ] Retention set; deletion date on calendar.
- [ ] `task`/`crawl` snapshots archived with the dataset hash.

## Legal one-liner (from README)
Respect site robots.txt and terms of service. Measurement code does not bypass
authentication walls with stolen sessions.
```

---

