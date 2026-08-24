#!/usr/bin/env bash
# Install Playwright's pinned Chromium (Chrome for Testing line).
# Playwright 1.62.0 → Chromium 151.0.7922.34
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$ROOT/ms-playwright}"
mkdir -p "$PLAYWRIGHT_BROWSERS_PATH"

if ! python -c "import playwright" >/dev/null 2>&1; then
  echo "Error: playwright is not installed in this Python. Activate the openwpm conda env first."
  exit 1
fi

echo "Installing Playwright Chromium into $PLAYWRIGHT_BROWSERS_PATH"
python -m playwright install chromium

python - <<'PY'
from openwpm.browser_bin import chromium_executable, chromium_version
exe = chromium_executable()
print("Chromium ready:", exe)
print("Version:", chromium_version())
PY
