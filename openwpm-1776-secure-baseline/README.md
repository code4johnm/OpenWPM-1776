# OpenWPM-1776 secure-software engineering baseline (increment 1)

| Field | Value |
|-------|-------|
| Document ID | OPENWPM-1776-SSE-BL-001 |
| Version | 0.1.3-draft |
| Date | 2026-08-24 |
| Platform | OpenWPM-1776 `VERSION` 0.35.0 |
| Engine | Playwright 1.62.0 + Chromium 151.0.7922.34 |
| Status | Draft — engineering baseline, not an ATO |

**This package is not** a U.S. Government issuance, Authorization to Operate, STIG certification, FIPS module claim, or EO 12333 collection authority. Intelligence Oversight appears only as purpose limitation and data minimization.

Canonical specification (architecture, SFRs, threat model, PR plan):

- [`SSE-BL-001.md`](SSE-BL-001.md)

Navigators:

- [`02-project-structure.md`](02-project-structure.md) — repo deltas, ownership, pipeline
- [`03-traceability-matrix.md`](03-traceability-matrix.md) — feature → NIST 800-53 / SSDF / CISA / IO notes
- [`skeletons/`](skeletons/) — copy-paste `conf/profiles.yml`, SBOM policy, GHCR sign workflow, intake template, operator checklist

Implementation lands in later PRs into the live tree (`conf/`, `openwpm/security/`, `.github/workflows/sbom-sign.yml`). Do not treat these skeletons as already wired.

## Live-code facts this baseline follows

`docs/Security-and-Privacy.md` still describes Firefox 0.34.0 and a privileged WebExtension. Live 0.35.0 uses Playwright + Chromium (`MeasurementController`, CDP, `js_inject.js`). Dataclass defaults `cookie_instrument=True` and `display_mode="native"` are **incompatible with `prod`**. Docker Chromium is **always `--no-sandbox`** in increment 1. Signed prod artifact is a **GHCR digest**, not Docker Hub `latest`.
