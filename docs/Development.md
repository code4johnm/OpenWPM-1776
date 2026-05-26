# Development Guide

**Document Version:** 1.0  
**OpenWPM Version:** 0.34.0  
**Last Updated:** 2025-04  
**Workspace:** OpenWPM-MAGA

---

## 1. Philosophy and Security Responsibilities

OpenWPM is research infrastructure. Changes must preserve (or improve) measurement fidelity, reproducibility, fault tolerance, and the security/privacy posture of the platform.

All contributors are expected to:

- Read and understand [Security-and-Privacy.md](Security-and-Privacy.md)
- Consider the sensitivity of data that new instrumentation or features will collect
- Never introduce unpinned dependencies or weaken supply-chain controls
- Add or update tests for any behavioral change
- Update documentation (especially Architecture, Configuration, and Security documents) when making structural changes

---

## 2. Setting Up a Development Environment

```bash
git clone https://github.com/openwpm/OpenWPM.git
cd OpenWPM
./install.sh
conda activate openwpm
pre-commit install
```

The `install.sh` script gives you everything needed for both runtime and development (black, mypy, pytest, etc.).

### Useful Development Commands

```bash
# Formatting & linting
black .
isort .
pre-commit run --all-files

# Type checking
mypy openwpm

# Run all tests (slow)
pytest -v

# Run only Python-only tests (no browser)
pytest -m pyonly -v

# Run specific test file or pattern
pytest test/test_http_instrumentation.py -v -k "test_http"
```

---

## 3. Project Structure (Key Paths)

```
openwpm/
├── task_manager.py          # Core orchestrator
├── browser_manager.py       # Per-browser process wrapper
├── config.py                # ManagerParams + BrowserParams + validation
├── commands/                # All BaseCommand implementations
├── deploy_browsers/         # Firefox profile + Selenium setup
├── storage/                 # StorageController + providers + schema
└── utilities/               # Helpers (cookies, platform, multiprocess, etc.)

Extension/
├── src/
│   ├── background/          # Instrumentation modules (HTTP, JS, cookies, nav, DNS)
│   ├── content/             # Content & page scope JS instrumentation
│   └── lib/                 # Shared utilities (post parsing, ordinals, etc.)
└── bundled/                 # Built privileged extension artifacts

scripts/
├── repin.sh                 # Dependency pinning (never edit environment.yaml directly)
├── build-extension.sh       # Rebuild the WebExtension
└── install-firefox.sh       # Firefox version management

test/
├── test_pages/              # Realistic test fixtures (fingerprinting, etc.)
└── ...                      # Extensive instrumentation and integration tests
```

---

## 4. Making Changes

### Python Changes

- Add type annotations to all new public and internal functions (mypy is strict).
- Prefer small, focused PRs.
- Run the full relevant test subset before pushing.
- If you touch storage or schema, also update `parquet_schema.py`, `test_values.py`, and Schema-Documentation.md.

### Extension / TypeScript Changes

1. Make edits under `Extension/src/`.
2. Rebuild:
   ```bash
   ./scripts/build-extension.sh
   # or from Extension/: npm run build
   ```
3. Test with `python -m test.manual_test` (rebuilds automatically with `--selenium`).
4. Add or update tests in `test/test_js_instrument.py`, `test/test_http_instrumentation.py`, etc.

The extension uses a custom privileged API layer (`experiment_apis`). Changes here have security implications — review with extra care.

### Adding a New Instrument

This is a significant undertaking. Typical steps:

1. Add background script under `Extension/src/background/`.
2. (If needed) Add content/page scope scripts.
3. Update the privileged manifest if new experiment APIs are required.
4. Define the structured schema in `schema.sql` + `parquet_schema.py`.
5. Wire the data path through `loggingdb.ts` / socket.
6. Add `BrowserParams` flag and validation logic.
7. Write comprehensive tests using the `test_pages/` fixtures.
8. Document in [Configuration.md](Configuration.md) and [Architecture.md](Architecture.md).
9. Update Security-and-Privacy.md if the new instrument increases data sensitivity.

---

## 5. Dependency Management

**Golden rule:** Never edit `environment.yaml` directly for new packages.

Workflow:

1. Add the new requirement (with desired version constraint) to:
   - `scripts/environment-unpinned.yaml` (runtime)
   - or `scripts/environment-unpinned-dev.yaml` (dev tools)
2. Run:
   ```bash
   cd scripts
   ./repin.sh
   ```
3. Commit the resulting changes to `environment.yaml` and the lock-like unpinned files.

Firefox version updates are performed by editing `TAG` in `scripts/install-firefox.sh` and running the installer.

---

## 6. Testing Philosophy

OpenWPM has two broad categories of tests:

- **pyonly** (`-m pyonly`): Pure Python logic, config validation, storage providers (fast, no browser).
- **Full integration**: Exercise the real browser + extension (slower, more realistic).

When adding instrumentation, prefer adding a minimal reproducible test page under `test/test_pages/` and a corresponding test that asserts on the structured output.

The `test/manual_test.py` utility is invaluable for interactive debugging of extension behavior.

---

## 7. Documentation

When you change behavior visible to users or researchers, update:

- The relevant section in [Configuration.md](Configuration.md)
- [Architecture.md](Architecture.md) if process model, data flows, or component responsibilities change
- [Security-and-Privacy.md](Security-and-Privacy.md) if sensitivity, attack surface, or hardening requirements change
- This Development Guide and/or [CONTRIBUTING.md](../CONTRIBUTING.md) for process changes

Schema documentation under `docs/schemas/` is auto-generated in some cases (see CONTRIBUTING.md for the npm script).

---

## 8. Code Review Expectations

Reviewers will pay special attention to:

- Security and privacy impact of new data collection
- Correctness of schema changes (both SQL and Parquet)
- Proper use of timeouts and error handling in the face of browser crashes
- Supply-chain hygiene (no unpinned or unvetted dependencies)
- Documentation completeness

---

## 9. Release Process (High Level)

See `docs/Release-Checklist.md` for the current checklist. Typical steps include:

- Version bump in `VERSION`
- Update CHANGELOG
- Verify all schema files are in sync
- Run full test matrix + pre-commit
- Build and smoke-test the Docker image
- Tag and publish

Security-sensitive releases may require additional coordinated disclosure steps per [SECURITY.md](../SECURITY.md).

---

## 10. Getting Help

- **Matrix:** `#OpenWPM:mozilla.org`
- **GitHub Discussions:** For usage and development questions
- **Issues:** For bugs (use Security Advisory for vulnerabilities)
- Internal team channels (if you are a maintainer)

When asking for help with a bug, include the OpenWPM version, Firefox version, exact configuration snippet, and relevant log excerpts.

---

## 11. Contribution Checklist (PR Template Summary)

- [ ] Security and privacy impact considered and documented
- [ ] Tests added or updated
- [ ] Documentation updated (Architecture / Configuration / Security as needed)
- [ ] `pre-commit run --all-files` passes
- [ ] `mypy openwpm` clean (or justified exceptions)
- [ ] `pytest -m "not slow"` passes locally
- [ ] CHANGELOG.md updated for user-visible changes
- [ ] No secrets, credentials, or large binary test fixtures committed

---

*Thank you for contributing to the web privacy research ecosystem. High-quality, well-documented, and security-conscious contributions are what keep OpenWPM valuable to the community.*

**End of Development Guide**