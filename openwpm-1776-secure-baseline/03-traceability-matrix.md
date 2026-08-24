# Compliance traceability seed matrix

**Source of truth:** [SSE-BL-001.md](SSE-BL-001.md) § Traceability seed matrix.

Mappings are publicly citable **alignment guidance**. They are not an ATO and not “EO 12333 compliance.”

| Feature / control | NIST 800-53 Rev. 5 | SSDF 800-218 | CISA / SBOM | IO / privacy note |
|-------------------|--------------------|--------------|-------------|-------------------|
| Pinned env (`repin.sh`, Playwright 1.62.0) | SA-8, SA-12, CM-8 | PS.1.1, PW.4.1 | Component producer/name/version/hash | Reproducible science |
| Privileged instrumentation containment (inject + CDP) | AC-6, SC-39, SI-7 | PW.5.1 | — | High data only with purpose |
| Instrument minimization (`prod` overlay) | SI-12, AC-6 | PO.5.1 | — | Primary IO control |
| Config snapshots (`task`/`crawl`) | AU-3, AU-10, CM-6 | PS.3.2 | Generation context sibling | Proves what was collected |
| Process isolation (TaskManager / BrowserManager / StorageController) | SC-7, SC-39 | PW.5.1 | — | Renderer blast radius |
| Watchdogs / `incomplete_visits` | SI-5, CP-10, SI-13 | RV.1.1 | — | Completeness vs host survival |
| Docker hardening (non-root, shm, dockerignore) | AC-6, CM-7, SC-5 | PW.5.1 | Base-layer SBOM | Renderer sandbox **off** in Docker (increment 1) |
| SBOM SPDX 3.0 JSON-LD | SA-12, SR-3, SR-4 | PS.3.1 | CISA 2026 field map | Chromium SHA-256 injected |
| Signed GHCR digest + SPDX attestation | SA-10, SC-8, SC-13 | PS.2.1, PW.4.4 | Author signature (cosign) | Hub `latest` not prod |
| Minimized operator logs | AU-2, AU-3, AU-11 | PW.5.1 | — | URLs yes; cookie/JS values no in logs |
| Data classification | MP-6, SC-28, SI-12 | PO.5.2 | — | High instruments → High dataset |
| Custom commands (increment 1) | AC-3, CM-7 | PW.1.1 | — | No pickle-callable jobs |
| C-SCRM intake | SR-5, SA-12 | PO.1.3 | Component producer | New deps cannot appear silently |
| Localhost dill boundary | SC-7, SI-10 | PW.5.1 | — | Host is TCB |
| Smoke fail-closed | SI-7, CM-3 | PW.8.2 | CI generation context | Missing browser binary fails release |

SFR identifiers and test IDs live in SSE-BL-001 § Security functional requirements.
