# Preventive maintenance programs

Manage reusable schedules at `/maintenance/programs`. Each company owns its
programs, tasks, rules, effective vehicle assignments, reminder history, audit
entries and notifications. Existing manual reminders keep their original
identity, status, deadlines and Work Order links.

## Data model

- `ServiceProgram`: name, description, active/archive flags, company and timestamps.
- `ServiceProgramTask`: service type, title, description, positive kilometer and/or
  calendar-month intervals, OR/AND behavior, optional warning thresholds, priority,
  automatic Work Order flag, active flag and display order.
- `ServiceProgramRule`: program, selector, effective date, active flag and assigner.
- `VehicleServiceProgram`: the effective governing assignment, including rule,
  assigner, assignment time, effective date and a frozen odometer baseline.
- `ServiceProgramReminder`: task/assignment/vehicle references, source completed
  Service, date/km deadlines, active flag, resolution history and optional Work Order.

Scheduling never inserts placeholder Services. Consequently, program reminders
cannot inflate service history, maintenance frequency or cost reporting. Legacy
placeholder Services are preserved, but `Status=Reminder` rows are not accepted as
completed service history by the new scheduler.

A partial unique index enforces one active assignment per company/vehicle and one
active reminder per company/assignment/task. One Work Order belongs to at most one
program reminder. A program cannot contain multiple tasks with the same service
type (case-insensitive validation), including inactive tasks. Reactivate an existing
task instead. A task with reminder history can change its title, intervals and
warnings, but retains its service type; use a new task for a different service type.

## Assignment precedence

The first matching level wins:

1. Explicit Vehicle.
2. Exact Brand and Model.
3. Brand, with all models.
4. Department.
5. Location.
6. Vehicle Category.
7. Fuel Type.

Within a level, the newest rule wins; ID breaks timestamp ties. Re-selecting an
older explicit rule moves it ahead of competing rules for that selector. Repeating
an already winning assignment is idempotent. Brand, model, category and fuel names
match case-insensitively. Vehicle, Location and Department selectors use IDs.

Department is obtained from the Driver on an active/overdue Vehicle Assignment.
When no such assignment exists, legacy Drivers assigned to the Vehicle supply
its department. This follows the repository's current model: Vehicles do not have
a direct Department column.

Inactive, archived and not-yet-effective programs/rules do not compete. Removing,
archiving or disabling a winner allows the next matching rule to govern. The old
assignment and reminders are retained as inactive history. Restoring the same
rule/effective date preserves its original mileage baseline, preventing deadline
drift. Archived Vehicles have no active program reminders.

## Scheduling and completion

For each active task, the latest non-archived completed Service with the matching
service type supplies the date baseline. The latest such Service with a recorded
odometer supplies the mileage baseline. Future Services are ignored until their
service date. Without history, use the rule's effective date and the odometer
frozen when the assignment is created. Missing mileage is never treated as zero;
it is filled from the first later recorded vehicle odometer.

Month arithmetic uses calendar months, clamping the day to month end (January 31
plus one month is February 28 or 29). A task may use km only, months only, or both:

- `whichever_occurs_first=true`: the most urgent threshold determines status.
- `false`: both thresholds must reach the corresponding warning/due/overdue state.
- A threshold exactly at its deadline is Due; past it is Overdue.
- Null warnings mean no advance warning for that dimension.
- An unknown odometer is Needs Baseline unless an OR date threshold independently
  establishes that the task is Due or Overdue.

Creation, editing, archival and restoration of Services synchronize the program
within the same database transaction. Service completion resolves the previous
program reminder and produces a successor based on the new completed Service.
An edit to the same baseline Service updates the existing reminder's deadlines.
Manual reminders, including those for the same service type, are untouched.

New Service forms default to the applicable program schedule. Operators can
explicitly keep a manual next-service reminder. Editing an existing manual
reminder retains its manual schedule by default. Program Work Order completion
requires a matching Service record and does not create a generic manual reminder.

When enabled on a task, an automatic Work Order is created with each new reminder,
including initial assignment and after completion. Its title, description,
priority and expected date come from the task. Repeated synchronization does not
create additional orders. Superseding/resolving reminders cancels untouched Open
or Assigned generated orders. Started work or orders with costs/clock history are
retained for an operator to finish; no labor or stock history is deleted.

Vehicle, Driver and Vehicle Assignment changes also synchronize relevant schedules.
Date-only transitions, future rules and future-dated history are evaluated by the
existing periodic command:

```sh
cd backend
python -m app.scripts.generate_notifications
```

Run it daily or more frequently using the deployment's scheduler. This change
integrates with that command; it does not install an OS scheduler. The UI's
“Synchronize schedules” action provides an immediate authorized refresh. Read
endpoints calculate reminder urgency at request time and do not create Work Orders.

## API and permissions

Base: `/api/v1/maintenance/programs`

| Method/path | Operation |
| --- | --- |
| GET / | Programs, optionally `include_archived=true` |
| POST / | Create program |
| GET /{id} | Program and tasks |
| PUT /{id} | Update program |
| DELETE /{id}, PUT /{id}/archive | Archive program |
| POST /{id}/restore | Restore program |
| GET, POST /{id}/tasks | List/create tasks |
| PUT, DELETE /{id}/tasks/{task_id} | Update/deactivate task |
| GET, POST /rules | List/create selector rules |
| PUT, DELETE /rules/{id} | Update/deactivate rule |
| GET /assignments | Effective assignments; `include_history=true` for history |
| GET /options | Tenant-owned selector choices |
| GET /compliance | Fleet compliance; optional `vehicle_id` |
| POST /synchronize | Refresh schedules within the caller's maintenance scope |

Reads require `maintenance.view`; mutations use the existing
`maintenance.assign_work_order` permission. Configuring automatic Work Orders
also requires `maintenance.create_work_order`. Shared program/task changes and
group rules require unrestricted maintenance scope; individual assignment,
compliance and synchronization respect Location, Department and own-record scope.
All company filtering is enforced by tenant-aware sessions, and linked selection
IDs are validated before writing. Program configuration grants authority for
subsequent automatic Work Order creation by the scheduler.

Task compliance = `(Current + Due Soon) / all active tasks × 100`. Due today,
Overdue and Needs Baseline are not compliant. Tasks Due Soon / Due are combined
for the displayed warning count. Program coverage is a separate percentage of
non-archived vehicles with a governing program. No tasks/vehicles produces a null
percentage (displayed as “—”), rather than claiming 100% compliance.

## Bulk compatibility

Preferred request:

```json
{
  "entity_type": "Vehicles",
  "action": "assign_service_program",
  "ids": [1, 2],
  "options": {"program_id": 7}
}
```

A numeric `value` is also accepted as a program ID. `created_ids` now contains real
`VehicleServiceProgram` assignment IDs. The Vehicle bulk UI selects an existing
program rather than accepting a generic service label.

Legacy name/service-type requests create or reuse a real one-task program. Legacy
`interval_days` must be a positive multiple of 30 and is converted to calendar
months; the default 180 days becomes six calendar months. Nonrepresentable day
intervals return a localized validation error instead of silently rounding.
Existing named programs are reused without modifying their tasks. Historical
placeholder reminders are not guessed or retroactively converted.

## Migration and verification

Migration `20260914_0018` creates the five tables and indexes without modifying
legacy Service, Work Order or Vehicle rows. It supports both populated databases
and the historical empty-database bootstrap. Back up before upgrading; downgrade
removes program tables and their history while preserving original fleet records.

Run `alembic upgrade head`, `python -m app.scripts.validate_company_migration`,
`pytest -q`, and frontend `npm run lint`, `npm run build`, `npm run i18n:check`,
`npm run i18n:scan`, and `npm run test:e2e`. English and Albanian UI/error keys,
parameterized Audit Logs and deduplicated notification keys are included.
