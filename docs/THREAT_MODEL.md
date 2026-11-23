# Wardenix — Threat Model

This document describes the threats Wardenix is designed to mitigate, the trust
boundaries in the system, and the residual risks an operator should understand.
It uses a STRIDE framing. Wardenix is a **security control point**, so its own
integrity and fail-closed behavior are paramount.

## System & trust boundaries

```
 Agents ──(1)──▶ Gateway Data Plane ──(2)──▶ Upstream MCP servers
                     │
 Dashboard ─(3)─▶ Control Plane (REST/WS) ─▶ PostgreSQL
```

1. **Agent ↔ Gateway** — agents are semi-trusted. They authenticate with an API
   key but may be buggy, confused, or compromised. This is the primary boundary
   Wardenix polices.
2. **Gateway ↔ Upstream** — upstream servers are operator-registered and run with
   the gateway's outbound privileges. They are a trust boundary for SSRF and for
   the data they return (treated as untrusted content).
3. **User ↔ Control Plane** — dashboard users are authenticated (JWT) and
   role-scoped (admin / approver / viewer).

## STRIDE

| Category | Threat | Mitigation | Residual risk |
|---|---|---|---|
| **Spoofing** | Forged agent identity | API keys stored as salted SHA-256 (pepper = app secret); revocable; identity bound into every approval permit | A leaked key impersonates that agent until rotated |
| | Forged dashboard user | Argon2 password hashes; short-lived JWT; role in token re-checked against DB each request | JWT valid until expiry if stolen (keep TTL short, use TLS) |
| **Tampering** | Edit/delete audit records | Append-only repository; DB role guidance (INSERT/SELECT only); `BEFORE UPDATE/DELETE` **and** `BEFORE TRUNCATE` triggers reject mutation for every role; hash chain detects any change | A DB superuser could disable triggers — detectable via chain verification |
| | Replay an approval permit | Single-use permit; atomic `UPDATE … WHERE status='approved' RETURNING`; `executions.permit_id` unique | — |
| | Modify args on an approved retry | Permit bound to canonical `args_hash`; modified args → new pending | — |
| **Repudiation** | "I didn't approve that" | Approvals attributed to the JWT user (`decided_by`); decision + outcome events hash-chained with `correlation_id` | — |
| **Information disclosure** | Secrets logged in audit / shown in approvals | Key-pattern redaction before any write or display; upstream `env`/`headers` never serialized to API or logs | Secret values not matching key patterns may pass through — tune `redaction` |
| | SSRF to internal infra / cloud metadata | HTTP upstream allowlist; DNS resolved and checked; metadata/link-local/multicast/reserved always blocked; private/loopback blocked unless explicitly allowed | Upstreams are operator-controlled; a malicious admin is out of scope |
| **Denial of service** | ReDoS via policy regex | `google-re2` (linear time); save-time pattern validation; length caps | — |
| | Oversized payloads / hung upstream | Arg size + depth caps; per-call timeout (`anyio.fail_after`); per-agent concurrency cap; circuit breaker opens after repeated failures | A flood of distinct agents can still load the gateway — front with a rate limiter |
| **Elevation of privilege** | Call a hidden or denied tool directly | **Independent per-call authorization**; `tools/list` filtering is UX only; precedence DENY > REQUIRE_APPROVAL > ALLOW > default DENY | — |
| | Path traversal / symlink escape via tool args | Path-typed args canonicalized and confined (where applied); real isolation is the upstream sandbox | FS safety ultimately depends on upstream server sandboxing |
| **Fail-open** | DB/engine error lets a call through un-audited | Global **fail-closed**: any evaluation or audit-write error ⇒ DENY; the upstream is never reached if the decision cannot be recorded | — |

## Non-goals / out of scope

- **Malicious operators / DB superusers.** Wardenix protects against compromised
  *agents* and provides tamper-*evidence* against record modification; it does not
  defend against an administrator with direct database or host access.
- **Upstream server sandboxing.** Wardenix governs *which* calls reach an upstream;
  it does not sandbox the upstream itself. See [HARDENING.md](HARDENING.md).
- **Exactly-once execution.** Wardenix guarantees **at-most-once dispatch**, not
  exactly-once execution; indeterminate outcomes are surfaced as `UNKNOWN` for
  manual reconciliation.
