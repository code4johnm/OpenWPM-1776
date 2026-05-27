# Security and Privacy

**Document Version:** 1.0  
**OpenWPM Version:** 0.34.0  
**Last Updated:** 2026-05-27T02:47:30Z  
**Workspace:** OpenWPM-1776  
**Classification:** Public (for researchers and operators)

---

## 1. Executive Summary

OpenWPM is a powerful web privacy measurement framework. Its design intentionally grants the instrumentation layer extremely high privileges inside Firefox in order to achieve the fidelity required for rigorous privacy research.

**This power creates real security and privacy risks** if the platform is misused, misconfigured, or if its outputs are not handled responsibly.

This document provides:

- A threat model for the platform itself and for studies conducted with it
- Security controls and hardening guidance aligned with OWASP, NIST Cybersecurity Framework, and SSDL practices
- Privacy-by-design considerations and data handling requirements
- Responsible disclosure and vulnerability management policy
- Known limitations and residual risks

**All operators and researchers using OpenWPM-1776 must read this document.**

---

## 2. Scope and Audience

| Audience                  | Relevant Sections                          |
|---------------------------|--------------------------------------------|
| Measurement Researchers   | 3–7, 9–10, 12                              |
| Platform Operators (cloud, cluster) | 4–8, 11                            |
| Security Reviewers        | All                                        |
| Contributors              | 4, 6, 8, 11, 13                            |
| Ethics/IRB Review Boards  | 3, 5, 9, 10, 12                            |

This document covers the OpenWPM platform code, the privileged WebExtension, build and deployment artifacts (Docker, install scripts), and the data it produces. It does **not** constitute legal advice.

---

## 3. Threat Model

### 3.1 Assets

1. **Measurement Integrity** — Accuracy and completeness of collected privacy signals.
2. **Researcher / Operator Infrastructure** — The machines, credentials, and networks running crawls.
3. **Study Subjects (Websites & Users)** — The sites being measured and any real users whose data may be collected incidentally.
4. **Collected Data** — Highly sensitive structured and unstructured artifacts (full HTTP bodies, JS values, cookies, DNS, screenshots, profiles).
5. **Platform Supply Chain** — Dependencies, Firefox build, extension build artifacts.

### 3.2 Adversaries

- Malicious or compromised websites being crawled
- Network adversaries (passive or active) on paths between crawlers and targets
- Malicious browser extensions or injected content (in the instrumented profile)
- Compromised researcher machines or supply chain attackers
- Insiders with access to raw measurement data
- Nation-state or sophisticated actors targeting high-value research infrastructure

### 3.3 High-Level Threats (STRIDE-inspired)

| Threat Category | Example in OpenWPM Context                                                                 | Primary Mitigations |
|-----------------|--------------------------------------------------------------------------------------------|---------------------|
| **Spoofing**    | Malicious site impersonating a first-party to poison measurements                          | None (inherent to web); use Tranco + known lists; post-processing validation |
| **Tampering**   | Site modifies DOM/JS to evade or poison JS instrumentation; profile corruption             | JS instrument hardening, profile isolation, hash verification where available |
| **Repudiation** | Researcher cannot prove what configuration produced a given dataset                        | Full `manager_params` + `browser_params` serialized in `task`/`crawl` tables |
| **Information Disclosure** | Full HTTP bodies, auth cookies, PII, internal network data exfiltrated from study data | Strict data classification, minimization, access control, encryption at rest |
| **Denial of Service** | Sites cause browser crashes, memory exhaustion, or extension hangs; resource exhaustion on researcher host | Watchdogs, failure limits, resource quotas, Docker limits, `maximum_profile_size` |
| **Elevation of Privilege** | Compromised extension or Firefox process escapes containment; malicious command injection via custom commands | Privileged extension only on dedicated measurement hosts; code review of custom commands; no untrusted code execution |

### 3.4 Data Sensitivity Classification

| Data Type              | Sensitivity | Example Tables / Artifacts          | Recommended Handling |
|------------------------|-------------|-------------------------------------|----------------------|
| HTTP URLs + metadata   | Medium-High | `http_requests`, `http_responses`   | Pseudonymize where possible; treat as potentially identifying |
| HTTP bodies / POST     | High        | `post_body*`, `save_content`        | Encrypt at rest; minimize collection; short retention |
| JavaScript values & args | Very High | `javascript.value`, `arguments`     | Highest protection; often contains tokens, emails, PII |
| Cookies (names + values) | Very High | `javascript_cookies`                | Treat as authentication material |
| DNS responses          | Medium      | `dns_responses`                     | Can reveal internal hostnames |
| Screenshots + page source | High     | `data_directory` artifacts          | May contain logged-in views, private content |
| Browser profiles       | Very High   | `profile_archive_dir`, seed tars    | Contain cookies, localStorage, cached credentials |
| Call stacks            | High        | `callstacks`, `javascript.call_stack` | Reveals application logic + researcher intent |

**Rule of thumb:** Treat all OpenWPM output as **sensitive personal or organizational data** unless you have explicitly proven otherwise for a specific study.

---

## 4. Security Controls and Hardening (NIST CSF / OWASP Aligned)

### 4.1 Protect

**Dependency Management (SSDL)**
- All Python, Node, and system dependencies are **pinned** via `scripts/repin.sh` + `environment.yaml`.
- Firefox version is explicitly managed in `scripts/install-firefox.sh`.
- Never edit `environment.yaml` directly. Use unpinned files + repin.
- Run `pre-commit` and full test matrix before any dependency change.

**Extension Hardening**
- The privileged extension uses `unsafe-eval` and extremely broad permissions **by design**.
- It must only be installed in dedicated, throwaway Firefox profiles on measurement infrastructure.
- Rebuild the extension (`npm run build` or `scripts/build-extension.sh`) after any source change.
- The extension is **not** intended for general-purpose browsing.

**Configuration Validation**
- `validate_browser_params`, `validate_manager_params`, and `validate_crawl_configs` are always invoked.
- JS instrumentation settings are normalized and validated (`clean_js_instrumentation_settings`).

**Least Privilege at Runtime**
- Run crawls with the minimum `num_browsers` necessary.
- Prefer `headless` or `xvfb` on servers.
- Use dedicated, non-privileged OS users for long-running jobs.
- In Docker: do not run as root inside the container unless absolutely required.

### 4.2 Detect

- CodeQL analysis runs on every push/PR (`.github/workflows/codeql-analysis.yml`).
- Comprehensive test suite with instrumentation-specific tests.
- `crawl_history` table records every command status, duration, error, and traceback.
- Watchdogs surface memory/process anomalies.

### 4.3 Respond & Recover

- BrowserManager isolation + automatic restart on critical failure.
- StorageController survives browser death.
- `incomplete_visits` table aids post-incident forensics.
- Full configuration snapshot in the `task` table enables exact reproduction of a compromised run.

### 4.4 Supply Chain Controls

| Control                  | Implementation                              | Notes |
|--------------------------|---------------------------------------------|-------|
| Pinned dependencies      | `repin.sh` + conda/pip exact pins           | Excellent |
| Reproducible Firefox     | `install-firefox.sh` + version script       | Good |
| CI with CodeQL (JS + Py) | GitHub Actions                              | Good; expand to more queries |
| Docker image signing     | Not currently implemented                   | **Gap** — recommend cosign or similar |
| SBOM generation          | Not currently implemented                   | **Gap** — recommend `syft` + `grype` in CI |
| Pre-commit + linting     | Enforced                                    | Strong |

**Recommendation:** Add SBOM generation and container image signing to the release process (see Release-Checklist.md).

---

## 5. Privacy-by-Design and Data Protection

### 5.1 Collection Minimization

Enable only the instruments you need for the specific research question:
- `http_instrument` + `save_content` are extremely high volume and high sensitivity.
- `js_instrument` with broad settings can capture authentication tokens and PII in arguments/values.
- `callstack_instrument` (when working) adds significant overhead and sensitivity.

### 5.2 Study Design Recommendations

1. **Separate measurement infrastructure** from any personal or production browsing.
2. Use fresh or carefully sanitized profiles for each major experiment.
3. Prefer stateless crawls (`seed_tar` only when state is explicitly required).
4. When studying logged-in behavior, document the exact accounts used and rotate credentials after the study.
5. Apply purpose limitation: raw data should only be accessible to researchers who need it for the approved protocol.
6. Consider differential privacy or heavy pseudonymization before publishing aggregate findings that could re-identify users or organizations.

### 5.3 Legal and Ethical Considerations

OpenWPM has been used in dozens of peer-reviewed studies. However:

- Crawling may violate website terms of service.
- Collecting certain data (e.g., authentication material, health, location) may have regulatory implications (GDPR, CCPA, HIPAA, etc.).
- Researchers must obtain appropriate IRB/ethics approval when studying human subjects (even indirect).

**Never** use OpenWPM to:
- Attack or exploit websites
- Exfiltrate data from systems you do not have explicit authorization to test
- Circumvent security controls for non-research purposes

---

## 6. WebExtension Security Analysis

The OpenWPM extension is the highest-privilege component.

**Manifest Highlights (as of v0.34.0):**
- `manifest_version: 2`
- `permissions`: `<all_urls>`, `webRequestBlocking`, `webNavigation`, `cookies`, `management`, `tabs`, `dns`, `mozillaAddons`
- `experiment_apis`: `sockets`, `profileDirIO`, `stackDump`
- `content_security_policy`: includes `'unsafe-eval'`

**Why this is necessary:**
High-fidelity HTTP and JavaScript instrumentation at the scale and depth required for privacy research cannot be achieved with standard WebExtensions or user scripts.

**Residual Risks & Mitigations:**
- **Risk:** Extension compromise or bug could allow arbitrary code execution in the browser context with very high privileges.
  - **Mitigation:** Run only on dedicated measurement hosts. Never load the OpenWPM extension in a browser profile containing personal credentials or used for general browsing.
- **Risk:** `unsafe-eval` + privileged APIs increase attack surface for malicious pages.
  - **Mitigation:** The instrumentation code itself is small and reviewed. JS settings allow fine-grained control over what is logged.
- **Risk:** ProfileDirIO and sockets APIs could be abused if a malicious extension or page gained access.
  - **Mitigation:** The extension is the only code granted these APIs in the measurement profile.

**Firefox Requirements:**
The extension will only load in unbranded Firefox builds or builds with `extensions.experiments.enabled` set and add-on signature requirements disabled. This is documented in the installation and deployment guides.

---

## 7. Operational Security

### 7.1 Host Hardening

- Run measurement jobs on dedicated VMs or containers.
- Disable unnecessary services and outbound access where possible.
- Use `memory_watchdog` and `process_watchdog` in long-running cloud jobs.
- Monitor for excessive disk usage (`maximum_profile_size`).
- Prefer Docker with `--shm-size=2g` (or higher) for stability and some isolation.

### 7.2 Network Considerations

- Studies often generate very large volumes of traffic. Coordinate with network operators.
- Some sites may detect and block or serve different content to measurement infrastructure (use residential proxies or diversity techniques only when scientifically justified and ethically reviewed).

### 7.3 Artifact Hygiene

- Screenshots and page sources frequently contain logged-in states or personal information.
- Browser profile archives (`*.tar.gz`) contain cookies, localStorage, and cached data — treat as equivalent to a full browser backup.
- Use the unstructured storage providers with encryption at rest when storing artifacts long-term.

### 7.4 Logging

- OpenWPM logs can contain URLs, error messages with sensitive values, and stack traces.
- Rotate and protect `manager_params.log_path` with the same sensitivity as the primary dataset.

---

## 8. Vulnerability Management and Responsible Disclosure

### 8.1 Reporting a Vulnerability

**Do not** open public GitHub issues for security vulnerabilities.

Preferred reporting paths (in order):

1. **GitHub Security Advisory** (private) — Preferred for this repository.
2. Email to the current maintainers listed in `pyproject.toml` / repository metadata (if present).
3. Matrix channel (`#OpenWPM:mozilla.org`) for initial coordination (do not include exploit details in public rooms).

Include:
- Description and impact
- Steps to reproduce
- Affected versions / commits
- Suggested fix or mitigation (if known)

### 8.2 Response Expectations

- Acknowledgment within 5 business days (best effort).
- Coordinated disclosure timeline agreed with reporter.
- Credit will be given to reporters unless anonymity is requested.

### 8.3 Security Policy File

A machine-readable `SECURITY.md` file exists at the repository root (see [SECURITY.md](../SECURITY.md)) and is the canonical source for reporting instructions.

---

## 9. Known Limitations and Residual Risks

| Limitation / Risk | Impact | Workaround / Status |
|-------------------|--------|---------------------|
| `callstack_instrument` broken | Loss of call stack fidelity for JS analysis | Disabled by default; raises `ConfigError` if enabled. See #557 |
| Manifest V2 + privileged APIs | Higher attack surface than modern MV3 | Necessary for current capabilities; monitor Firefox privileged extension evolution |
| `unsafe-eval` in extension CSP | Increased risk if extension is compromised | Contained by dedicated-host policy |
| `save_content` and some command outputs bypass unstructured providers | Data may land in `data_directory` with weaker controls | Manual encryption / access control |
| No built-in PII redaction or tokenization | Researchers must implement | Post-processing pipelines recommended |
| Docker images not signed | Supply chain risk for container users | Verify image digests manually today |
| No SBOM | Harder vulnerability impact assessment | Planned improvement |

---

## 10. Recommendations and Roadmap (Security & Privacy)

**High Priority**
1. Add SBOM generation (`syft`) + vulnerability scanning (`grype`) to CI and release process.
2. Implement container image signing (cosign) for published Docker images.
3. Expand CodeQL queries and add Semgrep rules for the Python and TypeScript codebases.
4. Create a data-handling checklist / template for new studies.

**Medium Priority**
5. Evaluate feasibility of a lower-privilege instrumentation path (e.g., using Firefox Marionette + CDP where sufficient).
6. Provide example post-processing scripts that perform basic PII detection and redaction on common fields.
7. Document a formal threat model document (beyond this overview) with attack trees.

**Longer Term**
8. Explore integration with modern browser automation primitives that reduce reliance on highly privileged extensions.
9. Add support for encrypted-at-rest storage providers with key management integration.

---

## 11. References and Standards Alignment

- **OWASP Top 10 (2021)** — Particularly A02 (Cryptographic Failures), A04 (Insecure Design), A05 (Security Misconfiguration), A06 (Vulnerable Components)
- **OWASP ASVS** — Level 2 controls applicable to research tooling (authentication where applicable, logging, error handling, dependency management)
- **NIST Cybersecurity Framework 2.0** — Govern, Identify, Protect, Detect, Respond, Recover functions mapped above
- **Secure Software Development Lifecycle (SSDL)** — Pinned dependencies, pre-commit, CodeQL, reproducible builds, security documentation
- **OWASP Top 10 for LLM Applications** — Not directly applicable today, but relevant if future AI-assisted analysis features are added
- **Privacy by Design** (Cavoukian) — Proactive not reactive; privacy as default; embedded into design
- Previous OpenWPM publications and the broader web measurement research literature

---

## 12. Conclusion

OpenWPM-1776 enables world-class web privacy research precisely because it collects data at a depth and scale that few other tools can match. That capability carries a corresponding duty of care.

**Operators and researchers who follow the guidance in this document materially reduce risk to themselves, their institutions, their subjects, and the broader research community.**

When in doubt, err on the side of minimization, isolation, and consultation with security and ethics experts.

---

*Document maintained by the OpenWPM maintainers. Contributions that improve security or privacy posture are strongly encouraged (see [CONTRIBUTING.md](../CONTRIBUTING.md)).*

**End of Security and Privacy Document**