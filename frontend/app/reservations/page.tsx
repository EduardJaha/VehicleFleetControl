"use client";

import { useEffect, useMemo, useState } from "react";
import { CreateEntityDialog } from "@/components/ui/CreateEntityDialog";
import { EntityPageHeader } from "@/components/ui/EntityPageHeader";
import { apiGet, apiPost, apiPut } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { RESERVATION_STATUS_LABELS, RESERVATION_STATUSES, RESERVATION_TYPES } from "@/lib/constants";
import { toApiDate, todayInputDate } from "@/lib/format";
import type { ApiMessage, Reservation } from "@/lib/types";

const initialForm = {
  license_plate: "",
  reserved_by: "",
  reservation_type: "Business Trip",
  start_date: todayInputDate(),
  end_date: todayInputDate(),
  notes: ""
};

export default function ReservationsPage() {
  const { can } = useAuth();
  const canCreate = can("reservationsCreate");
  const canApprove = can("reservationsApprove");
  const [reservations, setReservations] = useState<Reservation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [form, setForm] = useState(initialForm);
  const [isReservationDialogOpen, setIsReservationDialogOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [filters, setFilters] = useState({ search: "", status: "", type: "", from_date: "", to_date: "" });

  async function loadReservations() {
    setLoading(true);
    setError(null);
    try {
      setReservations(await apiGet<Reservation[]>("/reservations"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load reservations");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadReservations();
  }, []);

  const filtered = useMemo(() => {
    const text = filters.search.trim().toLowerCase();
    const from = filters.from_date ? new Date(filters.from_date) : null;
    const to = filters.to_date ? new Date(filters.to_date) : null;
    return reservations.filter((reservation) => {
      const [day, month, year] = reservation.start_date.split("-");
      const startDate = year ? new Date(`${year}-${month}-${day}`) : null;
      const matchesText = !text || [reservation.license_plate, reservation.reserved_by, reservation.notes ?? ""].some((value) => value.toLowerCase().includes(text));
      const matchesStatus = !filters.status || reservation.status === Number(filters.status);
      const matchesType = !filters.type || reservation.reservation_type === filters.type;
      const matchesFrom = !from || (startDate && startDate >= from);
      const matchesTo = !to || (startDate && startDate <= to);
      return matchesText && matchesStatus && matchesType && matchesFrom && matchesTo;
    });
  }, [reservations, filters]);

  async function createReservation(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setMessage(null);
    setSubmitting(true);
    try {
      const result = await apiPost<ApiMessage>("/reservations", {
        license_plate: form.license_plate,
        reserved_by: form.reserved_by,
        reservation_type: form.reservation_type,
        start_date: toApiDate(form.start_date),
        end_date: toApiDate(form.end_date),
        notes: form.notes || null
      });
      setMessage(result.message ?? "Reservation created.");
      setForm({ ...initialForm });
      setIsReservationDialogOpen(false);
      await loadReservations();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create reservation");
    } finally {
      setSubmitting(false);
    }
  }

  function openReservationDialog() {
    setForm({ ...initialForm });
    setError(null);
    setMessage(null);
    setIsReservationDialogOpen(true);
  }

  function closeReservationDialog() {
    if (submitting) return;
    setForm({ ...initialForm });
    setError(null);
    setIsReservationDialogOpen(false);
  }

  async function updateReservationStatus(id: number, action: "approve" | "reject") {
    setError(null);
    setMessage(null);
    try {
      const result = await apiPut<ApiMessage>(`/reservations/${id}/${action}`, {});
      setMessage(result.message ?? `Reservation ${action}d.`);
      await loadReservations();
    } catch (err) {
      setError(err instanceof Error ? err.message : `Failed to ${action} reservation`);
    }
  }

  return (
    <section>
      <EntityPageHeader
        title="Reservations"
        description="Schedule vehicle use and manage reservation requests."
        actionLabel={canCreate ? "Add Reservation" : undefined}
        onAction={canCreate ? openReservationDialog : undefined}
      />
      {error && !isReservationDialogOpen && <div className="error spaced" role="alert">{error}</div>}
      {message && <div className="success spaced" role="status">{message}</div>}

      {canCreate && <CreateEntityDialog
        open={isReservationDialogOpen}
        title="Add Reservation"
        description="Choose the vehicle, reservation dates, and purpose for this request."
        busy={submitting}
        onClose={closeReservationDialog}
      >
        <form onSubmit={createReservation} className="form dialogForm">
          {error && <div className="error" role="alert">{error}</div>}
          <div className="formGrid">
            <div className="formRow"><label htmlFor="reservation-license-plate">Licence plate</label><input id="reservation-license-plate" className="input" value={form.license_plate} onChange={(e) => setForm({ ...form, license_plate: e.target.value })} placeholder="Albania or Kosovo plate" required /></div>
            <div className="formRow"><label htmlFor="reservation-reserved-by">Reserved by</label><input id="reservation-reserved-by" className="input" value={form.reserved_by} onChange={(e) => setForm({ ...form, reserved_by: e.target.value })} required /></div>
            <div className="formRow"><label htmlFor="reservation-type">Type</label><select id="reservation-type" className="select" value={form.reservation_type} onChange={(e) => setForm({ ...form, reservation_type: e.target.value })}>{RESERVATION_TYPES.map((type) => <option key={type}>{type}</option>)}</select></div>
            <div className="formRow"><label htmlFor="reservation-start-date">Start date</label><input id="reservation-start-date" className="input" type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} required /></div>
            <div className="formRow"><label htmlFor="reservation-end-date">End date</label><input id="reservation-end-date" className="input" type="date" min={form.start_date} value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} required /></div>
            <div className="formRow span2"><label htmlFor="reservation-notes">Notes</label><textarea id="reservation-notes" className="input textarea" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></div>
          </div>
          <div className="actions dialogActions">
            <button className="secondaryButton" type="button" onClick={closeReservationDialog} disabled={submitting}>Cancel</button>
            <button className="button" type="submit" disabled={submitting}>{submitting ? "Creating..." : "Create Reservation"}</button>
          </div>
        </form>
      </CreateEntityDialog>}

      <div className="card filtersGrid spaced">
        <input className="input" value={filters.search} onChange={(e) => setFilters({ ...filters, search: e.target.value })} placeholder="Search plate, person, notes" />
        <select className="select" value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}><option value="">All statuses</option>{RESERVATION_STATUSES.map((status) => <option key={status.value} value={status.value}>{status.label}</option>)}</select>
        <select className="select" value={filters.type} onChange={(e) => setFilters({ ...filters, type: e.target.value })}><option value="">All types</option>{RESERVATION_TYPES.map((type) => <option key={type}>{type}</option>)}</select>
        <input className="input" type="date" value={filters.from_date} onChange={(e) => setFilters({ ...filters, from_date: e.target.value })} />
        <input className="input" type="date" value={filters.to_date} onChange={(e) => setFilters({ ...filters, to_date: e.target.value })} />
      </div>

      {loading ? <div className="card">Loading reservations...</div> : (
        <table className="table">
          <thead><tr><th>Plate</th><th>Reserved by</th><th>Type</th><th>Start</th><th>End</th><th>Status</th><th>Notes</th>{canApprove && <th>Actions</th>}</tr></thead>
          <tbody>
            {filtered.map((r) => <tr key={r.id}><td><strong>{r.license_plate}</strong></td><td>{r.reserved_by}</td><td>{r.reservation_type}</td><td>{r.start_date}</td><td>{r.end_date}</td><td><span className="badge">{RESERVATION_STATUS_LABELS[r.status] ?? r.status_name}</span></td><td>{r.notes ?? ""}</td>{canApprove && <td><div className="actions"><button className="button smallButton" type="button" disabled={r.status === 1} onClick={() => void updateReservationStatus(r.id, "approve")}>Approve</button><button className="dangerButton smallButton" type="button" disabled={r.status === 2} onClick={() => void updateReservationStatus(r.id, "reject")}>Reject</button></div></td>}</tr>)}
            {filtered.length === 0 && <tr><td colSpan={canApprove ? 8 : 7} className="muted">No reservations match your filters.</td></tr>}
          </tbody>
        </table>
      )}
    </section>
  );
}
