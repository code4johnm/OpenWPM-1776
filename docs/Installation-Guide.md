# Installation Guide

**Document Version:** 1.0  
**OpenWPM Version:** 0.34.0  
**Last Updated:** 2026-05-27T02:47:30Z  
**Workspace:** OpenWPM-1776

---

## 1. Overview and Security Notes

This guide provides detailed, step-by-step instructions for installing OpenWPM in a secure and reproducible manner.

**Security Warning:** OpenWPM installs a privileged WebExtension that requires a specially built Firefox with add-on security features disabled. This extension has extremely broad capabilities. Install and run OpenWPM **only on dedicated measurement infrastructure**, never on machines containing personal data, credentials, or used for general browsing.

After installation, review [Security-and-Privacy.md](Security-and-Privacy.md) before running any crawls.

---

## 2. System Requirements

### Supported Platforms

| Platform       | Status          | Notes |
|----------------|-----------------|-------|
| Ubuntu 22.04 / 24.04 | Primary (CI-tested) | Recommended |
| Other Linux    | Community       | Usually works via conda |
| macOS (Intel/Apple Silicon) | Community | Xcode tools required; XQuartz for Docker GUI |
| Windows        | Not supported   | See [#503](https://github.com/openwpm/OpenWPM/issues/503) |

### Minimum Resources (per browser instance, rough)

- 2–4 GB RAM (more for heavy JavaScript instrumentation + many tabs)
- 5–10 GB disk (profiles, artifacts, logs grow quickly)
- For Docker: `--shm-size=2g` or higher (critical)

### Required Tools

- Bash-compatible shell
- Conda (Miniconda recommended)
- Internet access (for dependency downloads and Firefox binary)
- `make`, `gcc` / build tools (for native Node modules during extension build)

---

## 3. Standard Installation (Recommended)

### Step 1: Clone the Repository

```bash
git clone https://github.com/openwpm/OpenWPM.git
cd OpenWPM
```

It is strongly recommended to check out a specific release tag rather than `master` for research use:

```bash
git checkout v0.34.0   # or the latest release tag
```

### Step 2: Run the Installation Script

```bash
./install.sh
```

The script will:
1. Create or overwrite the `openwpm` conda environment
2. Install the pinned dependencies from `environment.yaml`
3. Download and install a compatible unbranded Firefox build into `firefox-bin/`
4. Build the OpenWPM WebExtension (`openwpm.xpi`)

**Important flags:**

- `./install.sh --skip-create` — Skip conda environment creation (useful inside Docker or when you have already created the env).

On macOS, the script selects the `osx-64` conda subdir.

### Step 3: Activate the Environment

```bash
conda activate openwpm
```

Verify the installation:

```bash
python -c "from openwpm.config import BrowserParams, ManagerParams; print('OpenWPM OK')"
firefox --version   # should show the version installed by install-firefox.sh
```

### Step 4: (Optional but Recommended) Install Pre-commit Hooks

```bash
pre-commit install
```

This runs linting, formatting, and basic checks on every commit.

---

## 4. Post-Installation Verification

Run the demo in headless mode (safest for servers):

```bash
python demo.py --headless
```

Check that output was produced:

```bash
ls -la datadir/
```

You should see at least a SQLite database or Parquet files (depending on demo version) and a log file.

---

## 5. Platform-Specific Notes

### Ubuntu / Debian

```bash
sudo apt-get update
sudo apt-get install -y make gcc xvfb   # xvfb only needed for display_mode=xvfb
```

### macOS

1. Install Xcode command-line tools:
   ```bash
   xcode-select --install
   ```
2. For Docker GUI applications, install [XQuartz](https://www.xquartz.org/) and follow the instructions in `scripts/run-on-osx-via-docker.sh`.

Apple Silicon users may encounter occasional architecture-related issues with some native packages; the project welcomes fixes.

### Docker (Alternative / Recommended for Reproducibility)

See [Deployment.md](Deployment.md) for full Docker instructions. The container image produced by the root `Dockerfile` contains a complete, isolated OpenWPM environment.

---

## 6. Updating OpenWPM

1. Pull the latest changes or check out the desired release tag.
2. Re-run `./install.sh` (it will recreate the conda environment with the new pins).
3. Rebuild the extension if you modified anything under `Extension/`:
   ```bash
   ./scripts/build-extension.sh
   ```

**Never** edit `environment.yaml` directly. Use `scripts/environment-unpinned*.yaml` + `./scripts/repin.sh` (see [Development.md](Development.md)).

---

## 7. Troubleshooting Installation

| Symptom                                      | Likely Cause / Fix |
|----------------------------------------------|--------------------|
| `conda: command not found`                   | Install Miniconda/Anaconda first |
| Extension build fails with missing `make`/`gcc` | Install build-essential (Linux) or Xcode tools (macOS) |
| Firefox version mismatch errors              | Re-run `./install.sh` after cleaning `firefox-bin/` |
| `WebDriverException` on first run            | Usually missing display handling — use `headless` mode or install xvfb |
| Permission errors on `datadir/`              | Ensure the user running the crawl owns the output directory |
| Slow / hanging conda solve                   | Use `mamba` instead of `conda` for faster environment creation (experimental) |

Full troubleshooting: [Troubleshooting.md](Troubleshooting.md).

---

## 8. Uninstallation / Cleanup

```bash
conda env remove -n openwpm
rm -rf firefox-bin/
rm -rf datadir/   # if you want to delete previous crawl outputs
```

The repository itself can be safely deleted after uninstallation.

---

## 9. Next Steps

After successful installation:

1. Read [Security-and-Privacy.md](Security-and-Privacy.md)
2. Read [Usage-Guide.md](Usage-Guide.md)
3. Review [Configuration.md](Configuration.md) for instrumentation options
4. Run `python -m test.manual_test --help` for interactive debugging

**Questions?** Join the Matrix channel or open a GitHub Discussion (for non-security topics).

---

*This guide is part of the OpenWPM professional documentation set. Contributions and corrections are welcome.*