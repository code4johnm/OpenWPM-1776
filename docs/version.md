# OpenWPM-MAGA Versioning

**Document Version:** 1.0  
**Base Upstream Version:** 0.34.0  
**Fork Name:** OpenWPM-MAGA  
**Last Updated:** 2025-05

---

## Overview

This document describes the versioning approach for the **OpenWPM-MAGA** fork of [OpenWPM](https://github.com/openwpm/OpenWPM).

OpenWPM-MAGA is a maintained distribution focused on:
- High-quality, professional documentation following industry security and research standards (OWASP, NIST CSF, SSDL).
- Targeted robustness and reliability improvements.
- Operational excellence for privacy measurement research.

## Base Version

This fork is based on upstream OpenWPM **v0.34.0**.

The canonical upstream version is recorded in the root [VERSION](../VERSION) file.

## Fork Versioning Scheme

We follow a pragmatic hybrid versioning model:

- **Upstream alignment**: We track the upstream major.minor version (e.g., 0.34).
- **Fork patch / feature suffix**: When we make meaningful changes in this fork, we may append a local suffix in the form `0.34.0-maga.N` (where N is a sequential fork patch number) for releases or tagged builds.
- **Documentation-driven releases**: Because a large portion of the value in this fork currently comes from documentation and process improvements, documentation updates may trigger fork patch releases even without core code changes.

For day-to-day development, the root `VERSION` file continues to reflect the upstream base.

## Major Changes in the OpenWPM-MAGA Fork

### Documentation Overhaul (Primary Focus)

A complete professional documentation suite was added or significantly modernized, following current best practices for secure, auditable, research-grade open source software:

- **README.md** — Completely rewritten with security-first design, clear structure, and prominent links to new security and architecture documentation.
- **docs/Architecture.md** (new canonical document) — Comprehensive architecture reference with Mermaid diagrams covering the process model, data flows, command lifecycle, storage providers, and extensibility points.
- **docs/Security-and-Privacy.md** (new) — Full threat model (STRIDE-inspired), data sensitivity classification table, privileged WebExtension attack surface analysis, OWASP Top 10 / ASVS / NIST CSF / SSDL alignment, operational security guidance, and responsible disclosure process.
- **SECURITY.md** (new at repository root) — Formal vulnerability disclosure policy, supported versions, reporting channels, and scope.
- **Dedicated Guides** (all new):
  - `docs/Installation-Guide.md`
  - `docs/Usage-Guide.md`
  - `docs/Deployment.md`
  - `docs/Development.md`
  - `docs/Troubleshooting.md`
- **Enhanced existing docs**:
  - `docs/Configuration.md` — Added "Security and Privacy Implications of Configuration" section.
  - `CONTRIBUTING.md` — Added explicit security and privacy responsibilities for contributors.
- **CHANGELOG.md** — Added structured "Unreleased" section tracking fork changes.

All new and updated documentation emphasizes:
- Security hardening
- Data privacy and sensitivity classification
- Reproducibility
- Configuration management
- Traceability

### Code Improvements and Bug Fixes

The following targeted improvements have been applied on top of upstream v0.34.0:

| Area | Change | Related Upstream Issue |
|------|--------|------------------------|
| JavaScript Instrumentation | Added defensive `try/catch` guards around `eval(item.object)` and `Object.getPropertyNames(object)` inside `instrumentJS()` and `instrumentObject()`. Failing targets in custom or large instrumentation collections no longer abort processing of the entire collection. | [#1171](https://github.com/openwpm/OpenWPM/issues/1171) |
| Configuration Validation | Removed dead/unreachable code paths and improved the error message for the long-broken `callstack_instrument` flag. | [#557](https://github.com/openwpm/OpenWPM/issues/557) and follow-ups |
| Test Reliability | `test_cache_hits_recorded` now uses a per-test `?cachebust=` query parameter on the first visit to prevent stale HTTP cache entries (from the shared test server's long `max-age` headers) from polluting first-load assertions. The second visit still exercises real browser caching behavior. | [#1162](https://github.com/openwpm/OpenWPM/issues/1162) |

These changes are documented in the [CHANGELOG.md](../CHANGELOG.md) under the "Unreleased" section.

### Other Fork Characteristics

- Strong emphasis on documentation quality as a first-class deliverable.
- Accumulation of practical robustness fixes that improve the day-to-day reliability of the measurement platform in research and CI environments.
- All documentation follows a consistent professional style with version/date stamps, clear security/privacy callouts, and cross-references.

## Future Versioning

When preparing a release or significant update from this fork:

1. Update the root `VERSION` file if a new fork patch version is being cut.
2. Add a dated entry under the appropriate section in `CHANGELOG.md`.
3. Update this `docs/version.md` file with a summary of new changes.
4. Consider tagging with a fork-specific suffix (e.g., `v0.34.0-maga.1`).

## Relationship to Upstream

We aim to stay reasonably close to upstream OpenWPM for core measurement functionality while diverging primarily in:
- Documentation quality and completeness
- Selected reliability and robustness improvements
- Security and operational guidance tailored to privacy research use cases

Significant upstream changes should be evaluated for merge, with preference given to changes that do not regress the improvements made in this fork.

---

*This document should be updated with every meaningful change or release originating from the OpenWPM-MAGA fork.*