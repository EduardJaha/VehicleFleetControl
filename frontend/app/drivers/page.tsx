"use client";

import { useEffect, useMemo, useState } from "react";
import { apiDelete, apiGet, apiPost, apiPut, buildQuery } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { DRIVER_STATUSES } from "@/lib/constants";
import { toApiDate, toInputDate, todayInputDate } from "@/lib/format";
import type { ApiMessage, Driver, DriverPayload, DriverStatus } from "@/lib/types";

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

function expiryBadge(expiryDate: string) {
  const inputDate = toInputDate(expiryDate);
  if (!inputDate) return <span>{expiryDate}</span>;
  const today = new Date(todayInputDate());
  const expiry = new Date(inputDate);
  const daysLeft = Math.ceil((expiry.getTime() - today.getTime()) / 86_400_000);
  if (daysLeft < 0) return <span className="dangerBadge">Expired {expiryDate}</span>;
  if (daysLeft <= 30) return <span className="warningBadge">Expires in {daysLeft} day(s)</span>;
  return <span>{expiryDate}</span>;
}

export default function DriversPage() {
  const { can } = useAuth();
  const canWrite = can("driversWrite");
  const [drivers, setDrivers] = useState<Driver[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [form, setForm] = useState<DriverForm>(initialForm);
  const [editingId, setEditingId] = useState<number | null>(null);
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
      setError(err instanceof Error ? err.message : "Could not load drivers");
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
    try {
      if (editingId) {
        const updated = await apiPut<Driver>(`/drivers/${editingId}`, formToPayload(form));
        setMessage(`Driver ${updated.full_name} updated.`);
      } else {
        const created = await apiPost<Driver>("/drivers", formToPayload(form));
        setMessage(`Driver ${created.full_name} created.`);
      }
      setForm(initialForm);
      setEditingId(null);
      await loadDrivers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save driver");
    }
  }

  function startEdit(driver: Driver) {
    setEditingId(driver.id);
    setForm(driverToForm(driver));
    setMessage(null);
    setError(null);
  }

  function cancelEdit() {
    setEditingId(null);
    setForm(initialForm);
  }

  async function deleteDriver(driver: Driver) {
    if (!confirm(`Delete driver ${driver.full_name}? This cannot be undone.`)) return;
    setError(null);
    setMessage(null);
    try {
      const result = await apiDelete<ApiMessage>(`/drivers/${driver.id}`);
      setMessage(result.message ?? "Driver deleted.");
      await loadDrivers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete driver");
    }
  }

  return (
    <section>
      <div className="header">
        <div>
          <h1>Drivers</h1>
          <p className="muted">Manage driver records, assignments, status, and license expiry dates.</p>
        </div>
      </div>

      {error && <div className="error spaced">{error}</div>}
      {message && <div className="success spaced">{message}</div>}

      {canWrite && (
        <form onSubmit={saveDriver} className="form card fullWidthForm spaced">
          <h2>{editingId ? "Edit driver" : "Create driver"}</h2>
          <div className="formGrid">
            <div className="formRow"><label>Full name</label><input className="input" value={form.full_name} onChange={(event) => setForm({ ...form, full_name: event.target.value })} required /></div>
            <div className="formRow"><label>Phone</label><input className="input" value={form.phone_number} onChange={(event) => setForm({ ...form, phone_number: event.target.value })} /></div>
            <div className="formRow"><label>Email</label><input className="input" type="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} /></div>
            <div className="formRow"><label>Employee number</label><input className="input" value={form.employee_number} onChange={(event) => setForm({ ...form, employee_number: event.target.value })} required /></div>
            <div className="formRow"><label>Department</label><input className="input" value={form.department} onChange={(event) => setForm({ ...form, department: event.target.value })} /></div>
            <div className="formRow"><label>Status</label><select className="select" value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value as DriverStatus })}>{DRIVER_STATUSES.map((status) => <option key={status}>{status}</option>)}</select></div>
            <div className="formRow"><label>License number</label><input className="input" value={form.license_number} onChange={(event) => setForm({ ...form, license_number: event.target.value })} required /></div>
            <div className="formRow"><label>License category</label><input className="input" value={form.license_category} onChange={(event) => setForm({ ...form, license_category: event.target.value })} required /></div>
            <div className="formRow"><label>License expiry</label><input className="input" type="date" value={form.license_expiry_date} onChange={(event) => setForm({ ...form, license_expiry_date: event.target.value })} required /></div>
            <div className="formRow"><label>Assigned plate</label><input className="input" value={form.assigned_license_plate} onChange={(event) => setForm({ ...form, assigned_license_plate: event.target.value })} placeholder="01-123-AB" /></div>
            <div className="formRow"><label>User ID optional</label><input className="input" type="number" value={form.user_id} onChange={(event) => setForm({ ...form, user_id: event.target.value })} /></div>
            <div className="formRow span2"><label>Notes</label><textarea className="input textarea" value={form.notes} onChange={(event) => setForm({ ...form, notes: event.target.value })} /></div>
          </div>
          <div className="actions">
            <button className="button" type="submit">{editingId ? "Update driver" : "Create driver"}</button>
            {editingId && <button className="secondaryButton" type="button" onClick={cancelEdit}>Cancel</button>}
          </div>
        </form>
      )}

      <div className="card filtersGrid spaced">
        <input className="input" value={filters.search} onChange={(event) => setFilters({ ...filters, search: event.target.value })} placeholder="Search name, phone, email, license" />
        <select className="select" value={filters.status} onChange={(event) => setFilters({ ...filters, status: event.target.value })}>
          <option value="">All statuses</option>
          {DRIVER_STATUSES.map((status) => <option key={status}>{status}</option>)}
        </select>
        <select className="select" value={filters.department} onChange={(event) => setFilters({ ...filters, department: event.target.value })}>
          <option value="">All departments</option>
          {departments.map((department) => <option key={department}>{department}</option>)}
        </select>
        <input className="input" type="date" value={filters.license_expiring_before} onChange={(event) => setFilters({ ...filters, license_expiring_before: event.target.value })} title="License expiring before" />
        <button className="button" type="button" onClick={() => void loadDrivers()}>Apply filters</button>
      </div>

      {loading ? <div className="card">Loading drivers...</div> : (
        <table className="table">
          <thead><tr><th>Name</th><th>Contact</th><th>Employee</th><th>Department</th><th>License</th><th>Expiry</th><th>Assigned vehicle</th><th>Status</th>{canWrite && <th>Actions</th>}</tr></thead>
          <tbody>
            {drivers.map((driver) => (
              <tr key={driver.id}>
                <td><strong>{driver.full_name}</strong></td>
                <td>{driver.phone_number || driver.email ? <>{driver.phone_number || "-"}<br /><span className="muted">{driver.email || ""}</span></> : "-"}</td>
                <td>{driver.employee_number}</td>
                <td>{driver.department ?? "-"}</td>
                <td>{driver.license_number} <span className="muted">({driver.license_category})</span></td>
                <td>{expiryBadge(driver.license_expiry_date)}</td>
                <td>{driver.assigned_license_plate ?? "-"}</td>
                <td><span className="badge">{driver.status}</span></td>
                {canWrite && <td><div className="actions"><button className="secondaryButton smallButton" type="button" onClick={() => startEdit(driver)}>Edit</button><button className="dangerButton smallButton" type="button" onClick={() => void deleteDriver(driver)}>Delete</button></div></td>}
              </tr>
            ))}
            {drivers.length === 0 && <tr><td colSpan={canWrite ? 9 : 8} className="muted">No drivers match your filters.</td></tr>}
          </tbody>
        </table>
      )}
    </section>
  );
}
