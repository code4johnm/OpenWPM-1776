# Architecture

## Contents

- [Process](#process)
- [Where the pod lives](#where-the-pod-lives)

## Process

`dashboard/server.py` is the crawl console. It edits the link list and starts or stops Job `openwpm-crawl`. It is the Python standard library. The measurement image `openwpm-1776:local` is separate and is not built by this packaging.

## Where the pod lives

The dashboard Deployment is `k38-dashboard/deploy/openwpm-dashboard.yaml`. This repository already has the crawl `Dockerfile`. A second pod manifest is not added.
