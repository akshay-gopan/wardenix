# Wardenix — Runtime Security & Governance Platform for AI Agents

Wardenix is a **self-hosted security gateway** that sits between AI agents and
their [MCP](https://modelcontextprotocol.io) tools. Every tool call is
intercepted, risk-scored, evaluated against deterministic policy, optionally
gated behind **human approval**, and recorded in a **tamper-evident audit log**.

Free, open-source, and fully self-hostable — no external SaaS or API dependency.

> **Status:** all six MVP phases complete and tested (**79 backend tests + 4
> Playwright E2E**, verified in-browser): the MCP gateway, deterministic policy
> engine + risk scoring, the persisted approval workflow, the **React dashboard**
> with JWT auth + roles, and production hardening (circuit breaker, threat model,
> hardening guide).

## Why

AI agents call external tools with no checkpoint in between. A confused or
compromised agent can delete data, exfiltrate secrets, or spend money. Wardenix
is a **man-in-the-middle MCP proxy**: an MCP *server* to your agents, an MCP
*client* to the real tool servers — giving operators a deterministic control
point with policy, approvals, and an immutable record.

## Architecture (summary)

- **Data Plane** (`/mcp`): identify agent → resolve tool → risk assessment →
  policy enforcement (DENY > REQUIRE_APPROVAL > ALLOW > default DENY, fail-closed)
  → one-time approval permit → forward upstream → audit.
- **Control Plane** (`/api`, `/ws`): auth, policies/rules, approvals queue,
  audit + chain verification, server/agent management, live events.
- **Approvals**: persisted one-time permits (not held-open requests). Agent
  retries the identical call; a single-use permit is consumed atomically →
  **at-most-once dispatch**, replay- and tamper-resistant, restart-safe.
- **Audit**: hash-chained, append-only (DB trigger enforced), verifiable.

Stack: **Python / FastAPI / async SQLAlchemy / PostgreSQL** (backend),
**React / TypeScript / Tailwind / shadcn/ui** (dashboard), **Docker Compose**
(deployment), **Pytest + Playwright** (tests).

## Quick start (development)

```bash
cp .env.example .env            # then edit secrets
docker compose up --build       # starts postgres + gateway + dashboard
```

- **Dashboard:** <http://localhost:8080> (default login `admin@wardenix.local` / `changeme-admin`)
- **Gateway MCP endpoint (agents):** <http://localhost:8000/mcp>
- **API docs (OpenAPI):** <http://localhost:8000/docs>
- **Health:** `curl http://localhost:8000/readyz`

Point an MCP agent at the gateway with an API key (create one under **Agents** in
the dashboard):

```
Authorization: Bearer wrdx_...
```

stdio-only clients (Claude Desktop/Code) can use the bridge:

```bash
python -m bridge.stdio_bridge --url http://localhost:8000/mcp --api-key wrdx_...
```

## Testing

```bash
# Backend (needs the compose Postgres running): 79 tests
cd backend && pip install -e ".[dev]" && pytest
# End-to-end dashboard flow (Playwright, against the running stack):
cd e2e && npm install && npx playwright test
```

## Repository layout

```text
backend/           FastAPI gateway (MCP proxy + REST/WS control plane)
  app/             config, db, mcp_gateway, policy, risk, approvals, audit, api, security
  bridge/          stdio↔HTTP bridge with transparent approval retry
  alembic/         database migrations
  tests/           pytest suites
frontend/          React + TypeScript + Tailwind + shadcn/ui dashboard (nginx)
e2e/               Playwright end-to-end tests
docs/              THREAT_MODEL.md, HARDENING.md
docker-compose.yml postgres + gateway + frontend
```

## Security

Wardenix is fail-closed and secure-by-default. See [SECURITY.md](SECURITY.md),
[docs/THREAT_MODEL.md](docs/THREAT_MODEL.md), and
[docs/HARDENING.md](docs/HARDENING.md) before deploying beyond a trusted network.

## Contributing

Contributions are welcome! Read [CONTRIBUTING.md](CONTRIBUTING.md) for the dev setup, testing requirements, and PR process.

## License

Apache-2.0 — see [LICENSE](LICENSE).

