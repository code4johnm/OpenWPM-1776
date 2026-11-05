# Operations

## Contents

- [Commands](#commands)
- [Incidents](#incidents)

## Commands

```bash
cd /mnt/5TB/git/github/OpenWPM-1776
python3 dashboard/server.py
```

The pod is launched from the k3s console card, which applies a copy of `deploy/openwpm-dashboard.yaml` at replicas 1. The file on disk stays at 0. Do not build `openwpm-1776:local` unless asked. Do not crawl a publisher site.

## Incidents

Stop the card or delete Job `openwpm-crawl`. The dashboard process and the crawl job are different. Stopping the page does not by itself delete a running job. The console Stop action does.
