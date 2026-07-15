"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { apiPost, apiPostForm, apiPut, fileHref, maintenanceApi } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { SERVICE_KM_INTERVALS, SERVICE_SOURCES, SERVICE_TYPES } from "@/lib/constants";
import { toApiDate, toInputDate, todayInputDate } from "@/lib/format";
import type { ApiMessage, PageResult, ServiceSource, VehicleServiceOverview } from "@/lib/types";
import { formatMoney, MaintenanceEmptyState, MaintenancePageHeader, MaintenanceStatusBadge, MaintenanceTable, Pagination } from "@/components/maintenance/Maintenance";

type FormState = { license_plate: string; service_type: string; service_date: string; odometer_km: string; cost: string; labor_cost: string; parts_cost: string; workshop: string; description: string; next_service_date: string; next_service_km_interval: string; source: ServiceSource; work_order_id: string };
type Filters = { search: string; license_plate: string; service_type: string; workshop: string; from_date: string; to_date: string; source: string; has_linked_work_order: string; minimum_cost: string; maximum_cost: string };

function newForm(params?: URLSearchParams): FormState {
  const workOrder = params?.get("work_order_id") ?? "";
  return { license_plate: params?.get("license_plate") ?? "", service_type: "General Service", service_date: todayInputDate(), odometer_km: "", cost: "", labor_cost: "", parts_cost: "", workshop: "", description: "", next_service_date: "", next_service_km_interval: "10000", source: workOrder ? "Work Order" : "Manual", work_order_id: workOrder };
}

function serviceForm(service: VehicleServiceOverview): FormState {
  return { license_plate: service.license_plate, service_type: service.service_type, service_date: toInputDate(service.service_date), odometer_km: service.odometer_km ? String(service.odometer_km) : "", cost: service.cost ? String(service.cost) : "", labor_cost: service.labor_cost ? String(service.labor_cost) : "", parts_cost: service.parts_cost ? String(service.parts_cost) : "", workshop: service.workshop ?? "", description: service.description ?? "", next_service_date: toInputDate(service.next_service_date ?? ""), next_service_km_interval: service.next_service_km_interval ? String(service.next_service_km_interval) : "", source: service.source, work_order_id: service.linked_work_order ? String(service.linked_work_order.id) : "" };
}

function payload(form: FormState) {
  return { license_plate: form.license_plate, service_type: form.service_type, service_date: toApiDate(form.service_date), odometer_km: form.odometer_km ? Number(form.odometer_km) : null, cost: form.cost ? Number(form.cost) : null, labor_cost: form.labor_cost ? Number(form.labor_cost) : null, parts_cost: form.parts_cost ? Number(form.parts_cost) : null, workshop: form.workshop || null, description: form.description || null, next_service_date: form.next_service_date ? toApiDate(form.next_service_date) : null, next_service_km_interval: form.next_service_km_interval ? Number(form.next_service_km_interval) : null, source: form.source, work_order_id: form.work_order_id ? Number(form.work_order_id) : null };
}

export default function ServiceHistoryPage() {
  const searchParams = useSearchParams();
  const { can } = useAuth();
  const canWrite = can("servicesWrite");
  const [result, setResult] = useState<PageResult<VehicleServiceOverview>>({ items: [], page: 1, page_size: 20, total: 0, pages: 0 });
  const [filters, setFilters] = useState<Filters>({ search: searchParams.get("search") ?? "", license_plate: searchParams.get("license_plate") ?? "", service_type: searchParams.get("service_type") ?? "", workshop: searchParams.get("workshop") ?? "", from_date: searchParams.get("from_date") ?? "", to_date: searchParams.get("to_date") ?? "", source: searchParams.get("source") ?? "", has_linked_work_order: searchParams.get("has_linked_work_order") ?? "", minimum_cost: searchParams.get("minimum_cost") ?? "", maximum_cost: searchParams.get("maximum_cost") ?? "" });
  const [form, setForm] = useState<FormState>(() => newForm(searchParams));
  const [editingId, setEditingId] = useState<number | null>(null);
  const [billFile, setBillFile] = useState<File | null>(null);
  const [laterBill, setLaterBill] = useState({ license_plate: "", service_type: "General Service" });
  const [laterBillFile, setLaterBillFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(true); const [error, setError] = useState<string | null>(null); const [message, setMessage] = useState<string | null>(null);
  const mileageReminder = ["General Service", "Oil Change"].includes(form.service_type); const dateReminder = form.service_type === "Tire Change/Control";

  const load = useCallback(async (page = 1, values = filters) => {
    setLoading(true); setError(null);
    try { setResult(await maintenanceApi.getServices({ page, page_size: 20, ...values, from_date: toApiDate(values.from_date), to_date: toApiDate(values.to_date), has_linked_work_order: values.has_linked_work_order === "" ? undefined : values.has_linked_work_order === "true" })); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not load Service History"); } finally { setLoading(false); }
  }, [filters]);
  useEffect(() => { void load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function appendForm(data: FormData) { Object.entries(payload(form)).forEach(([key, value]) => { if (value !== null && value !== "") data.append(key, String(value)); }); }
  async function save(event: React.FormEvent) {
    event.preventDefault(); setError(null); setMessage(null);
    try {
      let response: ApiMessage | VehicleServiceOverview;
      if (editingId) response = await apiPut<VehicleServiceOverview>(`/services/id/${editingId}`, payload(form));
      else if (billFile) { const data = new FormData(); appendForm(data); data.append("file", billFile); response = await apiPostForm<ApiMessage>("/services/register-with-bill", data); }
      else response = await apiPost<ApiMessage>("/services", payload(form));
      setMessage(`Service #${response.id ?? editingId} ${editingId ? "updated" : "created"}.`); setEditingId(null); setForm(newForm()); setBillFile(null); await load(result.page);
    } catch (err) { setError(err instanceof Error ? err.message : "Could not save Service"); }
  }
  async function uploadLater(event: React.FormEvent) { event.preventDefault(); if (!laterBillFile) return setError("Choose a bill file first."); const data = new FormData(); data.append("license_plate", laterBill.license_plate); data.append("service_type", laterBill.service_type); data.append("bill_file", laterBillFile); try { const response = await apiPostForm<ApiMessage>("/services/upload-bill-later", data); setMessage(response.message ?? "Bill uploaded."); setLaterBillFile(null); } catch (err) { setError(err instanceof Error ? err.message : "Could not upload bill"); } }
  async function archive(service: VehicleServiceOverview) { if (!confirm(`Archive Service #${service.id}?`)) return; try { await apiPut(`/services/id/${service.id}/archive`, {}); setMessage(`Service #${service.id} archived.`); await load(result.page); } catch (err) { setError(err instanceof Error ? err.message : "Could not archive Service"); } }
  function applyFilters() { const query = new URLSearchParams(); Object.entries(filters).forEach(([key, value]) => { if (value) query.set(key, value); }); window.history.replaceState(null, "", `/services/overview${query.size ? `?${query}` : ""}`); void load(1, filters); }

  return <section>
    <MaintenancePageHeader title="Service History" description="Completed vehicle maintenance, actual costs, bills, next-service information, and source Work Orders." />
    {error && <div className="error spaced">{error}</div>}{message && <div className="success spaced">{message}</div>}
    {canWrite && <div className="grid cols-2 spaced">
      <form className="form card fullWidthForm" onSubmit={save}><h2>{editingId ? `Edit Service #${editingId}` : "Register completed Service"}</h2><div className="formGrid">
        <div className="formRow"><label>License plate</label><input className="input" required value={form.license_plate} onChange={(e) => setForm({ ...form, license_plate: e.target.value })} /></div>
        <div className="formRow"><label>Service type</label><select className="select" value={form.service_type} onChange={(e) => setForm({ ...form, service_type: e.target.value })}>{SERVICE_TYPES.map((v) => <option key={v}>{v}</option>)}</select></div>
        <div className="formRow"><label>Service date</label><input className="input" type="date" required value={form.service_date} onChange={(e) => setForm({ ...form, service_date: e.target.value })} /></div>
        <div className="formRow"><label>Odometer</label><input className="input" type="number" required={mileageReminder} value={form.odometer_km} onChange={(e) => setForm({ ...form, odometer_km: e.target.value })} /></div>
        <div className="formRow"><label>Source</label><select className="select" value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value as ServiceSource })}>{SERVICE_SOURCES.map((v) => <option key={v}>{v}</option>)}</select></div>
        <div className="formRow"><label>Work Order ID</label><input className="input" type="number" value={form.work_order_id} onChange={(e) => setForm({ ...form, work_order_id: e.target.value, source: e.target.value ? "Work Order" : form.source })} /></div>
        <div className="formRow"><label>Workshop</label><input className="input" value={form.workshop} onChange={(e) => setForm({ ...form, workshop: e.target.value })} /></div>
        <div className="formRow"><label>Legacy total cost</label><input className="input" type="number" step="0.01" value={form.cost} onChange={(e) => setForm({ ...form, cost: e.target.value })} /></div>
        <div className="formRow"><label>Labor cost</label><input className="input" type="number" step="0.01" value={form.labor_cost} onChange={(e) => setForm({ ...form, labor_cost: e.target.value })} /></div>
        <div className="formRow"><label>Parts cost</label><input className="input" type="number" step="0.01" value={form.parts_cost} onChange={(e) => setForm({ ...form, parts_cost: e.target.value })} /></div>
        {mileageReminder && <div className="formRow"><label>Next service interval</label><select className="select" value={form.next_service_km_interval} onChange={(e) => setForm({ ...form, next_service_km_interval: e.target.value })}>{SERVICE_KM_INTERVALS.map((v) => <option key={v} value={v}>{v.toLocaleString()} km</option>)}</select></div>}
        {dateReminder && <div className="formRow"><label>Next service date</label><input className="input" type="date" required value={form.next_service_date} onChange={(e) => setForm({ ...form, next_service_date: e.target.value })} /></div>}
        <div className="formRow span2"><label>Description</label><textarea className="input textarea" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></div>
        {!editingId && <div className="formRow span2"><label>Bill / invoice (optional)</label><input className="input" type="file" onChange={(e) => setBillFile(e.target.files?.[0] ?? null)} /></div>}
      </div><div className="actions"><button className="button">{editingId ? "Update Service" : "Save Service"}</button>{editingId && <button className="secondaryButton" type="button" onClick={() => { setEditingId(null); setForm(newForm()); }}>Cancel</button>}</div></form>
      <form className="form card fullWidthForm" onSubmit={uploadLater}><h2>Upload Service bill later</h2><div className="formRow"><label>License plate</label><input className="input" required value={laterBill.license_plate} onChange={(e) => setLaterBill({ ...laterBill, license_plate: e.target.value })} /></div><div className="formRow"><label>Service type</label><select className="select" value={laterBill.service_type} onChange={(e) => setLaterBill({ ...laterBill, service_type: e.target.value })}>{SERVICE_TYPES.map((v) => <option key={v}>{v}</option>)}</select></div><div className="formRow"><label>Bill file</label><input className="input" type="file" required onChange={(e) => setLaterBillFile(e.target.files?.[0] ?? null)} /></div><button className="button">Upload bill</button></form>
    </div>}
    <div className="card filtersGrid spaced">
      <input className="input" placeholder="Search service, plate, description" value={filters.search} onChange={(e) => setFilters({ ...filters, search: e.target.value })} /><input className="input" placeholder="License plate" value={filters.license_plate} onChange={(e) => setFilters({ ...filters, license_plate: e.target.value })} />
      <select className="select" value={filters.service_type} onChange={(e) => setFilters({ ...filters, service_type: e.target.value })}><option value="">All service types</option>{SERVICE_TYPES.map((v) => <option key={v}>{v}</option>)}</select><input className="input" placeholder="Workshop" value={filters.workshop} onChange={(e) => setFilters({ ...filters, workshop: e.target.value })} />
      <input className="input" type="date" value={filters.from_date} onChange={(e) => setFilters({ ...filters, from_date: e.target.value })} /><input className="input" type="date" value={filters.to_date} onChange={(e) => setFilters({ ...filters, to_date: e.target.value })} />
      <select className="select" value={filters.source} onChange={(e) => setFilters({ ...filters, source: e.target.value })}><option value="">All sources</option>{SERVICE_SOURCES.map((v) => <option key={v}>{v}</option>)}</select><select className="select" value={filters.has_linked_work_order} onChange={(e) => setFilters({ ...filters, has_linked_work_order: e.target.value })}><option value="">Any Work Order link</option><option value="true">Has linked Work Order</option><option value="false">No linked Work Order</option></select>
      <input className="input" type="number" placeholder="Minimum cost" value={filters.minimum_cost} onChange={(e) => setFilters({ ...filters, minimum_cost: e.target.value })} /><input className="input" type="number" placeholder="Maximum cost" value={filters.maximum_cost} onChange={(e) => setFilters({ ...filters, maximum_cost: e.target.value })} /><button className="button" type="button" onClick={applyFilters}>Apply filters</button>
    </div>
    {loading ? <div className="card">Loading Service History...</div> : !result.items.length ? <MaintenanceEmptyState>No Service records match the current filters.</MaintenanceEmptyState> : <MaintenanceTable><thead><tr><th>ID / Vehicle</th><th>Service</th><th>Date / Odometer</th><th>Workshop</th><th>Costs</th><th>Source</th><th>Next Service</th><th>Bill</th><th>Actions</th></tr></thead><tbody>{result.items.map((service) => <tr key={service.id}><td><Link className="link" href={`/services/${service.id}`}>#{service.id}</Link><br /><strong>{service.vehicle_name}</strong><br /><span className="muted">{service.license_plate}</span></td><td>{service.service_type}<br /><span className="muted">{service.description ?? "-"}</span></td><td>{service.service_date}<br /><span className="muted">{service.odometer_km ? `${service.odometer_km.toLocaleString()} km` : "-"}</span></td><td>{service.workshop ?? "-"}</td><td>{formatMoney(service.total_cost)}<br /><span className="muted">Labor {formatMoney(service.labor_cost)} · Parts {formatMoney(service.parts_cost)}</span></td><td>{service.source}{service.linked_work_order && <><br /><Link className="link" href={`/work-orders/${service.linked_work_order.id}`}>Work Order #{service.linked_work_order.id}</Link></>}</td><td>{service.next_service_date ?? (service.next_service_odometer_km ? `${service.next_service_odometer_km.toLocaleString()} km` : "-")}</td><td>{service.bill_file_path ? <a className="link" href={fileHref(service.bill_file_path)} target="_blank">Open bill</a> : "-"}</td><td><div className="actions"><Link className="secondaryButton smallButton" href={`/services/${service.id}`}>View</Link>{canWrite && <><button className="secondaryButton smallButton" onClick={() => { setEditingId(service.id); setForm(serviceForm(service)); window.scrollTo({ top: 0, behavior: "smooth" }); }}>Edit</button><button className="secondaryButton smallButton" onClick={() => void archive(service)}>Archive</button></>}</div></td></tr>)}</tbody></MaintenanceTable>}
    <Pagination page={result.page} pages={result.pages} total={result.total} onPageChange={(page) => void load(page)} />
  </section>;
}
