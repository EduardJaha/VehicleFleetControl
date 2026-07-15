"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { apiPost, apiPut, maintenanceApi } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { WORK_ORDER_PRIORITIES, WORK_ORDER_SOURCES, WORK_ORDER_STATUSES } from "@/lib/constants";
import { toApiDate, toInputDate, todayInputDate } from "@/lib/format";
import type { PageResult, WorkOrder, WorkOrderPayload, WorkOrderPriority, WorkOrderSource, WorkOrderStatus } from "@/lib/types";
import { formatMoney, MaintenanceEmptyState, MaintenancePageHeader, MaintenancePriorityBadge, MaintenanceStatusBadge, MaintenanceTable, Pagination } from "@/components/maintenance/Maintenance";

type FormState = {
  license_plate: string; driver_id: string; inspection_id: string; reminder_service_id: string;
  title: string; description: string; reported_issue: string; source: WorkOrderSource;
  priority: WorkOrderPriority; status: WorkOrderStatus; requested_by: string; assigned_to: string;
  workshop: string; expected_completion_date: string; actual_completion_date: string;
  labor_cost: string; parts_cost: string; completed_odometer_km: string; completion_notes: string; completed_by: string; notes: string;
};

type Filters = { search: string; license_plate: string; status: string; priority: string; source: string; assigned_to: string; workshop: string; from_date: string; to_date: string; overdue_only: boolean; has_linked_service: string };

function initialForm(params?: URLSearchParams): FormState {
  const inspectionId = params?.get("inspection_id") ?? "";
  const reminderId = params?.get("reminder_service_id") ?? "";
  return {
    license_plate: params?.get("license_plate") ?? "", driver_id: "", inspection_id: inspectionId, reminder_service_id: reminderId,
    title: params?.get("title") ?? "", description: "", reported_issue: params?.get("reported_issue") ?? "",
    source: inspectionId ? "Inspection" : reminderId ? "Service Reminder" : "Manual", priority: "Medium", status: "Open",
    requested_by: "", assigned_to: "", workshop: "", expected_completion_date: "", actual_completion_date: "",
    labor_cost: "", parts_cost: "", completed_odometer_km: "", completion_notes: "", completed_by: "", notes: ""
  };
}

function toForm(order: WorkOrder): FormState {
  return {
    license_plate: order.license_plate, driver_id: order.driver_id ? String(order.driver_id) : "",
    inspection_id: order.inspection_id ? String(order.inspection_id) : "", reminder_service_id: order.reminder_service_id ? String(order.reminder_service_id) : "",
    title: order.title, description: order.description ?? "", reported_issue: order.reported_issue ?? "", source: order.source,
    priority: order.priority, status: order.status, requested_by: order.requested_by ?? "", assigned_to: order.assigned_to ?? "", workshop: order.workshop ?? "",
    expected_completion_date: toInputDate(order.expected_completion_date ?? ""), actual_completion_date: toInputDate(order.actual_completion_date ?? ""),
    labor_cost: order.labor_cost ? String(order.labor_cost) : "", parts_cost: order.parts_cost ? String(order.parts_cost) : "",
    completed_odometer_km: order.completed_odometer_km ? String(order.completed_odometer_km) : "", completion_notes: order.completion_notes ?? "",
    completed_by: order.completed_by ?? "", notes: order.notes ?? ""
  };
}

function payload(form: FormState): WorkOrderPayload {
  return {
    license_plate: form.license_plate, driver_id: form.driver_id ? Number(form.driver_id) : null,
    inspection_id: form.inspection_id ? Number(form.inspection_id) : null,
    reminder_service_id: form.reminder_service_id ? Number(form.reminder_service_id) : null,
    title: form.title, description: form.description || null, reported_issue: form.reported_issue || null,
    source: form.source, priority: form.priority, status: form.status, requested_by: form.requested_by || null,
    assigned_to: form.assigned_to || null, workshop: form.workshop || null,
    expected_completion_date: form.expected_completion_date ? toApiDate(form.expected_completion_date) : null,
    actual_completion_date: form.actual_completion_date ? toApiDate(form.actual_completion_date) : null,
    labor_cost: form.labor_cost ? Number(form.labor_cost) : null, parts_cost: form.parts_cost ? Number(form.parts_cost) : null,
    completed_odometer_km: form.completed_odometer_km ? Number(form.completed_odometer_km) : null,
    completion_notes: form.completion_notes || null, completed_by: form.completed_by || null, notes: form.notes || null, archived: false
  };
}

function overdue(order: WorkOrder) {
  return !!order.expected_completion_date && !["Completed", "Cancelled"].includes(order.status) && new Date(toInputDate(order.expected_completion_date)) < new Date(todayInputDate());
}

export default function WorkOrdersPage() {
  const searchParams = useSearchParams();
  const { can } = useAuth();
  const canWrite = can("workOrdersWrite");
  const initialFilters = useMemo<Filters>(() => ({
    search: searchParams.get("search") ?? "", license_plate: searchParams.get("license_plate") ?? "", status: searchParams.get("status") ?? "",
    priority: searchParams.get("priority") ?? "", source: searchParams.get("source") ?? "", assigned_to: searchParams.get("assigned_to") ?? "",
    workshop: searchParams.get("workshop") ?? "", from_date: searchParams.get("from_date") ?? "", to_date: searchParams.get("to_date") ?? "",
    overdue_only: searchParams.get("overdue_only") === "true", has_linked_service: searchParams.get("has_linked_service") ?? ""
  }), [searchParams]);
  const [result, setResult] = useState<PageResult<WorkOrder>>({ items: [], page: 1, page_size: 20, total: 0, pages: 0 });
  const [filters, setFilters] = useState(initialFilters);
  const [form, setForm] = useState<FormState>(() => initialForm(searchParams));
  const [editingId, setEditingId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async (page = 1, values = filters) => {
    setLoading(true); setError(null);
    try {
      const data = await maintenanceApi.getWorkOrders({
        page, page_size: 20, ...values, from_date: toApiDate(values.from_date), to_date: toApiDate(values.to_date),
        overdue_only: values.overdue_only || undefined,
        has_linked_service: values.has_linked_service === "" ? undefined : values.has_linked_service === "true"
      });
      setResult(data);
    } catch (err) { setError(err instanceof Error ? err.message : "Could not load Work Orders"); }
    finally { setLoading(false); }
  }, [filters]);

  useEffect(() => { void load(Number(searchParams.get("page") ?? 1), initialFilters); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function applyFilters() {
    const query = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => { if (value !== "" && value !== false) query.set(key, String(value)); });
    window.history.replaceState(null, "", `/work-orders${query.size ? `?${query}` : ""}`);
    void load(1, filters);
  }

  async function save(event: React.FormEvent) {
    event.preventDefault(); setError(null); setMessage(null);
    try {
      const saved = editingId ? await apiPut<WorkOrder>(`/work-orders/${editingId}`, payload(form)) : await apiPost<WorkOrder>("/work-orders", payload(form));
      setMessage(`Work Order #${saved.id} ${editingId ? "updated" : "created"}.`); setEditingId(null); setForm(initialForm()); await load(result.page);
    } catch (err) { setError(err instanceof Error ? err.message : "Could not save Work Order"); }
  }

  async function changeStatus(order: WorkOrder, status: WorkOrderStatus) {
    try {
      await apiPut(`/work-orders/${order.id}/status`, { status, actual_completion_date: status === "Completed" ? (order.actual_completion_date ?? toApiDate(todayInputDate())) : order.actual_completion_date });
      setMessage(`Work Order #${order.id} is now ${status}.`); await load(result.page);
    } catch (err) { setError(err instanceof Error ? err.message : "Could not update Work Order status"); }
  }

  async function archive(order: WorkOrder) {
    if (!confirm(`Archive Work Order #${order.id}?`)) return;
    try { await apiPut(`/work-orders/${order.id}/archive`, {}); setMessage(`Work Order #${order.id} archived.`); await load(result.page); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not archive Work Order"); }
  }

  return (
    <section>
      <MaintenancePageHeader title="Work Orders" description="Plan, assign, track, and complete maintenance work from Inspections, Service Reminders, breakdowns, or manual requests." />
      {error && <div className="error spaced">{error}</div>}{message && <div className="success spaced">{message}</div>}

      {canWrite && <form className="form card fullWidthForm spaced" onSubmit={save}>
        <h2>{editingId ? `Edit Work Order #${editingId}` : "Create Work Order"}</h2>
        <div className="formGrid">
          <div className="formRow"><label>License plate</label><input className="input" required value={form.license_plate} onChange={(e) => setForm({ ...form, license_plate: e.target.value })} /></div>
          <div className="formRow"><label>Title</label><input className="input" required value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></div>
          <div className="formRow"><label>Source</label><select className="select" value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value as WorkOrderSource })}>{WORK_ORDER_SOURCES.map((source) => <option key={source}>{source}</option>)}</select></div>
          <div className="formRow"><label>Priority</label><select className="select" value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value as WorkOrderPriority })}>{WORK_ORDER_PRIORITIES.map((value) => <option key={value}>{value}</option>)}</select></div>
          <div className="formRow"><label>Status</label><select className="select" value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value as WorkOrderStatus })}>{WORK_ORDER_STATUSES.map((value) => <option key={value}>{value}</option>)}</select></div>
          <div className="formRow"><label>Inspection ID</label><input className="input" type="number" value={form.inspection_id} onChange={(e) => setForm({ ...form, inspection_id: e.target.value, source: e.target.value ? "Inspection" : form.source })} /></div>
          <div className="formRow"><label>Service Reminder ID</label><input className="input" type="number" value={form.reminder_service_id} onChange={(e) => setForm({ ...form, reminder_service_id: e.target.value, source: e.target.value ? "Service Reminder" : form.source })} /></div>
          <div className="formRow"><label>Driver ID</label><input className="input" type="number" value={form.driver_id} onChange={(e) => setForm({ ...form, driver_id: e.target.value })} /></div>
          <div className="formRow"><label>Requested by</label><input className="input" value={form.requested_by} onChange={(e) => setForm({ ...form, requested_by: e.target.value })} /></div>
          <div className="formRow"><label>Assigned person</label><input className="input" value={form.assigned_to} onChange={(e) => setForm({ ...form, assigned_to: e.target.value })} /></div>
          <div className="formRow"><label>Workshop</label><input className="input" value={form.workshop} onChange={(e) => setForm({ ...form, workshop: e.target.value })} /></div>
          <div className="formRow"><label>Expected completion</label><input className="input" type="date" value={form.expected_completion_date} onChange={(e) => setForm({ ...form, expected_completion_date: e.target.value })} /></div>
          <div className="formRow"><label>Actual completion</label><input className="input" type="date" required={form.status === "Completed"} value={form.actual_completion_date} onChange={(e) => setForm({ ...form, actual_completion_date: e.target.value })} /></div>
          <div className="formRow"><label>Labor cost</label><input className="input" type="number" min="0" step="0.01" value={form.labor_cost} onChange={(e) => setForm({ ...form, labor_cost: e.target.value })} /></div>
          <div className="formRow"><label>Parts cost</label><input className="input" type="number" min="0" step="0.01" value={form.parts_cost} onChange={(e) => setForm({ ...form, parts_cost: e.target.value })} /></div>
          <div className="formRow"><label>Completed odometer</label><input className="input" type="number" min="0" value={form.completed_odometer_km} onChange={(e) => setForm({ ...form, completed_odometer_km: e.target.value })} /></div>
          <div className="formRow"><label>Completed by</label><input className="input" value={form.completed_by} onChange={(e) => setForm({ ...form, completed_by: e.target.value })} /></div>
          <div className="formRow span2"><label>Reported issue</label><textarea className="input textarea" value={form.reported_issue} onChange={(e) => setForm({ ...form, reported_issue: e.target.value })} /></div>
          <div className="formRow span2"><label>Description</label><textarea className="input textarea" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></div>
          <div className="formRow span2"><label>Completion notes</label><textarea className="input textarea" value={form.completion_notes} onChange={(e) => setForm({ ...form, completion_notes: e.target.value })} /></div>
          <div className="formRow span2"><label>Internal notes</label><textarea className="input textarea" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></div>
        </div>
        <div className="actions"><button className="button" type="submit">{editingId ? "Update Work Order" : "Create Work Order"}</button>{editingId && <button className="secondaryButton" type="button" onClick={() => { setEditingId(null); setForm(initialForm()); }}>Cancel</button>}</div>
      </form>}

      <div className="card filtersGrid spaced">
        <input className="input" placeholder="Search title, issue, assignee" value={filters.search} onChange={(e) => setFilters({ ...filters, search: e.target.value })} />
        <input className="input" placeholder="License plate" value={filters.license_plate} onChange={(e) => setFilters({ ...filters, license_plate: e.target.value })} />
        <select className="select" value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}><option value="">All statuses</option>{WORK_ORDER_STATUSES.map((v) => <option key={v}>{v}</option>)}</select>
        <select className="select" value={filters.priority} onChange={(e) => setFilters({ ...filters, priority: e.target.value })}><option value="">All priorities</option>{WORK_ORDER_PRIORITIES.map((v) => <option key={v}>{v}</option>)}</select>
        <select className="select" value={filters.source} onChange={(e) => setFilters({ ...filters, source: e.target.value })}><option value="">All sources</option>{WORK_ORDER_SOURCES.map((v) => <option key={v}>{v}</option>)}</select>
        <input className="input" placeholder="Assigned person" value={filters.assigned_to} onChange={(e) => setFilters({ ...filters, assigned_to: e.target.value })} />
        <input className="input" placeholder="Workshop" value={filters.workshop} onChange={(e) => setFilters({ ...filters, workshop: e.target.value })} />
        <input className="input" type="date" value={filters.from_date} onChange={(e) => setFilters({ ...filters, from_date: e.target.value })} />
        <input className="input" type="date" value={filters.to_date} onChange={(e) => setFilters({ ...filters, to_date: e.target.value })} />
        <select className="select" value={filters.has_linked_service} onChange={(e) => setFilters({ ...filters, has_linked_service: e.target.value })}><option value="">Any Service link</option><option value="true">Has linked Service</option><option value="false">No linked Service</option></select>
        <label className="actions"><input type="checkbox" checked={filters.overdue_only} onChange={(e) => setFilters({ ...filters, overdue_only: e.target.checked })} /> Overdue only</label>
        <button className="button" type="button" onClick={applyFilters}>Apply filters</button>
      </div>

      {loading ? <div className="card">Loading Work Orders...</div> : result.items.length === 0 ? <MaintenanceEmptyState>No Work Orders match the current filters.</MaintenanceEmptyState> : <MaintenanceTable>
        <thead><tr><th>ID / Vehicle</th><th>Title / Issue</th><th>Source</th><th>Priority</th><th>Status</th><th>Assigned / Workshop</th><th>Completion</th><th>Total cost</th><th>Linked Service</th><th>Actions</th></tr></thead>
        <tbody>{result.items.map((order) => <tr key={order.id} className={order.priority === "Critical" ? "criticalRow" : overdue(order) ? "overdueRow" : undefined}>
          <td><Link className="link" href={`/work-orders/${order.id}`}>#{order.id}</Link><br /><strong>{order.vehicle_name}</strong><br /><span className="muted">{order.license_plate}</span></td>
          <td><strong>{order.title}</strong><br /><span className="muted">{order.reported_issue ?? order.description ?? "-"}</span></td>
          <td>{order.source}</td><td><MaintenancePriorityBadge priority={order.priority} /></td><td><MaintenanceStatusBadge status={order.status} />{overdue(order) && <><br /><span className="dangerBadge">Overdue</span></>}</td>
          <td>{order.assigned_to ?? order.driver_name ?? "-"}<br /><span className="muted">{order.workshop ?? "No workshop"}</span></td>
          <td>{order.expected_completion_date ?? "-"}<br /><span className="muted">Actual: {order.actual_completion_date ?? "-"}</span></td><td>{formatMoney(order.total_cost)}</td>
          <td>{order.linked_service ? <Link className="link" href={`/services/${order.linked_service.id}`}>Service #{order.linked_service.id}</Link> : "-"}</td>
          <td><div className="actions"><Link className="secondaryButton smallButton" href={`/work-orders/${order.id}`}>View</Link>{canWrite && <>
            <button className="secondaryButton smallButton" type="button" onClick={() => { setEditingId(order.id); setForm(toForm(order)); window.scrollTo({ top: 0, behavior: "smooth" }); }}>Edit</button>
            {order.status === "Assigned" && <button className="secondaryButton smallButton" onClick={() => void changeStatus(order, "In Progress")}>Start Work</button>}
            {order.status === "In Progress" && <button className="secondaryButton smallButton" onClick={() => void changeStatus(order, "Waiting for Parts")}>Waiting for Parts</button>}
            {["In Progress", "Waiting for Parts"].includes(order.status) && <button className="button smallButton" onClick={() => void changeStatus(order, "Completed")}>Complete</button>}
            {order.status === "Completed" && !order.linked_service && <Link className="secondaryButton smallButton" href={`/services/overview?work_order_id=${order.id}&license_plate=${encodeURIComponent(order.license_plate)}`}>Create Service</Link>}
            {["Completed", "Cancelled"].includes(order.status) && <button className="secondaryButton smallButton" onClick={() => void archive(order)}>Archive</button>}
          </>}</div></td>
        </tr>)}</tbody>
      </MaintenanceTable>}
      <Pagination page={result.page} pages={result.pages} total={result.total} onPageChange={(page) => void load(page)} />
    </section>
  );
}
