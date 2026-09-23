# Historical project analysis

Historical record of the earlier .NET-to-FastAPI migration plan. Its project inventory and recommended development order describe that earlier state and are outdated for the current repository. Use `AGENTS.md` and `README.md` for current architecture and setup.

## Existing structure

The uploaded project contains a .NET local solution:

```text
VehicleManagement.Local.sln
VehicleManagement.API/
VehicleManagement.App/
VehicleManagement.Shared/
README_LOCAL_RUN.md
run-local.bat
```

## Backend in the old project

`VehicleManagement.API` is an ASP.NET Core Web API project using Entity Framework Core and SQLite. Its main layers are:

```text
Controllers/
  DashboardController.cs
  VehicleAccidentsController.cs
  VehicleFuelsController.cs
  VehiclePapersController.cs
  VehicleReservationsController.cs
  VehicleServicesController.cs
  VehiclesController.cs
Models/
  Vehicle.cs
  VehiclePaper.cs
  VehicleService.cs
  ServiceBill.cs
  VehicleFuel.cs
  VehicleAccidents.cs
  AccidentFile.cs
  VehicleReservation.cs
Data/
  AppDbContext.cs
Migrations/
App_Data/
uploads/
```

The backend domain is solid, but the current code combines several concerns in controller classes: validation, date parsing, file upload storage, database queries, and response mapping.

## Frontend in the old project

`VehicleManagement.App` is a Blazor WebAssembly app. It contains:

```text
Pages/
  Vehicles.razor
  VehicleForm.razor
  VehicleEdit.razor
  VehicleServiceRegister.razor
  VehicleServiceOverview.razor
  ServiceReminders.razor
  VehicleFuelRegistration.razor
  FuelOverview.razor
  VehiclePapersUpload.razor
  VehiclePapersList.razor
  AccidentReport.razor
  AccidentList.razor
  CreateReservation.razor
  ReservationRequests.razor
  ReservedVehicles.razor
  VehicleReservationList.razor
Services/
  VehicleApiService.cs
  VehicleServicesApiService.cs
  VehicleFuelsApiService.cs
  VehiclePapersApiService.cs
  VehicleAccidentsApiService.cs
  VehicleReservationsApiService.cs
```

The Blazor pages call C# API service classes, which call the ASP.NET endpoints. In the new architecture, this becomes TypeScript pages/components calling a typed API client.

## Shared project in the old project

`VehicleManagement.Shared` contains the DTOs and enums used by both Blazor and ASP.NET:

```text
VehicleStatus
VehicleReservationStatus
CreateVehicleDto
UpdateVehicleDto
VehicleDto
AddServiceDto
ServiceReminderDto
FuelRecordDto
FuelOverviewDto
VehiclePaperListDto
DashboardSummaryDto
```

In the Next.js + FastAPI architecture, this `.csproj` no longer makes sense. Contracts are split into:

```text
backend/app/schemas.py        Pydantic request/response schemas
frontend/src/lib/types.ts     TypeScript request/response types
```

## Main entities preserved

- Vehicles
- Vehicle papers/documents
- Services and service bills
- Fuel records
- Accidents and accident files
- Reservations
- Dashboard summaries
- Service reminders

## Main route migration

| Old ASP.NET route | New FastAPI route |
|---|---|
| `GET /api/Vehicles` | `GET /api/v1/vehicles` |
| `POST /api/Vehicles` | `POST /api/v1/vehicles` |
| `GET /api/Vehicles/{id}` | `GET /api/v1/vehicles/{id}` |
| `GET /api/Vehicles/plate/{plate}` | `GET /api/v1/vehicles/plate/{plate}` |
| `PUT /api/Vehicles/{id}` | `PUT /api/v1/vehicles/{id}` |
| `DELETE /api/Vehicles/{id}` | `DELETE /api/v1/vehicles/{id}` |
| `GET /api/Dashboard/summary` | `GET /api/v1/dashboard/summary` |
| `POST /api/VehicleServices` | `POST /api/v1/services` |
| `POST /api/VehicleServices/register-with-bill` | `POST /api/v1/services/register-with-bill` |
| `GET /api/VehicleServices/reminders` | `GET /api/v1/services/reminders` |
| `GET /api/VehicleFuels/all` | `GET /api/v1/fuel/all` |
| `GET /api/VehicleFuels/overview` | `GET /api/v1/fuel/overview` |
| `POST /api/VehiclePapers/upload` | `POST /api/v1/papers/upload` |
| `GET /api/VehiclePapers/all` | `GET /api/v1/papers/all` |
| `POST /api/VehicleAccidents/report` | `POST /api/v1/accidents/report` |
| `GET /api/VehicleReservations` | `GET /api/v1/reservations` |

## Recommended next development order

1. Stabilize the FastAPI backend and confirm it reads the copied SQLite database.
2. Rebuild the Next.js pages one module at a time: Vehicles first, then Services, Fuel, Papers, Accidents, Reservations, Dashboard.
3. Add authentication and roles after the core module migration is stable.
4. Add Alembic migrations before production.
5. Add Docker, CI/CD, tests, and cloud deployment.
