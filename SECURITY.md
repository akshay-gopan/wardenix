# Security Policy

Wardenix is a security tool, so we take its own security seriously.

## Reporting a vulnerability

Please report suspected vulnerabilities privately (e.g. via a GitHub security
advisory on this repository) rather than opening a public issue. Include a
description, affected version/commit, and reproduction steps. We aim to
acknowledge reports promptly and coordinate a fix and disclosure.

## Security model

Wardenix is a runtime governance gateway for AI agents. Its design, trust
boundaries, and the threats it mitigates are documented in:

- [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) — STRIDE threat model and residual risks.
- [docs/HARDENING.md](docs/HARDENING.md) — production hardening checklist.

Key properties:

- **Fail-closed** — any policy, risk, or audit error denies the call.
- **Secure by default** — no matching policy ⇒ deny.
- **Independent authorization** — every tool call is evaluated on its own; tool
  list visibility is never a control.
- **Tamper-evident audit** — hash-chained, append-only, DB-trigger protected,
  verifiable via `/api/audit/verify`.
- **At-most-once dispatch** — approved operations dispatch at most once;
  indeterminate outcomes are surfaced as `UNKNOWN`, never silently retried.

## Supported versions

Wardenix is pre-1.0; security fixes target the latest `main`.
