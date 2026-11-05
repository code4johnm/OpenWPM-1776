# Threat model

## Contents

- [Boundaries](#boundaries)
- [Abuse](#abuse)

## Boundaries

Operator, dashboard process, kube-apiserver, and the crawl job. The link list is a host file. The job uses the measurement image when it exists.

## Abuse

The page is unauthenticated on port 8770. A reachable dashboard can submit a crawl job. The existing server is the control. This packaging does not add a network crawl client.
