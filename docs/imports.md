# Bulk imports

The existing `/imports` page and `/api/v1/imports` API support Vehicles, Drivers, Historical Services, Fuel and Charging Records, Vehicle Assignments, Documents Metadata, Vendors, and Parts. No second job system or schema migration is required.

## Workflow

1. Download an English or Albanian CSV/XLSX template.
2. Upload a populated file. The retained source is private.
3. Review suggested column mappings; required fields must be mapped. Driver references use employee numbers, not ambiguous personal names. Vehicle references require registration country and normalized AL/XK plate.
4. Validate (dry run). Target records are unchanged. Preview shows proposed actions, mapped values, errors, and warnings. Only the first 200 rows are included in the initial response; the existing detail endpoint supports up to 1,000 preview rows and filtering by row status. The error download covers every invalid/failed row.
5. Select transaction behavior and confirm. Changing a mapping or update mode requires validation again. Confirmation rechecks related records, duplicates, permissions and fingerprints of matched records.
6. Review counts and download the localized CSV error report. Formula-like source cells are escaped in this export.

The mode defaults to **Create Only**:

| Mode | Existing matching record | Unmatched record |
|---|---|---|
| Create Only (`create_only`) | Validation error | Create |
| Create or Skip Existing (`create_or_skip`) | Skip without editing | Create |
| Explicit Update Existing (`update_existing`) | Update mapped fields after preview | Create, preserving the original import system's explicit upsert behavior |

New adapters preserve unmapped optional fields during updates. A mapped blank intentionally clears an optional value where allowed by that field. Identity fields select the existing record; to correct an identity itself, use the entity's edit workflow. Ambiguous identities and duplicate rows within a file are errors in every mode. Archived targets and protected linked/live records cannot be overwritten by import.

## Entity behavior and identities

| Import | Duplicate identity | Behavior |
|---|---|---|
| Historical Services | Vehicle + service date/time + service type | Maps date, type, odometer, workshop, description, labor/parts/total costs, next date and interval. Uses existing `Imported` source value. Records with linked work orders remain protected. Historical rows can omit old reminder thresholds. A supplied mileage interval must be 5,000/10,000/15,000 km and have an odometer. |
| Fuel / Charging | Vehicle + date/time + odometer + unit | Quantity uses 3 decimals, unit price 4, total 2, half-up. Total must equal rounded quantity × unit price. Unit is `L` or `KWH` (case-insensitive input). Optional Historical Fuel Type supplies the historical snapshot; an existing row's snapshot survives when omitted during update, otherwise the current Vehicle supplies the default. Electric uses KWH; other supported fuel types use L. Legacy liters fields are not populated. |
| Assignments | Vehicle + driver + UTC start time | Completed records require end date and odometer. Completed/Cancelled historical records do not change current vehicle status, mileage, driver links or reservations. Completed overlaps generate warnings and preserve source dates; Scheduled conflicts are errors. Active/Overdue imports are rejected with guidance to use the checked handover workflow. |
| Documents Metadata | Vehicle or driver + document type + document number | Exactly one owner. Expiry cannot precede issue date. Expiry determines Valid/Expiring Soon/Expired; supplied status must agree, or use Renewal In Progress/Rejected. No imported verification bypass. Creates a DocumentVersion and appends a version on updates, preserving previous versions. Existing document requirements determine compliance dashboard visibility, as for legacy documents. |
| Vendors | Case-insensitive trimmed vendor name | Uses maintenance Vendor schema/type vocabulary and contact, address, payment and tax fields. Does not create vehicle-acquisition Suppliers. |
| Parts | Part number, with barcode conflict checks | Uses maintenance Part schema and active existing part category/vendor references. Unit cost has 4 decimals; minimum stock has 3. Catalog import does not create stock or inventory transactions. |

Historical service/fuel readings are not rejected merely because they are below today's vehicle reading. Conflicts with dated history, within-file mileage sequences, and readings above the current reading generate warnings. Current Vehicle mileage stays unchanged. Dates support ISO dates/times, `dd-MM-yyyy`, and `dd/MM/yyyy`; timezone-bearing timestamps normalize to UTC. Completed assignments and historical service/fuel records cannot be future-dated.

### Optional document files

`Existing Secure Attachment ID` associates a PDF that already passed the standard upload pipeline. The attachment must be unarchived, tenant-owned, stored under the private upload root, and linked to an unarchived document/version for the **same vehicle or driver**. Validation and confirmation recheck association and file availability. URLs, disk paths and arbitrary external downloads are not supported as import fields. New PDFs go through the normal secure document/file upload API.

### Permissions

Upload, validation and confirmation require `imports.manage` plus the applicable unrestricted domain grants. Job detail and error downloads also enforce these grants and the existing owner/admin rule. The tenant comes from authentication.

| Entity | Additional permissions |
|---|---|
| Vehicles | `vehicles.create`; updates also `vehicles.edit` |
| Drivers | `drivers.manage` |
| Services | `maintenance.assign_work_order`, `maintenance.manage_costs` |
| Fuel | `fuel.create`, `fuel.view_cost`; updates also `fuel.edit` |
| Assignments | `assignments.manage` |
| Documents | `documents.upload`, `documents.view` |
| Vendors | `vendors.manage` |
| Parts | `parts.manage` |

Scoped grants are rejected for bulk operations to prevent bypassing organizational/own-record restrictions.

## Transactions and scale

CSV and read-only XLSX iterators check row/column limits while reading. Uploads are limited to 10 MiB, 20,000 data rows, and 100 columns. XLSX archives also have a 100 MiB expanded-content limit; formula cells are rejected. Blank rows retain original spreadsheet row numbering in errors.

Validation stages row results in 250-row batches, retaining compact duplicate/overlap/mileage indexes rather than all raw spreadsheet rows in memory. Confirmation uses keyset batches of 250. Error downloads stream CSV rows. The compatibility `parse_import_bytes` helper materializes its return value for existing callers/tests; the upload/validation pipeline uses the streaming reader.

- **Row transaction:** savepoints isolate runtime row failures; successful rows and their audit/domain effects are committed at the end. Invalid/failed rows count as skipped. Intentional duplicate skips count as skipped without changing successful status to Completed With Errors.
- **File transaction:** every row must pass validation. Any runtime failure rolls back all target/domain/audit writes from the file and produces rollback error rows.
- Atomic status claims prevent concurrent execution of the same job. Private atomic JSON progress sidecars expose phase, processed rows and percentage while SQLite holds a target-write transaction. This works across local API processes sharing the upload root and requires no distributed worker.
- A synchronous operation holds its request open. A process crash rolls back its target transaction, but may leave the job marked Validating/Importing. An operator must verify that processing has stopped and reset that job to Uploaded (then revalidate) before retrying. Sidecar percentages are progress hints, not proof of committed data.

## Verification

`tests/test_import_coverage.py` covers all entity templates in both languages/formats, dry run, duplicates, explicit update, skip, numeric/date/plate/unit rules, warnings, version/attachment safety, row/file failures, progress, tenant and permission boundaries, authenticated error exports, and read-back through existing domain APIs. `frontend/tests/imports.spec.ts` exercises all six workflows with mocked APIs, including stale mapping protection and 75% progress. Browser mocks do not replace database integration tests.
