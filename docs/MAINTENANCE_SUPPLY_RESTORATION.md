# Maintenance supply restoration

Historical record of the 2026-09-13 restoration. Repository and database findings, the pre-edit plan, test counts, and migration state below describe that point in time; they are not current setup or verification guidance. Use `AGENTS.md` and `README.md` for current behavior and setup.

## Repository and database findings (2026-09-13)

Analysis preceded source edits. The checkout was clean at `95062b5`, on
`restore_complete_parts_vendors_etc`. `backend/app/schemas.py` is a module;
there is no `backend/app/schemas/` package.

The actual SQLite database was at `20260812_0016`. It contained all twelve
expanded-maintenance tables, each with zero rows: Vendors, PartCategories,
Parts, PartInventories, InventoryTransactions, PurchaseOrders,
PurchaseOrderItems, WorkOrderParts, Technicians, WorkOrderTechnicians,
LaborEntries, WorkOrderVendorCharges. Its foreign-key check was clean.
WorkOrders retained VendorId, ExternalVendorCost, TaxAmount and DiscountAmount;
VehicleServices retained VendorId. None were mapped by the current source.
PartCategories, PartInventories, WorkOrderTechnicians, LaborEntries and
WorkOrderVendorCharges had no CompanyId. Master uniqueness was global.
The separate Suppliers table belongs to vehicle acquisition and is preserved.

The no-op `20260810_0015` bridge recognizes the deleted deployed migration,
whose original revision created the twelve tables and extended WorkOrders and
VehicleServices. Current migrations had not restored their implementation.
The `expand_maintenance` branch points to `ff0b309`, with no expansion commit.
Searches of branches, reachable history and reflogs found no committed source.
`git fsck --no-reflogs --unreachable` found recoverable source in saved trees:

| Recovered artifact | Git object |
| --- | --- |
| Backend app tree | `186e46368dbc24462e58b685822aa12e3642e578` |
| Supply API | `693c0228f09e7b2aefb722fc0864224ff31abc95` |
| Supply service | `460510991cffb78135157d143231a30ac9396d85` |
| Supply schemas | `c4f04d42bdbcba00e3702fac2e611b290a61ad79` |
| Models | `90ff4f0858ced91e47e727a6f18306da7f1a9424` |
| Original migration | `d795623f88523322bb4c67b272904be03f4a5dda` |
| Original tests | `0015028d5e11b8e1f879e3d3213b39d5eddbfc7d` |
| Frontend app tree | `94918d3b212c25584e60190fddb2eb671aa3285b` |
| Frontend shared source | `f81c4fbf233d4e68248a73eb3bcd8c7c7d6b8907` |

The recovered frontend had `/parts`, `/vendors`, `/purchase-orders`, and
`/technicians`, plus Work Order details with read-only parts/labor sections.
It lacked the complete requested tabs, partial-receipt UI and live clocking.
Compiled `maintenance_supply`, its tests and the original migration are
remnants of these deleted modules. Source recovery made decompilation
unnecessary. Other inspection-template remnants concern a separate feature.

## Plan shared before edits

1. Recover reusable source, preserve the existing migration graph, and add an
   inspected, additive compatibility migration with complete tenant ownership.
2. Harden transactional supply/labor operations, permissions, audits,
   notifications, cost calculations, and Work Order/Service integration.
3. Add maintenance pages, editable Work Order tabs, reports, and bilingual UI.
4. Test fresh and populated legacy installations, run all requested checks,
   then migrate and inspect the repository database.

## Compatibility and accounting decisions

Physical historical names remain: ContactName is also exposed as
contact_person; SupplierId is also exposed as default_vendor_id; ActualHours
is also exposed as hours. Existing archive records, IDs, transaction history,
status strings and legacy authorization rows remain. Historical `Return`
ledger rows are readable as `Return from Work Order`.

The new migration freezes its own table definitions. It creates only missing
supply tables, derives missing tenant IDs from parents, validates cross-company
links, replaces global uniqueness with company uniqueness, and adds missing
columns/constraints. Partial historical migration fixtures without the core
fleet tables are left as fragments rather than inventing their dependencies.
Ambiguous shared category ownership or inconsistent existing tenant links
stops the migration transaction for explicit remediation; it is never guessed.
Downgrade is intentionally blocked instead of dropping business data.

Stock arithmetic uses guarded SQL updates, including reserved-stock checks.
Every stock movement, audit, notification, receipt/issue/return and cost update
commits together. Returns must reference an issued Work Order line and cannot
exceed its outstanding quantity. Closed/linked Work Orders lock their cost
lines. Active clocks prevent closure or technician deactivation. Sessions use
UTC; manual timed labor derives hours from timestamps.

A category with line items uses their server-calculated sum. Categories that
never had line items retain legacy manual subtotals. Completion copies the
entire total into a linked Service. Fleet reporting continues to count active
Services plus completed, unlinked Work Orders, so the Service link never adds
cost twice. Procurement spend reports received part value separately from
external charges and standalone services; issuing purchased stock does not
create additional procurement spend. Inventory value uses the catalog's
current unit cost, not FIFO or weighted-average valuation.

A SQLite online backup is retained under ignored `backend/data/backups/`.

## Delivered workflows

The maintenance navigation now includes Parts Catalog (with categories),
Parts Inventory, Vendors, Purchase Orders, Technicians and Supply Reports.
Work Order details include Overview, Parts, Labor, Vendor Charges,
Attachments and Timeline tabs. The UI follows the existing components and
supports English and Albanian, including notification and business-error text.

Inventory supports per-location available and reserved quantities, opening
balances, purchases, transfers, adjustments and write-offs. Work Order issue
and partial/full return operations preserve the movement ledger. Low-stock
notifications resolve on replenishment and reopen when stock falls again.
Purchase Orders support draft editing, submission, approval, ordering,
partial/final receipts, cancellation and archive/restore. Technician assignment
records estimated hours; labor supports manual entries and server-time clocking.
External charges can reference vendor invoices and Work Order attachments.

All ten requested reports are available at `/maintenance/reports`. Technician
utilization is actual hours divided by assigned estimated hours; it is not a
percentage of shift capacity. Inventory valuation uses current catalog cost.
Backend permission checks govern each mutation; PO approval is distinct from
creation, and receiving requires `inventory.manage`. Cost adjustments and
external charges require `maintenance.manage_costs`.

## Verification completed (2026-09-13)

| Check | Result |
| --- | --- |
| `.venv/bin/alembic upgrade head` (from `backend/`) | Repository database upgraded to `20260913_0017` |
| `.venv/bin/pytest` (from `backend/`) | 196 passed; 14 warnings |
| `npm run i18n:check` (from `frontend/`) | EN/SQ parity passed for all four namespaces |
| `npm run lint` (from `frontend/`) | Passed; nine existing React hook warnings in older modules |
| `npm run build` (from `frontend/`) | Passed, including all new maintenance routes |
| `git diff --check` | Passed |

The migration tests exercise fresh installation, a populated legacy schema,
a complete installation missing the supply tables, and ambiguous ownership
that must roll back without changing data or Alembic state. Workflow tests use
file-backed SQLite with foreign keys enabled and exercise concurrent issues
and receipts, partial returns, reservations, permissions, cross-tenant
references, clocks, audits, notifications, bilingual errors and accounting.
The €570 completed Work Order remains €570 in its linked Service and aggregate
maintenance reports. Active clocks also block generic archive/cancel updates
and direct Service linking.

After upgrading the repository database, all columns in the twelve supply
models plus WorkOrders and VehicleServices matched the actual schema.
CompanyId is required in all fourteen. Every pre-upgrade row and original
column value across all 51 business tables was preserved; only permission
and role-grant rows were added. SQLite `integrity_check` returned `ok` and
`foreign_key_check` returned no violations. The final pre-upgrade backup is
`backend/data/backups/before-supply-final-upgrade-20260913.db`.

Headless Chromium was exercised against the production frontend build and
an isolated seeded SQLite database. All six supply pages and all six Work
Order tabs loaded without API or JavaScript errors. Browser actions issued
stock to a Work Order and created/submitted/approved/ordered a Purchase Order,
then received 2 of 5 parts and verified its Partially Received status. Albanian
navigation, statuses and vendor forms were checked, along with desktop and
390px mobile rendering. Temporary test servers were stopped afterwards.

Verification covers SQLite. PostgreSQL deployment was not exercised.
