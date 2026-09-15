# Inspection templates and schedules

Apply `alembic upgrade head` from `backend` before starting the updated API. Revision `20260914_0019` adds four tenant-owned configuration tables and nullable snapshot fields. It does not populate or update historical inspection results. Existing system Admin and Fleet Manager roles receive `inspection_templates.manage`; custom roles retain their existing permissions.

Open `/admin/inspection-templates`. Create a template, add items, assign it, and add schedules as needed. The name presets include Daily, Pre-Trip, Post-Trip, Vehicle Return, Weekly Safety, Monthly, Winter and Electric Vehicle inspections. Presets provide names and inspection types; administrators supply the checklist and policies appropriate to their fleet. Winter and EV templates use the existing General inspection type. Duplicating copies template content and items into independent records, without copying assignments or schedules. Archive/restore retains the configuration. Reorder uses accessible up/down buttons.

## Selection

Selection is per company, vehicle and inspection type. Only active assignments to active, unarchived templates compete:

1. Specific Vehicle
2. Brand/Model (an exact model wins over a brand-wide rule)
3. Vehicle Category
4. Fuel Type
5. Location
6. Department

Within the same specificity, higher numeric priority wins; a tie uses the lowest assignment ID. Names match case-insensitively. Location and Department selectors store tenant-validated IDs. Department comes from the supplied handover/inspection driver; otherwise it comes from the active vehicle assignment, falling back to the legacy assigned driver. Vehicles without a matching template retain the existing checklist workflow.

## Inspection lifecycle

The Inspections page resolves and previews the applicable template. **Begin inspection** sends `POST /api/v1/inspections` with an empty `items` list. The server resolves again and copies the active items in display order, including all failure flags, names, descriptions, codes, categories and ordering. The saved template identity and name also remain available even after configuration changes. An optional `template_id` is a selection check; stale or unassigned IDs are rejected.

On the inspection detail page, save results and photo evidence, then complete the inspection. `PUT /api/v1/inspections/{id}` submits every original item ID and name with statuses, comments and `photo_attachment_ids`; `complete: true` requires every required item to be checked and locks the result. Template-based updates never replace item rows or accept a different vehicle/type. Saved snapshots are not refreshed from configuration. Completion is separate from the derived Passed/Failed/Needs Review status. Legacy inspections keep their existing editing behavior.

Failed items require their configured comment/photo evidence before results are saved. Photos must be active image attachments belonging to the same tenant and inspection. Referenced evidence cannot be archived. All failures derive Failed; critical failures additionally raise generated work-order and notification priority to Critical. Each item may independently create an order, set the vehicle to Out of Use, and notify Admin/Fleet Manager/Mechanic recipients. Orders have a unique `InspectionItemId`, including archived/completed orders. Saving or retrying a failed item cannot create another order for it. A later passing result does not automatically clear Out of Use or close a work order; normal fleet/maintenance review remains necessary.

## Scheduling and handovers

Schedules use the template's assignments and precedence. The existing notification-generation job now generates required inspection snapshots and deduplicated notifications:

```sh
cd backend
python -m app.scripts.generate_notifications
```

Run that existing job regularly with the deployment's scheduler, for example hourly. The admin **Generate due inspections** button runs inspection generation on demand for the current company. The API is `POST /api/v1/inspection-templates/generate`. No new external scheduling service is required.

- Daily and Weekly periods are anchored to `start_date`, in UTC.
- Monthly periods use the start day, clamped to month-end without drifting (January 31 → February 28 → March 31).
- Every X days requires a positive `interval_days`.
- Mileage requires positive `interval_km`, a shared `baseline_odometer_km`, and a known vehicle odometer. It triggers at reached interval thresholds; missing mileage is not guessed. Use vehicle-specific templates when baselines differ.
- Calendar/mileage generation creates the latest due occurrence and retains one unfinished overdue requirement rather than generating an unlimited backlog. It does not manufacture past inspection results.
- Before check-out requires a completed, passed inspection for the current UTC day and handover cycle (since the last completed/cancelled assignment). Both `/checkout` and `/{id}/start` enforce this. A blocked checkout persists the required inspection and notification, returns HTTP 409 with the inspection IDs, and leaves the handover unchanged. A completed failed check gets a new snapshot for rechecking; the failed result remains intact.
- After return creates a required inspection per return assignment regardless of the optional return-inspection checkbox. Both `/{id}/return` and `/{id}/complete` trigger it. Every return has its own snapshot, even when a previous return inspection is unfinished. With no return schedule, the existing checkbox uses the resolved Return Inspection template if present, otherwise its legacy checklist.
- Returning a vehicle does not clear an Out of Use status set by a failed inspection.

A scheduled inspection begins when its requirement is generated, so its policy remains fixed from that moment. Editing, disabling, archiving or reassigning configuration affects future generation/selection; already-created inspections keep their saved content and can still be completed. Completion resolves the required notification. Calendar/occurrence uniqueness and per-item work-order uniqueness are enforced in the database, with savepoints for concurrent duplicate creation.

## API and permissions

Configuration routes live under `/api/v1/inspection-templates`: list/create, `/{id}` get/update, `/{id}/preview`, `/{id}/duplicate`, `/{id}/archive`, `/{id}/restore`, `/{id}/items` and `/{id}/items/{item_id}`, `/{id}/items/reorder`, `/{id}/assignments` and `/{id}/assignments/{assignment_id}`, `/{id}/schedules` and `/{id}/schedules/{schedule_id}`, and `/resolve?vehicle_id=...&inspection_type=...`.

Reads require `inspections.view`. Configuration mutations and manual schedule generation require unrestricted `inspection_templates.manage`. Inspection creation, archive and evidence upload use the existing inspection permissions. Users with `inspections.create` can fill their own template drafts (record creator or linked driver); `inspections.manage` can fill any draft in the tenant. Completed results stay locked for all roles. The new UI, validation messages and generated notifications support English and Albanian; company-authored names and historical snapshot text remain literal.

Tests cover configuration CRUD, ordering, precedence, snapshot retention, completion locks, failure requirements, work-order idempotency, unavailable status, periods/month boundaries, handover entry points, notifications, permissions, tenant isolation, migration preservation and browser workflows.
