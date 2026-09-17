# Driver and technician mobile workspace

The mobile experience lives in the existing Next.js application at `/mobile`. Drivers and mechanics are directed there after login; other roles retain the desktop dashboard. Technician accounts use the existing `mechanic` role and must be linked through `Technician.user_id` and `WorkOrderTechnician`. Driver accounts require a linked `Driver.user_id` and an assigned or scheduled vehicle.

## Deployment

1. Apply `alembic upgrade head` from `backend/` using the normal deployment migration process. Revision `20260917_0022` adds `MobileOperations` and the narrow `assignments.self_service`, `accidents.report`, and `maintenance.report_issue` grants for standard driver, admin and fleet manager roles. Custom roles need explicit grants.
2. Build and deploy the frontend normally. Serve it over HTTPS (localhost is sufficient for development). Keep `/sw.js` uncached by the CDN/proxy; the Next headers already request revalidation. Deploy public icons with the build.
3. Use the existing trusted-origin and credentialed-cookie configuration. No authentication tokens are placed in browser storage or service-worker messages.
4. When changing offline shell behavior, bump `VERSION` in `frontend/public/sw.js`. Updates wait for the user to activate them. Activation does not reload an open editor; reopening loads the new UI. Keep old hashed assets available during rolling deployments so open tabs can finish their work.

The manifest provides standalone installation, 192/512 px icons, a maskable icon, an Apple touch icon, theme colors and a mobile start URL. Safari installation uses Share → Add to Home Screen. Platform install prompts, storage persistence grants and eviction behavior remain browser-controlled.

## Driver and technician flows

The driver home shows linked vehicles, active assignments, reservations linked by assignment IDs, check-out/return, issue reporting, inspections, accident drafts, documents/warnings and notifications. Reservation `reserved_by` is free text; the mobile projection never treats a name match as proof of ownership. Check-out and return reuse the existing handover validators, inspection gates, mileage checks, audit and safety behavior. Issue reporting creates an ordinary work order.

Technician home groups linked open orders into critical, in-progress and waiting-for-parts counts. Each order links directly to its existing Parts, Labor (including clocks), Attachments or completion workflow. These mutations still require a connection and the existing granular permissions. The PWA does not queue inventory, labor or handover mutations.

## Offline inspections

Before leaving coverage, download an inspection for a selected vehicle, type and date. This reserves a server draft with a frozen template and original item IDs. Start entering results at any time offline. Existing scheduled inspection drafts appear on the mobile home and can also be downloaded from the inspection detail page; use those records for scheduled handover requirements. The default legacy checklist is frozen as well when prepared for offline use.

Downloading reserves **one inspection**, not an unrestricted template capable of creating arbitrary future server records. Download each required inspection/date while connected. Enter results, failure comments and photographs, then use **Save locally** or **Queue for synchronization**. Queuing freezes the submission while it retries. Local edits display an unsaved indicator and a browser unload guard.

The offline workspace opens on a cold offline reload through the service worker. It does not authenticate offline users to ordinary application pages. It displays only deliberately saved local work for the remembered user/company. The app automatically tries queued work on reconnect while the workspace is open, and every 30 seconds thereafter. It also provides a manual synchronization button. Closing the app pauses synchronization; this is not a background-sync or push-notification implementation.

Statuses: Local Draft → Pending Sync → Syncing → Synced. Connection/validation errors become Failed; version or retry-key mismatches become Conflict. Failed validation can be corrected before another attempt. Conflicts never trigger an automatic overwrite: compare the current server results, export the local results and download individual unsent photo previews before deliberately deleting the local copy. Resolve the server record through the existing authorized inspection workflow. Completed or archived inspections stay locked.

## Offline accidents and photos

Save the vehicle for offline accident reporting while online, or prepare an accident draft. The offline workspace can then create new reports with the saved vehicle/driver, date/time, location, description and photos. Severity and post-accident vehicle availability are explicit fields; availability defaults to false. Reconnection creates a normal Reported accident using the existing safety, audit and notification behavior. Offline payloads cannot set management transitions or financial values.

Photos are decoded and compressed locally to JPEG at 90% quality, at most 2560 px on the longest side, before entering IndexedDB. Original raw files and EXIF metadata are not retained. Input accepts JPEG/PNG/WebP up to 20 MiB and 60 megapixels; compressed photos must fit 8 MiB. Review previews for legibility; this workflow is not an archival-original evidence repository.

Each draft allows 20 photos; each owner allows 30 unsent drafts and 60 MiB of compressed photos. Persistent browser storage is requested, but it is not guaranteed. Uploads show byte progress and use exponential retry delays capped at five minutes. Every photo carries a stable operation key and content hash. A durable server receipt prevents duplicate attachment creation after a lost response. Uploaded blobs are removed locally as each receipt arrives; all remaining local payload/photo content is removed after the complete report is acknowledged. Synced receipt summaries are pruned after seven days when new work is reserved. Unsent work is never silently expired; drafts older than 30 days show a cleanup reminder. Users can export results, download photo previews or delete local copies.

## Security and consistency

- Cache Storage contains only the public offline shell, icons, manifest and `/_next/static/` build assets. API responses, authenticated HTML, attachments and login/session responses are never cached.
- IndexedDB stores only explicit drafts and compressed photos. Local storage holds language preferences, the current user/company IDs and one explicitly saved accident vehicle pack per owner. These are local device data, not encrypted storage; use a private device and protect the device account.
- Each request revalidates the cookie session. Synchronization carries expected actor/company IDs; the API rejects an account switch. Permissions and vehicle/record ownership are checked before returning retry receipts as well as before writes. Password-reset-required sessions remain subject to the existing backend gate.
- A 401 pauses submission and retains drafts for reauthentication. Explicit logout clears local drafts/photos and saved vehicle packs. Company switching preserves isolated drafts under their original owner, and removes their active selection. Local persistence refuses writes after an owner change. Other tabs observe owner changes.
- Web Locks serialize synchronization across tabs, and IndexedDB revisions prevent stale local editors from replacing another tab's saved copy. Current browsers with Web Locks are required for synchronization.
- `MobileOperations` keys are unique per company/user. A payload hash rejects key reuse with different data. Receipts, domain changes, audits and notifications commit together. Photo storage precedes the transaction as in the existing file pipeline; a failed database transaction can leave an unreferenced private storage object, but cannot commit a duplicate attachment receipt.
- Inspection synchronization performs a conditional update against `UpdatedAt` before recording results. Concurrent server edits, completion and archival return a conflict without replacing results.
- Receipt retention is intentionally durable; do not purge receipts without a defined retry horizon. Deleting old receipts could permit an old client to recreate a report.

## Verification

- `cd backend && .venv/bin/python -m pytest -q`
- `cd frontend && npm run lint && npm run i18n:check && npm run i18n:scan`
- `cd frontend && npm run test:e2e:mobile` builds production assets and runs the dedicated Chromium mobile suite on port 3102.
- `cd frontend && npm run test:e2e` runs the existing desktop/live-auth suite separately.

Mobile browser tests use a real production Next server, service worker, Cache Storage, IndexedDB, compression and offline network toggles. API responses are mocked. Backend tests separately exercise HTTP authorization/localization, ownership, receipt idempotency, conflicts, validation rollback, photo replay and fresh/historical migrations. Native Android/iOS installation and physical-camera behavior require device testing; automated metadata and service-worker tests do not replace those checks.

Verified on 2026-09-17: backend **415 passed, 5 skipped**; production mobile browser suite **8 passed**, including Chromium installability eligibility and cold offline startup; existing browser suite **23 passed initially, with the remaining fuel dropdown timing failure passing its focused retry**. Production build/type checks, lint, EN/SQ parity and hardcoded-string scan passed; existing lint/deprecation warnings remain. Migrations were exercised only against disposable databases. No operational database migration or deployment was performed.
