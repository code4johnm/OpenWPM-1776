#!/bin/bash

# Reap Playwright/Chromium/Xvfb leftovers so the GitHub Actions step can
# finish. Hosted runners wait for the job cgroup; orphaned browsers after a
# BrowserManager crash otherwise sit until timeout-minutes and cancel the
# job after pytest has already printed results.
reap_browser_leftovers() {
    pkill -f '/ms-playwright/' || true
    pkill -f 'headless_shell' || true
    pkill -f 'playwright/driver' || true
    pkill -f '/usr/bin/Xvfb' || true
}

if [ -n "$GROUP" ] && [ -n "$SPLITS" ]; then
    # CI mode: use pytest-split for optimal distribution
    python -m pytest --splits "$SPLITS" --group "$GROUP" --splitting-algorithm least_duration --cov=openwpm --junit-xml=junit-report.xml --cov-report=xml -s -v --durations=10
else
    # Local mode: run specific tests or all
    python -m pytest --cov=openwpm --junit-xml=junit-report.xml --cov-report=xml $TESTS -s -v --durations=10
fi
code=$?
reap_browser_leftovers
exit "$code"
