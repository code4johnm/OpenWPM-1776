# OpenWPM

[![Documentation Status](https://readthedocs.org/projects/openwpm/badge/?version=latest)](https://openwpm.readthedocs.io/en/latest/?badge=latest)
[![Build Status](https://github.com/openwpm/OpenWPM/workflows/Tests%20and%20linting/badge.svg?branch=master)](https://github.com/openwpm/OpenWPM/actions?query=branch%3Amaster)
[![OpenWPM Matrix Channel](https://img.shields.io/matrix/OpenWPM:mozilla.org?label=Join%20us%20on%20matrix&server_fqdn=mozilla.modular.im)](https://matrix.to/#/#OpenWPM:mozilla.org?via=mozilla.org)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

**OpenWPM** is a research-grade web privacy measurement platform for conducting large-scale studies (thousands to millions of websites). It is built on Firefox with Selenium automation and captures HTTP traffic, JavaScript API calls, cookies, navigation events, and DNS queries through a privileged WebExtension.

**This is a powerful, high-privilege tool.** It collects highly sensitive data and runs with elevated browser capabilities. All users must follow responsible security and privacy practices. See [docs/Security-and-Privacy.md](docs/Security-and-Privacy.md) before running any measurement.

## Table of Contents

- [Key Features](#key-features)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Documentation](#documentation)
- [Security and Privacy](#security-and-privacy)
- [Architecture Overview](#architecture-overview)
- [Storage](#storage)
- [Docker Deployment](#docker-deployment)
- [Advice for Measurement Researchers](#advice-for-measurement-researchers)
- [Contributing](#contributing)
- [Citation](#citation)
- [License](#license)

## Key Features

- **High-Fidelity Instrumentation** — Full HTTP request/response/redirect lifecycle, JavaScript property access and function calls (configurable), cookie changes, detailed navigations, and DNS.
- **Fault-Tolerant Multi-Browser Architecture** — Isolated browser processes with automatic recovery, watchdogs, and centralized storage.
- **Flexible Storage Backends** — SQLite (recommended for exploration), Parquet/Arrow, LevelDB, gzip, S3, and Google Cloud Storage.
- **Reproducible by Design** — Full configuration snapshots, pinned dependencies, and explicit Firefox versioning.
- **Extensible** — Custom commands, pluggable storage providers, and tunable JavaScript instrumentation.
- **Research Proven** — Used in 75+ peer-reviewed studies on web privacy, tracking, and security.

---

## Installation

OpenWPM is tested on Ubuntu via GitHub Actions and commonly used via the provided Docker container (based on Ubuntu 22.04). The `install.sh` script works on most Linux distributions and macOS (with caveats).

**Windows is not supported** (see [#503](https://github.com/openwpm/OpenWPM/issues/503)).

### Prerequisites

- [Conda](https://docs.conda.io/projects/conda/en/latest/user-guide/install/index.html) (Miniconda or Anaconda recommended)

### Automated Installation

```bash
git clone https://github.com/openwpm/OpenWPM.git
cd OpenWPM
./install.sh
conda activate openwpm
```

The script:
1. Creates (or overwrites) a conda environment named `openwpm`
2. Installs a compatible unbranded Firefox build
3. Builds the privileged instrumentation WebExtension

**macOS note:** You may need Xcode command-line tools (`xcode-select --install`) for native modules. XQuartz is required for GUI applications under Docker.

After installation, verify:

```bash
python -c "import openwpm; print(openwpm.__file__)"
```

## Quick Start

The easiest way to run a measurement is with `demo.py`:

```bash
python demo.py
```

For a realistic top-sites crawl using the Tranco list (note: includes NSFW domains):

```bash
python demo.py --tranco
```

**Headless example (servers / CI):**

```python
from openwpm.config import BrowserParams, ManagerParams
from openwpm.storage.sql_provider import SQLiteStorageProvider
from openwpm.task_manager import TaskManager
from openwpm.command_sequence import CommandSequence

manager_params = ManagerParams(num_browsers=2)
browser_params = [BrowserParams(display_mode="headless") for _ in range(2)]

# Use SQLite for easy local exploration
structured = SQLiteStorageProvider(Path("./datadir/crawl.sqlite"))
tm = TaskManager(manager_params, browser_params, structured, None)

for site in ["https://example.com", "https://example.org"]:
    cs = CommandSequence(site)
    cs.get(sleep=3, timeout=60)
    cs.save_screenshot()
    tm.execute_command_sequence(cs)

tm.close()
```

See `demo.py` and `custom_command.py` for more patterns.

## Documentation

| Document | Purpose |
|----------|---------|
| [docs/Architecture.md](docs/Architecture.md) | Canonical system architecture, process model, data flows, Mermaid diagrams |
| [docs/Security-and-Privacy.md](docs/Security-and-Privacy.md) | Threat model, hardening, data classification, responsible disclosure (required reading) |
| [docs/Configuration.md](docs/Configuration.md) | All `ManagerParams` and `BrowserParams` options + instruments |
| [docs/Using_OpenWPM.md](docs/Using_OpenWPM.md) | Step-by-step usage, custom commands, analysis examples |
| [docs/Platform-Architecture.md](docs/Platform-Architecture.md) | Historical high-level overview |
| [docs/Architecture-Internals.md](docs/Architecture-Internals.md) | Detailed coupling, timeouts, and internals |

Additional resources: [Read the Docs](https://openwpm.readthedocs.io), [Papers using OpenWPM](docs/Papers.rst).

## Security and Privacy

**Critical:** OpenWPM intentionally uses a highly privileged WebExtension with broad permissions and `unsafe-eval`. This is required for measurement fidelity but creates a large attack surface.

**Before running any crawl:**

1. Read **[docs/Security-and-Privacy.md](docs/Security-and-Privacy.md)** in full.
2. Run only on dedicated measurement infrastructure (never on personal machines containing sensitive data).
3. Treat all output (especially HTTP bodies, JS values, cookies, and profile archives) as highly sensitive.
4. Enable only the instruments required for your specific research question.
5. Follow legal and ethical requirements for your jurisdiction and institution (IRB/ethics review when appropriate).

See also the repository root [SECURITY.md](SECURITY.md) for vulnerability reporting.

## Architecture Overview

OpenWPM uses a multi-process architecture for isolation and resilience:

- **TaskManager** — User-facing orchestrator, command scheduling, watchdogs, failure recovery.
- **N × BrowserManager** — One per Firefox instance (Selenium + privileged extension).
- **StorageController** (separate process) — Receives data over TCP, writes to pluggable structured/unstructured providers.
- **MPLogger** — Centralized log aggregation.

Full details and diagrams: [docs/Architecture.md](docs/Architecture.md).

## Storage

OpenWPM separates **structured** (tabular events) and **unstructured** (screenshots, page sources, profiles, saved bodies) data.

### Structured Storage Providers

| Provider                  | Best For                     | Notes |
|---------------------------|------------------------------|-------|
| `SQLiteStorageProvider`   | Local exploration & debugging | Recommended starting point |
| `LocalArrowProvider`      | Pandas / NumPy workflows     | Parquet output |
| S3 / GCS Parquet          | Large-scale cloud runs       | Requires credentials |

### Unstructured Storage Providers

- `LevelDBProvider` (recommended for most cases)
- `LocalGzipProvider`
- S3 / GCS object storage

**Schema note:** `openwpm/storage/schema.sql` and `openwpm/storage/parquet_schema.py` must be kept in sync. Compare with:

```bash
diff -y openwpm/storage/schema.sql openwpm/storage/parquet_schema.py
```

## Docker Deployment

The official Docker image provides the most reproducible environment.

```bash
docker build -f Dockerfile -t openwpm .
mkdir -p docker-volume
xhost +local:docker   # Linux GUI forwarding
docker run -v $PWD/docker-volume:/opt/OpenWPM/datadir \
  -e DISPLAY=$DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix --shm-size=2g \
  -it --init openwpm
```

**Important:** `--shm-size=2g` (or higher) is required to prevent Firefox crashes on many sites.

See the full Docker section in the original documentation and `scripts/run-on-osx-via-docker.sh` for macOS.

## Advice for Measurement Researchers

1. **Use a versioned release** (or pin to a specific commit + dependency state). Old Firefox versions contain known vulnerabilities.
2. **Record the exact OpenWPM version, Firefox version, and dependency pins** in your publication.
3. **Document your exact configuration** (the `task` and `crawl` tables already capture this).
4. **Apply data minimization** — only enable instruments you need.
5. **Protect raw data** with the same rigor as any dataset containing authentication material or PII.
6. **Consider ethics review** even for purely technical measurements.

OpenWPM has been used in over 75 published studies. Please add your work to the studies list if appropriate.

## Contributing

We welcome contributions that improve correctness, performance, documentation, or the security/privacy posture of the platform.

- Read [CONTRIBUTING.md](CONTRIBUTING.md)
- Install pre-commit hooks: `pre-commit install`
- Run the full test suite and linting before submitting PRs
- For security issues, follow the process in [SECURITY.md](SECURITY.md) (do not open public issues)

See also [docs/Development.md](docs/Development.md) and the developer notes in `AGENTS.md`.

## Citation

If you use OpenWPM in academic work, please cite the original CCS 2016 paper:

```bibtex
@inproceedings{englehardt2016census,
    author    = "Steven Englehardt and Arvind Narayanan",
    title     = "{Online tracking: A 1-million-site measurement and analysis}",
    booktitle = {Proceedings of ACM CCS 2016},
    year      = "2016",
}
```

## License

OpenWPM is licensed under the GNU General Public License v3.0.

Additional code has been incorporated from [FourthParty](https://github.com/fourthparty/fourthparty) and [Privacy Badger](https://github.com/EFForg/privacybadgerfirefox), both licensed GPLv3+.

---

**Maintained by the OpenWPM community.** For the most up-to-date security guidance, always consult the latest version of [docs/Security-and-Privacy.md](docs/Security-and-Privacy.md).
