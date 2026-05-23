# ADR 0018: Local Bearer Token Authentication (No OAuth/RBAC)

Date: 2025-06-10
Status: Accepted

## Context

PersonAgent is designed as a single-user local desktop application. The backend runs on `localhost` and is not exposed to the internet. Complex auth (OAuth, RBAC, multi-tenancy) would add friction without security benefit.

## Decision

Use a **local-only bearer token** stored in a file with restricted permissions.

**Token sources**
1. `PERSONAGENT_LOCAL_AUTH_TOKEN` env var (highest priority).
2. `PERSONAGENT_LOCAL_AUTH_TOKEN_PATH` file (default: `~/.cache/personagent/local_auth_token`).
3. `.env` file in the project root.

**Electron desktop**
- Preload exposes `auth.getHeaders()` which reads the token from the main process and injects it into every API request as `Authorization: Bearer <token>` and `X-PersonAgent-Client: desktop-electron`.

**Backend**
- `install_local_auth()` in `interfaces/api/security.py` validates the token on every request.
- CORS origins are restricted to `http://localhost:5176` (dev) and `file://` (packaged).

**Out of scope**
- OAuth, SSO, session cookies, refresh tokens, RBAC roles, multi-user workspaces.

## Consequences

- **Easier**: zero login flow for the primary use case; token rotation is a single file write.
- **Harder**: no user identity for audit logs; sharing the token file grants full access.
- **Risk**: if the backend is accidentally exposed to the network, the token is the only barrier. Mitigation: bind to `127.0.0.1`, deny non-local origins.
- **Explicitly documented as current state**, not a permanent design. May be superseded by a proper auth subsystem if multi-user or remote usage becomes a requirement.

## Alternatives Considered

- **OAuth2 with PKCE**: rejected because there is no identity provider and the app is offline-first.
- **No auth at all**: rejected because it would allow any local process to mutate the user's workspace.

## Validation

- `@backend/tests/test_api_security.py` verifies token rejection, CORS blocking, and env-file parsing.
