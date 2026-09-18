"""Capture ORM domain changes at flush, enqueue after generated IDs exist. No network IO."""
from sqlalchemy import inspect
from app import models as m
from app.services.webhooks import enqueue_event

CREATED = {m.Vehicle: "vehicle.created", m.Driver: "driver.created", m.WorkOrder: "work_order.created",
           m.VehicleService: "service.created", m.VehicleFuel: "fuel.created", m.VehicleAccident: "accident.reported"}
# Deliberately bounded, non-secret data. Consumers can fetch details using scoped APIs.
FIELDS = ("status", "vehicle_id", "driver_id", "vehicle_assignment_id", "reservation_id", "accident_id",
          "odometer_km", "overall_status", "claim_status", "completed_at")


def changed(row, name):
    return inspect(row).attrs[name].history.has_changes()


def capture_events(db, _context):
    pending = []
    for row in db.new.union(db.dirty):
        kind = type(row)
        fresh = row in db.new
        if not fresh and not db.is_modified(row, include_collections=False):
            continue
        names = [CREATED[kind]] if fresh and kind in CREATED else []
        if kind is m.Vehicle and not fresh:
            names.append("vehicle.updated")
        if kind is m.VehicleAssignment and (fresh or changed(row, "status")):
            if row.status == "Active": names.append("assignment.started")
            if row.status == "Completed": names.append("assignment.completed")
        if kind is m.Inspection and row.overall_status == "Failed" and (fresh or changed(row, "overall_status")):
            names.append("inspection.failed")
        if kind is m.WorkOrder and row.status == "Completed" and (fresh or changed(row, "status")):
            names.append("work_order.completed")
        if kind is m.VehicleReservation and row.status == 1 and (fresh or changed(row, "status")):
            names.append("reservation.approved")
        if kind is m.AccidentClaim:
            names.append("claim.updated")
        for name in names:
            pending.append((name, row.company_id, row.id, {key: getattr(row, key) for key in FIELDS if hasattr(row, key)}))
    db.info["integration_events"] = pending


def persist_events(db, _context):
    for name, company_id, entity_id, data in db.info.pop("integration_events", []):
        enqueue_event(db, name, company_id, entity_id, data)


def clear_events(db):
    db.info.pop("integration_events", None)
