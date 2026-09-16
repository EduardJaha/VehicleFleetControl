# Authentication security review and deployment guide

Reviewed and verified 2026-09-16. This is focused authentication hardening, not a claim that the entire application or deployment has undergone a penetration test.

## Existing capabilities and concrete findings

The application already had administrator-created accounts, bcrypt password hashing, expiring signed JWTs, six default roles and granular permissions, tenant sessions/company memberships, active-user checks, `session_version` revocation, administrator password reset, self-service password change, `password_reset_required`, `last_login_at`, audit logs, and English/Albanian localization. These have been reused, not rebuilt. No User columns, role definitions, or permissions were added.

| Finding before changes | Implemented change |
| --- | --- |
| Browser JWT persisted in localStorage; logout only removed that browser copy | HttpOnly cookie session; server logout invalidates all of the user's sessions |
| Password-change-required was a UI warning, not a general API restriction | Backend allowlist and frontend redirect/block until password change |
| No login throttling; inactive-login errors distinguished account state | Shared database-backed IP/account and IP-only budgets; generic localized errors |
| Minimum eight-character new passwords; bcrypt truncation affected long UTF-8 input | Shared minimum 12; new hashes use bcrypt_sha256, existing bcrypt hashes remain valid |
| Production settings did not enforce secure cookies or exact HTTPS origins; no application security-header policy | Fail-closed production validation, CSRF origin checks, frontend/API headers |
| Legacy membership fallback could accept explicitly disabled membership rows | An existing inactive membership can no longer fall through to the legacy role |
| Administration could reuse loaded related records without explicit company checks; user serialization could report the acting administrator's role | Explicit company predicates for managed users/related scopes and correct target-user role output |
| Activation/deactivation and role changes were only generic user updates | Specific audit events; existing password/reset/revocation audits retained |

The existing public company-onboarding UI and `/auth/register` endpoint are retained under the requested compatibility exception. No new self-registration, invitations, email recovery, social login, refresh tokens, MFA, or device-management workflow was introduced. Ordinary account management remains Administrator → Users → Add User → credentials delivered by the administrator. Deployments requiring no public company onboarding must restrict that existing route separately.

## Session storage and transmission

FastAPI signs the existing JWT with user ID, selected company ID, expiration and session version. Login, company switch and password change return `{ "user": ... }`; the JWT is **not** returned in JSON. It is sent in `Set-Cookie` with:

- Name `vehicle_fleet_control_session` (configurable).
- `HttpOnly`, `Path=/`, host-only (no Domain attribute).
- `Secure` required in production; configurable off for local HTTP development.
- `SameSite=Lax` by default, optionally `Strict`.
- Max-Age matching `ACCESS_TOKEN_EXPIRE_MINUTES`.

Frontend requests, including protected file downloads, use `credentials: "include"`. JavaScript cannot read the cookie. The old localStorage token key is removed on startup and is never read/transmitted. Language and other non-sensitive preferences are retained.

This fits the existing client-side Next.js → FastAPI architecture without a proxy/BFF, refresh-token store or new authentication framework. Expiration remains the existing configurable 480-minute default; use a shorter deployment value if appropriate to the fleet's work sessions. Expiration requires another login; there is no sliding renewal or refresh endpoint. JWT validation now explicitly requires `exp`.

The backend still accepts already-issued Bearer JWTs for rolling compatibility, with the same expiry, user-state, company and revocation checks. The web application has no Bearer/localStorage path, and login no longer issues a JSON access token. External clients relying on that old JSON contract must migrate to a cookie jar and trusted Origin header. This is an intentional login-response contract change.

Logout increments the existing global `session_version` atomically and deletes the cookie: **all sessions for that user, across companies/devices, are revoked**. This avoids introducing a per-device session registry. Administrator reset/revoke/deactivation and the user's password change also invalidate older sessions. Password change issues a replacement cookie for the current browser. Deactivated users cannot log in or access protected endpoints; reactivation does not revive old cookies.

Any API 401 clears browser authentication state and expires the cookie. Normal page content is unmounted on logout. Company switching performs a full navigation after receiving the new cookie so previous-company page state and requests are discarded. A failed logout request is shown as an error, not reported as a successful revocation.

## CSRF, CORS, HTTPS and headers

Cookie-authenticated unsafe methods require an exact trusted Origin, or a valid trusted Referer origin when Origin is absent. Missing, `null`, malformed, and untrusted origins fail closed. Login and existing registration enforce this even before a cookie exists, preventing login CSRF. SameSite adds defense in depth. Header-only legacy clients without browser-origin headers remain supported; a present untrusted Origin is rejected regardless of credential type.

`CORS_ORIGINS` must contain complete origins (scheme, host, optional port), with no paths, trailing slash, credentials, query, fragment or wildcard. Production requires nonempty HTTPS origins and credentialed CORS only for those origins. Include the actual frontend origin even when using a same-origin reverse proxy.

Deploy frontend and API **same-site**: for example `https://app.example.com` and `https://api.example.com`, or one HTTPS origin with an API reverse proxy. Unrelated frontend/API sites will not work with Lax/Strict cookies; do not solve this by weakening the cookie to `None`. Locally use matching hosts on both sides, preferably `http://localhost:3000` and `http://localhost:8000`; mixing `127.0.0.1` and `localhost` is cross-site despite both being loopback.

Both applications configure `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy` disabling camera/microphone/geolocation, and a deliberately limited CSP: `frame-ancestors 'none'; object-src 'none'; base-uri 'self'`. This is **not a comprehensive script/XSS CSP**; script/style restrictions need a separate Next.js nonce/hash rollout. Production build and browser tests verify the current policy does not break normal flows. Next's powered-by header is disabled. API responses use `Cache-Control: private, no-store`.

FastAPI emits HSTS only in production when the normalized request scheme is HTTPS. It does not directly trust an arbitrary `X-Forwarded-Proto`. Configure the reverse proxy/Uvicorn to accept forwarded scheme/client IP only from known proxy addresses, keep the API inaccessible around that proxy, and redirect HTTP to HTTPS there. Configure HSTS on the HTTPS frontend/edge too; Next configuration does not unconditionally emit it on HTTP. The API policy includes subdomains, so every covered subdomain must support HTTPS. TLS/proxy deployment was not installed or externally tested by this change.

## Password and login protections

New, temporary and replacement passwords require 12–128 characters centrally in the existing DTOs. Unicode, passphrases, password managers and paste are supported without arbitrary composition/rotation rules. Existing short passwords continue to authenticate until changed. New hashes use Passlib's bcrypt_sha256 scheme so characters beyond bcrypt's byte limit affect verification; legacy bcrypt hashes still verify unchanged. Existing hashes are not rewritten by migration.

Unknown email, wrong password, inactive user and inactive membership return the same public invalid-credentials response. Unknown identities perform dummy password verification rather than returning immediately. This reduces an obvious timing difference; it is not a guarantee of identical network timing.

Login uses atomic fixed-window reservations in `LoginRateLimits`, shared across application workers using the same database:

- IP + normalized-email bucket: default five attempts per 900 seconds; further requests receive localized HTTP 429 and `Retry-After` until the original window ends.
- IP-only bucket: ten times that limit (default 50) across all accounts, including successful requests, to bound account spraying and throttle-row allocation.
- Successful authentication clears the pair bucket and updates existing `last_login_at`; it does not clear the broader IP budget.
- Retrying never extends the fixed cooldown. No User is permanently disabled or account-wide locked; there is no new administrator unlock control to manage.
- Keys are HMACs using the configured secret; raw IP/email combinations are not stored in this table. Existing security audits may retain IP addresses. Stale throttle rows are cleaned during login.
- A known user's repeated-failure threshold produces one audit event per window, avoiding per-failure noise. General successful login and account-management actions remain audited without passwords, cookie values or JWTs.

Limits are a practical application defense, not a distributed bot/DDoS solution. Users behind a shared NAT share the IP budget; tune it via the base limit/window and add appropriate edge controls for the deployment. Do not trust arbitrary client-supplied forwarding headers for the throttle identity. Administrator reset endpoints retain `users.manage` authorization and CSRF protection; no unauthenticated reset endpoint was added.

## Administrator and user workflows

All administrator actions below use the existing `users.manage` permission, checked by the backend. Current company comes from authenticated tenant context, not a posted `company_id`. Other-company user mutations return not found; related driver/location/department/cost-center IDs are company-checked. Role definitions remain global under the existing model; grants are company-scoped.

| Action | UI / behavior |
| --- | --- |
| Create User | Administration → Users → Add User; enter full name, email, initial password, role, preferred language and active status. Require password change defaults on. The password is cleared after successful creation and is never returned. Deliver it securely outside the app. |
| Assign/change Role | Select an active role at creation or Edit User and save. Existing scoped grants/permissions remain authoritative; no duplicate permission model is added. |
| Reset Password | Edit User, enter a Temporary Password and select Reset Password. The UI requires a change at next login and revokes existing sessions. Deliver the temporary password securely; it is not retrievable afterward. |
| Deactivate | Edit User, turn Active off, save. Login and protected API access are blocked on subsequent requests and old sessions revoked. |
| Reactivate | Edit User, turn Active on, save. The user signs in again; existing password remains unless reset separately. |
| Revoke Sessions | Edit User and select Force logout (the existing revoke-sessions action). All sessions for that user become invalid; next protected request requires login. |
| Inspect last login | Existing Last Login column now uses localized date/time formatting; no new tracking field is needed. |

A temporary-password user can log in but is sent to `/account/password`; the API allows only `/auth/me`, language preference, password change and logout until the flag is cleared. Direct navigation/API calls do not bypass it. Change Password requires current password, new password and matching frontend confirmation. The server verifies current password and shared new-password policy, clears the flag, revokes old sessions, writes an audit, and issues the replacement cookie. Administrators can deliberately opt out of mandatory change through the existing policy controls.

## Configuration and rollout

Use the placeholders in `backend/.env.example`; never deploy the placeholder secret. Root `.env.example` supplies Compose overrides for local development. Compose remains a development setup, not a production deployment manifest.

| Setting | Value / requirement |
| --- | --- |
| `ENVIRONMENT` | `production` enables strict production checks; local default `development` |
| `DEBUG` | Must be `false` in production |
| `JWT_SECRET_KEY` | Stable cryptographically random secret, at least 32 characters; defaults/placeholders and obviously repetitive values rejected in production. Do not generate a new key on each startup. |
| `JWT_ALGORITHM` | Existing `HS256` default retained |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Positive duration, default `480`; no refresh setting |
| `AUTH_COOKIE_NAME` | Default `vehicle_fleet_control_session`; keep stable across replicas |
| `COOKIE_SECURE` | Must be `true` in production; `false` for local HTTP only |
| `COOKIE_SAMESITE` | `lax` default or `strict` |
| `CORS_ORIGINS` | Comma-separated exact trusted frontend origins, HTTPS only in production |
| `LOGIN_RATE_LIMIT_ATTEMPTS` | Positive pair budget, default `5`; IP budget is ten times this |
| `LOGIN_RATE_LIMIT_WINDOW_SECONDS` | Positive fixed window/cooldown, default `900` |
| `NEXT_PUBLIC_API_URL` | Frontend's same-site API URL, including `/api/v1`; set at frontend build time |
| `DATABASE_URL` | Existing shared application database; throttle implementation supports SQLite and PostgreSQL |

Migration **`20260915_0021_authentication_hardening.py`** follows `20260915_0020`. It adds only `LoginRateLimits` with `KeyHash` (64-character PK), `AttemptCount`, `WindowStartedAt`, `UpdatedAt`, and an UpdatedAt index. It does not alter Users, passwords, activation, roles, memberships, permissions or session versions. Revision downgrade removes only throttle data; earlier revisions have their own downgrade restrictions.

Back up the operational database using the deployment's established process, then, from `backend/` with its configured environment and virtualenv:

```sh
alembic current
alembic upgrade head
alembic current
```

Apply this migration before starting the new backend, then deploy backend/frontend together. Browser users with only the former localStorage credential must sign in once after the update. Old signed tokens remain cryptographically valid until normal expiry/revocation, but are no longer read by the browser. No operational database was migrated during this task. Fresh and populated SQLite upgrades were tested; SQL uses PostgreSQL-compatible upserts/schema, but no live PostgreSQL server was available for verification. Other dialects, including the repository's unconfigured SQL Server target, are not supported by this throttle implementation.

## Verification and changed files

See [the verification record and complete file inventory](authentication-security-verification.md) for exact commands, results and test limitations.

Future enhancements, deliberately excluded: optional MFA, self-service email recovery, SSO, a comprehensive nonce/hash CSP, and independent deployment penetration testing. These are not prerequisites added to the current administrator-managed account workflow.
