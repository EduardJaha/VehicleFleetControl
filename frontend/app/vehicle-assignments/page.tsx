"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { AssignmentHistoryTable } from "@/components/assignments/AssignmentHistoryTable";
import { Pagination } from "@/components/maintenance/Maintenance";
import { CreateEntityDialog } from "@/components/ui/CreateEntityDialog";
import { EntityPageHeader } from "@/components/ui/EntityPageHeader";
import { apiGet, vehicleAssignmentsApi } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type {
  Driver,
  PageResult,
  Reservation,
  Vehicle,
  VehicleAssignment,
  VehicleAssignmentCompletePayload,
  VehicleAssignmentPayload,
  VehicleAssignmentStartPayload,
  VehicleAssignmentStatus
} from "@/lib/types";

const ASSIGNMENT_STATUSES: VehicleAssignmentStatus[] = ["Scheduled", "Active", "Completed", "Cancelled", "Overdue"];

function localDateTime(value = new Date()): string {
  const adjusted = new Date(value.getTime() - value.getTimezoneOffset() * 60_000);
  return adjusted.toISOString().slice(0, 16);
}

type AssignmentForm = {
  vehicle_id: string;
  driver_id: string;
  reservation_id: string;
  start_datetime: string;
  start_odometer_km: string;
  start_energy_level: string;
  purpose: string;
  notes: string;
};

const emptyAssignmentForm = (): AssignmentForm => ({
  vehicle_id: "",
  driver_id: "",
  reservation_id: "",
  start_datetime: localDateTime(),
  start_odometer_km: "",
  start_energy_level: "",
  purpose: "",
  notes: ""
});

function assignmentToForm(assignment: VehicleAssignment): AssignmentForm {
  return {
    vehicle_id: String(assignment.vehicle_id),
    driver_id: String(assignment.driver_id),
    reservation_id: assignment.reservation_id ? String(assignment.reservation_id) : "",
    start_datetime: localDateTime(new Date(assignment.start_datetime)),
    start_odometer_km: String(assignment.start_odometer_km),
    start_energy_level: assignment.start_energy_level == null ? "" : String(assignment.start_energy_level),
    purpose: assignment.purpose ?? "",
    notes: assignment.notes ?? ""
  };
}

function assignmentPayload(form: AssignmentForm): VehicleAssignmentPayload {
  return {
    vehicle_id: Number(form.vehicle_id),
    driver_id: Number(form.driver_id),
    reservation_id: form.reservation_id ? Number(form.reservation_id) : null,
    start_datetime: new Date(form.start_datetime).toISOString(),
    start_odometer_km: Number(form.start_odometer_km),
    start_energy_level: form.start_energy_level ? Number(form.start_energy_level) : null,
    purpose: form.purpose || null,
    notes: form.notes || null
  };
}

export default function VehicleAssignmentsPage() {
  const { t } = useTranslation(["modules", "common"]);
  const { can, user } = useAuth();
  const canWrite = can("vehicleAssignmentsWrite");
  const [history, setHistory] = useState<PageResult<VehicleAssignment>>({ items: [], page: 1, page_size: 20, total: 0, pages: 0 });
  const [activeAssignments, setActiveAssignments] = useState<VehicleAssignment[]>([]);
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [drivers, setDrivers] = useState<Driver[]>([]);
  const [reservations, setReservations] = useState<Reservation[]>([]);
  const [filters, setFilters] = useState({
    search: "",
    vehicle_id: "",
    driver_id: "",
    status: "",
    from_date: "",
    to_date: "",
    active_only: false,
    include_archived: false
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [assignmentFormState, setAssignmentFormState] = useState<AssignmentForm>(emptyAssignmentForm);
  const [editing, setEditing] = useState<VehicleAssignment | null>(null);
  const [assignmentDialogOpen, setAssignmentDialogOpen] = useState(false);
  const [starting, setStarting] = useState<VehicleAssignment | null>(null);
  const [startForm, setStartForm] = useState({ start_datetime: localDateTime(), start_odometer_km: "", start_energy_level: "", notes: "" });
  const [completing, setCompleting] = useState<VehicleAssignment | null>(null);
  const [completeForm, setCompleteForm] = useState({ end_datetime: localDateTime(), end_odometer_km: "", end_energy_level: "", return_notes: "" });
  const [submitting, setSubmitting] = useState(false);

  const loadAssignments = useCallback(async (page = 1, currentFilters = filters) => {
    setLoading(true);
    setError(null);
    try {
      const baseFilters = {
        search: currentFilters.search,
        vehicle_id: currentFilters.vehicle_id,
        driver_id: currentFilters.driver_id,
        from_date: currentFilters.from_date,
        to_date: currentFilters.to_date
      };
      const [rows, active] = await Promise.all([
        vehicleAssignmentsApi.list({
          ...baseFilters,
          status: currentFilters.status,
          active_only: currentFilters.active_only || undefined,
          include_archived: currentFilters.include_archived || undefined,
          page,
          page_size: 20
        }),
        vehicleAssignmentsApi.list({ ...baseFilters, active_only: true, page: 1, page_size: 100 })
      ]);
      setHistory(rows);
      setActiveAssignments(active.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:vehicleAssignments.loadError"));
    } finally {
      setLoading(false);
    }
  }, [filters, t]);

  useEffect(() => {
    void Promise.all([
      apiGet<Vehicle[]>("/vehicles"),
      apiGet<Driver[]>("/drivers"),
      apiGet<Reservation[]>("/reservations")
    ]).then(([vehicleRows, driverRows, reservationRows]) => {
      setVehicles(vehicleRows);
      setDrivers(driverRows);
      setReservations(reservationRows);
    }).catch((err) => setError(err instanceof Error ? err.message : t("modules:vehicleAssignments.loadError")));
    void loadAssignments();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const matchesSearch = useCallback((assignment: VehicleAssignment) => {
    const search = filters.search.trim().toLowerCase();
    if (!search) return true;
    return [
      assignment.vehicle_license_plate,
      assignment.vehicle_name,
      assignment.driver_name,
      assignment.purpose ?? "",
      assignment.notes ?? "",
      assignment.return_notes ?? ""
    ].some((value) => value.toLowerCase().includes(search));
  }, [filters.search]);

  const filteredHistory = useMemo(() => history.items.filter(matchesSearch), [history.items, matchesSearch]);
  const filteredActive = useMemo(() => activeAssignments.filter(matchesSearch), [activeAssignments, matchesSearch]);
  const formReservations = useMemo(
    () => reservations.filter((reservation) => !assignmentFormState.vehicle_id || reservation.vehicle_id === Number(assignmentFormState.vehicle_id)),
    [assignmentFormState.vehicle_id, reservations]
  );

  function openCreate() {
    setEditing(null);
    setAssignmentFormState(emptyAssignmentForm());
    setError(null);
    setAssignmentDialogOpen(true);
  }

  function openEdit(assignment: VehicleAssignment) {
    setEditing(assignment);
    setAssignmentFormState(assignmentToForm(assignment));
    setError(null);
    setAssignmentDialogOpen(true);
  }

  function closeAssignmentDialog() {
    if (submitting) return;
    setAssignmentDialogOpen(false);
    setEditing(null);
  }

  async function saveAssignment(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const saved = editing
        ? await vehicleAssignmentsApi.update(editing.id, assignmentPayload(assignmentFormState))
        : await vehicleAssignmentsApi.create(assignmentPayload(assignmentFormState));
      setMessage(t(editing ? "modules:vehicleAssignments.updated" : "modules:vehicleAssignments.created", { id: saved.id }));
      setAssignmentDialogOpen(false);
      setEditing(null);
      await loadAssignments(1);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:vehicleAssignments.saveError"));
    } finally {
      setSubmitting(false);
    }
  }

  function openStart(assignment: VehicleAssignment) {
    setStarting(assignment);
    setStartForm({
      start_datetime: localDateTime(),
      start_odometer_km: String(assignment.start_odometer_km),
      start_energy_level: assignment.start_energy_level == null ? "" : String(assignment.start_energy_level),
      notes: assignment.notes ?? ""
    });
    setError(null);
  }

  async function startAssignment(event: React.FormEvent) {
    event.preventDefault();
    if (!starting) return;
    setSubmitting(true);
    setError(null);
    const payload: VehicleAssignmentStartPayload = {
      start_datetime: new Date(startForm.start_datetime).toISOString(),
      start_odometer_km: Number(startForm.start_odometer_km),
      start_energy_level: startForm.start_energy_level ? Number(startForm.start_energy_level) : null,
      notes: startForm.notes || null
    };
    try {
      const result = await vehicleAssignmentsApi.start(starting.id, payload);
      setMessage(t("modules:vehicleAssignments.started", { id: result.id }));
      setStarting(null);
      await loadAssignments(1);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:vehicleAssignments.actionError"));
    } finally {
      setSubmitting(false);
    }
  }

  function openComplete(assignment: VehicleAssignment) {
    setCompleting(assignment);
    setCompleteForm({
      end_datetime: localDateTime(),
      end_odometer_km: String(Math.max(assignment.start_odometer_km, vehicles.find((vehicle) => vehicle.id === assignment.vehicle_id)?.odometer_km ?? 0)),
      end_energy_level: "",
      return_notes: ""
    });
    setError(null);
  }

  async function completeAssignment(event: React.FormEvent) {
    event.preventDefault();
    if (!completing) return;
    setSubmitting(true);
    setError(null);
    const payload: VehicleAssignmentCompletePayload = {
      end_datetime: new Date(completeForm.end_datetime).toISOString(),
      end_odometer_km: Number(completeForm.end_odometer_km),
      end_energy_level: completeForm.end_energy_level ? Number(completeForm.end_energy_level) : null,
      return_notes: completeForm.return_notes || null
    };
    try {
      const result = await vehicleAssignmentsApi.complete(completing.id, payload);
      setMessage(t("modules:vehicleAssignments.completed", { id: result.id }));
      setCompleting(null);
      await loadAssignments(1);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:vehicleAssignments.actionError"));
    } finally {
      setSubmitting(false);
    }
  }

  async function cancelAssignment(assignment: VehicleAssignment) {
    if (!confirm(t("modules:vehicleAssignments.cancelConfirm", { id: assignment.id }))) return;
    try {
      await vehicleAssignmentsApi.cancel(assignment.id);
      setMessage(t("modules:vehicleAssignments.cancelled", { id: assignment.id }));
      await loadAssignments(1);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:vehicleAssignments.actionError"));
    }
  }

  async function archiveAssignment(assignment: VehicleAssignment) {
    if (!confirm(t("modules:vehicleAssignments.archiveConfirm", { id: assignment.id }))) return;
    try {
      await vehicleAssignmentsApi.archive(assignment.id);
      setMessage(t("modules:vehicleAssignments.archived", { id: assignment.id }));
      await loadAssignments(1);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:vehicleAssignments.actionError"));
    }
  }

  async function restoreAssignment(assignment: VehicleAssignment) {
    try {
      await vehicleAssignmentsApi.restore(assignment.id);
      setMessage(t("modules:vehicleAssignments.restored", { id: assignment.id }));
      await loadAssignments(1);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:vehicleAssignments.actionError"));
    }
  }

  function renderActions(assignment: VehicleAssignment) {
    if (!canWrite) return null;
    if (assignment.archived) {
      return user?.role === "admin"
        ? <button className="secondaryButton smallButton" type="button" onClick={() => void restoreAssignment(assignment)}>{t("common:actions.restore")}</button>
        : null;
    }
    return (
      <>
        {assignment.status === "Scheduled" && (
          <>
            <button className="secondaryButton smallButton" type="button" onClick={() => openEdit(assignment)}>{t("common:actions.edit")}</button>
            <button className="button smallButton" type="button" onClick={() => openStart(assignment)}>{t("modules:vehicleAssignments.start")}</button>
          </>
        )}
        {(assignment.status === "Active" || assignment.status === "Overdue") && (
          <button className="button smallButton" type="button" onClick={() => openComplete(assignment)}>{t("modules:vehicleAssignments.complete")}</button>
        )}
        {["Scheduled", "Active", "Overdue"].includes(assignment.status) && (
          <button className="dangerButton smallButton" type="button" onClick={() => void cancelAssignment(assignment)}>{t("common:actions.cancel")}</button>
        )}
        {!["Active", "Overdue"].includes(assignment.status) && (
          <button className="dangerButton smallButton" type="button" onClick={() => void archiveAssignment(assignment)}>{t("common:actions.archive")}</button>
        )}
      </>
    );
  }

  return (
    <section>
      <EntityPageHeader
        title={t("modules:vehicleAssignments.title")}
        description={t("modules:vehicleAssignments.description")}
        actionLabel={canWrite ? t("modules:vehicleAssignments.add") : undefined}
        onAction={canWrite ? openCreate : undefined}
      />

      {error && !assignmentDialogOpen && !starting && !completing && <div className="error spaced" role="alert">{error}</div>}
      {message && <div className="success spaced" role="status">{message}</div>}

      <CreateEntityDialog
        open={assignmentDialogOpen}
        title={editing ? t("modules:vehicleAssignments.edit") : t("modules:vehicleAssignments.add")}
        description={t("modules:vehicleAssignments.formDescription")}
        busy={submitting}
        onClose={closeAssignmentDialog}
      >
        <form className="form dialogForm" onSubmit={saveAssignment}>
          {error && <div className="error">{error}</div>}
          <div className="formGrid">
            <div className="formRow">
              <label htmlFor="assignment-vehicle">{t("common:labels.vehicle")}</label>
              <select id="assignment-vehicle" className="select" required value={assignmentFormState.vehicle_id} onChange={(event) => {
                const vehicleId = event.target.value;
                const vehicle = vehicles.find((row) => row.id === Number(vehicleId));
                setAssignmentFormState({ ...assignmentFormState, vehicle_id: vehicleId, reservation_id: "", start_odometer_km: vehicle?.odometer_km == null ? "" : String(vehicle.odometer_km) });
              }}>
                <option value="">{t("modules:vehicleAssignments.selectVehicle")}</option>
                {vehicles.map((vehicle) => <option key={vehicle.id} value={vehicle.id}>{vehicle.license_plate} · {vehicle.brand} {vehicle.model}</option>)}
              </select>
            </div>
            <div className="formRow">
              <label htmlFor="assignment-driver">{t("common:labels.driver")}</label>
              <select id="assignment-driver" className="select" required value={assignmentFormState.driver_id} onChange={(event) => setAssignmentFormState({ ...assignmentFormState, driver_id: event.target.value })}>
                <option value="">{t("modules:vehicleAssignments.selectDriver")}</option>
                {drivers.map((driver) => <option key={driver.id} value={driver.id}>{driver.full_name} · {driver.employee_number}</option>)}
              </select>
            </div>
            <div className="formRow">
              <label htmlFor="assignment-reservation">{t("modules:vehicleAssignments.reservationOptional")}</label>
              <select id="assignment-reservation" className="select" value={assignmentFormState.reservation_id} onChange={(event) => setAssignmentFormState({ ...assignmentFormState, reservation_id: event.target.value })}>
                <option value="">{t("modules:vehicleAssignments.noReservation")}</option>
                {formReservations.map((reservation) => <option key={reservation.id} value={reservation.id}>#{reservation.id} · {reservation.reserved_by} · {reservation.start_date}</option>)}
              </select>
            </div>
            <div className="formRow"><label htmlFor="assignment-start">{t("modules:vehicleAssignments.startDateTime")}</label><input id="assignment-start" className="input" type="datetime-local" required value={assignmentFormState.start_datetime} onChange={(event) => setAssignmentFormState({ ...assignmentFormState, start_datetime: event.target.value })} /></div>
            <div className="formRow"><label htmlFor="assignment-odometer">{t("modules:vehicleAssignments.startOdometer")}</label><input id="assignment-odometer" className="input" type="number" min="0" required value={assignmentFormState.start_odometer_km} onChange={(event) => setAssignmentFormState({ ...assignmentFormState, start_odometer_km: event.target.value })} /></div>
            <div className="formRow"><label htmlFor="assignment-energy">{t("modules:vehicleAssignments.startEnergy")}</label><input id="assignment-energy" className="input" type="number" min="0" max="100" value={assignmentFormState.start_energy_level} onChange={(event) => setAssignmentFormState({ ...assignmentFormState, start_energy_level: event.target.value })} /></div>
            <div className="formRow span2"><label htmlFor="assignment-purpose">{t("modules:vehicleAssignments.purpose")}</label><input id="assignment-purpose" className="input" value={assignmentFormState.purpose} onChange={(event) => setAssignmentFormState({ ...assignmentFormState, purpose: event.target.value })} /></div>
            <div className="formRow span2"><label htmlFor="assignment-notes">{t("common:labels.notes")}</label><textarea id="assignment-notes" className="input textarea" value={assignmentFormState.notes} onChange={(event) => setAssignmentFormState({ ...assignmentFormState, notes: event.target.value })} /></div>
          </div>
          <div className="actions dialogActions"><button className="secondaryButton" type="button" onClick={closeAssignmentDialog}>{t("common:actions.cancel")}</button><button className="button" type="submit" disabled={submitting}>{submitting ? t("common:states.saving") : t("common:actions.save")}</button></div>
        </form>
      </CreateEntityDialog>

      <CreateEntityDialog open={Boolean(starting)} title={t("modules:vehicleAssignments.start")} description={t("modules:vehicleAssignments.startDescription")} busy={submitting} onClose={() => setStarting(null)}>
        <form className="form dialogForm" onSubmit={startAssignment}>
          {error && <div className="error">{error}</div>}
          <div className="formGrid">
            <div className="formRow"><label htmlFor="start-date-time">{t("modules:vehicleAssignments.startDateTime")}</label><input id="start-date-time" className="input" type="datetime-local" required value={startForm.start_datetime} onChange={(event) => setStartForm({ ...startForm, start_datetime: event.target.value })} /></div>
            <div className="formRow"><label htmlFor="start-odometer">{t("modules:vehicleAssignments.startOdometer")}</label><input id="start-odometer" className="input" type="number" min="0" required value={startForm.start_odometer_km} onChange={(event) => setStartForm({ ...startForm, start_odometer_km: event.target.value })} /></div>
            <div className="formRow"><label htmlFor="start-energy">{t("modules:vehicleAssignments.startEnergy")}</label><input id="start-energy" className="input" type="number" min="0" max="100" value={startForm.start_energy_level} onChange={(event) => setStartForm({ ...startForm, start_energy_level: event.target.value })} /></div>
            <div className="formRow span2"><label htmlFor="start-notes">{t("common:labels.notes")}</label><textarea id="start-notes" className="input textarea" value={startForm.notes} onChange={(event) => setStartForm({ ...startForm, notes: event.target.value })} /></div>
          </div>
          <div className="actions dialogActions"><button className="secondaryButton" type="button" onClick={() => setStarting(null)}>{t("common:actions.cancel")}</button><button className="button" type="submit" disabled={submitting}>{t("modules:vehicleAssignments.start")}</button></div>
        </form>
      </CreateEntityDialog>

      <CreateEntityDialog open={Boolean(completing)} title={t("modules:vehicleAssignments.complete")} description={t("modules:vehicleAssignments.completionDescription")} busy={submitting} onClose={() => setCompleting(null)}>
        <form className="form dialogForm" onSubmit={completeAssignment}>
          {error && <div className="error">{error}</div>}
          <div className="formGrid">
            <div className="formRow"><label htmlFor="complete-date-time">{t("modules:vehicleAssignments.endDateTime")}</label><input id="complete-date-time" className="input" type="datetime-local" required value={completeForm.end_datetime} onChange={(event) => setCompleteForm({ ...completeForm, end_datetime: event.target.value })} /></div>
            <div className="formRow"><label htmlFor="complete-odometer">{t("modules:vehicleAssignments.endOdometer")}</label><input id="complete-odometer" className="input" type="number" min={completing?.start_odometer_km ?? 0} required value={completeForm.end_odometer_km} onChange={(event) => setCompleteForm({ ...completeForm, end_odometer_km: event.target.value })} /></div>
            <div className="formRow"><label htmlFor="complete-energy">{t("modules:vehicleAssignments.endEnergy")}</label><input id="complete-energy" className="input" type="number" min="0" max="100" value={completeForm.end_energy_level} onChange={(event) => setCompleteForm({ ...completeForm, end_energy_level: event.target.value })} /></div>
            <div className="formRow span2"><label htmlFor="return-notes">{t("modules:vehicleAssignments.returnNotes")}</label><textarea id="return-notes" className="input textarea" value={completeForm.return_notes} onChange={(event) => setCompleteForm({ ...completeForm, return_notes: event.target.value })} /></div>
          </div>
          <div className="actions dialogActions"><button className="secondaryButton" type="button" onClick={() => setCompleting(null)}>{t("common:actions.cancel")}</button><button className="button" type="submit" disabled={submitting}>{t("modules:vehicleAssignments.complete")}</button></div>
        </form>
      </CreateEntityDialog>

      <div className="card filtersGrid spaced">
        <input className="input" placeholder={t("modules:vehicleAssignments.searchPlaceholder")} value={filters.search} onChange={(event) => setFilters({ ...filters, search: event.target.value })} />
        <select className="select" value={filters.vehicle_id} onChange={(event) => setFilters({ ...filters, vehicle_id: event.target.value })}><option value="">{t("modules:vehicleAssignments.allVehicles")}</option>{vehicles.map((vehicle) => <option key={vehicle.id} value={vehicle.id}>{vehicle.license_plate}</option>)}</select>
        <select className="select" value={filters.driver_id} onChange={(event) => setFilters({ ...filters, driver_id: event.target.value })}><option value="">{t("modules:vehicleAssignments.allDrivers")}</option>{drivers.map((driver) => <option key={driver.id} value={driver.id}>{driver.full_name}</option>)}</select>
        <select className="select" value={filters.status} onChange={(event) => setFilters({ ...filters, status: event.target.value })}><option value="">{t("modules:vehicleAssignments.allStatuses")}</option>{ASSIGNMENT_STATUSES.map((status) => <option key={status} value={status}>{t(`common:status.${status}`)}</option>)}</select>
        <label className="formRow"><span>{t("modules:vehicleAssignments.fromDate")}</span><input className="input" type="date" value={filters.from_date} onChange={(event) => setFilters({ ...filters, from_date: event.target.value })} /></label>
        <label className="formRow"><span>{t("modules:vehicleAssignments.toDate")}</span><input className="input" type="date" value={filters.to_date} onChange={(event) => setFilters({ ...filters, to_date: event.target.value })} /></label>
        <label className="actions"><input type="checkbox" checked={filters.active_only} onChange={(event) => setFilters({ ...filters, active_only: event.target.checked })} /> {t("modules:vehicleAssignments.activeOnly")}</label>
        {user?.role === "admin" && <label className="actions"><input type="checkbox" checked={filters.include_archived} onChange={(event) => setFilters({ ...filters, include_archived: event.target.checked })} /> {t("modules:vehicleAssignments.includeArchived")}</label>}
        <button className="button" type="button" onClick={() => void loadAssignments(1)}>{t("common:actions.applyFilters")}</button>
      </div>

      <section className="assignmentSection">
        <h2>{t("modules:vehicleAssignments.activeAssignments")}</h2>
        <AssignmentHistoryTable assignments={filteredActive} emptyMessage={t("modules:vehicleAssignments.noActive")} renderActions={canWrite ? renderActions : undefined} />
      </section>
      <section className="assignmentSection">
        <h2>{t("modules:vehicleAssignments.assignmentHistory")}</h2>
        {loading ? <div className="card">{t("modules:vehicleAssignments.loading")}</div> : <AssignmentHistoryTable assignments={filteredHistory} renderActions={canWrite ? renderActions : undefined} />}
        <Pagination page={history.page} pages={history.pages} total={history.total} onPageChange={(page) => void loadAssignments(page)} />
      </section>
    </section>
  );
}
