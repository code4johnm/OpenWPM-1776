#!/bin/bash

# Subprocess coverage leaves multiprocess children alive after the suite
# (coverage.process_startup + os._exit). That kept groups 4/5/7 open until
# timeout-minutes after pytest had already printed results. CI=true also
# gates test/conftest.py so it cannot put this variable back.
unset COVERAGE_PROCESS_START

if [ -n "$GROUP" ] && [ -n "$SPLITS" ]; then
    pytest_args=(--splits "$SPLITS" --group "$GROUP" --splitting-algorithm least_duration --cov=openwpm --junit-xml=junit-report.xml --cov-report=xml -s -v --durations=10)
else
    # Local mode: run specific tests or all
    # shellcheck disable=SC2206
    pytest_args=(--cov=openwpm --junit-xml=junit-report.xml --cov-report=xml $TESTS -s -v --durations=10)
fi

# Run pytest in the foreground so the job exit code is pytest's real 0/1.
# Do not SIGTERM pytest after junit-report.xml appears — that was exit 143
# on Tests and linting #61 groups 4/5/7.
python -m pytest "${pytest_args[@]}"
code=$?

# After pytest has exited, drain leftover browsers/display so the hosted
# runner cgroup can finish. This is hygiene after the real status is known,
# not a substitute for session.quit() / conftest child reap.
pkill -P $$ || true

exit "$code"
