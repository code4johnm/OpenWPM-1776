# Security Policy

**OpenWPM / OpenWPM-1776**  
**Version:** 1.0 | 2026-05-27T02:47:30Z

---

## Supported Versions

OpenWPM follows a time-based release model aligned roughly with Firefox ESR/release cadence.

| Version   | Supported          | Notes |
|-----------|--------------------|-------|
| 0.34.x    | :white_check_mark: | Current stable |
| < 0.34    | :x:                | Upgrade immediately; older versions contain known vulnerabilities in bundled Firefox and dependencies |
| < 0.10    | :x:                | Legacy architecture — do not use |

**We strongly recommend always using the latest release or pinning to a specific commit with its exact pinned dependency state.**

---

## Reporting a Vulnerability

**Do not** create public GitHub issues for security vulnerabilities.

### Preferred Reporting Channels (in order)

1. **GitHub Security Advisory (private)** — Recommended for this repository.  
   Go to the repository → Security → Advisories → "Report a vulnerability".

2. **Direct email to maintainers** — Use the contact information listed in the repository or `pyproject.toml` metadata.

3. **Matrix** — `#OpenWPM:mozilla.org` (for initial coordination only — do not include exploit details or sensitive reproduction steps in public rooms).

### What to Include in Your Report

- Description of the vulnerability and potential impact
- Affected versions / commit ranges
- Detailed steps to reproduce (including configuration)
- Proof-of-concept or exploit code (if safe to share)
- Suggested mitigation or fix (if known)
- Whether you are willing to be credited publicly

### Response Timeline (Best Effort)

- **Acknowledgment:** Within 5 business days
- **Initial assessment:** Within 10 business days
- **Coordinated disclosure:** Timeline mutually agreed with reporter

We will keep you informed of progress. Credit will be given in release notes and security advisories unless you request anonymity.

---

## Scope

This policy covers:

- The OpenWPM Python platform code
- The privileged WebExtension (`Extension/`)
- Build scripts, Dockerfiles, and installation tooling
- Dependency pinning and supply-chain issues
- Documentation and configuration that affects security posture

**Out of scope (examples):**
- Vulnerabilities in websites being measured
- Issues in upstream Firefox, Selenium, or conda packages (report to those projects)
- Social engineering or physical attacks against researchers
- Misuse of the tool for malicious purposes

---

## Security Design Philosophy

OpenWPM is a **research measurement tool**, not a general-purpose browser or security product. Its architecture intentionally grants the instrumentation extension extremely high privileges inside Firefox because that is required to achieve the data fidelity needed for rigorous web privacy research.

Consequently:

- The tool must only be run on **dedicated, isolated measurement infrastructure**.
- All output must be handled as **potentially highly sensitive data**.
- Researchers are responsible for the ethical and legal use of the platform and its outputs.

See the comprehensive guidance in [docs/Security-and-Privacy.md](docs/Security-and-Privacy.md).

---

## Known Security-Relevant Limitations

- The privileged WebExtension uses Manifest V2, `experiment_apis`, broad permissions (`<all_urls>`, `webRequestBlocking`, etc.), and `'unsafe-eval'` in its CSP. These are necessary for current capabilities.
- `callstack_instrument` is currently non-functional (see [#557](https://github.com/openwpm/OpenWPM/issues/557)).
- Some command outputs (screenshots, page sources) still write to `data_directory` rather than going through the configured unstructured storage providers.
- Docker images are not yet cryptographically signed (planned improvement).
- No SBOM is currently generated in CI (planned improvement).

These limitations are documented in detail in [docs/Security-and-Privacy.md](docs/Security-and-Privacy.md#9-known-limitations-and-residual-risks).

---

## Supply Chain Security

OpenWPM maintains strong supply-chain controls:

- All Python, Node.js, and system dependencies are **exactly pinned** via `scripts/repin.sh`.
- Firefox version is explicitly managed in `scripts/install-firefox.sh`.
- Pre-commit hooks, linting, type checking, and CodeQL run on every push and PR.
- GitHub Actions workflows use pinned actions where practical.

We encourage researchers to reproduce builds from source and verify dependency pins when publishing high-impact results.

---

## Questions

For non-security questions about the platform's security model or responsible use, open a GitHub Discussion or reach out on the Matrix channel.

---

*This policy is effective as of the date at the top of the file. It will be updated as the project evolves. The canonical version is always in the repository root.*