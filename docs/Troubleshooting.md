# Troubleshooting Guide

**Document Version:** 1.0  
**OpenWPM Version:** 0.34.0  
**Last Updated:** 2026-05-27T02:47:30Z  
**Workspace:** OpenWPM-1776

---

## 1. Quick Diagnostic Checklist

Before diving into specific errors, verify the following:

1. **Conda environment active?** `conda activate openwpm` (check with `conda env list`)
2. **Using a supported platform?** Ubuntu 22.04/24.04 recommended. Windows is not supported.
3. **Recent OpenWPM + Firefox?** Old versions have known vulnerabilities and compatibility issues. Prefer latest release.
4. **Headless / display mode correct?** On servers/CI without X, you must use `display_mode="headless"` or install `xvfb` + use `"xvfb"`.
5. **Docker shm-size?** Firefox crashes frequently without `--shm-size=2g` (or higher).
6. **Disk space?** Profiles, screenshots, and LevelDB can consume tens of GB quickly.
7. **Pre-commit / linting clean?** Many CI failures are formatting or type issues.

---

## 2. Common Errors and Solutions

### `WebDriverException: Message: The browser appears to have exited before we could connect...`

**Most common cause:** Firefox crashed or failed to start.

**Immediate checks:**

- Are you running on a headless server/CI without `display_mode="headless"`?
- Did you forget `--shm-size=2g` in Docker?
- Is the conda environment using the correct Firefox? Run:
  ```bash
  cd firefox-bin/
  ./firefox --version
  ```
- Are Selenium and geckodriver versions compatible with the installed Firefox? Re-run `./install.sh`.

**Other causes:**
- Overloaded system (CPU/memory). Reduce `num_browsers`.
- Corrupted profile (rare). Delete `tmp_profile_dir` contents or use a fresh seed.
- Missing system libraries (especially in minimal containers). Compare against the Dockerfile.

### `ConfigError: ... callstack_instrument ...`

`callstack_instrument` is currently broken and raises `ConfigError` when enabled (see [#557](https://github.com/openwpm/OpenWPM/issues/557)). Leave it `False` (the default).

### Extension fails to start / port discovery timeout

Look for these files in the profile directory:
- `extension_port.txt`
- `OPENWPM_STARTUP_SUCCESS.txt`

If they are missing:
- Rebuild the extension: `./scripts/build-extension.sh`
- Check for JavaScript errors in the extension background page (use manual test + browser console).
- Verify you are running a compatible unbranded Firefox (the one installed by `install-firefox.sh`).

### High memory usage / browser crashes after many sites

- Enable `memory_watchdog=True`.
- Set `maximum_profile_size` (e.g., 100–500 MB) to force periodic browser recycling.
- Reduce instrumentation (especially `js_instrument` + `save_content`).
- Increase Docker `shm-size`.

### SQLite / Parquet schema drift errors

The structured schema must be kept in sync:

```bash
diff -y openwpm/storage/schema.sql openwpm/storage/parquet_schema.py
```

If you modified one without the other, tests and storage providers will fail. See Development Guide for the update process.

### `PYTHONNOUSERSITE` / user site packages conflicts

Symptom: Import errors or wrong package versions despite correct conda environment.

Fix (temporary):

```bash
PYTHONNOUSERSITE=True python your_script.py
```

Permanent: Clear your user site packages directory or set the variable in your shell profile when working with OpenWPM.

### Slow or hanging crawls on many sites

- JavaScript instrumentation with deep recursion or broad settings is expensive.
- Some sites trigger very large numbers of requests or complex JS.
- Network latency or rate limiting by the target site.
- Profile bloat — use `maximum_profile_size` or stateless crawls.

### Docker GUI issues on macOS

Install XQuartz, reboot, and use the helper script `scripts/run-on-osx-via-docker.sh`.

---

## 3. Debugging Techniques

### Interactive Manual Testing (Most Valuable Tool)

```bash
# Rebuilds extension + launches instrumented Firefox
python -m test.manual_test

# With Selenium (drops into IPython with `driver` variable)
python -m test.manual_test --selenium

# Clean browser, no extension (baseline)
python -m test.manual_test --selenium --no_extension
```

This is the fastest way to reproduce extension or instrumentation bugs.

### Enabling Verbose Logging

- Set `manager_params.log_path` to a writable location.
- The `crawl_history` table in structured storage already captures command status, duration, errors, and tracebacks for every command.

### Inspecting Extension Behavior

1. Use `manual_test --selenium`.
2. Open `about:debugging` in the browser.
3. Inspect the OpenWPM extension background page.
4. Use the Browser Console (Ctrl+Shift+J) — many instrumentation messages are logged there.

### Storage / Data Issues

- For SQLite: Use `sqlite3` CLI or DB Browser for SQLite.
- For Parquet: Use `pyarrow`, DuckDB, or Polars.
- Enable only one instrument at a time when debugging data volume or schema problems.

---

## 4. Performance and Stability Tuning

| Symptom                        | Tuning Options |
|--------------------------------|----------------|
| Memory exhaustion              | `memory_watchdog`, lower `num_browsers`, `maximum_profile_size`, reduce JS instrumentation |
| Frequent browser crashes       | Increase `--shm-size` (Docker), `maximum_profile_size`, reduce concurrent browsers, check disk space |
| Very large output              | Disable `save_content`, tighten JS settings, sample sites, use remote storage |
| Slow startup                   | Use smaller seed profiles, avoid dumping full profiles unnecessarily |
| High CPU on simple pages       | JS instrumentation with `recursive=True` or deep `recursion_depth` on complex sites |

---

## 5. Getting Additional Help

1. Search existing GitHub issues (many common problems are already documented).
2. Reproduce with the smallest possible configuration + `manual_test`.
3. Collect:
   - OpenWPM version (`cat VERSION`)
   - Firefox version (`firefox-bin/firefox --version`)
   - Exact `manager_params` / `browser_params` used (JSON)
   - Relevant excerpt from the platform log
   - `crawl_history` rows for the failing visit(s)
4. Post on GitHub Discussions (usage / development) or open a bug report with the above information.

**For security vulnerabilities or sensitive issues:** Follow the process in [SECURITY.md](../SECURITY.md). Do **not** open public issues.

---

## 6. Preventive Measures

- Always develop and test with `pre-commit` hooks enabled.
- Run the full test suite (or at least the relevant subset) before large PRs or production deployments.
- Pin to releases for research; use `master` only for active development.
- Monitor disk usage and set `maximum_profile_size` proactively.
- Keep your measurement hosts patched and isolated.

---

*Most problems are caused by display mode misconfiguration, insufficient shared memory, or overly broad instrumentation settings. When stuck, reduce to the smallest reproducing case and use the manual test utility.*

**End of Troubleshooting Guide**