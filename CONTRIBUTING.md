# Contributing to Wardenix

Thank you for your interest in contributing! This document covers everything you need to get from zero to a merged pull request.

## Table of contents

- [Code of Conduct](#code-of-conduct)
- [How to contribute](#how-to-contribute)
- [Development setup](#development-setup)
- [Running the tests](#running-the-tests)
- [Code style](#code-style)
- [Pull request process](#pull-request-process)
- [Architecture overview](#architecture-overview)

---

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). By participating you agree to abide by its terms.

## How to contribute

- **Bug reports** — open a GitHub issue using the *Bug report* template. Include steps to reproduce and the relevant log output.
- **Feature requests** — open a GitHub issue using the *Feature request* template. Describe the problem you are solving, not just the solution.
- **Security issues** — do **not** open a public issue. Follow the process in [SECURITY.md](SECURITY.md).
- **Code changes** — fork the repo, create a branch, and open a pull request against `main`.

## Development setup

### Prerequisites

| Tool | Version |
|---|---|
| Docker + Docker Compose | v2+ |
| Python | 3.12+ |
| Node.js | 20+ |

### 1 — Clone and configure

```bash
git clone https://github.com/akshay-gopan/wardenix.git
cd wardenix
cp .env.example .env   # edit secrets if needed; defaults work for local dev
```

### 2 — Start PostgreSQL

```bash
docker compose up -d db
```

### 3 — Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

The gateway itself runs inside Docker (`docker compose up --build`), but unit tests run directly against the local venv + the compose Postgres.

### 4 — Frontend (optional, for UI work)

```bash
cd frontend
npm install
npm run dev    # Vite dev server at http://localhost:5173
```

### 5 — Full stack

```bash
docker compose up --build        # gateway :8000, dashboard :8080
```

Default admin login: `admin@wardenix.local` / `changeme-admin`

## Running the tests

### Backend unit + integration tests (79 tests)

Requires the compose Postgres to be running (`docker compose up -d db`).

```bash
cd backend
source .venv/bin/activate
pytest                   # all tests
pytest -k test_policy    # filter by name
pytest -x                # stop on first failure
```

**New code must include tests.** Bug fixes need a regression test; new features need unit tests for the new logic and, if they touch the gateway pipeline, an integration test.

### End-to-end (Playwright, 4 tests)

Requires the full stack running (`docker compose up -d --build`).

```bash
cd e2e
npm install
npx playwright test
npx playwright test --ui    # interactive mode
```

### Linting

```bash
cd backend
ruff check app bridge tests    # must be clean
ruff format --check .          # formatting check
```

```bash
cd frontend
npm run lint                   # oxlint
npm run build                  # TypeScript type-check + Vite build
```

## Code style

- **Python**: `ruff` enforces PEP 8 + isort + pyupgrade. Run `ruff check --fix` before committing.
- **TypeScript/React**: `oxlint` + `tsc --noEmit`. No `any` casts without a comment explaining why.
- **SQL / migrations**: add a new Alembic version file; never edit existing migration files.
- **No new comments explaining *what* the code does** — name things clearly instead. Comments are for *why*: hidden constraints, workarounds, non-obvious invariants.
- **No added abstractions beyond what the task requires.** Three similar lines are better than a premature helper.

## Pull request process

1. **Branch naming**: `feat/short-description`, `fix/short-description`, `docs/short-description`.
2. **Keep PRs small and focused.** One concern per PR is easier to review and faster to merge.
3. **All tests must pass** (CI runs `pytest` + `ruff check` automatically on every PR).
4. **Update docs** if your change affects behaviour documented in `README.md`, `docs/THREAT_MODEL.md`, or `docs/HARDENING.md`.
5. **Changelog**: add a line under `Unreleased` in [CHANGELOG.md](CHANGELOG.md).
6. A maintainer will review within a few days. Address review comments in new commits; do not force-push after a review has started.

## Architecture overview

```
agents (MCP clients)
        │  Bearer wrdx_...
        ▼
  ┌─────────────────────────────────────────┐
  │  Wardenix gateway  (:8000/mcp)          │
  │  identify → risk → policy → approve?    │
  │  → dispatch upstream → audit            │
  └─────────────────────────────────────────┘
        │  MCP client (per-call)
        ▼
  real MCP tool servers
```

Key components under `backend/app/`:

| Package | Responsibility |
|---|---|
| `mcp_gateway/` | MCP proxy: auth, pipeline orchestration, circuit breaker |
| `policy/` | Rule evaluation (DENY > REQUIRE_APPROVAL > ALLOW, fail-closed) |
| `risk/` | Weighted signal scorer → risk band |
| `approvals/` | Persisted one-time permits, at-most-once dispatch |
| `audit/` | Hash-chained append-only audit log |
| `security/` | SSRF guard, ReDoS-safe regex, redaction, JWT/argon2 |
| `api/` | REST control plane (FastAPI routers) + WebSocket hub |

See [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) and [docs/HARDENING.md](docs/HARDENING.md) for the security model.
