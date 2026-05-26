
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

See also [docs/Development.md](docs/Development.md) (when created) and the developer notes in `AGENTS.md`.

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

## Installation

OpenWPM is tested on Ubuntu 24.04 via GitHub Actions and is commonly used via the docker container
that this repo builds, which is based on Ubuntu 22.04. Although we don't officially support
other platforms, conda is a cross platform utility and the install script can be expected
to work on OSX and other linux distributions.

OpenWPM does not support windows: <https://github.com/openwpm/OpenWPM/issues/503>

### Pre-requisites

The main pre-requisite for OpenWPM is conda, a fast cross-platform package management tool.

Conda is open-source and can be installed from <https://docs.conda.io/projects/conda/en/latest/user-guide/install/index.html>.

### Install

An installation script, `install.sh` is included to: install the conda environment,
install unbranded firefox, and build the instrumentation extension.

All installation is confined to your conda environment and should not affect your machine.
The installation script will, however, override any existing conda environment named openwpm.

To run the install script, run

```bash
./install.sh
```

After running the install script, activate your conda environment by running:

```bash
conda activate openwpm
```

### Mac OSX

You may need to install `make` / `gcc` in order to build the extension.
The necessary packages are part of xcode: `xcode-select --install`

We do not run CI tests for Mac, so new issues may arise. We welcome PRs to fix
these issues and add full CI testing for Mac.

Running Firefox with xvfb on OSX is untested and will require the user to install
an X11 server. We suggest [XQuartz](https://www.xquartz.org/). This setup has not
been tested, we welcome feedback as to whether this is working.

## Quick Start

Once installed, it is very easy to run a quick test of OpenWPM. Check out
`demo.py` for an example. This will use the default setting specified in
`openwpm/config.py::ManagerParams` and
`openwpm/config.py::BrowserParams`, with the exception of the changes
specified in `demo.py`.

The demo script also includes a sample of how to use the
[Tranco](https://tranco-list.eu/) top sites list via the optional command line
flag `demo.py --tranco`. Note that since this is a real top sites list it will
include NSFW websites, some of which will be highly ranked.

More information on the instrumentation and configuration parameters is given
below.

The docs provide a more [in-depth tutorial](docs/Using_OpenWPM.md),
and a description of the [methods of data collection](docs/Configuration.md#Instruments)
available.

## Troubleshooting

1. `WebDriverException: Message: The browser appears to have exited before we could connect...`

    This error indicates that Firefox exited during startup (or was prevented from
    starting). There are many possible causes of this error:

    - If you are seeing this error for all browser spawn attempts check that:
      - Both selenium and Firefox are the appropriate versions. Run the following
      commands and check that the versions output match the required versions in
      `install.sh` and `environment.yaml`. If not, re-run the install script.

      ```sh
      cd firefox-bin/
      firefox --version
      ```

      and

      ```sh
        conda list selenium
      ```

      - If you are running in a headless environment (e.g. a remote server), ensure
      that all browsers have `display_mode` set to `"headless"` before
      launching.
    - If you are seeing this error randomly during crawls it can be caused by
    an overtaxed system, either memory or CPU usage. Try lowering the number of
    concurrent browsers.

2. In older versions of firefox (pre 74) the setting to enable extensions was called
    `extensions.legacy.enabled`. If you need to work with earlier firefox, update the
    setting name `extensions.experiments.enabled` in
    `openwpm/deploy_browsers/configure_firefox.py`.

3. Make sure your conda environment is activated (`conda activate openwpm`). You can see
    you environments and the activate one by running `conda env list` the active environment
    will have a `*` by it.

4. `make` / `gcc` may need to be installed in order to build the web extension.
    On Ubuntu, this is achieved with `apt-get install make`. On OSX the necessary
    packages are part of xcode: `xcode-select --install`.
5. On a very sparse operating system additional dependencies may need to be
    installed. See the [Dockerfile](Dockerfile) for more inspiration, or open
    an issue if you are still having problems.
6. If you see errors related to incompatible or non-existing python packages,
    try re-running the file with the environment variable
    `PYTHONNOUSERSITE` set. E.g., `PYTHONNOUSERSITE=True python demo.py`.
    If that fixes your issues, you are experiencing
    [issue 689](https://github.com/openwpm/OpenWPM/issues/689), which can be
    fixed by clearing your
    python [user site packages directory](https://www.python.org/dev/peps/pep-0370/),
    by prepending `PYTHONNOUSERSITE=True` to a specific command, or by setting
    the environment variable for the session (e.g., `export PYTHONNOUSERSITE=True`
    in bash). Please also add a comment to that issue to let us know you ran
    into this problem.

## Documentation

Further information is available at [OPENWPM's Documentation Page](https://openwpm.readthedocs.io).

## Advice for Measurement Researchers

OpenWPM is [often used](https://openwpm.readthedocs.io/Papers.html) for web
measurement research. We recommend the following for researchers using the tool:

**Use a versioned [release](https://github.com/openwpm/OpenWPM/releases).** We
aim to follow Firefox's release cadence, which is roughly once every four
weeks. If we happen to fall behind on checking in new releases, please file an
issue. Versions more than a few months out of date will use unsupported
versions of Firefox, which are likely to have known security
vulnerabilities. Versions less than v0.10.0 are from a previous architecture
and should not be used.

**Include the OpenWPM version number in your publication.** As of v0.10.0
OpenWPM pins all python, npm, and system dependencies. Including this
information alongside your work will allow other researchers to contextualize
the results, and can be helpful if future versions of OpenWPM have
instrumentation bugs that impact results.

## Developer instructions

If you want to contribute to OpenWPM have a look at our [CONTRIBUTING.md](./CONTRIBUTING.md)

## Instrumentation and Configuration

OpenWPM provides a breadth of configuration options which can be found
in [Configuration.md](docs/Configuration.md)
More detail on the output is available [below](#storage).

## Storage

OpenWPM distinguishes between two types of data, structured and unstructured.
Structured data is all data captured by the instrumentation or emitted by the platform.
Generally speaking all data you download is unstructured data.

For each of the data classes we offer a variety of storage providers, and you are encouraged
to implement your own, should the provided backends not be enough for you.

We have an outstanding issue to enable saving content generated by commands, such as
screenshots and page dumps to unstructured storage (see [#232](https://github.com/openwpm/OpenWPM/issues/232)).  
For now, they get saved to `manager_params.data_directory`.

### Local Storage

For storing structured data locally we offer two StorageProviders:

- The SQLiteStorageProvider which writes all data into a SQLite database
  - This is the recommended approach for getting started as the data is easily explorable
- The LocalArrowProvider which stores the data into Parquet files.
  - This method integrates well with NumPy/Pandas
  - It might be harder to ad-hoc process

For storing unstructured data locally we also offer two solutions:

- The LevelDBProvider which stores all data into a LevelDB
  - This is the recommended approach
- The LocalGzipProvider that gzips and stores the files individually on disk
  - Please note that file systems usually don't like thousands of files in one folder
  - Use with care or for single site visits

### Remote storage

When running in the cloud, saving records to disk is not a reasonable thing to do.
So we offer a remote StorageProviders for S3 (See [#823](https://github.com/openwpm/OpenWPM/issues/823)) and GCP.
Currently, all remote StorageProviders write to the respective object storage service (S3/GCS).
The structured providers use the Parquet format.

**NOTE:** The Parquet and SQL schemas should be kept in sync except
output-specific columns (e.g., `instance_id` in the Parquet output). You can compare
the two schemas by running
`diff -y openwpm/storage/schema.sql openwpm/storage/parquet_schema.py`.

## Docker Deployment for OpenWPM

OpenWPM can be run in a Docker container. This is similar to running OpenWPM in
a virtual machine, only with less overhead.

### Building the Docker Container

**Step 1:** install Docker on your system. Most Linux distributions have Docker
in their repositories. It can also be installed from
[docker.com](https://www.docker.com/). For Ubuntu you can use:
`sudo apt-get install docker.io`

You can test the installation with: `sudo docker run hello-world`

_Note,_ in order to run Docker without root privileges, add your user to the
`docker` group (`sudo usermod -a -G docker $USER`). You will have to
logout-login for the change to take effect, and possibly also restart the
Docker service.

**Step 2:** to build the image, run the following command from a terminal
within the root OpenWPM directory:

```bash
    docker build -f Dockerfile -t openwpm .
```

After a few minutes, the container is ready to use.

### Running Measurements from inside the Container

You can run the demo measurement from inside the container, as follows:

First of all, you need to give the container permissions on your local
X-server. You can do this by running: `xhost +local:docker`

Then you can run the demo script using:

```bash
    mkdir -p docker-volume && docker run -v $PWD/docker-volume:/opt/OpenWPM/datadir \
    -e DISPLAY=$DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix --shm-size=2g \
    -it --init openwpm
```

**Note:** the `--shm-size=2g` parameter is required, as it increases the
amount of shared memory available to Firefox. Without this parameter you can
expect Firefox to crash on 20-30% of sites.

This command uses _bind-mounts_ to share scripts and output between the
container and host, as explained below (note the paths in the command assume
it's being run from the root OpenWPM directory):

- `run` starts the `openwpm` container and executes the
    `python /opt/OpenWPM/demo.py` command.

- `-v` binds a directory on the host (`$PWD/docker-volume`) to a
    directory in the container (`/opt/OpenWPM/datadir`). Binding allows the script's
    output to be saved on the host (`./docker-volume`), and also allows
    you to pass inputs to the docker container (if necessary). We first create
    the `docker-volume` direction (if it doesn't exist), as docker will
    otherwise create it with root permissions.

- The `-it` option states the command is to be run interactively (use
    `-d` for detached mode).

- The demo scripts runs instances of Firefox that are not headless. As such,
    this command requires a connection to the host display server. If you are
    running headless crawls you can remove the following options:
    `-e DISPLAY=$DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix`.

Alternatively, it is possible to run jobs as the user _openwpm_ in the container
too, but this might cause problems with none headless browers. It is therefore
only recommended for headless crawls.

### MacOS GUI applications in Docker

**Requirements**: Install XQuartz by following [these instructions](https://stackoverflow.com/a/47309184).

Given properly installed prerequisites (including a reboot), the helper script
`run-on-osx-via-docker.sh` in the project root folder can be used to facilitate
working with Docker in Mac OSX.

To open a bash session within the environment:

```bash
./run-on-osx-via-docker.sh /bin/bash
```

Or, run commands directly:

```bash
./run-on-osx-via-docker.sh python demo.py
./run-on-osx-via-docker.sh python -m test.manual_test
./run-on-osx-via-docker.sh python -m pytest
./run-on-osx-via-docker.sh python -m pytest -vv -s
```

## Citation

If you use OpenWPM in your research, please cite our CCS 2016 [publication](http://randomwalker.info/publications/OpenWPM_1_million_site_tracking_measurement.pdf)
on the infrastructure. You can use the following BibTeX.

```bibtex
@inproceedings{englehardt2016census,
    author    = "Steven Englehardt and Arvind Narayanan",
    title     = "{Online tracking: A 1-million-site measurement and analysis}",
    booktitle = {Proceedings of ACM CCS 2016},
    year      = "2016",
}
```

OpenWPM has been used in over [75 studies](https://github.com/openwpm/studies/blob/main/studies.md).

## License

OpenWPM is licensed under GNU GPLv3. Additional code has been included from
[FourthParty](https://github.com/fourthparty/fourthparty) and
[Privacy Badger](https://github.com/EFForg/privacybadgerfirefox), both of which
are licensed GPLv3+.
