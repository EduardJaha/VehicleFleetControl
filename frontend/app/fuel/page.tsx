"use client";

import { useEffect, useMemo, useState } from "react";
import { apiDelete, apiGet, apiPostForm, apiPut, fileHref } from "@/lib/api";
import { FUEL_TYPES } from "@/lib/constants";
import { toApiDate, toInputDate, todayInputDate } from "@/lib/format";
import type { ApiMessage, FuelRecord } from "@/lib/types";

type FuelForm = {
  license_plate: string;
  refuel_date: string;
  fuel_type: string;
  liters: string;
  cost_per_liter: string;
  location: string;
  station_name: string;
  odometer_km: string;
};

const initialFuelForm: FuelForm = {
  license_plate: "",
  refuel_date: todayInputDate(),
  fuel_type: "Diesel",
  liters: "",
  cost_per_liter: "",
  location: "",
  station_name: "",
  odometer_km: ""
};

export default function FuelPage() {
  const [records, setRecords] = useState<FuelRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [form, setForm] = useState<FuelForm>(initialFuelForm);
  const [billFile, setBillFile] = useState<File | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<Omit<FuelForm, "license_plate"> | null>(null);
  const [filters, setFilters] = useState({ search: "", fuel_type: "", location: "", station: "", from_date: "", to_date: "" });

  async function loadFuelRecords() {
    setLoading(true);
    setError(null);
    try {
      setRecords(await apiGet<FuelRecord[]>("/fuel/all"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load fuel records");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadFuelRecords();
  }, []);

  const locations = useMemo(() => Array.from(new Set(records.map((r) => r.location).filter(Boolean))).sort(), [records]);

  const filtered = useMemo(() => {
    const text = filters.search.trim().toLowerCase();
    const from = filters.from_date ? new Date(filters.from_date) : null;
    const to = filters.to_date ? new Date(filters.to_date) : null;
    return records.filter((record) => {
      const recordDate = toInputDate(record.refuel_date) ? new Date(toInputDate(record.refuel_date)) : null;
      const matchesText = !text || [record.license_plate, record.brand, record.model, record.location, record.station_name].some((value) => value.toLowerCase().includes(text));
      const matchesFuel = !filters.fuel_type || record.fuel_type === filters.fuel_type;
      const matchesLocation = !filters.location || record.location === filters.location;
      const matchesStation = !filters.station || record.station_name.toLowerCase().includes(filters.station.toLowerCase());
      const matchesFrom = !from || (recordDate && recordDate >= from);
      const matchesTo = !to || (recordDate && recordDate <= to);
      return matchesText && matchesFuel && matchesLocation && matchesStation && matchesFrom && matchesTo;
    });
  }, [records, filters]);

  async function registerFuel(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setMessage(null);
    try {
      const data = new FormData();
      data.append("license_plate", form.license_plate);
      data.append("refuel_date", toApiDate(form.refuel_date));
      data.append("fuel_type", form.fuel_type);
      data.append("liters", form.liters);
      if (form.cost_per_liter) data.append("cost_per_liter", form.cost_per_liter);
      if (form.location) data.append("location", form.location);
      if (form.station_name) data.append("station_name", form.station_name);
      if (form.odometer_km) data.append("odometer_km", form.odometer_km);
      if (billFile) data.append("bill_file", billFile);
      const result = await apiPostForm<{ message?: string }>("/fuel", data);
      setMessage(result.message ?? "Fuel record added.");
      setForm(initialFuelForm);
      setBillFile(null);
      await loadFuelRecords();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add fuel record");
    }
  }

  function startEdit(record: FuelRecord) {
    setEditingId(record.id);
    setEditForm({
      refuel_date: toInputDate(record.refuel_date),
      fuel_type: record.fuel_type,
      liters: String(record.liters ?? ""),
      cost_per_liter: String(record.cost_per_liter ?? ""),
      location: record.location ?? "",
      station_name: record.station_name ?? "",
      odometer_km: String(record.odometer_km ?? "")
    });
  }

  async function saveEdit(recordId: number) {
    if (!editForm) return;
    setError(null);
    setMessage(null);
    try {
      const result = await apiPut<ApiMessage>(`/fuel/${recordId}`, {
        refuel_date: toApiDate(editForm.refuel_date),
        fuel_type: editForm.fuel_type,
        liters: Number(editForm.liters),
        cost_per_liter: editForm.cost_per_liter ? Number(editForm.cost_per_liter) : null,
        location: editForm.location,
        station_name: editForm.station_name,
        odometer_km: editForm.odometer_km ? Number(editForm.odometer_km) : null
      });
      setMessage(result.message ?? "Fuel record updated.");
      setEditingId(null);
      setEditForm(null);
      await loadFuelRecords();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update fuel record");
    }
  }

  async function deleteFuel(record: FuelRecord) {
    if (!confirm(`Delete fuel record for ${record.license_plate} from ${record.refuel_date}?`)) return;
    setError(null);
    setMessage(null);
    try {
      const result = await apiDelete<ApiMessage>(`/fuel/${record.id}`);
      setMessage(result.message ?? "Fuel record deleted.");
      await loadFuelRecords();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete fuel record");
    }
  }

  return (
    <section>
      <div className="header"><div><h1>Fuel</h1><p className="muted">Register fuel, upload bills, edit/delete records, and filter fuel history.</p></div></div>
      {error && <div className="error spaced">{error}</div>}
      {message && <div className="success spaced">{message}</div>}

      <form onSubmit={registerFuel} className="form card fullWidthForm spaced">
        <h2>Register fuel</h2>
        <div className="formGrid">
          <div className="formRow"><label>License plate</label><input className="input" value={form.license_plate} onChange={(e) => setForm({ ...form, license_plate: e.target.value })} placeholder="01-123-AB" required /></div>
          <div className="formRow"><label>Refuel date</label><input className="input" type="date" value={form.refuel_date} onChange={(e) => setForm({ ...form, refuel_date: e.target.value })} required /></div>
          <div className="formRow"><label>Fuel type</label><select className="select" value={form.fuel_type} onChange={(e) => setForm({ ...form, fuel_type: e.target.value })}>{FUEL_TYPES.map((fuel) => <option key={fuel}>{fuel}</option>)}</select></div>
          <div className="formRow"><label>Liters</label><input className="input" type="number" step="0.01" value={form.liters} onChange={(e) => setForm({ ...form, liters: e.target.value })} required /></div>
          <div className="formRow"><label>Cost per liter</label><input className="input" type="number" step="0.01" value={form.cost_per_liter} onChange={(e) => setForm({ ...form, cost_per_liter: e.target.value })} /></div>
          <div className="formRow"><label>Odometer KM</label><input className="input" type="number" value={form.odometer_km} onChange={(e) => setForm({ ...form, odometer_km: e.target.value })} /></div>
          <div className="formRow"><label>Location</label><input className="input" value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} /></div>
          <div className="formRow"><label>Station</label><input className="input" value={form.station_name} onChange={(e) => setForm({ ...form, station_name: e.target.value })} /></div>
          <div className="formRow span2"><label>Bill file optional</label><input className="input" type="file" onChange={(e) => setBillFile(e.target.files?.[0] ?? null)} /></div>
        </div>
        <button className="button" type="submit">Save fuel record</button>
      </form>

      <div className="card filtersGrid spaced">
        <input className="input" value={filters.search} onChange={(e) => setFilters({ ...filters, search: e.target.value })} placeholder="Search plate, vehicle, location" />
        <select className="select" value={filters.fuel_type} onChange={(e) => setFilters({ ...filters, fuel_type: e.target.value })}><option value="">All fuel</option>{FUEL_TYPES.map((fuel) => <option key={fuel}>{fuel}</option>)}</select>
        <select className="select" value={filters.location} onChange={(e) => setFilters({ ...filters, location: e.target.value })}><option value="">All locations</option>{locations.map((location) => <option key={location}>{location}</option>)}</select>
        <input className="input" value={filters.station} onChange={(e) => setFilters({ ...filters, station: e.target.value })} placeholder="Station" />
        <input className="input" type="date" value={filters.from_date} onChange={(e) => setFilters({ ...filters, from_date: e.target.value })} />
        <input className="input" type="date" value={filters.to_date} onChange={(e) => setFilters({ ...filters, to_date: e.target.value })} />
      </div>

      {loading ? <div className="card">Loading fuel records...</div> : (
        <table className="table">
          <thead><tr><th>Plate</th><th>Vehicle</th><th>Date</th><th>Fuel</th><th>Liters</th><th>Cost/L</th><th>Total</th><th>Location</th><th>Station</th><th>Odometer</th><th>Bill</th><th>Actions</th></tr></thead>
          <tbody>
            {filtered.map((record) => {
              const isEditing = editingId === record.id && editForm;
              return (
                <tr key={record.id}>
                  <td><strong>{record.license_plate}</strong></td>
                  <td>{record.brand} {record.model}</td>
                  <td>{isEditing ? <input className="input compactInput" type="date" value={editForm.refuel_date} onChange={(e) => setEditForm({ ...editForm, refuel_date: e.target.value })} /> : record.refuel_date}</td>
                  <td>{isEditing ? <select className="select compactInput" value={editForm.fuel_type} onChange={(e) => setEditForm({ ...editForm, fuel_type: e.target.value })}>{FUEL_TYPES.map((fuel) => <option key={fuel}>{fuel}</option>)}</select> : record.fuel_type}</td>
                  <td>{isEditing ? <input className="input compactInput" type="number" step="0.01" value={editForm.liters} onChange={(e) => setEditForm({ ...editForm, liters: e.target.value })} /> : record.liters}</td>
                  <td>{isEditing ? <input className="input compactInput" type="number" step="0.01" value={editForm.cost_per_liter} onChange={(e) => setEditForm({ ...editForm, cost_per_liter: e.target.value })} /> : record.cost_per_liter}</td>
                  <td>{record.total_cost}</td>
                  <td>{isEditing ? <input className="input compactInput" value={editForm.location} onChange={(e) => setEditForm({ ...editForm, location: e.target.value })} /> : record.location}</td>
                  <td>{isEditing ? <input className="input compactInput" value={editForm.station_name} onChange={(e) => setEditForm({ ...editForm, station_name: e.target.value })} /> : record.station_name}</td>
                  <td>{isEditing ? <input className="input compactInput" type="number" value={editForm.odometer_km} onChange={(e) => setEditForm({ ...editForm, odometer_km: e.target.value })} /> : record.odometer_km}</td>
                  <td>{record.bill_file_path ? <a className="link" href={fileHref(record.bill_file_path)} target="_blank">Open</a> : "-"}</td>
                  <td>
                    <div className="actions">
                      {isEditing ? <><button className="button smallButton" type="button" onClick={() => void saveEdit(record.id)}>Save</button><button className="secondaryButton smallButton" type="button" onClick={() => { setEditingId(null); setEditForm(null); }}>Cancel</button></> : <button className="secondaryButton smallButton" type="button" onClick={() => startEdit(record)}>Edit</button>}
                      <button className="dangerButton smallButton" type="button" onClick={() => void deleteFuel(record)}>Delete</button>
                    </div>
                  </td>
                </tr>
              );
            })}
            {filtered.length === 0 && <tr><td colSpan={12} className="muted">No fuel records match your filters.</td></tr>}
          </tbody>
        </table>
      )}
    </section>
  );
}
