# Wardenix — Production Hardening Guide

Wardenix ships with safe defaults for development. Before exposing it beyond a
trusted network, work through this checklist.

## 1. Secrets & configuration

| Setting | Dev default | Production |
|---|---|---|
| `WARDENIX_JWT_SECRET` | insecure placeholder | **32+ random bytes** (`openssl rand -hex 32`) |
| `POSTGRES_PASSWORD` | `wardenix_dev_pw_change_me` | strong, unique |
| `WARDENIX_BOOTSTRAP_ADMIN_PASSWORD` | `changeme-admin` | set once, then rotate via the dashboard |
| `WARDENIX_ACCESS_TOKEN_TTL_MINUTES` | 30 | keep short (15–30) |
| `WARDENIX_DEFAULT_ACTION` | `deny` | keep `deny` (secure by default) |
| `WARDENIX_SSRF_ALLOW_PRIVATE` | `true` | **`false`** unless upstreams are on private IPs you trust |
| `WARDENIX_SSRF_ALLOWLIST` | empty | explicit `host:port` list for HTTP upstreams |

Serve the dashboard and API **behind TLS** (terminate at nginx or a reverse
proxy in front of the `frontend` service). JWTs and API keys are bearer
credentials — they must never travel over plaintext HTTP.

## 2. Audit log integrity (defense in depth)

The append-only triggers protect every role, but for full separation of duties
run the application as a dedicated DB role that is granted only `INSERT, SELECT`
on `audit_events` (no `UPDATE`/`DELETE`/`TRUNCATE`), with migrations run by a
separate owner role. Verify the chain regularly:

```bash
curl -H "Authorization: Bearer <viewer-token>" https://host/api/audit/verify
# {"ok": true, "count": N}
```

A non-`ok` result with a `first_bad_seq` means records were altered at the DB
level — investigate immediately.

## 3. Upstream MCP server isolation

Upstream servers run with the gateway's privileges when launched via `stdio`.
Treat each upstream as a separate trust domain:

- **Run each stdio upstream in its own container** with a non-root user, a
  read-only root filesystem, dropped Linux capabilities (`cap_drop: [ALL]`),
  `no-new-privileges`, and CPU/memory limits.
- **Scope the environment** — pass only the variables the server needs (Wardenix
  stores `env` per server and never logs it).
- **Prefer HTTP upstreams behind the SSRF allowlist** for anything network-reachable.
- For filesystem servers, confine them to a bind-mounted directory; do not grant
  access to host paths or secrets.

Wardenix governs *which* tool calls reach an upstream and records them; it does
not replace sandboxing the upstream process itself.

## 4. Network posture

- Expose only the dashboard (`:8080`) and, to agents, the gateway `/mcp`
  endpoint. The Control Plane API and WebSocket should sit behind the same
  authenticated origin.
- Put a rate limiter / WAF in front for public deployments — Wardenix caps
  per-agent concurrency and payload size but does not itself rate-limit auth
  attempts.
- Restrict Postgres to the internal network; never expose `:5432` publicly
  (the dev compose maps it for convenience — remove that mapping in prod).

## 5. Operational

- **Approvals** have a TTL (`WARDENIX_APPROVAL_TTL_SECONDS`); stale ones are
  swept to `expired` on startup and on demand.
- **`UNKNOWN` executions** (gateway crash or upstream timeout after dispatch) are
  never auto-retried. Reconcile them manually: confirm whether the side effect
  occurred, then issue a fresh request if needed. On restart, `EXECUTING` rows
  become `UNKNOWN` and un-dispatched `AUTHORIZED` rows become `NOT_DISPATCHED`.
- Back up the Postgres volume; the audit chain and approval history live there.
