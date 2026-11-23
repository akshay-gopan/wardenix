# Changelog

All notable changes to Wardenix are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Wardenix uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — 2024-11-23

Initial MVP release. All six build phases complete.

### Added

- **MCP gateway** — man-in-the-middle MCP proxy (HTTP streamable + stdio bridge); identifies agents by `wrdx_` API key; forwards to real upstream MCP servers.
- **Policy engine** — deterministic ALLOW / REQUIRE_APPROVAL / DENY rules with glob matching on agent, server, tool, and risk band; precedence DENY > REQUIRE_APPROVAL > ALLOW > default-DENY; fail-closed on any evaluation error.
- **Risk assessor** — weighted signal scorer (destructive keywords, secret keys, broad file paths, network targets); four risk bands (low / medium / high / critical).
- **Approval workflow** — persisted one-time approval permits; at-most-once dispatch with atomic consume; execution state machine (AUTHORIZED → EXECUTING → SUCCEEDED / FAILED / UNKNOWN / NOT_DISPATCHED); restart-safe reconciliation on startup; stale-permit expiry.
- **Tamper-evident audit log** — SHA-256 hash-chained append-only event store; PostgreSQL triggers block UPDATE / DELETE / TRUNCATE; `/api/audit/verify` endpoint.
- **React dashboard** — JWT auth with RBAC (admin / approver / viewer); live WebSocket event feed; pages for overview, approvals queue, policies, audit log, MCP servers, agents, and users.
- **Security hardening** — SSRF guard (metadata / link-local always blocked); ReDoS-safe regex via `google-re2`; argument redaction; circuit breaker on upstream connections; `argon2` password hashing; SHA-256 + pepper API key storage.
- **Docs** — `docs/THREAT_MODEL.md`, `docs/HARDENING.md`, `SECURITY.md`.
- **Tests** — 79 backend pytest tests; 4 Playwright end-to-end tests.
- **Docker Compose** deployment (Postgres 16 + gateway + nginx-served dashboard).

[Unreleased]: https://github.com/akshay-gopan/wardenix/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/akshay-gopan/wardenix/releases/tag/v0.1.0
