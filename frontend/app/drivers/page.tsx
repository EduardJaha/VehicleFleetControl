"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { CreateEntityDialog } from "@/components/ui/CreateEntityDialog";
import { EntityPageHeader } from "@/components/ui/EntityPageHeader";
import { apiDelete, apiGet, apiPost, apiPut, buildQuery } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { DRIVER_STATUSES } from "@/lib/constants";
import { toApiDate, toInputDate, todayInputDate } from "@/lib/format";
import type { ApiMessage, Driver, DriverPayload, DriverStatus } from "@/lib/types";
import { translateStatus } from "@/i18n/translate";
import { useLanguage } from "@/components/i18n/LanguageProvider";

type DriverForm = {
  full_name: string;
  phone_number: string;
  email: string;
  employee_number: string;
  department: string;
  license_number: string;
  license_category: string;
  license_expiry_date: string;
  assigned_license_plate: string;
  user_id: string;
  status: DriverStatus;
  notes: string;
};

const initialForm: DriverForm = {
  full_name: "",
  phone_number: "",
  email: "",
  employee_number: "",
  department: "",
  license_number: "",
  license_category: "B",
  license_expiry_date: todayInputDate(),
  assigned_license_plate: "",
  user_id: "",
  status: "Active",
  notes: ""
};

function formToPayload(form: DriverForm): DriverPayload {
  return {
    full_name: form.full_name,
    phone_number: form.phone_number || null,
    email: form.email || null,
    employee_number: form.employee_number,
    department: form.department || null,
    license_number: form.license_number,
    license_category: form.license_category,
    license_expiry_date: toApiDate(form.license_expiry_date),
    assigned_license_plate: form.assigned_license_plate || null,
    user_id: form.user_id ? Number(form.user_id) : null,
    status: form.status,
    notes: form.notes || null
  };
}

function driverToForm(driver: Driver): DriverForm {
  return {
    full_name: driver.full_name,
    phone_number: driver.phone_number ?? "",
    email: driver.email ?? "",
    employee_number: driver.employee_number,
    department: driver.department ?? "",
    license_number: driver.license_number,
    license_category: driver.license_category,
    license_expiry_date: toInputDate(driver.license_expiry_date),
    assigned_license_plate: driver.assigned_license_plate ?? "",
    user_id: driver.user_id ? String(driver.user_id) : "",
    status: driver.status,
    notes: driver.notes ?? ""
  };
}

function expiryBadge(expiryDate: string, expired: string, expiresIn: (days: number) => string) {
  const inputDate = toInputDate(expiryDate);
  if (!inputDate) return <span>{expiryDate}</span>;
  const today = new Date(todayInputDate());
  const expiry = new Date(inputDate);
  const daysLeft = Math.ceil((expiry.getTime() - today.getTime()) / 86_400_000);
  if (daysLeft < 0) return <span className="dangerBadge">{expired}</span>;
  if (daysLeft <= 30) return <span className="warningBadge">{expiresIn(daysLeft)}</span>;
  return <span>{expiryDate}</span>;
}

export default function DriversPage() {
  const { t } = useTranslation(["modules", "common"]);
  const { formatDate } = useLanguage();
  const { can } = useAuth();
  const canWrite = can("driversWrite");
  const [drivers, setDrivers] = useState<Driver[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [form, setForm] = useState<DriverForm>(initialForm);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [isDriverDialogOpen, setIsDriverDialogOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [filters, setFilters] = useState({ search: "", status: "", department: "", license_expiring_before: "" });

  async function loadDrivers(currentFilters = filters) {
    setLoading(true);
    setError(null);
    try {
      const query = buildQuery({
        search: currentFilters.search,
        status: currentFilters.status,
        department: currentFilters.department,
        license_expiring_before: toApiDate(currentFilters.license_expiring_before)
      });
      setDrivers(await apiGet<Driver[]>(`/drivers${query}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:drivers.loadError"));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadDrivers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const departments = useMemo(() => Array.from(new Set(drivers.map((driver) => driver.department).filter(Boolean) as string[])).sort(), [drivers]);

  async function saveDriver(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setMessage(null);
    setSubmitting(true);
    try {
      if (editingId) {
        const updated = await apiPut<Driver>(`/drivers/${editingId}`, formToPayload(form));
        setMessage(t("modules:drivers.updated", { name: updated.full_name }));
      } else {
        const created = await apiPost<Driver>("/drivers", formToPayload(form));
        setMessage(t("modules:drivers.created", { name: created.full_name }));
      }
      setForm({ ...initialForm });
      setEditingId(null);
      setIsDriverDialogOpen(false);
      await loadDrivers();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:drivers.saveError"));
    } finally {
      setSubmitting(false);
    }
  }

  function openCreateDialog() {
    setForm({ ...initialForm });
    setEditingId(null);
    setError(null);
    setMessage(null);
    setIsDriverDialogOpen(true);
  }

  function startEdit(driver: Driver) {
    setEditingId(driver.id);
    setForm(driverToForm(driver));
    setMessage(null);
    setError(null);
    setIsDriverDialogOpen(true);
  }

  function closeDriverDialog() {
    if (submitting) return;
    setEditingId(null);
    setForm({ ...initialForm });
    setError(null);
    setIsDriverDialogOpen(false);
  }

  async function deleteDriver(driver: Driver) {
    if (!confirm(t("modules:drivers.archiveConfirm", { name: driver.full_name }))) return;
    setError(null);
    setMessage(null);
    try {
      const result = await apiDelete<ApiMessage>(`/drivers/${driver.id}`);
      setMessage(t("modules:drivers.archived"));
      await loadDrivers();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:drivers.archiveError"));
    }
  }

  return (
    <section>
      <EntityPageHeader
        title={t("modules:drivers.title")}
        description={t("modules:drivers.description")}
        actionLabel={canWrite ? t("modules:drivers.add") : undefined}
        onAction={canWrite ? openCreateDialog : undefined}
      />

      {error && !isDriverDialogOpen && <div className="error spaced" role="alert">{error}</div>}
      {message && <div className="success spaced" role="status">{message}</div>}

      {canWrite && <CreateEntityDialog
        open={isDriverDialogOpen}
        title={editingId ? t("modules:drivers.edit") : t("modules:drivers.add")}
        description={editingId ? t("modules:drivers.editDescription") : t("modules:drivers.formDescription")}
        busy={submitting}
        onClose={closeDriverDialog}
      >
        <form onSubmit={saveDriver} className="form dialogForm">
          {error && <div className="error" role="alert">{error}</div>}
          <div className="formGrid">
            <div className="formRow"><label htmlFor="driver-full-name">{t("common:labels.fullName")}</label><input id="driver-full-name" className="input" value={form.full_name} onChange={(event) => setForm({ ...form, full_name: event.target.value })} required /></div>
            <div className="formRow"><label htmlFor="driver-phone">{t("modules:drivers.phone")}</label><input id="driver-phone" className="input" value={form.phone_number} onChange={(event) => setForm({ ...form, phone_number: event.target.value })} /></div>
            <div className="formRow"><label htmlFor="driver-email">{t("common:labels.email")}</label><input id="driver-email" className="input" type="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} /></div>
            <div className="formRow"><label htmlFor="driver-employee-number">{t("modules:drivers.employeeNumber")}</label><input id="driver-employee-number" className="input" value={form.employee_number} onChange={(event) => setForm({ ...form, employee_number: event.target.value })} required /></div>
            <div className="formRow"><label htmlFor="driver-department">{t("common:labels.department")}</label><input id="driver-department" className="input" value={form.department} onChange={(event) => setForm({ ...form, department: event.target.value })} /></div>
            <div className="formRow"><label htmlFor="driver-status">{t("common:labels.status")}</label><select id="driver-status" className="select" value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value as DriverStatus })}>{DRIVER_STATUSES.map((status) => <option key={status} value={status}>{translateStatus(status)}</option>)}</select></div>
            <div className="formRow"><label htmlFor="driver-license-number">{t("modules:drivers.licenceNumber")}</label><input id="driver-license-number" className="input" value={form.license_number} onChange={(event) => setForm({ ...form, license_number: event.target.value })} required /></div>
            <div className="formRow"><label htmlFor="driver-license-category">{t("modules:drivers.licenceCategory")}</label><input id="driver-license-category" className="input" value={form.license_category} onChange={(event) => setForm({ ...form, license_category: event.target.value })} required /></div>
            <div className="formRow"><label htmlFor="driver-license-expiry">{t("modules:drivers.licenceExpiry")}</label><input id="driver-license-expiry" className="input" type="date" value={form.license_expiry_date} onChange={(event) => setForm({ ...form, license_expiry_date: event.target.value })} required /></div>
            <div className="formRow"><label htmlFor="driver-assigned-plate">{t("modules:drivers.assignedPlate")}</label><input id="driver-assigned-plate" className="input" value={form.assigned_license_plate} onChange={(event) => setForm({ ...form, assigned_license_plate: event.target.value })} placeholder={t("modules:drivers.platePlaceholder")} /></div>
            <div className="formRow"><label htmlFor="driver-user-id">{t("modules:drivers.userIdOptional")}</label><input id="driver-user-id" className="input" type="number" value={form.user_id} onChange={(event) => setForm({ ...form, user_id: event.target.value })} /></div>
            <div className="formRow span2"><label htmlFor="driver-notes">{t("common:labels.notes")}</label><textarea id="driver-notes" className="input textarea" value={form.notes} onChange={(event) => setForm({ ...form, notes: event.target.value })} /></div>
          </div>
          <div className="actions dialogActions">
            <button className="secondaryButton" type="button" onClick={closeDriverDialog} disabled={submitting}>{t("common:actions.cancel")}</button>
            <button className="button" type="submit" disabled={submitting}>{submitting ? (editingId ? t("modules:drivers.updating") : t("modules:drivers.creating")) : (editingId ? t("modules:drivers.update") : t("modules:drivers.create"))}</button>
          </div>
        </form>
      </CreateEntityDialog>}

      <div className="card filtersGrid spaced">
        <input className="input" value={filters.search} onChange={(event) => setFilters({ ...filters, search: event.target.value })} placeholder={t("modules:drivers.searchPlaceholder")} />
        <select className="select" value={filters.status} onChange={(event) => setFilters({ ...filters, status: event.target.value })}>
          <option value="">{t("modules:drivers.allStatuses")}</option>
          {DRIVER_STATUSES.map((status) => <option key={status} value={status}>{translateStatus(status)}</option>)}
        </select>
        <select className="select" value={filters.department} onChange={(event) => setFilters({ ...filters, department: event.target.value })}>
          <option value="">{t("modules:drivers.allDepartments")}</option>
          {departments.map((department) => <option key={department}>{department}</option>)}
        </select>
        <input className="input" type="date" value={filters.license_expiring_before} onChange={(event) => setFilters({ ...filters, license_expiring_before: event.target.value })} title={t("modules:drivers.expiringBefore")} />
        <button className="button" type="button" onClick={() => void loadDrivers()}>{t("common:actions.applyFilters")}</button>
      </div>

      {loading ? <div className="card">{t("modules:drivers.loading")}</div> : (
        <table className="table">
          <thead><tr><th>{t("common:labels.name")}</th><th>{t("modules:drivers.contact")}</th><th>{t("modules:drivers.employee")}</th><th>{t("common:labels.department")}</th><th>{t("modules:drivers.licence")}</th><th>{t("modules:drivers.expiry")}</th><th>{t("modules:drivers.assignedVehicle")}</th><th>{t("common:labels.status")}</th>{canWrite && <th>{t("common:labels.actions")}</th>}</tr></thead>
          <tbody>
            {drivers.map((driver) => (
              <tr key={driver.id}>
                <td><strong>{driver.full_name}</strong></td>
                <td>{driver.phone_number || driver.email ? <>{driver.phone_number || "-"}<br /><span className="muted">{driver.email || ""}</span></> : "-"}</td>
                <td>{driver.employee_number}</td>
                <td>{driver.department ?? "-"}</td>
                <td>{driver.license_number} <span className="muted">({driver.license_category})</span></td>
                <td>{expiryBadge(driver.license_expiry_date, t("modules:drivers.expired", { date: formatDate(driver.license_expiry_date) }), (days) => t("modules:drivers.expiresIn", { count: days }))}</td>
                <td>{driver.assigned_license_plate ?? "-"}</td>
                <td><span className="badge">{translateStatus(driver.status)}</span></td>
                {canWrite && <td><div className="actions"><button className="secondaryButton smallButton" type="button" onClick={() => startEdit(driver)}>{t("common:actions.edit")}</button><button className="dangerButton smallButton" type="button" onClick={() => void deleteDriver(driver)}>{t("common:actions.archive")}</button></div></td>}
              </tr>
            ))}
            {drivers.length === 0 && <tr><td colSpan={canWrite ? 9 : 8} className="muted">{t("modules:drivers.empty")}</td></tr>}
          </tbody>
        </table>
      )}
    </section>
  );
}
