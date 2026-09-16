# Authentication hardening: verification and file inventory

Verified 2026-09-16. See [the security review and deployment guide](authentication-security.md) for existing capabilities, findings, session design, administrator workflows, migration and environment settings.

## Executed quality gates

Commands ran against the existing local dependencies. Backend tests use isolated SQLite databases, not operational data.

| Working directory | Exact command | Actual result |
| --- | --- | --- |
| Repository root | `PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/pytest -q backend/tests` | 383 passed, 29 warnings, 58.07 seconds |
| Repository root | `PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/pytest -q backend/tests/test_auth_security.py backend/tests/test_auth_security_edges.py` | Final focused rerun after adding the foreign-company creation input: 24 passed, 6 warnings, 26.13 seconds |
| `frontend/` | `npm run i18n:check` | Passed EN/SQ parity across four namespaces |
| `frontend/` | `npm run lint` | Passed, nine existing React hook dependency warnings |
| `frontend/` | `npm run build` | Passed compilation, type checking and generation of 38 static pages; same lint warnings |
| `frontend/` | `npm run test:e2e` | 24 Chromium tests passed, 21.2 seconds |
| Repository root | `git diff --check` | Passed |

Backend warnings concern dependency deprecations (Passlib/crypt, Starlette HTTPX, Alembic path separator) and existing SQLAlchemy reflection/table-cycle warnings. Frontend warnings remain in audit logs, fuel, maintenance, notifications, papers, reservations, vehicle edit and VehicleForm; unrelated refactoring was deliberately avoided. Browser execution also reports the harmless NO_COLOR/FORCE_COLOR conflict.

During implementation, an initial build exposed an obsolete language-provider token helper; that was removed. Initial backend failures were six migration assertions still expecting revision `20260915_0020`; they now expect `20260915_0021`, and the full suite passes. Initial browser runs required permission to bind local test ports; the final run completed with that permission. Reported results above are the final successful full runs, not those intermediate failures.

## Coverage and limitations

The two new backend test modules exercise valid/invalid/unknown/inactive login; generic EN/SQ responses; last-login/hash/no-secret output; cookie attributes; Origin/Referer failure modes; production settings/CORS/HSTS; expiration/revocation/deactivation; admin create/role/edit/reset/revoke; current-company listing and foreign-company denial; mandatory password change and current-password verification; long Unicode and legacy bcrypt passwords; shared minimum policy; atomic concurrent throttling/cooldown; and fresh/populated migration preservation. Existing permission, tenant-isolation and domain suites remain passing. The creation test additionally posts a foreign `company_id` and asserts that server-side company ownership wins.

Five new mocked browser tests exercise the administrator lifecycle, temporary-password routing/change/confirmation, session expiry, English/Albanian generic and cooldown errors, logout/preference preservation, and viewer/direct-navigation denial. Eighteen pre-existing browser tests continue to cover feature workflows with mocks.

One new browser test uses a **real isolated FastAPI process and in-memory SQLite**. Playwright forwards the browser-visible localhost API requests to its ephemeral port; no authentication responses are mocked. It checks cookie login, reload persistence, HttpOnly invisibility to JavaScript, SameSite=Lax metadata, absence of localStorage credentials, rejection of an untrusted-origin mutation, cookie deletion and rejection of a captured cookie after logout. The process is stopped after testing. It requires the backend's Unix virtualenv at `backend/.venv/bin/python`, installed backend dependencies, and Playwright Chromium. Production Secure/HSTS behavior is tested with HTTPS TestClient requests, not a deployed TLS proxy.

No live PostgreSQL database, production HTTPS proxy, deployed cross-subdomain browser configuration, distributed attack test, or full penetration test was run. PostgreSQL schema/upsert compatibility is implemented but not claimed as live integration verification. All browser tests use Chromium; other browser engines were not run. Production deployment and operational migration remain operator actions.

## Complete changed-file inventory

All paths below are repository-relative. New files are marked **new**. No dependencies, operational databases, secrets, uploads or generated build/test artifacts are included.

### Configuration and documentation

- `.env.example` — local Compose cookie/lifetime/throttle overrides.
- `AGENTS.md` — updated authentication contracts, migration head, configuration and testing guidance.
- `README.md` — security deployment guide link.
- `backend/.env.example` — documented security settings/placeholders.
- `docker-compose.yml` — pass local cookie/lifetime/throttle settings.
- `docs/authentication-security.md` — **new**, findings, design, administrator workflows and rollout guide.
- `docs/authentication-security-verification.md` — **new**, this verification record and complete inventory.

### Backend implementation

- `backend/alembic/versions/20260915_0021_authentication_hardening.py` — **new**, additive throttle table/index only.
- `backend/app/api/v1/endpoints/admin.py` — company-safe management, default temporary passwords, atomic revocation, action audits.
- `backend/app/api/v1/endpoints/auth.py` — cookie issuance, generic throttled login, password change, server logout and corrected user serialization.
- `backend/app/core/authorization.py` — use target user's role rather than actor context when serializing another user.
- `backend/app/core/config.py` — security settings and production validation.
- `backend/app/core/errors.py` — expire authentication cookie on 401.
- `backend/app/core/http_security.py` — **new**, CSRF checks and API headers.
- `backend/app/core/i18n.py` — English/Albanian security errors.
- `backend/app/core/security.py` — cookie/JWT validation, mandatory-change enforcement, bcrypt_sha256 with legacy support.
- `backend/app/main.py` — security middleware registration inside CORS.
- `backend/app/models.py` — LoginRateLimit model.
- `backend/app/schemas.py` — centralized password minimum, default require-change, user-only authentication response.
- `backend/app/services/login_security.py` — **new**, atomic shared fixed-window login budgets.

### Backend verification

- `backend/tests/auth_browser_server.py` — **new**, isolated real API for browser cookie testing.
- `backend/tests/test_auth_security.py` — **new**, authentication/admin lifecycle integration tests.
- `backend/tests/test_auth_security_edges.py` — **new**, CSRF/production/Unicode/tenant/concurrency/migration edge tests.
- `backend/tests/test_fuel_migration.py` — update expected migration head.
- `backend/tests/test_permissions.py` — expect unauthenticated 401 for inactive-user credentials.
- `backend/tests/test_program_migration.py` — update expected migration head.
- `backend/tests/test_supply_migration.py` — update expected migration head.

### Frontend implementation

- `frontend/app/account/password/page.tsx` — shared policy guidance, cookie-based result, confirmation/current-password flow.
- `frontend/app/admin/users/page.tsx` — temporary-password defaults, password clearing/validation, explicit role selection, localized last login.
- `frontend/app/login/page.tsx` — cookie auth and mandatory-change routing; new-password minimum.
- `frontend/next.config.mjs` — security headers and powered-by suppression.
- `frontend/src/components/i18n/LanguageProvider.tsx` — remove obsolete token dependency; delegate authenticated preference saves.
- `frontend/src/components/layout/AppShell.tsx` — mandatory-change gate, server logout/switch errors, tenant notification cleanup.
- `frontend/src/i18n/locales/en/errors.json` — English security errors.
- `frontend/src/i18n/locales/en/modules.json` — English password and security audit labels.
- `frontend/src/i18n/locales/sq/errors.json` — Albanian security errors.
- `frontend/src/i18n/locales/sq/modules.json` — Albanian password and security audit labels.
- `frontend/src/lib/api.ts` — credentialed requests; remove token helpers; consistent unauthorized handling.
- `frontend/src/lib/auth.tsx` — cookie restore/login/logout, old credential cleanup, language preservation and company reload.
- `frontend/src/lib/types.ts` — user-only auth response.

### Frontend verification

- `frontend/tests/auth-cookie-live.spec.ts` — **new**, real cookie/API browser test.
- `frontend/tests/auth-security.spec.ts` — **new**, five administrator/authentication browser flows.
- `frontend/tests/critical-workflows.spec.ts` — remove obsolete browser token setup/JSON token mocks.
- `frontend/tests/imports.spec.ts` — remove obsolete token setup.
- `frontend/tests/inspection-templates.spec.ts` — remove obsolete token setup.
- `frontend/tests/maintenance-programs.spec.ts` — remove obsolete token setup.
