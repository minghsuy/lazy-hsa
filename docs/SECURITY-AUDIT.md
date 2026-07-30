# Public metadata audit

Audit date: 2026-07-30

The public release tree previously included an unrelated machine-heartbeat
example. It described a particular development environment rather than the
lazy-hsa package. The helper and its service definitions were removed before
release.

The audit covered the current tree and all reachable Git history:

- GitHub reported zero open secret-scanning alerts.
- A targeted scan found zero known provider-token, API-key, or private-key
  signatures in the current tree or reachable history.
- Environment metadata was present in the current helper and two historical
  commits. No credential value was identified.

History is not rewritten for metadata-only exposure because rewriting public
commits would invalidate existing clones and commit references without revoking
a credential. If a credential is ever found, rotate it privately first and
assess history remediation without copying the value into a public issue.

`scripts/check-public-metadata.py` now rejects environment-specific repository
targets, absolute user-home paths, direct SSH machine endpoints, and
non-example email addresses. The default test suite runs this guard so it cannot
become an optional release check.
