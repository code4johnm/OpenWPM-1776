"""Locate the Playwright-bundled Chromium binary.

Pin: Playwright 1.62.0 ships Chromium 151.0.7922.34 (Chrome for Testing
line). Install with ``python -m playwright install chromium``.
"""

from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_LOCAL_BROWSERS = _REPO_ROOT / "ms-playwright"


def ensure_browsers_path() -> None:
    """Prefer a repo-local Playwright browser cache when present."""
    if "PLAYWRIGHT_BROWSERS_PATH" in os.environ:
        return
    if _LOCAL_BROWSERS.exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(_LOCAL_BROWSERS)


def chromium_executable() -> Path:
    """Return the Playwright Chromium executable path.

    Raises RuntimeError if the binary is missing.
    """
    ensure_browsers_path()
    override = os.environ.get("OPENWPM_CHROMIUM_EXECUTABLE")
    if override:
        path = Path(override)
        if not path.is_file():
            raise RuntimeError(
                "No file found at OPENWPM_CHROMIUM_EXECUTABLE="
                f"{override}. Install Chromium with: python -m playwright install chromium"
            )
        return path

    roots = []
    env_root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env_root:
        roots.append(Path(env_root))
    roots.append(_LOCAL_BROWSERS)
    roots.append(Path.home() / ".cache" / "ms-playwright")

    candidates = []
    for root in roots:
        if not root.exists():
            continue
        candidates.extend(root.glob("chromium-*/chrome-linux*/chrome"))
        candidates.extend(root.glob("chromium-*/chrome-linux*/Chromium"))
        candidates.extend(root.glob("chromium-*/chrome-mac*/Chromium"))
        candidates.extend(root.glob("chromium-*/chrome-win*/chrome.exe"))

    for exe in candidates:
        if exe.is_file():
            return exe

    raise RuntimeError(
        "Chromium binary not found. Run `python -m playwright install chromium` "
        "(see README). CI/Docker should fail closed if this happens."
    )


def require_chromium() -> Path:
    """Alias used by smoke tests and pytest session setup."""
    return chromium_executable()


def chromium_version() -> str:
    """Best-effort Chromium version string for crawl metadata."""
    exe = chromium_executable()
    import subprocess

    try:
        out = subprocess.check_output([str(exe), "--version"], text=True).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(
            "Failed to execute Chromium --version. "
            "Run `python -m playwright install chromium`."
        ) from exc
    # Typical: "Chromium 151.0.7922.34" or "Google Chrome 151.0.7922.34"
    parts = out.split()
    return parts[-1] if parts else out
