#!/bin/bash

# Subprocess coverage leaves multiprocess children alive after the suite
# (coverage.process_startup + os._exit). That is what kept groups 4/5/7
# open until timeout-minutes after pytest had already printed results.
unset COVERAGE_PROCESS_START

# Reap leftover workers so the GitHub Actions step can finish. Hosted
# runners wait for the job cgroup; orphaned BrowserManager/Chromium
# processes otherwise sit until the 30-minute job cancel.
reap_leftovers() {
    local pytest_pid="${1:-}"
    if [ -n "$pytest_pid" ]; then
        pkill -P "$pytest_pid" || true
    fi
    pkill -f '/ms-playwright/' || true
    pkill -f 'headless_shell' || true
    pkill -f 'playwright/driver' || true
    pkill -f '/usr/bin/Xvfb' || true
}

if [ -n "$GROUP" ] && [ -n "$SPLITS" ]; then
    pytest_args=(--splits "$SPLITS" --group "$GROUP" --splitting-algorithm least_duration --cov=openwpm --junit-xml=junit-report.xml --cov-report=xml -s -v --durations=10)
else
    # Local mode: run specific tests or all
    # shellcheck disable=SC2206
    pytest_args=(--cov=openwpm --junit-xml=junit-report.xml --cov-report=xml $TESTS -s -v --durations=10)
fi

python -m pytest "${pytest_args[@]}" &
pytest_pid=$!

# If pytest writes junit and then hangs on leftover workers, reap so it
# can exit with the real status instead of sitting until timeout-minutes.
while kill -0 "$pytest_pid" 2>/dev/null; do
    if [ -f junit-report.xml ]; then
        sleep 20
        if kill -0 "$pytest_pid" 2>/dev/null; then
            echo "pytest still running after junit-report.xml; reaping leftover workers"
            reap_leftovers "$pytest_pid"
            sleep 10
            if kill -0 "$pytest_pid" 2>/dev/null; then
                echo "pytest still hung after reap; sending SIGTERM"
                kill -TERM "$pytest_pid" || true
                sleep 5
                kill -KILL "$pytest_pid" || true
            fi
        fi
        break
    fi
    sleep 5
done

wait "$pytest_pid"
code=$?
reap_leftovers
exit "$code"
