#!/usr/bin/env bash
# Container entrypoint: ensure capture dir exists and is writable, then exec.
# Exit codes are preserved so Compose/Jobs can retry on failure.
# Do not swallow crawl errors. Do not delete datadir.
set -euo pipefail

DATADIR="${OPENWPM_DATADIR:-/opt/OpenWPM/datadir}"
mkdir -p "${DATADIR}"

if [[ ! -w "${DATADIR}" ]]; then
  echo "openwpm-entrypoint: ${DATADIR} is not writable by uid $(id -u)." >&2
  echo "openwpm-entrypoint: chown the host volume to 10001:10001 or run with a matching user." >&2
  exit 2
fi

if [[ "${OPENWPM_CHROMIUM_EXECUTABLE:-}" != "" ]]; then
  echo "openwpm-entrypoint: OPENWPM_CHROMIUM_EXECUTABLE is set; using an unpinned binary. Prefer the image Playwright Chromium." >&2
fi

# Default to image CMD when invoked with no arguments.
if [[ "$#" -eq 0 ]]; then
  set -- python -m openwpm.smoke --outdir "${DATADIR}"
fi

exec "$@"
