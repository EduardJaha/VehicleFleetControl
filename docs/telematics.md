# Telematics foundation

This is a provider-neutral backend and typed client foundation. **Geotab, Samsara, Motive and OEM APIs are not implemented or operational.** There is no hardware integration, polling job, live map or simulated telemetry. The generic adapter accepts the canonical contract from a trusted upstream translator. Real vendor adapters require documented APIs, credentials, authentication verification and provider-specific tests before registration.

## Storage and access

`IntegrationConnection` stores company, provider, status, credential reference, last successful receipt time, sanitized error code and strictly allowlisted settings. It starts `NotConfigured`; `Ready` means able to receive generic data, not proof of a working provider connection. `Disabled` stops ingestion. Provider discovery reports adapter availability separately from operational connectivity.

All ten models are tenant-owned. `ExternalVehicleMapping` binds a connection's external vehicle/device/VIN to a company vehicle. It detects duplicate external IDs, internal vehicles, devices and VINs within a connection, and VIN mismatches with internal vehicles. Mappings are immutable through this API to preserve history. Multiple connections can map the same internal vehicle; history preserves each source.

Administrative APIs (including location/history reads) require unrestricted `integrations.manage`, default admin only. Existing API keys cannot access these APIs. This conservative initial permission boundary prevents new location data from broadening existing vehicle visibility. Future dashboard access should add deliberate location permissions/scopes.

Migration: `20260918_0024`. Run `alembic upgrade head` from `backend/` during normal deployment. Tests use disposable databases; development/operational data is not automatically migrated by this feature.

## Configure a generic receiver

1. Provision a random signing secret of at least 32 characters in the API process environment, e.g. `TELEMATICS_FLEET_A`. Use a distinct secret per connection; never put values in settings, requests or source control.
2. `POST /api/v1/telematics/connections` with `{"provider":"generic","credentials_reference":"env:TELEMATICS_FLEET_A"}`. Only namespaced environment references are supported; an external secret manager can inject the value into the environment. References and secrets are excluded from responses/audits.
3. `PUT /telematics/connections/{id}` with `{"enabled":true}`. This fails closed if the adapter or secret is missing. This operation can also update the reference or settings, or disable reception. Omitted settings retain their current values; supplied setting fields merge with the current settings.
4. `POST /telematics/connections/{id}/mappings` with `vehicle_id`, `external_vehicle_id`, and optional `vin` / `external_device_id`. Company is derived from authentication.
5. Deliver signed batches to `/api/v1/telematics/webhooks/{id}`. Administrators can also submit canonical batches to `/telematics/connections/{id}/events` for testing/import. Both use the same transaction service.

Generic webhook headers:

- `X-VFC-Delivery`: bounded delivery identifier.
- `X-VFC-Signature`: `t=<unix_seconds>,v1=<hex_hmac_sha256>`.
- Sign the exact bytes: `timestamp + "." + connection_id + ":" + delivery_id + "." + body`, using the provisioned secret. Timestamp tolerance is 300 seconds. `services.webhooks.signature(secret, timestamp, f"{connection_id}:{delivery_id}", body)` implements this format.

Requests are limited to 1 MiB and 500 events. The company comes from the authenticated connection, never the body. Inactive companies/connections, bad signatures, future timestamps and unknown mappings are rejected. Vendor-specific webhook authentication must be implemented separately; this signature is the generic bridge contract, not any vendor's native protocol. Apply deployment request/rate limits at the existing reverse proxy as appropriate for the real feed.

Canonical batch example (replace time and identities with actual data):

```json
{"events":[{"kind":"location","external_event_id":"gps-message-123","external_vehicle_id":"provider-vehicle-42","occurred_at":"2026-09-18T10:00:00Z","latitude":41.3275,"longitude":19.8187,"speed_kph":0,"heading":90,"ignition":true,"idling":true}]}
```

`telematics_schemas.py` / OpenAPI define all event variants: location, completed trip (start=`occurred_at`, `ended_at`, distance and idle seconds), odometer/confidence, engine hours, fuel percentage, battery SOC percentage, DTC code/active state, and driver behavior/duration. Coordinates are WGS84 decimal degrees, speed km/h, distances km, durations seconds, heading degrees [0,360). All input timestamps must have a timezone and are normalized to UTC; history timestamps include UTC offsets. Nonfinite/out-of-range values are rejected. Canonical precision is seven decimal places for coordinates, four for confidence and three for other measurements; extra precision is truncated before storage/hashing, so confidence and mileage cannot be rounded upward. Adapters must convert vendor units and provide stable IDs and trustworthy confidence.

Event identity is `(company, connection, event kind, external_event_id)`. Identical retries are no-ops; reuse with different canonical content is a conflict. Batches are atomic, including mileage and audit changes. Events arriving late remain in history. Read projections sort by event time rather than receipt time. Trip events are immutable completed trips; partial vendor updates must be assembled in an adapter before ingestion.

## Odometer safeguards

Mappings default to synchronization disabled. `PUT /telematics/mappings/{id}/odometer-policy` with `{"enabled":true}` opts in. Readings only apply if confidence meets the connection threshold (default/minimum 0.9), age is within the configured window (default one hour, maximum one day), timestamp is newer than the last applied telematics reading, and mileage does not decrease. Vehicle mileage stores whole km, so fractional readings are floored.

Ordinary ORM changes to vehicle mileage (vehicle editing, services, fuel, handovers, imports) set `odometer_manual_override`. Automatic writes are then held until an administrator explicitly passes `release_manual_override:true` to the policy endpoint. An existing mileage baseline is preserved until opt-in and a valid reading. Bulk/raw SQL mileage writers must explicitly set the protection field because ORM flush hooks cannot observe them.

Each reading records `sync_result`: disabled, manual_override, low_confidence, stale, out_of_order, decreasing or applied. Applied readings and policy changes are audited in the same transaction. Provider timestamps/watermarks span connections, so a delayed reading from another provider cannot regress the latest applied reading. Automatic writes use locked vehicle rows and preserve existing maintenance synchronization/outbox hooks.

## Future dashboard services

- `GET /telematics/vehicles/{id}/summary`: last known location; online/offline/unknown inferred from latest non-trip event age (default 15 minutes); latest readings; diagnostic alerts; mileage and idling observed today.
- `GET /telematics/vehicles/{id}/events/{kind}`: history, including `trip`; descending event time with `before_id` cursor, default 50 / maximum 200 rows.
- `frontend/src/lib/telematics.ts`: typed authenticated wrappers. No map/UI or fabricated records are added.

Online is an age heuristic, not a live connection check. Old locations retain their timestamps. Active diagnostic alerts are the latest event per connection/code; clearing a DTC requires a newer inactive event. “Mileage today” is the observed first-to-last nondecreasing high-confidence odometer delta within the company timezone, not a fabricated midnight baseline. Missing/ambiguous multi-source data returns null. Idling sums complete trips entirely inside today from one source; it excludes partial/cross-midnight trips and returns null for overlapping trip intervals. These are explicitly partial observations, not guaranteed daily totals. A production feed should define retention, volume targets, trusted confidence, trip overlap handling and vendor polling/checkpointing before rollout.

## Verification

`tests/test_telematics.py` covers HTTP permissions/tenants, mapping conflicts, deduplication/changed retries, atomic rollback, timestamp ordering, mileage guards, manual protection, audits, normalized types and signed generic webhooks. Migration verification covers fresh creation and a populated previous revision. Tests use synthetic events and local signing credentials; they do not establish any commercial integration as operational.
