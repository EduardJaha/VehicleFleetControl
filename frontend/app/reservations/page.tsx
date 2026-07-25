"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { CreateEntityDialog } from "@/components/ui/CreateEntityDialog";
import { EntityPageHeader } from "@/components/ui/EntityPageHeader";
import { apiGet, apiPost, apiPut } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { RESERVATION_STATUS_KEYS, RESERVATION_STATUSES, RESERVATION_TYPES } from "@/lib/constants";
import { useTranslation } from "react-i18next";
import { toApiDate, todayInputDate } from "@/lib/format";
import type { ApiMessage, Reservation } from "@/lib/types";
import { translateType } from "@/i18n/translate";
import { useLanguage } from "@/components/i18n/LanguageProvider";

const initialForm = {
  license_plate: "",
  reserved_by: "",
  reservation_type: "Business Trip",
  start_date: todayInputDate(),
  end_date: todayInputDate(),
  notes: ""
};

export default function ReservationsPage() {
  const { formatDate } = useLanguage();
  const { t } = useTranslation(["common", "modules"]);
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
      setError(err instanceof Error ? err.message : t("modules:reservations.loadError"));
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
      setMessage(t("modules:reservations.created"));
      setForm({ ...initialForm });
      setIsReservationDialogOpen(false);
      await loadReservations();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:reservations.createError"));
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
      setMessage(t(`modules:reservations.${action === "approve" ? "approved" : "rejected"}`));
      await loadReservations();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:reservations.updateError"));
    }
  }

  return (
    <section>
      <EntityPageHeader
        title={t("modules:reservations.title")}
        description={t("modules:reservations.description")}
        actionLabel={canCreate ? t("modules:reservations.add") : undefined}
        onAction={canCreate ? openReservationDialog : undefined}
      />
      {error && !isReservationDialogOpen && <div className="error spaced" role="alert">{error}</div>}
      {message && <div className="success spaced" role="status">{message}</div>}

      {canCreate && <CreateEntityDialog
        open={isReservationDialogOpen}
        title={t("modules:reservations.add")}
        description={t("modules:reservations.formDescription")}
        busy={submitting}
        onClose={closeReservationDialog}
      >
        <form onSubmit={createReservation} className="form dialogForm">
          {error && <div className="error" role="alert">{error}</div>}
          <div className="formGrid">
            <div className="formRow"><label htmlFor="reservation-license-plate">{t("common:labels.licencePlate")}</label><input id="reservation-license-plate" className="input" value={form.license_plate} onChange={(e) => setForm({ ...form, license_plate: e.target.value })} placeholder={t("modules:drivers.platePlaceholder")} required /></div>
            <div className="formRow"><label htmlFor="reservation-reserved-by">{t("modules:reservations.reservedBy")}</label><input id="reservation-reserved-by" className="input" value={form.reserved_by} onChange={(e) => setForm({ ...form, reserved_by: e.target.value })} required /></div>
            <div className="formRow"><label htmlFor="reservation-type">{t("common:labels.type")}</label><select id="reservation-type" className="select" value={form.reservation_type} onChange={(e) => setForm({ ...form, reservation_type: e.target.value })}>{RESERVATION_TYPES.map((type) => <option key={type} value={type}>{translateType(type)}</option>)}</select></div>
            <div className="formRow"><label htmlFor="reservation-start-date">{t("common:labels.startDate")}</label><input id="reservation-start-date" className="input" type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} required /></div>
            <div className="formRow"><label htmlFor="reservation-end-date">{t("common:labels.endDate")}</label><input id="reservation-end-date" className="input" type="date" min={form.start_date} value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} required /></div>
            <div className="formRow span2"><label htmlFor="reservation-notes">{t("common:labels.notes")}</label><textarea id="reservation-notes" className="input textarea" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></div>
          </div>
          <div className="actions dialogActions">
            <button className="secondaryButton" type="button" onClick={closeReservationDialog} disabled={submitting}>{t("common:actions.cancel")}</button>
            <button className="button" type="submit" disabled={submitting}>{submitting ? t("modules:reservations.creating") : t("modules:reservations.create")}</button>
          </div>
        </form>
      </CreateEntityDialog>}

      <div className="card filtersGrid spaced">
        <input className="input" value={filters.search} onChange={(e) => setFilters({ ...filters, search: e.target.value })} placeholder={t("modules:reservations.searchPlaceholder")} />
        <select className="select" value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}><option value="">{t("modules:reservations.allStatuses")}</option>{RESERVATION_STATUSES.map((status) => <option key={status.value} value={status.value}>{t(`common:${status.labelKey}`)}</option>)}</select>
        <select className="select" value={filters.type} onChange={(e) => setFilters({ ...filters, type: e.target.value })}><option value="">{t("modules:reservations.allTypes")}</option>{RESERVATION_TYPES.map((type) => <option key={type} value={type}>{translateType(type)}</option>)}</select>
        <input className="input" type="date" value={filters.from_date} onChange={(e) => setFilters({ ...filters, from_date: e.target.value })} />
        <input className="input" type="date" value={filters.to_date} onChange={(e) => setFilters({ ...filters, to_date: e.target.value })} />
      </div>

      {loading ? <div className="card">{t("modules:reservations.loading")}</div> : (
        <table className="table">
          <thead><tr><th>{t("common:labels.licencePlate")}</th><th>{t("modules:reservations.reservedBy")}</th><th>{t("common:labels.type")}</th><th>{t("common:labels.startDate")}</th><th>{t("common:labels.endDate")}</th><th>{t("common:labels.status")}</th><th>{t("common:labels.notes")}</th>{canApprove && <th>{t("common:labels.actions")}</th>}</tr></thead>
          <tbody>
            {filtered.map((r) => <tr key={r.id}><td><strong>{r.license_plate}</strong></td><td>{r.reserved_by}</td><td>{translateType(r.reservation_type)}</td><td>{formatDate(r.start_date)}</td><td>{formatDate(r.end_date)}</td><td><span className="badge">{RESERVATION_STATUS_KEYS[r.status] ? t(`common:${RESERVATION_STATUS_KEYS[r.status]}`) : r.status_name}</span></td><td>{r.notes ?? ""}</td>{canApprove && <td><div className="actions">{r.status === 1 && !r.vehicle_assignment_id && <Link className="button smallButton" href={`/vehicle-assignments?checkout=1&reservation_id=${r.id}`}>{t("modules:vehicleAssignments.checkOutVehicle")}</Link>}{r.vehicle_assignment_id && <Link className="secondaryButton smallButton" href={`/vehicle-assignments/${r.vehicle_assignment_id}`}>#{r.vehicle_assignment_id}</Link>}<button className="button smallButton" type="button" disabled={r.status === 1 || r.status === 4} onClick={() => void updateReservationStatus(r.id, "approve")}>{t("common:actions.approve")}</button><button className="dangerButton smallButton" type="button" disabled={r.status === 2 || r.status === 4} onClick={() => void updateReservationStatus(r.id, "reject")}>{t("common:actions.reject")}</button></div></td>}</tr>)}
            {filtered.length === 0 && <tr><td colSpan={canApprove ? 8 : 7} className="muted">{t("modules:reservations.empty")}</td></tr>}
          </tbody>
        </table>
      )}
    </section>
  );
}
