# VehicleFleetControl

## Production deployment

Use PostgreSQL, private S3-compatible storage and the separate production Compose stack. The [deployment runbook](docs/production-deployment.md) covers first installation, staging, HTTPS, secrets, migrations, encrypted backup/restore, gated releases and clean source archives. Development remains available through `docker-compose.yml` and SQLite.

VehicleFleetControl is a full-stack vehicle fleet management system designed to help companies manage their vehicles, service history, fuel records, vehicle papers, accidents, and reservations from one centralized platform.

The project is built with a **Next.js + TypeScript frontend** and a **Python FastAPI backend**. It uses SQLite for local development and PostgreSQL for staging and production.

---

## Tech Stack

### Frontend

* Next.js
* TypeScript
* React
* CSS Modules / global styling
* Fetch-based API integration

### Backend

* Python
* FastAPI
* SQLAlchemy
* Pydantic
* SQLite
* Uvicorn

### Development Tools

* Git
* Node.js / npm
* Python virtual environment
* FastAPI Swagger documentation

---

## Main Features

VehicleFleetControl currently includes the following modules:

### User Administration and Permissions

* Default Admin, Fleet Manager, Mechanic, Driver, Finance, and Viewer roles are retained
* Granular backend-enforced permissions support custom roles without relying on hidden UI controls
* Users can have scoped role assignments by Location, Department, Cost Center, or own records only
* Administrators can create and edit users, activate or deactivate accounts, link Driver profiles, set preferred language, reset passwords, and revoke sessions
* Locations, Departments, and Cost Centers are managed master data while legacy free-text fields remain available during migration
* Administration pages are available at `/admin/users`, `/admin/roles`, and `/admin/settings`
* Browser sessions use expiring JWTs in Secure, HttpOnly cookies with session-version revocation, login throttling, and mandatory temporary-password changes; see [Authentication security](docs/authentication-security.md)

### Dashboard

* Fleet overview
* Vehicle statistics
* Reservation summary
* Vehicle status overview
* Vehicle location overview

### Vehicle Management

* Add new vehicles
* Edit vehicle details
* Delete vehicles
* Search and filter vehicles
* Track vehicle status
* Track vehicle location
* Track odometer readings
* Validate vehicle license plate format

### Driver Management

* Create, edit, delete, search, and filter driver records
* Track employee number, department, license number, license category, and license expiry
* Optionally link drivers to users and assigned vehicles
* Highlight expired or soon-expiring driver licenses

### Vehicle Inspection Checklists

* Create, edit, delete, search, and filter vehicle inspections
* Use default daily/weekly/trip checklist items with pass/fail/not checked states
* Track inspection type, date, driver, vehicle, overall status, notes, and failed items
* Automatically flags inspections with failed checklist items

### Work Orders

* Create, edit, delete, search, and filter vehicle work orders
* Track status workflow, priority, assignee, workshop, expected and actual completion dates
* Link work orders to vehicles, drivers, and inspections
* Track labor, parts, and total costs with overdue and critical highlighting

### Reports

* View fleet summary, fuel costs, service costs, vehicle costs, reservations, document expiry, and work order reports
* Filter reports by date range, license plate, vehicle status, department, and driver
* Export report KPIs and rows to Excel files

### Vehicle Lifecycle and TCO

* Record acquisition, ownership/lease, warranty, expected service life, depreciation, residual value, and disposal details
* Track insurance, registration, and other operating costs alongside fuel, charging, maintenance, parts, labor, accidents, leases, and depreciation
* Prevent linked Work Order and Service costs from being counted twice
* Calculate liquid-fuel and EV efficiency from usable odometer intervals and identify fuel/charging anomalies
* Review total cost, cost/km, category and monthly trends, downtime, maintenance frequency, current book value, and replacement status at `/reports/tco`
* Use deterministic Retain, Monitor, Replace Soon, and Replace rules based on age, mileage, annual cost, downtime, and reliability; these are not presented as AI recommendations
* Export the TCO report to Excel in English or Albanian

### Service Management

* Register vehicle services
* Upload service bills
* Upload bills later
* View service history
* Delete service records
* Search and filter services
* Track service costs
* Track service workshops
* Support kilometer-based and date-based service reminders

### Preventive Maintenance Programs

Reusable programs contain kilometer, calendar-month or combined tasks, warning
thresholds and optional automatic Work Orders. Assign programs directly or through
Brand/Model, Department, Location, Category and Fuel Type rules. Manage programs,
tasks, assignments and compliance at `/maintenance/programs`; Vehicle Details
shows the assigned program, next tasks and overdue tasks.

Manual reminders are preserved. See [Maintenance Programs](docs/maintenance-programs.md)
for precedence, scheduling, permissions, API routes and bulk compatibility.

### Fuel Management

* Register fuel records
* Edit fuel records
* Delete fuel records
* Upload fuel bills
* Track unit-aware fuel and charging quantities, unit prices, and total cost
* Derive each record's fuel or energy type from the selected Vehicle
* Track liquid fuels in liters and Electric charging in kWh
* Search and filter fuel records
* View fuel history by vehicle

Hybrid Vehicles remain liter-based because the current propulsion model does
not distinguish standard hybrids from plug-in hybrids. Dual-unit plug-in
hybrid records and advanced charging-session fields are deferred follow-up work.

### Vehicle Papers

* Upload vehicle papers
* Manage registration documents
* Manage insurance documents
* View uploaded files
* Delete vehicle papers
* Search and filter vehicle documents

### Accident Management

* Report accidents against a Vehicle, Driver, Assignment, and optional Reservation
* Assess severity, police involvement, fault, damage cost, and post-accident availability
* Automatically move unsafe Vehicles to In Service
* Track involved Parties and Injuries
* Open and settle Insurance Claims, including policy, adjuster, deductible, and settlement values
* Link Insurance Documents, Work Orders, and completed Service records
* Use guarded Reported → Review → Claim/Repair → Resolved → Closed workflow actions
* Store authenticated attachments while preserving all legacy Accident files
* Review Summary, People, Insurance Claim, Repair, Attachments, and Timeline detail tabs
* Archive and restore Accident records without deleting linked history

The Accident report includes Accidents by Driver and Vehicle, Accident rate per
100,000 km, Claim and unrecovered costs, average resolution time, and fault
distribution, with the same filters and Excel export support as other reports.

### Reservation Management

* Create vehicle reservations
* Approve reservations
* Reject reservations
* Track reservation status
* Prevent overlapping active reservations
* Search and filter reservations

---

## Project Structure

```text
VehicleFleetControl/
  backend/
    app/
      api/
        v1/
          endpoints/
      core/
      db/
      utils/
      main.py
      models.py
      schemas.py
    data/
    uploads/
    requirements.txt

  frontend/
    app/
      dashboard/
      vehicles/
      services/
      fuel/
      papers/
      accidents/
      reservations/
    src/
      components/
      lib/
    package.json
    tsconfig.json

  docs/
  scripts/
  docker-compose.yml
  README.md
```

---

## Prerequisites

Before running the project, install the following tools:

### Required

* Git
* Python 3.11 or newer
* Node.js 18 or newer
* npm

Check your installed versions:

```bash
git --version
python --version
node --version
npm --version
```

On some Linux or macOS systems, Python may be available as `python3` instead of `python`.

```bash
python3 --version
```

---

## Clone the Repository

```bash
git clone https://github.com/EduardJaha/VehicleFleetControl.git
cd VehicleFleetControl
```

---

# Running the Project

The project has two applications:

1. FastAPI backend
2. Next.js frontend

You need to run both applications at the same time.

---

## Backend Setup

The backend is located inside the `backend` folder.

### Windows PowerShell

```powershell
cd backend

python -m venv .venv

.venv\Scripts\Activate.ps1

pip install -r requirements-dev.txt

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Windows Command Prompt

```bat
cd backend

python -m venv .venv

.venv\Scripts\activate

pip install -r requirements-dev.txt

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### macOS / Linux

```bash
cd backend

python3 -m venv .venv

source .venv/bin/activate

pip install -r requirements-dev.txt

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The backend will run at:

```text
http://localhost:8000
```

FastAPI documentation will be available at:

```text
http://localhost:8000/docs
```

Health check endpoint:

```text
http://localhost:8000/health
```

### Database migrations

Alembic is the authoritative schema migration system. The application no longer
changes existing schemas during FastAPI startup. From `backend`, run:

```bash
python -m app.scripts.validate_numeric_migration
alembic current
alembic history
alembic upgrade head
alembic revision --autogenerate -m "description"
alembic downgrade -1
```

The numeric preflight reports invalid legacy text values without modifying the
database. The reliability migrations preserve existing rows, convert financial
columns to `NUMERIC`, add archive metadata, and create Audit Log, Notification,
and Attachment tables. Back up production databases before every migration.

The multi-company migration creates a `Default Company`, backfills every
business-owned row, validates that no `CompanyId` is missing, and then enforces
non-null tenant keys. After upgrading, the same invariant can be checked at any
time with:

```bash
python -m app.scripts.validate_company_migration
```

Authenticated database sessions carry the active company from the signed JWT
and automatically scope tenant-owned ORM reads, updates, and deletes. Company
membership is stored in `CompanyUsers`; the UI only renders a company selector
when the signed-in user has more than one active membership. Background
notification generation iterates active companies independently.

For a new environment, install dependencies and migrate before starting:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

On Windows, activate with `.venv\Scripts\activate` (Command Prompt) or
`.venv\Scripts\Activate.ps1` (PowerShell), then run the same `pip`, `alembic`,
and `uvicorn` commands.

### Reliability and production configuration

Copy `backend/.env.example` to `backend/.env` and replace the JWT secret. In
production:

- set `ENVIRONMENT=production`;
- use a unique `JWT_SECRET_KEY` of at least 32 characters;
- set explicit `CORS_ORIGINS` (wildcards are rejected);
- keep `DEBUG=false`;
- point `DATABASE_URL` to the production database;
- store `UPLOAD_DIRECTORY` on durable private storage.

Uploads are not mounted as public static files. New files use UUID storage
names, streamed size/type/content validation, metadata records, and
authenticated download endpoints.

Time-based notifications and retryable email delivery run automatically in a
dedicated scheduler process. Compose starts exactly one scheduler service; API
workers do not start their own schedulers. Configuration and production
architecture are documented in `docs/scheduled-notifications.md`.

The one-shot maintenance command is still available from `backend`:

```bash
python -m app.scripts.generate_notifications
```

Do not schedule that command when the dedicated scheduler process is running.

### Verification

```bash
cd backend
pytest -q

cd ../frontend
npm run lint
npm run build
```

The completed-maintenance reporting rule is: a linked Service supplies the
actual cost, while its source Work Order is excluded from cost aggregation.
Incomplete Work Orders continue to represent planned or estimated cost.

### Vehicle Brand and Model Catalog

Vehicle creation and editing use the local database catalog rather than a
third-party API. On startup, the additive migration creates the catalog tables,
adds nullable catalog references to existing Vehicles, and backfills references
from the legacy Brand and Model display values without deleting those values.

Seed the practical starter catalog from the `backend` directory:

```bash
python -m app.scripts.seed_vehicle_catalog
```

The command is idempotent: it adds missing brands and models without deleting
custom entries. The starter JSON is in `app/data/vehicle_catalog.json`. It
covers common passenger cars, SUVs, vans, and light commercial vehicles, but is
not intended to be a complete global catalog.

Authenticated catalog readers use:

```text
GET /api/v1/vehicle-catalog/brands
GET /api/v1/vehicle-catalog/brands/{brand_id}/models
```

Admin users can create, update, or deactivate brands and models through the
corresponding `/api/v1/vehicle-catalog` management endpoints. Deletion is a
soft deactivation so historical Vehicles remain valid.

Run the dependency-free backend catalog tests from the `backend` directory:

```bash
python -m unittest discover -s tests -v
```

### First Admin User

Authentication is required for `/api/v1` application endpoints. For a new local database, start the backend and frontend, open `http://localhost:3000/login`, and choose **Create first Admin user**. The public first-admin registration is only available while the `Users` table is empty; after that, an Admin must create additional users through the authenticated API.

Auth-related backend environment variables can be set in `backend/.env`:

```text
SECRET_KEY=replace-with-a-long-random-secret
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480
```

---

## Frontend Setup

Open a second terminal and run the frontend.

The frontend is located inside the `frontend` folder.

### Windows / macOS / Linux

```bash
cd frontend

npm install

npm run dev
```

The frontend will run at:

```text
http://localhost:3000
```

---

## Local Development URLs

| Service           | URL                                 |
| ----------------- | ----------------------------------- |
| Frontend          | `http://localhost:3000`             |
| Backend API       | `http://localhost:8000`             |
| API Documentation | `http://localhost:8000/docs`        |
| Health Check      | `http://localhost:8000/health`      |
| Uploaded Files    | `http://localhost:8000/uploads/...` |

---

## Running with Local Scripts

The repository includes helper scripts for local development.

### Windows

From the project root:

```bat
scripts\run-local.bat
```

### macOS / Linux

From the project root:

```bash
chmod +x scripts/run-local.sh
./scripts/run-local.sh
```

These scripts start the backend and frontend locally.

---

## Database

The project uses SQLite for local development.

The local database is stored in:

```text
backend/data/vehiclemanagement.db
```

The database file is not committed to GitHub because it is local development data.

If the database does not exist, the backend can create the required database structure when the application starts.

---

## Uploads

Uploaded files are stored locally in:

```text
backend/uploads/
```

This includes files such as:

* Service bills
* Fuel bills
* Vehicle papers
* Accident photos or documents

Uploaded user files are not committed to GitHub.

---

## API Documentation

FastAPI automatically generates API documentation.

After starting the backend, open:

```text
http://localhost:8000/docs
```

From there you can test backend endpoints directly in the browser.

---

## Useful Commands

### Start Backend

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Start Frontend

```bash
cd frontend
npm run dev
```

### Install Backend Dependencies

```bash
cd backend
pip install -r requirements-dev.txt
```

### Install Frontend Dependencies

```bash
cd frontend
npm install
```

### Build Frontend

```bash
cd frontend
npm run build
```

---

## Recommended Development Workflow

1. Start the backend first.
2. Confirm the backend is running at `http://localhost:8000/docs`.
3. Open a second terminal.
4. Start the frontend.
5. Open the app at `http://localhost:3000`.
6. Use the browser UI to manage vehicles, services, fuel records, papers, accidents, and reservations.

---

## Environment Notes

For local development, the frontend expects the backend API to be available at:

```text
http://localhost:8000/api/v1
```

Make sure the backend is running before using the frontend.

---

## Common Issues

### `python` is not recognized

Use:

```bash
python3 --version
```

If `python3` works, use `python3` instead of `python` when creating the virtual environment.

---

### PowerShell blocks virtual environment activation

Run PowerShell as Administrator and execute:

```powershell
Set-ExecutionPolicy RemoteSigned
```

Then activate the virtual environment again:

```powershell
.venv\Scripts\Activate.ps1
```

---

### Port 8000 is already in use

Stop the application currently using port `8000`, or run the backend on another port:

```bash
uvicorn app.main:app --reload --port 8001
```

If you change the backend port, update the frontend API base URL accordingly.

---

### Port 3000 is already in use

Run the frontend on another port:

```bash
npm run dev -- -p 3001
```

---

### Frontend cannot connect to backend

Make sure the backend is running:

```text
http://localhost:8000/docs
```

Also confirm the frontend is using the correct backend API URL:

```text
http://localhost:8000/api/v1
```

---

## Git Ignore

The repository should not include generated or local-only files such as:

```text
frontend/node_modules/
frontend/.next/
backend/.venv/
backend/data/*.db
backend/uploads/
__pycache__/
.env
```

These files are generated locally and should stay outside GitHub.

---

## License

This project is currently private/internal. Add a license file if the repository will be made public or shared with external contributors.

---

## Project Status

VehicleFleetControl is under active development. The current version provides the core structure and main fleet management functionality for vehicles, services, fuel, documents, accidents, and reservations.

---

## English and Albanian localization

The application uses `i18next` and `react-i18next` with the stable language codes `en` and `sq`. Translation dictionaries live under:

```text
frontend/src/i18n/locales/{en,sq}/
```

They are divided into `common`, `navigation`, `modules`, and `errors` namespaces. Add every new semantic key to both languages and keep canonical API/database enum values in English; translate them only at presentation boundaries.

The active language is stored in `vehicleFleetControl.language` in local storage. For authenticated users it is also saved in `Users.PreferredLanguage` through:

```text
PUT /api/v1/auth/me/language
{"language": "sq"}
```

The frontend sends `Accept-Language` with every API and file-export request. Backend errors return stable codes and localized messages. New notifications, audit entries, and timeline events store translation keys plus language-neutral parameters; historical free-text records continue to display through their fallback fields.

Run localization checks from `frontend/`:

```bash
npm run i18n:check
npm run i18n:scan
```

`i18n:check` fails when EN/SQ dictionary keys diverge. `i18n:scan` reports high-confidence hardcoded UI-string candidates for review.

Apply the bilingual schema migration before running the updated application:

```bash
cd backend
alembic upgrade head
```

### Configurable inspection templates

Inspection templates, per-item failure rules and schedules are managed at `/admin/inspection-templates`. Apply `alembic upgrade head` and continue running the existing notification-generation job. Historical results are preserved as described in the [inspection template guide](docs/inspection-templates.md).
