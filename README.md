# Vehicle Fleet Control - Next.js + FastAPI

This is a reorganized version of the original VehicleManagement project.

The old solution was:

```text
VehicleManagement.API      ASP.NET Core Web API
VehicleManagement.App      Blazor WebAssembly frontend
VehicleManagement.Shared   C# DTOs/enums shared between API and Blazor
```

The new structure is:

```text
VehicleManagement_Next_FastAPI/
  backend/        Python FastAPI API, SQLAlchemy models, Pydantic schemas
  frontend/       Next.js App Router frontend with TypeScript
  docs/           Migration notes and structure analysis
  scripts/        Local run helpers
```

## What changed

- `VehicleManagement.App` was replaced by `frontend/`.
- `VehicleManagement.API` was replaced by `backend/`.
- `VehicleManagement.Shared` was replaced by:
  - `backend/app/schemas.py` for API contracts.
  - `frontend/src/lib/types.ts` for frontend TypeScript contracts.
- The SQLite database is copied to `backend/data/vehiclemanagement.db`.
- Uploads are served by FastAPI from `backend/uploads`.

## Run backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API docs:

```text
http://localhost:8000/docs
```

API base URL:

```text
http://localhost:8000/api/v1
```

## Run frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend URL:

```text
http://localhost:3000
```

The frontend expects:

```text
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
```

## Windows one-click run

```powershell
scripts\run-local.bat
```

## Important migration note

This scaffold preserves the domain model and the main API operations from the current C# project, but it is a modernization scaffold, not a pixel-perfect rewrite of every Blazor screen. The backend has full FastAPI route modules for vehicles, dashboard, papers, services, fuel, accidents, and reservations. The frontend is structured with matching Next.js pages and typed API calls so you can continue rebuilding each Blazor page cleanly.

## Frontend features added in this version

The Next.js frontend now includes operational forms and actions for the main fleet modules:

- Vehicle search/filtering and vehicle delete buttons.
- Service registration form, including reminder fields for kilometer-based and date-based service types.
- Service bill upload during registration and separate bill upload after registration.
- Service history filtering and service delete buttons.
- Fuel registration form with liters, cost per liter, station, location, odometer, and optional bill upload.
- Inline fuel edit/save/cancel controls and fuel delete buttons.
- Paper/document upload form, document filtering, file open links, and paper delete buttons.
- Accident report form with multiple file/photo upload and accident search/filtering.
- Reservation creation form, reservation filtering, and approve/reject buttons.
- Service reminder filtering.

A small backend compatibility change was also added: service overview rows now return the service `id`, which is required for safe service deletion from the frontend.
