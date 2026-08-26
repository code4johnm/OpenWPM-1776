# Project structure deltas

**Source of truth:** [SSE-BL-001.md](SSE-BL-001.md) § Project structure deltas. This file is a navigator.

Extend the existing OpenWPM-1776 repository. Do not invent a greenfield monorepo.

## Add

```
conf/profiles.yml
conf/sbom-policy.yml
conf/intake/TEMPLATE.md
conf/intake/README.md
.github/workflows/sbom-sign.yml
openwpm/security/profiles.py          # required for fail-closed overlay
openwpm/__main__.py                   # validator: python -m openwpm --profile
scripts/docker-entrypoint.sh
scripts/install-sbom-tools.sh
scripts/merge-spdx3-cisa.py
scripts/assert-spdx3-cisa.py
scripts/check-schema-sync.py
docs/operators/checklist.md
docs/operators/docker-prod.md
docs/operators/profiles.md
evidence/                             # gitignored outputs
.dockerignore
```

Copy-ready increment-1 skeletons: [`skeletons/`](skeletons/).

## Ownership

| Area | Owner | Paths |
|------|-------|-------|
| Core measurement | Platform maintainers | `openwpm/task_manager.py`, `browser_manager.py`, `instrumentation/`, `storage/`, `config.py` |
| Security / policy | Security + maintainers | `conf/`, `docs/Security-and-Privacy.md`, `docs/operators/`, `openwpm/security/` |
| Release / supply chain | Maintainers + operators | `environment.yaml`, `scripts/repin.sh`, `.github/workflows/`, `Dockerfile`, SBOM |

## Pipeline

```
repin (conda-forge + PyPI)
  → license + secret scan
  → SAST / pre-commit
  → pytest + smoke + schema-sync
  → build image
  → SPDX 3.0 JSON-LD SBOM + optional CycloneDX + grype.json
  → push GHCR + cosign sign + attest
  → verify job fail-closed
```

Docker Hub `openwpm/openwpm:latest` remains unsigned and is **not** a prod artifact.

## Evidence convention

Add to `.gitignore`:

```
evidence/**
!evidence/.gitignore
!evidence/README.md
```
