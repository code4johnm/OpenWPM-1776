# Security requirements

## Contents

- [NIST SP 800-53](#nist-sp-800-53)
- [CISA SSDF](#cisa-ssdf)

## NIST SP 800-53

| Family | Present | Gap |
| --- | --- | --- |
| AC | The pod file stays at replicas 0 until the console launches it. | The page has no login. |
| AU | The server prints listen and job actions. | No remote audit store. |
| CM | The manifest is in the k38 repository. | The measurement image is local and unpinned here. |
| IA | None on the dashboard. | |
| SA | Dashboard dependencies are the standard library. | The crawl image is a separate, heavier supply chain. |
| SC | ClusterIP plus hostPort 8770 as already written in the k38 manifest. | No TLS. |
| SI | Link-list edits are the existing file write. | Job contents are not signed. |

## CISA SSDF

The requirement is to keep the dashboard as the control and not start a publisher crawl. Verification is importing the server module's configuration defaults by starting it only when intended. Response is to delete the Job. This is not an ATO.
