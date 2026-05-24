---
title: Authentication (Django OIDC + Nuxt session cookies)
description: Generated documentation for changes to authentication.
aiAssistedGeneration: true
---


## Overview

- **Identity provider**: Cloudflare Access OIDC (Django is the relying party via Authlib).
- **Session owner**: Django (`sessionid` cookie on the API host).
- **Public API**: `/v2/…` — `IsAuthenticatedOrReadOnly` (unchanged).
- **Console session**: `GET /auth/session/` (staff checks in Nuxt use `user.is_staff`).
- **Nuxt console**: `/console` on the site origin (gated by `NUXT_PUBLIC_ADMIN_ENABLED`); `auth-console` middleware + `console` layout enforce staff session client-side; login via `/auth/login/?next=…` pointing at the console URL.
- **Future staff-only write APIs**: add under `/v2/…` with `SessionAuthentication` + `IsAdminUser` as needed (no separate `/v2/admin/` prefix).

## Auth endpoints (`/auth/`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/auth/login/?next=<url>` | Start OIDC; `next` must match allowlisted origin |
| GET | `/auth/callback/` | OIDC callback (also `/auth/oauth-auth/` legacy) |
| POST | `/auth/logout/` | End Django session (CSRF required) |
| GET | `/auth/session/` | Current session JSON |
| GET | `/auth/csrf/` | CSRF token JSON + cookie |

## Environment variables

| Variable | Purpose |
|----------|---------|
| `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_CONFIGURATION` | Cloudflare Access OIDC client |
| `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS` | Cross-origin Nuxt origins |
| `AUTH_ALLOWED_NEXT_ORIGINS` | Optional override for post-login `next` URLs (comma-separated origins) |
| `NUXT_SITE_ORIGIN` | Django: prefix for relative `next` paths under `/console` (default `http://localhost:3000`) |
| `SESSION_COOKIE_SAMESITE`, `CSRF_COOKIE_SAMESITE` | Override cookie policy (prod default: `None` with `Secure`) |

## Cloudflare Access (operational)

- Register OIDC redirect URI: `https://api.wheretheystand.nz/auth/callback/` (and `http://localhost:8000/auth/callback/` for local).
- To avoid **double login**, prefer path-based Access policies: e.g. protect `/admin/` at the edge, allow `/auth/*` for OIDC and session without a second interactive Access gate on console API calls—or rely on Django OIDC only.
- Django logout does not clear the Cloudflare Access browser session; users may re-authenticate silently on next OIDC login.

## Local development

- Use **`http://localhost:3000`** and **`http://localhost:8000`** consistently (not `127.0.0.1` for one and `localhost` for the other).
- `DEBUG=True` keeps `SameSite=Lax` on HTTP; production uses `SameSite=None` + `Secure`.
