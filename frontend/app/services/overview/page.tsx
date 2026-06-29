"use client";

import { useEffect, useMemo, useState } from "react";
import { apiDelete, apiGet, apiPost, apiPostForm, buildQuery, fileHref } from "@/lib/api";
import { SERVICE_KM_INTERVALS, SERVICE_TYPES } from "@/lib/constants";
import { toApiDate, todayInputDate } from "@/lib/format";
import type { ApiMessage, VehicleServiceOverview } from "@/lib/types";

type ServiceForm = {
  license_plate: string;
  service_type: string;
  service_date: string;
  odometer_km: string;
  cost: string;
  workshop: string;
  description: string;
  next_service_date: string;
  next_service_km_interval: string;
};

const initialServiceForm: ServiceForm = {
  license_plate: "",
  service_type: "General Service",
  service_date: todayInputDate(),
  odometer_km: "",
  cost: "",
  workshop: "",
  description: "",
  next_service_date: "",
  next_service_km_interval: "10000"
};

export default function ServicesOverviewPage() {
  const [services, setServices] = useState<VehicleServiceOverview[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [filters, setFilters] = useState({ plate: "", type: "", workshop: "", from_date: "", to_date: "" });
  const [form, setForm] = useState<ServiceForm>(initialServiceForm);
  const [billFile, setBillFile] = useState<File | null>(null);
  const [laterBill, setLaterBill] = useState({ license_plate: "", service_type: "General Service" });
  const [laterBillFile, setLaterBillFile] = useState<File | null>(null);

  const mileageReminder = form.service_type === "General Service" || form.service_type === "Oil Change";
  const dateReminder = form.service_type === "Tire Change/Control";

  async function loadServices(currentFilters = filters) {
    setLoading(true);
    setError(null);
    try {
      const query = buildQuery({
        plate: currentFilters.plate,
        type: currentFilters.type,
        workshop: currentFilters.workshop,
        from_date: toApiDate(currentFilters.from_date),
        to_date: toApiDate(currentFilters.to_date)
      });
      setServices(await apiGet<VehicleServiceOverview[]>(`/services/overview-filter${query}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load services");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadServices();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const serviceCount = useMemo(() => services.length, [services]);

  function appendServiceFields(data: FormData) {
    data.append("license_plate", form.license_plate);
    data.append("service_type", form.service_type);
    data.append("service_date", toApiDate(form.service_date));
    if (form.description) data.append("description", form.description);
    if (form.workshop) data.append("workshop", form.workshop);
    if (form.odometer_km) data.append("odometer_km", form.odometer_km);
    if (form.cost) data.append("cost", form.cost);
    if (mileageReminder && form.next_service_km_interval) data.append("next_service_km_interval", form.next_service_km_interval);
    if (dateReminder && form.next_service_date) data.append("next_service_date", toApiDate(form.next_service_date));
  }

  async function registerService(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setMessage(null);
    try {
      let result: ApiMessage;
      if (billFile) {
        const data = new FormData();
        appendServiceFields(data);
        data.append("file", billFile);
        result = await apiPostForm<ApiMessage>("/services/register-with-bill", data);
      } else {
        result = await apiPost<ApiMessage>("/services", {
          license_plate: form.license_plate,
          service_type: form.service_type,
          service_date: toApiDate(form.service_date),
          description: form.description || null,
          workshop: form.workshop || null,
          odometer_km: form.odometer_km ? Number(form.odometer_km) : null,
          cost: form.cost ? Number(form.cost) : null,
          next_service_date: dateReminder && form.next_service_date ? toApiDate(form.next_service_date) : null,
          next_service_km_interval: mileageReminder && form.next_service_km_interval ? Number(form.next_service_km_interval) : null
        });
      }
      setMessage(result.message ?? "Service registered.");
      setForm(initialServiceForm);
      setBillFile(null);
      await loadServices();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to register service");
    }
  }

  async function uploadBillLater(event: React.FormEvent) {
    event.preventDefault();
    if (!laterBillFile) {
      setError("Choose a bill file first.");
      return;
    }
    setError(null);
    setMessage(null);
    try {
      const data = new FormData();
      data.append("license_plate", laterBill.license_plate);
      data.append("service_type", laterBill.service_type);
      data.append("bill_file", laterBillFile);
      const result = await apiPostForm<ApiMessage>("/services/upload-bill-later", data);
      setMessage(result.message ?? "Bill uploaded.");
      setLaterBill({ license_plate: "", service_type: "General Service" });
      setLaterBillFile(null);
      await loadServices();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to upload bill");
    }
  }

  async function deleteService(service: VehicleServiceOverview) {
    if (!confirm(`Delete ${service.service_type} for ${service.license_plate}?`)) return;
    setError(null);
    setMessage(null);
    try {
      const result = await apiDelete<ApiMessage>(`/services/${service.id}`);
      setMessage(result.message ?? "Service deleted.");
      await loadServices();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete service");
    }
  }

  return (
    <section>
      <div className="header">
        <div>
          <h1>Services</h1>
          <p className="muted">Register services, upload bills, filter history, and delete old records.</p>
        </div>
      </div>

      {error && <div className="error spaced">{error}</div>}
      {message && <div className="success spaced">{message}</div>}

      <div className="grid cols-2 spaced">
        <form onSubmit={registerService} className="form card fullWidthForm">
          <h2>Register service</h2>
          <div className="formGrid">
            <div className="formRow"><label>License plate</label><input className="input" value={form.license_plate} onChange={(e) => setForm({ ...form, license_plate: e.target.value })} placeholder="01-123-AB" required /></div>
            <div className="formRow"><label>Service type</label><select className="select" value={form.service_type} onChange={(e) => setForm({ ...form, service_type: e.target.value })}>{SERVICE_TYPES.map((type) => <option key={type}>{type}</option>)}</select></div>
            <div className="formRow"><label>Service date</label><input className="input" type="date" value={form.service_date} onChange={(e) => setForm({ ...form, service_date: e.target.value })} required /></div>
            <div className="formRow"><label>Odometer KM</label><input className="input" type="number" value={form.odometer_km} onChange={(e) => setForm({ ...form, odometer_km: e.target.value })} required={mileageReminder} /></div>
            <div className="formRow"><label>Cost</label><input className="input" type="number" step="0.01" value={form.cost} onChange={(e) => setForm({ ...form, cost: e.target.value })} /></div>
            <div className="formRow"><label>Workshop</label><input className="input" value={form.workshop} onChange={(e) => setForm({ ...form, workshop: e.target.value })} /></div>
            {mileageReminder && <div className="formRow"><label>Next service interval</label><select className="select" value={form.next_service_km_interval} onChange={(e) => setForm({ ...form, next_service_km_interval: e.target.value })}>{SERVICE_KM_INTERVALS.map((km) => <option key={km} value={km}>{km.toLocaleString()} km</option>)}</select></div>}
            {dateReminder && <div className="formRow"><label>Next service date</label><input className="input" type="date" value={form.next_service_date} onChange={(e) => setForm({ ...form, next_service_date: e.target.value })} required /></div>}
            <div className="formRow span2"><label>Description</label><textarea className="input textarea" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></div>
            <div className="formRow span2"><label>Bill file optional</label><input className="input" type="file" onChange={(e) => setBillFile(e.target.files?.[0] ?? null)} /></div>
          </div>
          <button className="button" type="submit">Save service</button>
        </form>

        <form onSubmit={uploadBillLater} className="form card fullWidthForm">
          <h2>Upload service bill later</h2>
          <div className="formGrid">
            <div className="formRow"><label>License plate</label><input className="input" value={laterBill.license_plate} onChange={(e) => setLaterBill({ ...laterBill, license_plate: e.target.value })} placeholder="01-123-AB" required /></div>
            <div className="formRow"><label>Service type</label><select className="select" value={laterBill.service_type} onChange={(e) => setLaterBill({ ...laterBill, service_type: e.target.value })}>{SERVICE_TYPES.map((type) => <option key={type}>{type}</option>)}</select></div>
            <div className="formRow span2"><label>Bill file</label><input className="input" type="file" onChange={(e) => setLaterBillFile(e.target.files?.[0] ?? null)} required /></div>
          </div>
          <button className="button" type="submit">Upload bill</button>
        </form>
      </div>

      <div className="card filtersGrid spaced">
        <input className="input" value={filters.plate} onChange={(e) => setFilters({ ...filters, plate: e.target.value })} placeholder="Plate" />
        <select className="select" value={filters.type} onChange={(e) => setFilters({ ...filters, type: e.target.value })}><option value="">All service types</option>{SERVICE_TYPES.map((type) => <option key={type}>{type}</option>)}</select>
        <input className="input" value={filters.workshop} onChange={(e) => setFilters({ ...filters, workshop: e.target.value })} placeholder="Workshop" />
        <input className="input" type="date" value={filters.from_date} onChange={(e) => setFilters({ ...filters, from_date: e.target.value })} />
        <input className="input" type="date" value={filters.to_date} onChange={(e) => setFilters({ ...filters, to_date: e.target.value })} />
        <button className="button" type="button" onClick={() => void loadServices()}>Apply filters</button>
      </div>

      <p className="muted">Showing {serviceCount} service record(s).</p>
      {loading ? <div className="card">Loading services...</div> : (
        <table className="table">
          <thead><tr><th>Plate</th><th>Type</th><th>Date</th><th>Workshop</th><th>Cost</th><th>Odometer</th><th>Next</th><th>Bill</th><th>Actions</th></tr></thead>
          <tbody>
            {services.map((s) => (
              <tr key={s.id}>
                <td><strong>{s.license_plate}</strong></td><td>{s.service_type}</td><td>{s.service_date}</td><td>{s.workshop ?? "-"}</td><td>{s.cost ?? "-"}</td><td>{s.odometer_km ?? "-"}</td>
                <td>{s.next_service_odometer_km ? `${s.next_service_odometer_km} km` : s.next_service_date ?? "-"}</td>
                <td>{s.bill_file_path ? <a className="link" href={fileHref(s.bill_file_path)} target="_blank">Open</a> : "-"}</td>
                <td><button className="dangerButton smallButton" type="button" onClick={() => void deleteService(s)}>Delete</button></td>
              </tr>
            ))}
            {services.length === 0 && <tr><td colSpan={9} className="muted">No service records found.</td></tr>}
          </tbody>
        </table>
      )}
    </section>
  );
}
