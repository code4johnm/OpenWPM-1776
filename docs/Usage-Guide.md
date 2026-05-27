# Usage Guide

**Document Version:** 1.0  
**OpenWPM Version:** 0.34.0  
**Last Updated:** 2026-05-27T02:47:30Z  
**Workspace:** OpenWPM-1776

---

## 1. Introduction

This guide walks through common usage patterns for OpenWPM, from basic crawls to custom instrumentation and data analysis. It builds on the examples in `demo.py` and `custom_command.py`.

**Prerequisites:** Successful installation (see [Installation-Guide.md](Installation-Guide.md)) and a solid understanding of the security and privacy responsibilities outlined in [Security-and-Privacy.md](Security-and-Privacy.md).

---

## 2. Basic Measurement Script Structure

A typical OpenWPM measurement follows this pattern:

```python
from pathlib import Path
from openwpm.config import BrowserParams, ManagerParams
from openwpm.storage.sql_provider import SQLiteStorageProvider
from openwpm.task_manager import TaskManager
from openwpm.command_sequence import CommandSequence

# 1. Configure the platform
manager_params = ManagerParams(num_browsers=3)
manager_params.data_directory = Path("./datadir")
manager_params.log_path = Path("./datadir/openwpm.log")

# 2. Configure browsers (one BrowserParams per browser instance)
browser_params = [BrowserParams() for _ in range(manager_params.num_browsers)]
for bp in browser_params:
    bp.display_mode = "headless"          # or "native" / "xvfb"
    bp.http_instrument = True
    bp.js_instrument = True
    bp.cookie_instrument = True
    bp.navigation_instrument = True
    bp.dns_instrument = False             # Enable only when needed

# 3. Choose storage providers
structured = SQLiteStorageProvider(manager_params.data_directory / "crawl.sqlite")
unstructured = None   # or LevelDBProvider(...) / S3 / etc.

# 4. Create TaskManager
tm = TaskManager(manager_params, browser_params, structured, unstructured)

# 5. Define and submit work
sites = ["https://example.com", "https://example.org", "https://example.net"]
for site in sites:
    cs = CommandSequence(site, site_rank=1)   # site_rank optional (e.g. from Tranco)
    cs.get(sleep=5, timeout=60)               # Navigate + wait
    cs.save_screenshot()                      # Optional: visual artifact
    cs.dump_page_source()                     # Optional: rendered HTML
    tm.execute_command_sequence(cs)           # Non-blocking by default

# 6. Wait for completion and shut down cleanly
tm.close()
```

**Key principles:**
- Always call `tm.close()` (or use a context manager if wrapping).
- Non-blocking execution means your script can finish before work completes.
- Configuration is validated at `TaskManager` construction time.

---

## 3. Command Sequences

`CommandSequence` is the fundamental unit of work. Commands execute sequentially on one browser.

Common commands (see `openwpm/commands/browser_commands.py` and `profile_commands.py`):

| Method                  | Description                              | Typical Timeout |
|-------------------------|------------------------------------------|-----------------|
| `get(url, sleep=..., timeout=...)` | Navigate to URL and wait                 | 60s |
| `save_screenshot(...)`  | Capture viewport or full page            | 30s |
| `dump_page_source(...)` | Save rendered HTML                       | 30s |
| `dump_profile(...)`     | Archive the entire browser profile       | 120s |
| `custom_function(...)`  | Execute arbitrary Python in the BM process | variable |

Example of a more complex sequence:

```python
cs = CommandSequence("https://example.com/login")
cs.get(sleep=3)
cs.save_screenshot("login-page.png")
cs.custom_function(custom_login, "user@example.com", "hunter2")  # defined elsewhere
cs.get("https://example.com/dashboard", sleep=5)
cs.save_screenshot("dashboard.png")
```

**Custom commands must be defined in a separate, importable Python module** (see [#837](https://github.com/openwpm/OpenWPM/issues/837) and `custom_command.py`).

---

## 4. Instrumentation Configuration

Instrumentation is controlled per-browser via `BrowserParams`.

### Recommended Starting Set for Privacy Research

```python
bp = BrowserParams()
bp.http_instrument = True
bp.js_instrument = True
bp.js_instrument_settings = ["collection_fingerprinting"]   # or custom list/dict
bp.cookie_instrument = True
bp.navigation_instrument = True
bp.dns_instrument = True
bp.save_content = False   # Extremely high volume — enable with care
```

### JavaScript Instrumentation Settings

The `js_instrument_settings` parameter is powerful and can generate very large amounts of sensitive data.

See [Configuration.md](Configuration.md#js_instrument) and the schema files under `docs/schemas/` for the full object model.

Common patterns:

- Use built-in collections: `"collection_fingerprinting"`
- Provide custom settings objects to instrument only specific objects/properties
- Control recursion, call stack capture, and argument/value logging

**Security note:** Logging JS arguments and return values can capture authentication tokens, CSRF values, email addresses, and other PII. Use the most restrictive settings that still answer your research question.

---

## 5. Working with Browser Profiles

OpenWPM supports both stateless and stateful crawls.

### Stateless (Default)

Each browser starts with a fresh profile. Good for most measurement studies.

### Stateful / Seeded Profiles

```python
bp = BrowserParams()
bp.seed_tar = Path("/path/to/profile-archive.tar.gz")
```

Use `dump_profile()` inside a `CommandSequence` to create new seed archives after logging into accounts or performing desired setup steps.

**Warning:** Profile archives contain cookies, localStorage, cached credentials, and browsing history. Treat them with the highest sensitivity.

See [Configuration.md](Configuration.md#browser-profile-support) for `profile_archive_dir` and `recovery_tar` options.

---

## 6. Data Analysis Basics

After a crawl, the primary structured output is usually a SQLite database.

Example: Find sites that exfiltrated a known email address over HTTP:

```python
import sqlite3

conn = sqlite3.connect("datadir/crawl.sqlite")
cur = conn.cursor()

email = "alice@example.com"
cur.execute("""
    SELECT DISTINCT top_level_url
    FROM http_requests
    WHERE post_body LIKE ?
""", (f"%{email}%",))

for row in cur.fetchall():
    print(row[0])
```

For larger datasets, use the Parquet output + DuckDB, Polars, or Pandas.

Unstructured artifacts (screenshots, saved content) live in `manager_params.data_directory` or the configured unstructured storage backend.

---

## 7. Scaling and Performance

- Start with 1–4 browsers locally; many researchers successfully run 10–20 in the cloud.
- Use `memory_watchdog=True` and `process_watchdog=True` for long-running jobs.
- Set `maximum_profile_size` to periodically recycle browsers and control disk usage.
- For very large campaigns, combine with external orchestration (Kubernetes, custom scripts) and remote storage (S3/GCS).
- Monitor disk I/O and network — full instrumentation on popular sites generates substantial data.

---

## 8. Debugging

### Interactive Manual Testing

```bash
python -m test.manual_test
python -m test.manual_test --selenium
python -m test.manual_test --selenium --no_extension
```

The manual test utility rebuilds the extension and drops you into an IPython shell with a live browser.

### Common Debug Flags

- `display_mode="native"` + small `num_browsers=1`
- Reduce timeouts during development
- Enable only one instrument at a time when isolating problems

### Logs

- Platform log: `manager_params.log_path`
- Per-browser and extension logs are also captured in the structured storage and `crawl_history`.

---

## 9. Best Practices Checklist

- [ ] Read and followed [Security-and-Privacy.md](Security-and-Privacy.md)
- [ ] Using a pinned release or exact commit + dependency state
- [ ] Only enabled required instruments
- [ ] Using dedicated measurement hosts / VMs / containers
- [ ] Output directories and logs have appropriate access controls and encryption at rest
- [ ] Configuration (including JS settings) documented in the study protocol
- [ ] Ethics / IRB review obtained if required
- [ ] Raw data retention policy defined before starting the crawl

---

## 10. Next Steps and Resources

- [Configuration.md](Configuration.md) — Complete reference for all parameters
- [Architecture.md](Architecture.md) — Understand what happens under the hood
- `custom_command.py` — Template for new commands
- `test/` directory — Many realistic usage examples
- Matrix channel and GitHub Discussions for community support

**When in doubt about data sensitivity or platform behavior, consult the Security and Privacy document and, if necessary, institutional security or ethics teams before proceeding.**

---

*End of Usage Guide*